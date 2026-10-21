"""Lichess-Serveranalyse -> Stellungsformat von engine.py, damit Online-Partien ohne lokales Stockfish
durch metrics.annotate_game laufen (Fehlerklassen, Kipp-Punkte, Uhr, Schluesselstellungen, Viewer-Kurve).

Lichess-Export (evals=true): analysis[i] = Bewertung NACH Halbzug i (Weiss-Sicht, cp oder mate);
bei Fehlern zusaetzlich best (UCI) und variation (SAN) = was STATT Halbzug i besser war.
clocks: Restzeit des Ziehenden nach jedem Halbzug in Hundertstelsekunden.
"""
from __future__ import annotations

import chess
import chess.engine

from ..engine import MATE_CP, _terminal

START_CP = 20   # Grundstellung (Stockfish ~ +0.2); Lichess liefert dafuer keinen Wert


def _score(cp=None, mate=None) -> chess.engine.Score:
    return chess.engine.Mate(mate) if mate is not None else chess.engine.Cp(int(cp or 0))


def positions(g: dict) -> list[dict] | None:
    """Liste mit len(ucis)+1 Stellungen ({cp, mate, wdl, best, best_san, pv}) oder None ohne Analyse."""
    an = g.get("analysis") or []
    n = len(g["ucis"])
    if len(an) < n - 1:            # letzte Stellung (Matt) fehlt manchmal; sonst unvollstaendig -> keine Auswertung
        return None
    b = chess.Board()
    sc0 = _score(START_CP)
    pos = [{"cp": START_CP, "mate": None, "wdl": list(_wdl(sc0, 0)), "best": None, "best_san": None, "pv": []}]
    for i, u in enumerate(g["ucis"]):
        b.push(chess.Move.from_uci(u))
        t = _terminal(b)
        if t is None:
            e = an[i] if i < len(an) else {}
            if "eval" not in e and "mate" not in e:
                return None
            sc = _score(e.get("eval"), e.get("mate"))
            t = {"cp": sc.score(mate_score=MATE_CP), "mate": sc.mate(), "wdl": list(_wdl(sc, b.ply())),
                 "best": None, "best_san": None, "pv": []}
        pos.append(t)
    for i, e in enumerate(an[:n]):           # besserer Zug gehoert zur Stellung VOR Halbzug i
        if e.get("best"):
            var = (e.get("variation") or "").split()
            pos[i].update(best=e["best"], best_san=var[0] if var else None, pv=var[:8])
    return pos


def _wdl(score: chess.engine.Score, ply: int) -> tuple[int, int, int]:
    w = score.wdl(model="sf", ply=ply)
    return (w.wins, w.draws, w.losses)


def as_game(g: dict) -> dict:
    """Online-Datensatz um die Felder ergaenzen, die metrics.annotate_game erwartet."""
    cl = g.get("clocks_cs") or []
    out = dict(g)
    out["clocks"] = [c / 100 for c in cl[:len(g["ucis"])]] if cl else []
    out["time_control"] = g.get("time_control") or ""
    out["opening_header"] = (g.get("opening") or {}).get("name", "")
    out["eco"] = (g.get("opening") or {}).get("eco", "")
    return out
