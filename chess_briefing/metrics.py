"""Kennzahlen je Zug, je Partie und je Farbe des Gegners.

Konventionen:
  * Alle Werte aus Sicht des GEGNERS (des analysierten Spielers), sofern nicht anders genannt.
  * Erwartungswert (exp) = (W + D/2) / 1000 aus der Engine-WDL, 0..1.
  * Fehlerklassen nur in "lebenden" Stellungen (0.15 <= exp_vorher <= 0.85), Schwellen aus config.
  * Genauigkeit nach Lichess-Formel (aus Gewinnwahrscheinlichkeit je Zug), 0..100.
"""
from __future__ import annotations

import math
import re
import statistics as st
from collections import Counter, defaultdict

import chess

from . import config
from .openings import family, label_for_player, name_line

PHASES = ["Eröffnung", "Mittelspiel", "Endspiel"]


# ---------------------------------------------------------------- Helfer
def _exp(wdl) -> float:
    w, d, l = wdl
    t = (w + d + l) or 1
    return (w + 0.5 * d) / t


def _win_pct(cp: float) -> float:
    cp = max(-1000, min(1000, cp))
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def _move_accuracy(wp_before: float, wp_after: float) -> float:
    d = max(0.0, wp_before - wp_after)
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * d) - 3.1669))


def _pieces(board: chess.Board) -> int:
    return sum(len(board.pieces(pt, c)) for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
               for c in (chess.WHITE, chess.BLACK))


def _backrank_sparse(board: chess.Board) -> bool:
    w = sum(1 for sq in chess.SquareSet(chess.BB_RANK_1) if (p := board.piece_at(sq)) and p.color == chess.WHITE)
    b = sum(1 for sq in chess.SquareSet(chess.BB_RANK_8) if (p := board.piece_at(sq)) and p.color == chess.BLACK)
    return w < 4 or b < 4


def phases_for(ucis: list[str]) -> list[str]:
    """Phase je Zug (Stellung VOR dem Zug). Eroeffnung endet spaetestens nach Zug 15 oder
    sobald Figuren getauscht/entwickelt sind; Endspiel ab <= 6 Figuren (ohne Bauern/Koenige)."""
    b = chess.Board()
    out, phase = [], 0
    for u in ucis:
        pcs = _pieces(b)
        if phase < 2 and pcs <= config.PHASE_END_PIECES:
            phase = 2
        elif phase == 0 and (pcs <= config.PHASE_MIDDLE_PIECES or _backrank_sparse(b)
                             or b.fullmove_number > config.PHASE_OPENING_MAX_MOVE):
            phase = 1
        out.append(PHASES[phase])
        b.push(chess.Move.from_uci(u))
    return out


def _increment(tc: str) -> int | None:
    m = re.search(r"\+(\d+)", tc or "")
    return int(m.group(1)) if m else None


def infer_increment(clocks: list) -> int:
    """Inkrement aus Uhrzeiten schaetzen: groesster kleiner Zuwachs (<= 60 s) zwischen zwei eigenen Zuegen."""
    gains = []
    for i in range(2, len(clocks)):
        a, b = clocks[i - 2], clocks[i]
        if a is not None and b is not None and 0 < b - a <= 60:
            gains.append(b - a)
    if not gains:
        return 0
    g = max(gains)   # Uhren sind auf Sekunden gerundet und der Zug kostet Zeit -> auf uebliche Inkremente aufrunden
    return next((c for c in (2, 3, 5, 10, 15, 20, 30, 60) if c >= g), int(round(g)))


def time_control_label(g: dict) -> str:
    """'90+30' aus Startuhr und Inkrement (Minuten + Sekunden), sonst TimeControl-Header."""
    c = g.get("clocks") or []
    if g.get("time_control"):
        tc = g["time_control"]
        m = re.match(r"(\d+)\+(\d+)", tc)
        return f"{int(m.group(1)) // 60}+{m.group(2)}" if m else tc
    if c and c[0]:
        base = round((c[0] - (g.get("increment_s") or 0)) / 60 / 5) * 5
        return f"{base}+{g.get('increment_s') or 0}"
    return "?"


def _structure(board: chess.Board) -> dict:
    files_open = files_half = 0
    for f in range(8):
        mask = chess.BB_FILES[f]
        wp = board.pieces_mask(chess.PAWN, chess.WHITE) & mask
        bp = board.pieces_mask(chess.PAWN, chess.BLACK) & mask
        if not wp and not bp:
            files_open += 1
        elif not wp or not bp:
            files_half += 1
    typ = "offen" if files_open >= 2 else "halboffen" if (files_open == 1 or files_half >= 2) else "geschlossen"
    wk, bk = board.king(chess.WHITE), board.king(chess.BLACK)
    opp_castle = wk is not None and bk is not None and abs(chess.square_file(wk) - chess.square_file(bk)) >= 3
    return {"type": typ, "opposite_castling": opp_castle,
            "queens_on": bool(board.pieces(chess.QUEEN, chess.WHITE) or board.pieces(chess.QUEEN, chess.BLACK))}


# ---------------------------------------------------------------- je Partie
def annotate_game(g: dict, pos: list[dict]) -> dict:
    ucis = g["ucis"]
    phases = phases_for(ucis)
    inc = _increment(g.get("time_control", ""))
    clocks = g.get("clocks") or []
    if inc is None and clocks:
        inc = infer_increment(clocks)
    g["increment_s"] = inc
    moves = []
    queen_trade_move = None
    b = chess.Board()
    for i, u in enumerate(ucis):
        white_moves = b.turn == chess.WHITE
        pb, pa = pos[i], pos[i + 1]
        sgn = 1 if white_moves else -1
        cap = config.EVAL_CAP_CP
        before = max(-cap, min(cap, pb["cp"])) * sgn
        after = max(-cap, min(cap, pa["cp"])) * sgn
        cpl = min(config.CPL_CAP_CP, max(0, before - after))
        eb = _exp(pb["wdl"]) if white_moves else 1 - _exp(pb["wdl"])
        ea = _exp(pa["wdl"]) if white_moves else 1 - _exp(pa["wdl"])
        loss = max(0.0, eb - ea)
        live = config.LIVE_MIN <= eb <= config.LIVE_MAX
        level = ""
        if live:
            level = "blunder" if loss > config.EXP_BLUNDER else "mistake" if loss > config.EXP_MISTAKE \
                else "inaccuracy" if loss > config.EXP_INACCURACY else ""
        acc = _move_accuracy(_win_pct(before), _win_pct(after))
        clk = clocks[i] if i < len(clocks) else None
        spent = None
        if clk is not None and i >= 2 and i - 2 < len(clocks) and clocks[i - 2] is not None:
            spent = max(0.0, clocks[i - 2] - clk + (inc or 0))
        san = g["sans"][i]
        moves.append({
            "ply": i + 1, "move_no": b.fullmove_number, "white": white_moves, "san": san, "uci": u,
            "fen_before": b.fen(), "phase": phases[i],
            "cp_before": pb["cp"], "cp_after": pa["cp"], "mate_after": pa["mate"],
            "cpl": cpl, "exp_before": round(eb, 4), "exp_after": round(ea, 4), "loss": round(loss, 4),
            "live": live, "level": level, "accuracy": round(acc, 1),
            "best_san": pb.get("best_san"), "best_uci": pb.get("best"), "pv": pb.get("pv", []),
            "reply_pv": pa.get("pv", [])[:6],
            "is_best": pb.get("best") == u, "clock": clk, "spent": spent,
            "own": white_moves == g["is_white"],
        })
        b.push(chess.Move.from_uci(u))
        if queen_trade_move is None and not b.pieces(chess.QUEEN, chess.WHITE) and not b.pieces(chess.QUEEN, chess.BLACK):
            queen_trade_move = b.fullmove_number
    # Kipp-Punkte: Fehler + Bestand (naechste eigene Zuege bleiben unter 0.5)
    for side in (True, False):
        seq = [m for m in moves if m["white"] == side]
        for k, m in enumerate(seq):
            nxt = seq[k + 1:k + 1 + config.TIPPING_PERSIST]
            m["tipping"] = m["level"] in ("mistake", "blunder") and bool(nxt) and all(x["exp_before"] < 0.5 for x in nxt)
    eco, oname, _ = name_line(ucis)
    if not oname and g.get("opening_header"):
        oname = g["opening_header"]
    eco = eco or g.get("eco", "")
    own = [m for m in moves if m["own"]]
    opp = [m for m in moves if not m["own"]]
    exp_seq = [m["exp_before"] for m in own]
    # Struktur beim Uebergang ins Mittelspiel (erster Mittelspielzug) und Endspiel-Typ
    mid_idx = next((k for k, p in enumerate(phases) if p != "Eröffnung"), None)
    struct = None
    if mid_idx is not None:
        bb = chess.Board(moves[mid_idx]["fen_before"])
        struct = _structure(bb)
    end_idx = next((k for k, p in enumerate(phases) if p == "Endspiel"), None)
    endgame = _endgame_type(chess.Board(moves[end_idx]["fen_before"])) if end_idx is not None else None
    open_end = mid_idx if mid_idx is not None else len(moves)
    after_opening = moves[open_end - 1]["exp_after"] if open_end and own else None
    if after_opening is not None and not moves[open_end - 1]["own"]:
        after_opening = 1 - after_opening
    return {
        "id": g["id"], "moves": moves, "eco": eco, "opening": oname, "family": family(oname),
        "label": label_for_player(g),
        "accuracy": round(st.mean(m["accuracy"] for m in own), 1) if own else None,
        "opp_accuracy": round(st.mean(m["accuracy"] for m in opp), 1) if opp else None,
        "acpl": round(st.mean(m["cpl"] for m in own)) if own else None,
        "max_exp": max(exp_seq) if exp_seq else None, "min_exp": min(exp_seq) if exp_seq else None,
        "tipping": sum(1 for m in own if m["tipping"]),
        "opp_tipping": sum(1 for m in opp if m["tipping"]),
        "structure": struct, "endgame": endgame, "queen_trade_move": queen_trade_move,
        "exp_after_opening": after_opening, "plies": len(moves),
        "has_clock": any(m["clock"] is not None for m in own),
    }


def viewer_moves(g: dict, a: dict) -> list[dict]:
    """Zugdaten fuer den Partie-Viewer (Turnier und online gleich)."""
    return [{"san": m["san"], "uci": m["uci"], "fen": m["fen_before"], "cp": m["cp_after"], "mate": m["mate_after"],
             "exp": round(m["exp_after"] if m["white"] == g["is_white"] else 1 - m["exp_after"], 4),
             "lvl": m["level"], "tip": m["tipping"], "own": m["own"], "best": m["best_san"], "best_uci": m["best_uci"],
             "clk": m["clock"], "ph": m["phase"]} for m in a["moves"]]


def _endgame_type(b: chess.Board) -> str:
    def has(pt):
        return bool(b.pieces(pt, chess.WHITE) or b.pieces(pt, chess.BLACK))
    if has(chess.QUEEN):
        return "Damenendspiel" if not has(chess.ROOK) else "Schwerfigurenendspiel"
    if has(chess.ROOK):
        return "Turmendspiel" if not (has(chess.KNIGHT) or has(chess.BISHOP)) else "Turm + Leichtfigur"
    if has(chess.KNIGHT) or has(chess.BISHOP):
        return "Leichtfigurenendspiel"
    return "Bauernendspiel"


# ---------------------------------------------------------------- Aggregation
def _pct(a, b):
    return round(100 * a / b, 1) if b else None


def color_stats(games: list[dict], ann: dict[str, dict], white: bool) -> dict:
    gs = [g for g in games if g["is_white"] == white]
    res = Counter()
    for g in gs:
        sc = g["player_score"]
        res["w" if sc == 1 else "d" if sc == 0.5 else "l" if sc == 0 else "?"] += 1
    scored = [g["player_score"] for g in gs if g["player_score"] is not None]
    own = [m for g in gs for m in ann[g["id"]]["moves"] if m["own"]]
    live = [m for m in own if m["live"]]
    per_phase = {}
    for ph in PHASES:
        pm = [m for m in own if m["phase"] == ph]
        lm = [m for m in pm if m["live"]]
        per_phase[ph] = {
            "moves": len(pm), "live": len(lm),
            "accuracy": round(st.mean(m["accuracy"] for m in pm), 1) if pm else None,
            "acpl": round(st.mean(m["cpl"] for m in pm)) if pm else None,
            "loss_avg": round(100 * st.mean(m["loss"] for m in lm), 1) if lm else None,
            "inaccuracies": sum(m["level"] == "inaccuracy" for m in pm),
            "mistakes": sum(m["level"] == "mistake" for m in pm),
            "blunders": sum(m["level"] == "blunder" for m in pm),
            "tipping": sum(m["tipping"] for m in pm),
            "errors_per_100": round(100 * sum(m["level"] in ("mistake", "blunder") for m in lm) / len(lm), 1) if lm else None,
            "best_move_rate": _pct(sum(m["is_best"] for m in pm), len(pm)),
        }
    opp_elos = [g["opponent_elo"] for g in gs if g["opponent_elo"]]
    score_pct = _pct(sum(scored), len(scored))
    perf = None
    if opp_elos and scored:
        p = sum(scored) / len(scored)
        perf = round(st.mean(opp_elos) + 800 * (p - 0.5)) if 0 < p < 1 else round(st.mean(opp_elos) + (400 if p == 1 else -400))
    # Verwertung / Widerstand
    winning_all = [g for g in gs if (ann[g["id"]]["max_exp"] or 0) >= 0.80]
    losing_all = [g for g in gs if (ann[g["id"]]["min_exp"] if ann[g["id"]]["min_exp"] is not None else 1) <= 0.20]
    # Verwertung/Widerstand nur mit bekanntem Ergebnis; Faelle ohne Ergebnis werden getrennt gezaehlt
    winning = [g for g in winning_all if g["player_score"] is not None]
    losing = [g for g in losing_all if g["player_score"] is not None]
    after_open = [ann[g["id"]]["exp_after_opening"] for g in gs if ann[g["id"]]["exp_after_opening"] is not None]
    return {
        "games": len(gs), "w": res["w"], "d": res["d"], "l": res["l"], "unscored": res["?"], "score_pct": score_pct,
        "avg_opp_elo": round(st.mean(opp_elos)) if opp_elos else None, "performance": perf,
        "moves": len(own), "live_moves": len(live),
        "accuracy": round(st.mean(m["accuracy"] for m in own), 1) if own else None,
        "acpl": round(st.mean(m["cpl"] for m in own)) if own else None,
        "acpl_median": round(st.median(m["cpl"] for m in own)) if own else None,
        "mistakes": sum(m["level"] == "mistake" for m in own),
        "blunders": sum(m["level"] == "blunder" for m in own),
        "inaccuracies": sum(m["level"] == "inaccuracy" for m in own),
        "tipping": sum(m["tipping"] for m in own),
        "tipping_per_game": round(sum(m["tipping"] for m in own) / len(gs), 2) if gs else None,
        "opp_tipping": sum(ann[g["id"]]["opp_tipping"] for g in gs),
        "phases": per_phase,
        "conversion": {"games": len(winning),
                       "won": sum(1 for g in winning if g["player_score"] == 1),
                       "drawn": sum(1 for g in winning if g["player_score"] == 0.5),
                       "lost": sum(1 for g in winning if g["player_score"] == 0),
                       "unknown": len(winning_all) - len(winning)},
        "resilience": {"games": len(losing),
                       "saved": sum(1 for g in losing if g["player_score"] >= 0.5),
                       "won": sum(1 for g in losing if g["player_score"] == 1),
                       "unknown": len(losing_all) - len(losing)},
        "exp_after_opening": round(st.mean(after_open), 3) if after_open else None,
        "exp_after_opening_n": len(after_open),
    }


def trouble_threshold(g: dict) -> float:
    """Zeitnot-Schwelle in Sekunden: 5 min, bei kurzen Bedenkzeiten 10 % der Grundzeit."""
    c = g.get("clocks") or []
    base = (c[0] + (g.get("increment_s") or 0)) if c and c[0] else None
    return min(config.TIME_TROUBLE_SEC, config.TIME_TROUBLE_SHARE * base) if base else config.TIME_TROUBLE_SEC


def time_stats(games: list[dict], ann: dict[str, dict]) -> dict:
    gs = [g for g in games if ann[g["id"]]["has_clock"]]
    if not gs:
        return {"games": 0}
    marks = {}
    for mv in (20, 30, 40):
        vals = []
        for g in gs:
            own = [m for m in ann[g["id"]]["moves"] if m["own"] and m["move_no"] == mv and m["clock"] is not None]
            if own:
                vals.append(own[0]["clock"])
        marks[mv] = {"n": len(vals), "avg_min": round(st.mean(vals) / 60, 1) if vals else None,
                     "min_min": round(min(vals) / 60, 1) if vals else None}
    trouble_games, err_tt, mv_tt, err_norm, mv_norm = 0, 0, 0, 0, 0
    longest = []
    for g in gs:
        own = [m for m in ann[g["id"]]["moves"] if m["own"] and m["clock"] is not None]
        thr = trouble_threshold(g)
        if any(m["clock"] < thr and m["move_no"] <= 40 for m in own):
            trouble_games += 1
        for m in own:
            bad = m["level"] in ("mistake", "blunder")
            if m["clock"] < thr:
                mv_tt += 1
                err_tt += bad
            else:
                mv_norm += 1
                err_norm += bad
        for m in own:
            if m["spent"] is not None:
                longest.append({"game": g["id"], "move_no": m["move_no"], "san": m["san"], "white": m["white"],
                                "spent_min": round(m["spent"] / 60, 1), "phase": m["phase"], "level": m["level"]})
    longest.sort(key=lambda x: -x["spent_min"])
    by_phase = defaultdict(list)
    for g in gs:
        for m in ann[g["id"]]["moves"]:
            if m["own"] and m["spent"] is not None:
                by_phase[m["phase"]].append(m["spent"])
    return {
        "games": len(gs), "time_controls": sorted({time_control_label(g) for g in gs}),
        "clock_at": marks, "trouble_games": trouble_games,
        "moves_in_trouble": mv_tt, "errors_in_trouble": err_tt,
        "moves_normal": mv_norm, "errors_normal": err_norm,
        "avg_spent_by_phase_min": {ph: round(st.mean(v) / 60, 1) for ph, v in by_phase.items() if v},
        "longest_thinks": longest[:6],
    }


def _picks_per_game(moves: list[dict], per_game: int) -> list[tuple[dict, bool]]:
    """Hoechstens per_game Fehler einer Partie: zuerst der letzte entscheidende (danach kam sein Erwartungswert
    nie mehr auf das Niveau vor dem Fehler zurueck), dann weitere entscheidende, dann der groesste uebrige Fehler."""
    own = [m for m in moves if m["own"]]
    errs = [m for m in own if m["level"] in ("mistake", "blunder")]

    def decisive(m):
        return not any(x["exp_before"] >= m["exp_before"] - config.EXP_MISTAKE for x in own if x["ply"] > m["ply"])
    dec = [m for m in errs if decisive(m)]
    picks = [dec[-1]] if dec else []
    rest = sorted((m for m in errs if m is not (picks[0] if picks else None)),
                  key=lambda m: (m not in dec, -m["loss"]))
    picks += rest[:per_game - len(picks)]
    return [(m, m in dec) for m in sorted(picks, key=lambda m: m["ply"])]


def key_moments(games: list[dict], ann: dict[str, dict], limit: int = 10, per_game: int = 2) -> list[dict]:
    out = []
    for g in games:
        for m, dec in _picks_per_game(ann[g["id"]]["moves"], per_game):
            out.append({
                "game": g["id"], "white": g["white"], "black": g["black"], "date": g["date"],
                "opponent": g["opponent"], "is_white": g["is_white"], "result": g["result"],
                "move_no": m["move_no"], "ply": m["ply"], "san": m["san"], "best_san": m["best_san"],
                "pv": m["pv"][:6], "fen": m["fen_before"], "phase": m["phase"], "level": m["level"],
                "exp_before": m["exp_before"], "exp_after": m["exp_after"], "loss": m["loss"],
                "tipping": m["tipping"], "decisive": dec, "clock_min": round(m["clock"] / 60, 1) if m["clock"] is not None else None,
                "uci": m["uci"], "best_uci": m["best_uci"],
                "refutation": m["reply_pv"], "cp_after": m["cp_after"], "mate_after": m["mate_after"],
            })
    years = sorted({int(x["date"][:4]) for x in out if x["date"][:4].isdigit()})
    newest = years[-1] if years else 0

    def weight(x):
        y = int(x["date"][:4]) if x["date"][:4].isdigit() else newest - 5
        return x["loss"] * (1.0 if newest - y <= 2 else 0.7) * (1.5 if x["decisive"] else 1.0)
    out.sort(key=lambda x: (-weight(x), x["date"]))
    return out[:limit]


def opponent_errors(games: list[dict], ann: dict[str, dict]) -> dict:
    """Wie reagiert er auf gegnerische Fehler? (verpasste Bestrafung = eigener Folgezug mit Verlust)"""
    total = punished = 0
    for g in games:
        mv = ann[g["id"]]["moves"]
        for k, m in enumerate(mv):
            if not m["own"] and m["level"] in ("mistake", "blunder") and k + 1 < len(mv):
                total += 1
                nxt = mv[k + 1]
                if nxt["loss"] <= config.EXP_INACCURACY:
                    punished += 1
    return {"opp_errors": total, "punished_next_move": punished}


def _score(scores: list) -> int | None:
    """Score in % nur ueber Partien mit Ergebnis; None, wenn keine ein Ergebnis hat."""
    s = [x for x in scores if x is not None]
    return round(100 * sum(s) / len(s)) if s else None


def structure_stats(games: list[dict], ann: dict[str, dict]) -> dict:
    out = {}
    for white in (True, False):
        gs = [g for g in games if g["is_white"] == white]
        types = defaultdict(list)
        for g in gs:
            s = ann[g["id"]]["structure"]
            if s:
                types[s["type"]].append(g["player_score"])
        eg = defaultdict(list)
        for g in gs:
            e = ann[g["id"]]["endgame"]
            if e:
                eg[e].append(g["player_score"])
        qt = [g for g in gs if (ann[g["id"]]["queen_trade_move"] or 99) <= 25]
        opp_c = [g for g in gs if (ann[g["id"]]["structure"] or {}).get("opposite_castling")]
        out["white" if white else "black"] = {
            "structure": {k: {"n": len(v), "score": _score(v)} for k, v in types.items()},
            "endgames": {k: {"n": len(v), "score": _score(v)} for k, v in eg.items()},
            "early_queen_trade": {"n": len(qt), "score": _score([g["player_score"] for g in qt])},
            "opposite_castling": {"n": len(opp_c), "score": _score([g["player_score"] for g in opp_c])},
        }
    return out


def team_stats(rows: list[dict]) -> dict:
    if not rows:
        return {}
    def sc(r):
        return {"1": 1.0, "0": 0.0, "½": 0.5, "+": 1.0, "-": 0.0}.get(r["result"])
    played = [r for r in rows if r["result"] not in ("+", "-")]
    by = {}
    for col in ("white", "black"):
        rr = [r for r in played if r["color"] == col]
        s = [sc(r) for r in rr if sc(r) is not None]
        dwz = [r["opponent_dwz"] for r in rr if r["opponent_dwz"]]
        by[col] = {"games": len(rr), "points": sum(s), "score_pct": _pct(sum(s), len(s)),
                   "avg_opp_dwz": round(st.mean(dwz)) if dwz else None}
    seasons = defaultdict(list)
    for r in played:
        seasons[r["season"]].append(r)
    season_rows = []
    for s_, rr in sorted(seasons.items(), reverse=True):
        s = [sc(r) for r in rr if sc(r) is not None]
        boards = [r["board"] for r in rr if r["board"]]
        dwz = [r["opponent_dwz"] for r in rr if r["opponent_dwz"]]
        divs = []
        for r in rr:
            if r["division"] not in divs:
                divs.append(r["division"])
        season_rows.append({"season": s_, "team": rr[0]["team"], "division": ", ".join(divs),
                            "games": len(rr), "points": sum(s),
                            "boards": f"{min(boards)}–{max(boards)}" if boards else "",
                            "avg_opp_dwz": round(st.mean(dwz)) if dwz else None})
    recent = sorted(played, key=lambda r: (r["season"], r["date"], r["round"]), reverse=True)[:10]
    return {"total": len(rows), "played": len(played), "forfeits": len(rows) - len(played),
            "by_color": by, "seasons": season_rows, "recent": recent}
