"""Offline-Tests (ohne Netz, ohne Engine) fuer die Risiken, die beim Ausbau schon einmal aufgetreten sind
oder still falsche Reports erzeugen wuerden. Start: python briefing.py selftest"""
from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chess_briefing import config, engine, games as G, pipeline  # noqa: E402
from chess_briefing.identify import Identity  # noqa: E402
from chess_briefing.online import fingerprint as FP, platforms as P  # noqa: E402
from chess_briefing.online.accounts import compare_trees  # noqa: E402
from chess_briefing.openings import name_line  # noqa: E402
from chess_briefing.util import name_matches  # noqa: E402
from chess_briefing.validate import validate_briefing  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "morphy.pgn"


def morphy() -> Identity:
    return Identity(last="Morphy", first="Paul")


class NamesAndGames(unittest.TestCase):
    def test_name_matching(self):
        self.assertEqual(name_matches("Muster, Maximilian", "Muster", "Maximilian"), "strong")
        self.assertEqual(name_matches("Maximilian Muster", "Muster", "Maximilian"), "strong")
        self.assertEqual(name_matches("Muster,M", "Muster", "Maximilian"), "initial")
        self.assertEqual(name_matches("Muster, Mia", "Muster", "Maximilian"), "")
        self.assertEqual(name_matches("Lössing, Thorsten", "Loessing", "Thorsten"), "strong")

    def test_duplicates_from_two_sources_are_merged(self):
        games = G.merge(G.parse_pgn(FIX.read_text(encoding="utf-8"), morphy()))
        self.assertEqual(len(games), 2)                       # Opera-Partie doppelt -> 1, plus Paulsen-Partie
        opera = [g for g in games if g["is_white"]][0]
        self.assertEqual(opera["date"], "1858-11-02")        # vollstaendiges Datum gewinnt
        self.assertEqual(opera["player_score"], 1.0)

    def test_opening_name_from_book(self):
        g = [x for x in G.parse_pgn(FIX.read_text(encoding="utf-8"), morphy()) if x["is_white"]][0]
        self.assertIn("Philidor", name_line(g["ucis"])[1])


class Engine(unittest.TestCase):
    def test_mate_is_scored_for_the_side_that_mates(self):
        b = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
        b.push_san("Ra8#")
        t = engine._terminal(b)
        self.assertEqual(t["cp"], engine.MATE_CP)            # Schwarz ist matt -> positiv fuer Weiss
        self.assertEqual(t["wdl"], (1000, 0, 0))

    def test_chunks_are_fixed_by_position_number(self):
        # gleiche Abschnittsgrenzen, egal welche Stellungen ausgewaehlt sind -> Ergebnis unabhaengig von der Auswahl
        self.assertEqual(engine.chunks([0, 1, 2, 3, 4], 2), [[0, 1], [2, 3], [4]])
        self.assertEqual(engine.chunks([5, 1, 3], 2), [[1], [3], [5]])

    def test_suspects_only_lossy_moves_in_live_positions(self):
        def p(exp_white):   # WDL aus Weiss-Sicht mit gegebenem Erwartungswert, ohne Remisanteil
            return {"wdl": [round(1000 * exp_white), 0, 1000 - round(1000 * exp_white)], "depth": 14}
        pos = [p(.50), p(.50), p(.60),    # 1... Schwarz verliert 0,10 in umkaempfter Stellung -> Stellungen 1, 2
               p(.95), p(.99), p(.99)]    # 2... Schwarz verliert 0,04, steht aber schon bei 0,05 (entschieden)
        self.assertEqual(engine.suspects(pos), [1, 2])
        pos[0] = pos[1] = p(.20)                                                           # Schwarz steht 0,80 ...
        pos[2] = {"cp": 0, "mate": None, "wdl": (0, 1000, 0), "best": None, "pv": []}    # ... und setzt patt
        self.assertEqual(engine.suspects(pos), [1])        # Endstellung braucht keine Engine


def _dossier(online=True):
    facts = [{"id": "F1", "text": "Mit Schwarz 7 Partien.", "scope": "black"},
             {"id": "F2", "text": "Mit Weiß 5 Partien.", "scope": "white"},
             {"id": "F3", "text": "12 Partien gesamt.", "scope": "all"}]
    ofacts = [{"id": "O1", "text": "Online mit Schwarz 41 Partien.", "scope": "black"}]
    return {"facts": facts + (ofacts if online else []), "key_moments": [],
            "online": {"active": online, "facts": ofacts}}


def _briefing():
    side = {"goal": "Ziel.", "opening": [{"title": "T", "line": "1.e4 e5 2.Nf3", "idea": "Idee.", "basis": "partien",
                                          "evidence": ["F1"]}],
            "plan": [{"phase": "Eröffnung", "do": "Tun.", "why": "Weil 7 Partien.", "evidence": ["F1"]}] * 3,
            "avoid": []}
    black = json.loads(json.dumps(side).replace('"F1"', '"F2"'))
    return {"headline": "H.", "summary": [{"title": "a", "text": "b", "evidence": ["F3"]}] * 3,
            "as_white": side, "as_black": black}


class KeyMoments(unittest.TestCase):
    def test_at_most_two_per_game_and_last_decisive_first(self):
        from chess_briefing.metrics import _picks_per_game

        def mv(ply, lvl, before, loss, phase="Mittelspiel"):
            return {"own": True, "ply": ply, "level": lvl, "exp_before": before, "loss": loss, "phase": phase}
        moves = [mv(10, "mistake", .60, .20), mv(20, None, .45, 0), mv(30, "blunder", .48, .40, "Endspiel"),
                 mv(40, None, .55, 0), mv(50, "blunder", .52, .45, "Endspiel"), mv(60, None, .05, 0)]
        picks = _picks_per_game(moves, 2)
        self.assertEqual(len(picks), 2)
        # Ply 50 ist der letzte Fehler ohne Erholung danach -> entscheidend; dazu der groesste uebrige (Ply 30)
        self.assertEqual([(m["ply"], dec) for m, dec in picks], [(30, False), (50, True)])


class Validator(unittest.TestCase):
    def test_valid_briefing_passes(self):
        P_, _ = validate_briefing(_briefing(), _dossier(online=False))
        self.assertEqual(P_, [])

    def test_perspective_error(self):
        b = _briefing()
        b["as_white"]["plan"][0] = dict(b["as_white"]["plan"][0], evidence=["F2"])   # Weiss-Daten im Weiss-Plan
        P_, _ = validate_briefing(b, _dossier(online=False))
        self.assertTrue(any("Perspektivfehler" in p for p in P_))

    def test_online_and_tournament_evidence_are_separated(self):
        b = _briefing()
        b["as_white"]["plan"][0] = dict(b["as_white"]["plan"][0], evidence=["F1", "O1"])
        b["as_white"]["opening"][0]["online"] = {"title": "o", "line": "1.e4", "idea": "i", "evidence": ["F1"]}
        P_, _ = validate_briefing(b, _dossier())
        self.assertTrue(any("Online-Beleg O1" in p for p in P_))
        self.assertTrue(any("Turnier-Beleg F1" in p for p in P_))

    def test_online_fields_need_accepted_account(self):
        b = _briefing()
        b["as_white"]["online_goal"] = "x"
        P_, _ = validate_briefing(b, _dossier(online=False))
        self.assertTrue(any("ohne übernommenen Online-Account" in p for p in P_))

    def test_illegal_line(self):
        b = _briefing()
        b["as_white"]["opening"][0]["line"] = "1.e4 e5 2.Ke3"
        P_, _ = validate_briefing(b, _dossier(online=False))
        self.assertTrue(any("illegal" in p for p in P_))


class EvidenceSnapshot(unittest.TestCase):
    def test_changed_evidence_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = config.PLAYERS_DIR
            config.PLAYERS_DIR = Path(tmp)
            try:
                pdir = Path(tmp) / "x"
                pdir.mkdir()
                (pdir / "dossier.json").write_text(json.dumps(_dossier(online=False)), encoding="utf-8")
                (pdir / "briefing.json").write_text(json.dumps(_briefing()), encoding="utf-8")
                self.assertEqual(pipeline.validate("x"), 0)                       # stempelt
                self.assertIn("_evidence_snapshot", json.loads((pdir / "briefing.json").read_text(encoding="utf-8")))
                d = _dossier(online=False)
                d["facts"][0]["text"] = "Mit Schwarz 9 Partien."                  # neuer Lauf, anderer Inhalt
                (pdir / "dossier.json").write_text(json.dumps(d), encoding="utf-8")
                self.assertEqual(pipeline.validate("x"), 1)
            finally:
                config.PLAYERS_DIR = old


class Determinism(unittest.TestCase):
    def test_comparison_order_is_stable_on_ties(self):
        def tree(paths):
            return {"nodes": {p: {"ply": 2, "n": 2, "score_pct": 50, "name": "", "eco": ""} for p in paths}}
        otb = {"white": tree([]), "black": tree([])}
        onl = {"white": tree(["e4 e5", "e4 c5", "d4 d5"]), "black": tree([])}
        rows = compare_trees(otb, onl, ply=2)
        self.assertEqual([r["path"] for r in rows], ["d4 d5", "e4 c5", "e4 e5"])

    def test_sample_is_deterministic_and_spread(self):
        gs = [{"id": f"g{i:03d}", "date": f"2026-{1 + i % 12:02d}-{1 + i % 28:02d}"} for i in range(300)]
        a, b = P.sample_evenly(gs, 100), P.sample_evenly(list(reversed(gs)), 100)
        self.assertEqual([g["id"] for g in a], [g["id"] for g in b])
        self.assertEqual(len(a), 100)
        self.assertEqual(a[0]["date"], max(g["date"] for g in gs))

    def test_stratified_sample_prefers_long_games_in_every_period(self):
        # zwei Jahre, jeden Tag eine Blitz- und jeden dritten Tag eine Schnellschachpartie
        import datetime as dt
        d0 = dt.date(2024, 1, 1)
        gs = [{"id": f"{s}{i:03d}", "speed": s, "date": (d0 + dt.timedelta(days=i)).isoformat()}
              for i in range(730) for s in ("blitz", "rapid") if s == "blitz" or i % 3 == 0]
        a = P.sample_stratified(gs, 100)
        self.assertEqual([g["id"] for g in a], [g["id"] for g in P.sample_stratified(list(reversed(gs)), 100)])
        self.assertEqual(len(a), 100)
        self.assertTrue(all(g["speed"] == "rapid" for g in a))
        years = [g["date"][:4] for g in a]
        self.assertLessEqual(abs(years.count("2024") - years.count("2025")), 10)

    def test_full_tree_prunes_rare_lines_but_keeps_sample_lines(self):
        from chess_briefing.openings import build_tree
        main = {"sans": ["e4", "c5", "Nf3"], "ucis": ["e2e4", "c7c5", "g1f3"], "is_white": True, "player_score": 1}
        rare = {"sans": ["e4", "e5", "Nf3"], "ucis": ["e2e4", "e7e5", "g1f3"], "is_white": True, "player_score": 0}
        pool = [dict(main, id=f"m{i}") for i in range(5)] + [dict(rare, id="r1"), dict(rare, id="r2")]
        t = build_tree(pool, True, {}, keep_games=False, min_n=3)["nodes"]
        self.assertNotIn("e4 e5", t)
        self.assertEqual([c["path"] for c in t["e4"]["children"]], ["e4 c5"])
        t = build_tree(pool, True, {}, keep_games=False, min_n=3, keep_ids={"r1"})["nodes"]
        self.assertEqual(t["e4 e5 Nf3"]["n"], 2)
        self.assertNotIn("games", t["e4"])

    def test_fingerprint_prefers_rare_matching_choice(self):
        otb = [{"sans": ["e4", "c5", "d4", "cxd4", "c3"], "is_white": True}] * 3
        morra = [{"sans": ["e4", "c5", "d4", "cxd4", "c3"], "white": "A", "black": "x"}] * 4
        normal = [{"sans": ["e4", "c5", "Nf3", "d6", "d4"], "white": "B", "black": "x"}] * 4
        tables = {"A": FP.node_table(morra, "A"), "B": FP.node_table(normal, "B")}
        s = FP.score_candidates(otb, tables)
        self.assertGreater(s["A"]["lift"], s["B"]["lift"])


class LichessTokens(unittest.TestCase):
    def test_all_tokens_in_order_and_rotation(self):
        import os
        from unittest import mock
        env = {"LICHESS_TOKEN_3": "t3", "LICHESS_TOKEN": "t1", "LICHESS_TOKEN_2": "t2", "LICHESS_TOKEN_X": "t1",
               "LICHESS_TOKENS": "kein-treffer"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "ROOT", Path(tmp)), \
                mock.patch.dict(os.environ, env, clear=False), mock.patch.object(P, "_tok_idx", 0), \
                mock.patch.object(P, "note", lambda m: None):
            self.assertEqual([k for k, _ in P._tokens()], ["LICHESS_TOKEN", "LICHESS_TOKEN_2", "LICHESS_TOKEN_3"])
            self.assertEqual(P._token(), "t1")
            self.assertTrue(P._rotate_token())
            self.assertEqual(P._token(), "t2")
            self.assertTrue(P._rotate_token())
            self.assertFalse(P._rotate_token())          # kein weiterer Token -> Aufrufer wartet
            self.assertEqual(P._token(), "t3")


class AccountFeatures(unittest.TestCase):
    def test_first_name_must_be_own_part_of_username(self):
        from chess_briefing.online.accounts import first_in_username as f
        for u in ("erster-Theo", "TheoK", "theo_2011", "Theo"):
            self.assertTrue(f("Theo", u), u)
        for u in ("Theodora", "atheon", "xTHEOx"):
            self.assertFalse(f("Theo", u), u)
        self.assertFalse(f("Jo", "Jo_x"))          # zu kurz, zu viele Zufallstreffer

    def test_lichess_inflated_low_and_blitz_curves_cross(self):
        from chess_briefing.online import rating_map as RM
        li = lambda r: RM.online_to_elo("lichess", "blitz", r)[0]
        cc = lambda r: RM.online_to_elo("chesscom", "blitz", r)[0]
        self.assertLess(li(1400), cc(1400))       # gleiche Zahl unten: Lichess ist weniger wert
        self.assertGreater(li(2600), cc(2600))    # oben: Chess.com-Zahl ist weniger wert -> Kreuzung
        self.assertIsNone(RM.online_to_elo("chesscom", "daily", 1500))
        self.assertGreaterEqual(li(600), 1400)    # FIDE-Untergrenze

    def test_several_over_threshold_without_margin_accept_none(self):
        from chess_briefing.online.accounts import select_accounts
        c = lambda u, p, plat="lichess", ov=None: {"platform": plat, "username": u, "confidence": p, "override": ov}
        acc, amb = select_accounts([c("a", 0.82), c("b", 0.78), c("x", 0.9, "chesscom")])
        self.assertEqual([a["username"] for a in acc], ["x"])          # je Plattform getrennt
        self.assertEqual({a["username"] for a in amb}, {"a", "b"})
        acc, _ = select_accounts([c("a", 0.95), c("b", 0.6)])          # Abstand >= 1 Log-Odds
        self.assertEqual([a["username"] for a in acc], ["a"])
        acc, _ = select_accounts([c("a", 0.8), c("b", 0.99, ov={"status": "bestätigt"})])
        self.assertEqual([a["username"] for a in acc], ["b"])

    def test_dwz_reference_when_no_elo(self):
        from chess_briefing.online import rating_map as RM
        ident = Identity(last="X", first="Y", elo={"blitz": 1896}, dsb={"dwz": 1767})
        ref = RM.reference(ident)
        self.assertEqual(ref["kind"], "DWZ")
        self.assertTrue(1800 < ref["elo"] < 1880)  # 1400–2000: Elo ~ DWZ + 100 (FIDE-Anhebung 2024)
        ok = RM.check("lichess", {"rapid": 2123, "blitz": 2076}, ref)
        self.assertEqual(ok["verdict"], "plausibel")
        bad = RM.check("lichess", {"blitz": 1100}, ref)
        self.assertEqual(bad["verdict"], "unplausibel")
        self.assertIsNone(RM.check("lichess", {}, ref))

    def test_username_pattern_is_weak_and_finds_name_prefixes(self):
        from chess_briefing.online import accounts as A
        self.assertTrue(A.pattern_matches("?b?u???", "Abdu_11"))
        self.assertFalse(A.pattern_matches("?b?u???", "abdu12"))           # Laenge gehoert zum Muster
        self.assertTrue(A.pattern_matches("ab*", "abX"))
        self.assertEqual(A.pattern_prefixes("?b?u???", ["Abdullah", "Aksoy"]), ["abdu", "abdul", "abdull", "abdulla"])
        self.assertEqual(A.pattern_prefixes("?b?u???", ["Aksoy"]), [])      # passt nicht -> keine Suche
        alone = 1 / (1 + math.exp(-A._logit({"pattern": 1, "club": 1})))
        self.assertLess(alone, A.ACCEPT)                                      # nie allein ausreichend
        self.assertLess(A._logit({"pattern_miss": 1, "fp": 1}), A._logit({"fp": 1}))


UNDATED = """[Event "SnoopChess OTB"]
[Site "?"]
[Date "????.??.??"]
[White "Freund, Dominik"]
[Black "Morphy, Paul"]
[Result "*"]

1. e4 c5 2. Nf3 d6 3. d4 cxd4 *

[Event "SnoopChess OTB"]
[Date "????.??.??"]
[White "Morphy, Paul"]
[Black "Adam, Max"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0
"""


class ImportWithoutDateOrResult(unittest.TestCase):
    def test_unknown_result_is_not_counted_as_loss_or_draw(self):
        from chess_briefing.metrics import _score
        from chess_briefing.openings import build_tree
        games = G.merge(G.parse_pgn(UNDATED, morphy()))
        self.assertEqual(len(games), 2)
        black = [g for g in games if not g["is_white"]][0]
        self.assertEqual((black["date"], black["player_score"]), ("", None))
        self.assertIsNone(build_tree(games, False, {})["nodes"][""]["score_pct"])     # nicht 0 %
        self.assertEqual(build_tree(games, True, {})["nodes"][""]["score_pct"], 100)
        self.assertIsNone(_score([None, None]))
        self.assertEqual(_score([None, 1.0, 0.0]), 50)
        self.assertIn('[Date "????"]', G.to_pgn(black))                                 # games.pgn ohne Datum


CR_GRID = """<form action="./PartieSuche.aspx?lan=1"><input type="hidden" name="__VIEWSTATE" value="x" />
<table class="CRs2" id="P1_GridView1"><tr><th>Game</th><th>Board Pairings</th><th>Res.</th><th>dbkey</th><th>Rd</th>
<th>Tournament</th><th>PGN</th><th>GameID</th></tr>
<tr><td><a href="javascript:x">Show</a></td><td>Morphy - Adam</td><td>1-0</td><td>123</td><td>3</td><td>Open</td>
<td>1. e4 e5 2. Nf3 Nc6</td><td>777</td></tr></table></form>"""
CR_PGN = """[Event "Open"]
[Round "3"]
[White "Morphy, P."]
[Black "Adam, Max"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0

[Event "Open 960"]
[Variant "chess 960"]
[FEN "bbqnnrkr/pppppppp/8/8/8/8/PPPPPPPP/BBQNNRKR w HFhf - 0 1"]
[SetUp "1"]
[White "Morphy, Paul"]
[Black "Adam, Max"]
[Result "1-0"]

1. e4 e5 1-0
"""


class ChessResults(unittest.TestCase):
    def test_grid_rows_and_bot_page(self):
        from bs4 import BeautifulSoup
        from chess_briefing.sources import chessresults as CR
        rows = CR._table_rows(BeautifulSoup(CR_GRID, "html.parser"))
        self.assertEqual((rows[0]["GameID"], rows[0]["Rd"]), ("777", "3"))
        with self.assertRaises(CR.Blocked):                  # keine Formularseite -> Browser-Schritt, keine Umgehung
            CR._form(BeautifulSoup("<html>Please verify you are human</html>", "html.parser"), CR.GAME_SEARCH)

    def test_fide_search_marks_side_and_skips_chess960(self):
        from chess_briefing.sources import chessresults as CR
        ident = Identity(last="Morphy", first="Paul", fide_id=1234)
        rows = [{"GameID": "777", "Rd": "3", "PGN": "1. e4 e5 2. Nf3 Nc6"}, {"GameID": "778", "Rd": "4", "PGN": "1. e4"}]
        out, empty, skipped = CR.tag_games(CR_PGN, rows, ident)
        self.assertEqual((len(out), empty, skipped), (1, 0, 1))
        g = G.parse_pgn(out[0], ident)[0]                    # "Morphy, P." nur ueber FideId-Kopf erkannt
        self.assertTrue(g["is_white"])
        self.assertEqual(g["source_urls"], [f"{CR.BASE}/PartieSuche.aspx?lan=1&art=36&id=777"])


if __name__ == "__main__":
    unittest.main()


class LichessAnalysis(unittest.TestCase):
    def test_best_move_belongs_to_position_before_the_error(self):
        from chess_briefing.online import lichess_analysis as LA
        sans = ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]
        g = {"ucis": [], "sans": sans}
        b = chess.Board()
        for s in sans:
            g["ucis"].append(b.push_san(s).uci())
        g["analysis"] = [{"eval": 30}, {"eval": 30}, {"eval": 0}, {"eval": 10}, {"eval": 20},
                         {"mate": 1, "best": "g7g6", "variation": "g6 Qf3 Nf6", "judgment": {"name": "Blunder"}}]
        pos = LA.positions(g)
        self.assertEqual(len(pos), len(sans) + 1)
        self.assertEqual(pos[5]["best"], "g7g6")          # Stellung vor 3...Nf6??
        self.assertEqual(pos[5]["pv"][0], "g6")
        self.assertEqual(pos[-1]["cp"], engine.MATE_CP)     # Matt am Ende ohne Analyse-Eintrag

    def test_time_trouble_threshold_is_relative(self):
        from chess_briefing.metrics import trouble_threshold
        self.assertEqual(trouble_threshold({"clocks": [5400.0], "increment_s": 30}), 300)    # 90+30 -> 5 min
        self.assertEqual(trouble_threshold({"clocks": [600.0], "increment_s": 5}), 60.5)     # 10+5 -> 10 %


class Remap(unittest.TestCase):
    def test_moved_evidence_is_remapped_changed_is_not(self):
        b = {"as_white": {"plan": [{"evidence": ["O2", "O3"]}]},
             "_evidence_snapshot": {"O2": "Text A", "O3": "Text B"}}
        moved = pipeline._remap(b, {"O7": "Text A", "O3": "Text B geändert"})
        self.assertEqual(moved, {"O2": "O7"})
        self.assertEqual(b["as_white"]["plan"][0]["evidence"], ["O7", "O3"])


class Profile(unittest.TestCase):
    FIT = {"a": math.log(0.06), "b": -0.12}    # 6 Fehler je 100 Zuege bei Elo 2000, je 100 Elo ~11 % weniger

    def test_only_move_positions_are_sharp(self):
        from chess_briefing import profile as PR
        m = {"phase": "Mittelspiel", "move_no": 20, "white": True, "best_san": "Nf3"}
        sharp = {"alt": {"wdl": [500, 400, 100], "wdl2": [200, 500, 300]}}     # 0,70 gegen 0,45
        quiet = {"alt": {"wdl": [500, 400, 100], "wdl2": [480, 420, 100]}}     # 0,70 gegen 0,69
        self.assertEqual(PR.move_class(m, sharp), "scharf")
        self.assertEqual(PR.move_class(m, quiet), "ruhig")
        self.assertEqual(PR.move_class(dict(m, white=False), sharp), "ruhig")  # fuer Schwarz ist Zug 2 besser
        self.assertEqual(PR.move_class(dict(m, phase="Endspiel"), sharp), "endspiel")
        self.assertIsNone(PR.move_class(m, {"alt": {"wdl": [1, 0, 0], "wdl2": None}}))   # nur ein legaler Zug

    def test_teil_elo_is_pulled_to_own_rating_with_few_moves(self):
        from chess_briefing import profile as PR
        few = PR.teil_elo(self.FIT, 20, 4, 1900)          # 20 % Fehler, aber nur 20 Zuege
        many = PR.teil_elo(self.FIT, 600, 120, 1900)      # gleiche Quote, viele Zuege
        self.assertTrue(few["open"])
        self.assertLess(many["elo"], few["elo"])          # viele Zuege -> naeher an der schlechten Quote
        self.assertLess(abs(few["elo"] - 1900), abs(many["elo"] - 1900))
        self.assertIsNone(PR.teil_elo(None, 100, 5, 1900)["elo"])

    def test_teil_elo_uses_rating_at_game_time(self):
        # heute 1900, die Partien stammen aus seiner 1700er-Zeit und zeigen genau 1700er-Fehler:
        # gemessen an der damaligen Wertung spielt er normal -> Teil-Elo = heutige Elo, nicht 1700
        from chess_briefing import profile as PR
        n = 500
        x = round(n * PR.rate_at(self.FIT, 1700))
        now = PR.teil_elo(self.FIT, n, x, 1900)                                   # ohne Zeitbezug: zu niedrig
        dated = PR.teil_elo(self.FIT, n, x, 1900, x0=n * PR.rate_at(self.FIT, 1700))
        self.assertLess(now["elo"], 1850)
        self.assertLess(abs(dated["elo"] - 1900), 15)

    def test_fit_needs_falling_error_rate(self):
        from chess_briefing import profile as PR
        rows = [{"elo": 1500 + 200 * k, "n": 400, "x": 40 - 6 * k} for k in range(5)]
        self.assertLess(PR._fit(rows)["b"], 0)
        self.assertIsNone(PR._fit([dict(r, x=10 + 6 * k) for k, r in enumerate(rows)]))

    def test_corridor_steers_to_smaller_gap_and_shifts_at_most_one_step_each(self):
        from chess_briefing import profile as PR
        te = {"scharf": {"elo": 2200, "open": False}, "ruhig": {"elo": 2000, "open": False},
              "endspiel": {"elo": 2100, "open": False}}
        d = {"profile": {"elo": 2100, "teil": te, "axes": {}}, "trees": {}}
        me = {"rating": {"value": 1900, "system": "Elo"}}
        self.assertEqual(PR.corridor(d, me)["target"], 1)             # Abstand ruhig 100 kleiner als scharf 300
        self.assertEqual(PR.corridor(d, dict(me, goal="sieg"))["target"], 2)   # schwaecher + Sieg noetig: +1
        self.assertEqual(PR.corridor(d, dict(me, goal="sieg", style=5))["target"], 3)
        c = PR.corridor(d, dict(me, weaknesses=["Taktik"]))
        self.assertEqual(c["my_teil"]["scharf"], 1900 - config.ME_ADJUST)
        self.assertTrue(all(f["id"].startswith("M") for f in c["facts"]))

    def test_me_evidence_limited_in_plan(self):
        b = _briefing()
        d = _dossier(online=False)
        d["facts"].append({"id": "M1", "text": "Nutzerangabe.", "scope": "all"})
        b["as_white"]["plan"] = [dict(s, evidence=["F1", "M1"]) for s in b["as_white"]["plan"]]
        P_, _ = validate_briefing(b, d)
        self.assertTrue(any("Eigenprofil" in p for p in P_))
