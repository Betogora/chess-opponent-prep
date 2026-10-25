"""Offline-Tests fuer die schnellen Stufen scout-fast und briefing-medium (ohne Netz, ohne Engine)."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chess_briefing import games as G  # noqa: E402
from chess_briefing.identify import parse_input  # noqa: E402
from chess_briefing.modes import common as C, scout as S  # noqa: E402
from chess_briefing.openings import build_tree  # noqa: E402
from chess_briefing.validate import validate_briefing  # noqa: E402
from tests.test_pipeline import FIX, _briefing, _dossier, morphy  # noqa: E402


class Deadline(unittest.TestCase):
    def test_slow_step_is_cut_off_and_reported(self):
        log = []
        t0 = time.monotonic()
        r = C.timed("langsam", lambda: time.sleep(5) or "zu spät", 0.3, log)
        self.assertIsNone(r)
        self.assertLess(time.monotonic() - t0, 2.0)          # wartet nicht auf die Quelle
        self.assertEqual(log[0]["status"], "zeitlimit")

    def test_parallel_steps_overlap_and_keep_their_order(self):
        def boom():
            raise ValueError("kaputt")
        t0 = time.monotonic()
        out = C.timed_all([("langsam", lambda: time.sleep(0.4) or "a", 5), ("schnell", lambda: "b", 5),
                           ("fehler", boom, 5), ("zu spät", lambda: time.sleep(5), 0.3)])
        self.assertLess(time.monotonic() - t0, 1.5)           # gleichzeitig, nicht 0,4 + 0,3 s nacheinander
        self.assertEqual([r for r, _, _ in out], ["a", "b", None, None])
        self.assertGreaterEqual(out[0][1], 0.4)               # Sekunden je Quelle
        self.assertEqual([n[0]["status"] for _, _, n in out[2:]], ["fehler", "zeitlimit"])
        self.assertIn("seconds", out[3][2][0])

    def test_no_budget_left_skips_step(self):
        log = []
        self.assertIsNone(C.timed("x", lambda: 1, 0, log))
        self.assertEqual(log[0]["status"], "uebersprungen")

    def test_errors_do_not_stop_the_run(self):
        log = []
        self.assertIsNone(C.timed("kaputt", lambda: 1 / 0, 2, log))
        self.assertEqual(log[0]["status"], "fehler")

    def test_deadline_without_budget_is_unlimited(self):
        self.assertEqual(C.Deadline(None).left(), float("inf"))
        self.assertIsNone(C.Deadline(None).at())
        d = C.Deadline(10)
        self.assertLessEqual(d.left(reserve=3), 7)

    def test_atomic_write_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.json"
            C.write_json_atomic(p, {"x": 1})
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"x": 1})
            self.assertEqual([f.name for f in Path(tmp).iterdir()], ["a.json"])


class Selection(unittest.TestCase):
    def test_newest_games_first_undated_last(self):
        gs = [{"date": "2024-05-01", "round": "1"}, {"date": "", "round": ""}, {"date": "2026-01-02", "round": "3"}]
        self.assertEqual([g["date"] for g in C.newest(gs, 2)], ["2026-01-02", "2024-05-01"])

    def test_results_count_only_scored_games(self):
        gs = [{"player_score": 1, "opponent_elo": 2000}, {"player_score": None, "opponent_elo": None},
              {"player_score": 0.5, "opponent_elo": 1800}]
        r = C.results(gs)
        self.assertEqual((r["games"], r["w"], r["d"], r["unscored"], r["score_pct"]), (3, 1, 1, 1, 75.0))

    def test_output_folders(self):
        p = Path("players/x")
        self.assertEqual(C.output_dir(p, "scout").name, "scout")
        self.assertEqual(C.output_dir(p, "briefing", "white").name, "briefing_ich-weiss")
        self.assertEqual(C.output_dir(p, "medium", "black").name, "briefing_ich-schwarz")   # alter Stufenname
        self.assertEqual(C.output_dir(p, "briefing", "both").name, "briefing")              # beide: ohne Farbe

    def test_chessbase_download_is_taken_into_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            dl, inbox = Path(tmp) / "Downloads", Path(tmp) / "inbox"
            dl.mkdir()
            inbox.mkdir()
            (dl / "Morphy_Paul.pgn").write_text(FIX.read_text(encoding="utf-8"), encoding="utf-8")
            (dl / "Anderer_Spieler.pgn").write_text("[Event \"x\"]", encoding="utf-8")
            got = C.pull_download(morphy(), inbox, dl)
            self.assertEqual(got.name, f"chessbase_{morphy().slug}.pgn")
            self.assertIsNone(C.pull_download(morphy(), inbox, dl))        # schon übernommen, nichts Neueres

    def test_chessbase_inbox_is_reused_and_flagged_when_old(self):
        import os
        from chess_briefing import config
        from chess_briefing.sources import chessbase
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            f = inbox / f"chessbase_{morphy().slug}.pgn"
            f.write_text(FIX.read_text(encoding="utf-8"), encoding="utf-8")
            txt, log = chessbase.collect(morphy(), inbox)
            self.assertTrue(txt and log[0]["status"] == "ok" and not log[0].get("stale"))
            old = time.time() - (config.CHESSBASE_MAX_AGE_DAYS + 1) * 86400
            os.utime(f, (old, old))
            txt, log = chessbase.collect(morphy(), inbox)
            self.assertTrue(txt)                                              # alte Datei wird weiter genutzt ...
            self.assertTrue(log[0]["stale"])                                  # ... aber zum Neuladen geraten
            self.assertIn(f"chessbase_{morphy().slug}.pgn", log[0]["hint"]["download_in_page"])

    def test_receiver_takes_exactly_its_file_and_stops(self):
        import threading
        import urllib.parse
        import urllib.request
        from chess_briefing import config, receiver
        old = config.PLAYERS_DIR
        with tempfile.TemporaryDirectory() as tmp:
            config.PLAYERS_DIR = Path(tmp)
            try:
                res = {}
                th = threading.Thread(target=lambda: res.setdefault("p", receiver.serve("muster_max", 10, port=8799)))
                th.start()
                time.sleep(0.3)
                body = urllib.parse.urlencode({"pgn": FIX.read_text(encoding="utf-8")}).encode()
                with self.assertRaises(Exception):            # fremder Dateiname wird abgelehnt
                    urllib.request.urlopen("http://127.0.0.1:8799/upload/chessbase_anderer.pgn", body, timeout=5)
                urllib.request.urlopen("http://127.0.0.1:8799/upload/chessbase_muster_max.pgn", body, timeout=5).read()
                th.join(5)
                self.assertFalse(th.is_alive())                # beendet sich nach dem Empfang
                self.assertIn("[Event ", res["p"].read_text(encoding="utf-8"))
            finally:
                config.PLAYERS_DIR = old

    def test_chessbase_link_without_number(self):
        p = parse_input("https://players.chessbase.com/de/player/mustermann_max")
        self.assertEqual((p["kind"], p["last"], p["first"]), ("chessbase_url", "Mustermann", "Max"))
        p = parse_input("https://players.chessbase.com/en/player/musterfrau_erika/123456")
        self.assertEqual((p["last"], p["first"]), ("Musterfrau", "Erika"))


def _game(sans, white, score, date, opp="Gegner, A"):
    import chess
    b, ucis = chess.Board(), []
    for s in sans:
        ucis.append(b.push_san(s).uci())
    g = {"white": "Morphy, Paul" if white else opp, "black": opp if white else "Morphy, Paul", "result": "*",
         "date": date, "event": "Test", "site": "", "round": "1", "white_elo": None, "black_elo": None, "eco": "",
         "opening_header": "", "time_control": "", "sans": sans, "ucis": ucis, "clocks": [], "sources": ["Test"],
         "source_urls": [], "is_white": white, "player_score": score, "opponent": opp, "opponent_elo": 1800,
         "player_elo": None}
    g["id"] = f"{date}{len(sans)}{white}{score}"
    return g


class Scout(unittest.TestCase):
    def games(self):
        line = ["e4", "c5", "Nf3", "d6", "d4", "cxd4"]
        return [_game(line + ["Nxd4", "Nf6"], False, 0, "2025-01-01"),
                _game(line + ["Nxd4", "a6"], False, 0.5, "2025-02-01"),
                _game(["d4", "Nf6", "c4", "e6"], False, 1, "2025-03-01"),
                _game(["e4", "e5", "Nf3", "Nc6"], True, 1, "2025-04-01")]

    def test_recurring_lines_stop_where_he_deviates(self):
        tree = build_tree(self.games(), False, {})
        lines = S.trunk_lines(tree)
        self.assertEqual(lines[0]["path"], "e4 c5 Nf3 d6 d4 cxd4 Nxd4")   # zweimal gleich, danach getrennt
        self.assertEqual(lines[0]["n"], 2)

    def test_rule_based_steckbrief_with_evidence_and_both_colors(self):
        d, viewer = S.build_scout(morphy(), self.games(), [], {}, [], "black")
        ids = {f["id"] for f in d["facts"]}
        b = d["briefing"]
        self.assertTrue(b["summary"])
        for s in b["summary"]:                                # jede Aussage hat einen vorhandenen Beleg
            self.assertTrue(s["evidence"] and set(s["evidence"]) <= ids)
        self.assertEqual(b["summary"][0]["title"], "Sein Repertoire mit Schwarz")   # seine Farbe zuerst
        self.assertEqual(d["color_stats"]["white"]["games"], 1)                    # andere Farbe bleibt enthalten
        self.assertEqual(len(viewer), 4)
        self.assertTrue(all(m["cp"] is None for mv in viewer.values() for m in mv))  # ohne Engine

    def test_scout_html_is_written_next_to_research(self):
        d, viewer = S.build_scout(morphy(), self.games(), [], {}, [], "white")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / d["identity"]["slug"] / "scout"
            C.write_json_atomic(out / "dossier.json", d)
            C.write_json_atomic(out / "viewer.json", viewer)
            from chess_briefing.render.html import render_player
            html = render_player(out)
            self.assertEqual(html.name, f"scout_{d['identity']['slug']}.html")
            self.assertEqual(html.parent, out.parent)
            t = html.read_text(encoding="utf-8")
            self.assertIn("Schnellcheck", t)
            self.assertIn("chess-opponent-scout-fast", t)

    def test_fixture_games_parse_for_scout(self):
        gs = G.merge(G.parse_pgn(FIX.read_text(encoding="utf-8"), morphy()))
        d, _ = S.build_scout(morphy(), gs, [], {}, [], "black")
        self.assertEqual(d["data"]["games"], 2)


class MediumValidation(unittest.TestCase):
    def dossier(self):
        d = _dossier(online=False)
        d["mode"] = {"name": "medium", "sides": ["as_white"], "min_plan_steps": 3}
        return d

    def test_only_users_side_is_required(self):
        b = _briefing()
        b.pop("as_black")
        P_, _ = validate_briefing(b, self.dossier())
        self.assertEqual(P_, [])

    def test_other_side_is_rejected(self):
        P_, _ = validate_briefing(_briefing(), self.dossier())
        self.assertTrue(any("nur für as_white" in p for p in P_))

    def test_research_still_needs_both_sides(self):
        b = _briefing()
        b.pop("as_black")
        P_, _ = validate_briefing(b, _dossier(online=False))
        self.assertTrue(any("as_black" in p for p in P_))


if __name__ == "__main__":
    unittest.main()
