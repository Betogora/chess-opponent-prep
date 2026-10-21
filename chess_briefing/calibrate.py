"""Vergleichskurven fuer das Spielerprofil: Fehlerquote je Elo und Stellungsart, Vergleichswerte je Ratingband.

Quelle: Lichess-Uebertragungen von Turnierpartien (echte FIDE-Elo, meist mit Uhrzeiten). Die Turnierliste steht in
data/calibration_tours.json (wird mit --discover aus den Uebertragungen der vorhandenen Gegner ergaenzt).
Auswahl ohne Zufall: Partien nach ID sortiert, aufgenommen solange eine ihrer Seiten in einem Band noch fehlt.
Analyse wie beim Gegner (engine.analyse_games, zweitbester Zug fuer beide Seiten); jede Partie zaehlt fuer beide Seiten.
Ergebnis: data/elo_curves.json (nur Durchschnittswerte, keine Partien) - darf weitergegeben werden.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import statistics as st

import chess.pgn

from . import config, engine, metrics
from .games import record
from .metrics import PHASES
from .profile import CLASSES, CURVES_FILE, _fit, side_stats
from .sources import lichess
from .util import fetch, log, read_json, write_json

TOURS_FILE = config.DATA_DIR / "calibration_tours.json"


def band_of(elo: int) -> int | None:
    k = (elo - config.CALIB_BAND_LO) // config.CALIB_BAND_W
    if elo < config.CALIB_BAND_LO - 100 or k >= config.CALIB_BANDS:
        return None
    return max(0, k)


def band_center(k: int) -> int:
    return config.CALIB_BAND_LO + config.CALIB_BAND_W * k + config.CALIB_BAND_W // 2


def discover() -> list[str]:
    """Turnier-IDs aus den Lichess-Uebertragungen aller vorhandenen Gegner (output/players/*/identity.json)."""
    tours = set((read_json(TOURS_FILE) or {}).get("tours", []))
    for idf in sorted(config.PLAYERS_DIR.glob("*/identity.json")):
        fid = (read_json(idf) or {}).get("fide_id")
        if not fid:
            continue
        for rnd in lichess.broadcast_rounds(fid):
            t = lichess.tour_of_round(rnd["round_id"])
            if t and t.get("id"):
                tours.add(t["id"])
    out = sorted(tours)
    write_json(TOURS_FILE, {"tours": out, "note": "Lichess-Broadcast-Turniere fuer briefing.py calibrate"})
    return out


def _long_time(g: chess.pgn.Game, rec: dict) -> bool:
    c = rec["clocks"]
    if c and c[0]:
        return c[0] >= 0.9 * config.CALIB_MIN_BASE_SEC
    tc = g.headers.get("TimeControl", "")
    try:
        return int(tc.split("+")[0].split("/")[-1]) >= config.CALIB_MIN_BASE_SEC
    except ValueError:
        return False


def candidates(tours: list[str]) -> list[tuple[str, dict, dict]]:
    """(id, Datensatz Weiss, Datensatz Schwarz) fuer alle geeigneten Partien, sortiert nach ID."""
    seen, out = set(), []
    for tid in tours:
        pgn = fetch(f"https://lichess.org/api/broadcast/{tid}.pgn", ttl_hours=24 * 365)
        if not pgn:
            log(f"  ! Turnier {tid} nicht geladen")
            continue
        stream = io.StringIO(pgn)
        while True:
            try:
                g = chess.pgn.read_game(stream)
            except Exception:  # noqa: BLE001 - kaputte Einzelpartie ueberspringen
                continue
            if g is None:
                break
            h = g.headers
            if h.get("Variant", "Standard") != "Standard":
                continue
            try:
                we, be = int(h.get("WhiteElo", "0")), int(h.get("BlackElo", "0"))
            except ValueError:
                continue
            if band_of(we) is None or band_of(be) is None:
                continue
            w = record(g, True)
            if not w or len(w["ucis"]) < 40 or w["player_score"] is None or not _long_time(g, w):
                continue
            gid = hashlib.sha1(("|".join(w["ucis"]) + h.get("White", "") + h.get("Black", "")).encode()).hexdigest()[:12]
            if gid in seen:
                continue
            seen.add(gid)
            b = record(g, False)
            w["id"] = b["id"] = gid
            out.append((gid, w, b))
    out.sort(key=lambda x: x[0])
    return out


def select(cands, per_band: int) -> list[tuple[str, dict, dict]]:
    need = [per_band] * config.CALIB_BANDS
    out = []
    for c in cands:
        bw, bb = band_of(c[1]["player_elo"]), band_of(c[2]["player_elo"])
        if need[bw] > 0 or need[bb] > 0:
            out.append(c)
            need[bw] -= 1
            need[bb] -= 1
        if all(n <= 0 for n in need):
            break
    return out


def _agg(rows: list[dict], elo: int) -> dict:
    def rate(hits, n):
        return round(hits / n, 4) if n else None
    marks = [sum(r["markers"].values()) for r in rows]
    sh = [r["clock30_share"] for r in rows if r["clock30_share"] is not None]
    tt = [r["trouble"] for r in rows if r["trouble"] is not None]
    win = [r for r in rows if r["winning"]]
    los = [r for r in rows if r["losing"]]
    oe = sum(r["opp_errors"] for r in rows)
    return {
        "elo": elo, "sides": len(rows),
        "markers_mean": round(st.mean(marks), 4) if marks else None,
        "markers_sd": round(st.pstdev(marks), 4) if len(marks) > 1 else None,
        "draw_rate": rate(sum(1 for r in rows if r["score"] == 0.5), len(rows)),
        "conversion": rate(sum(1 for r in win if r["score"] == 1), len(win)), "conversion_n": len(win),
        "resilience": rate(sum(1 for r in los if r["score"] >= 0.5), len(los)), "resilience_n": len(los),
        "punish": rate(sum(r["punished"] for r in rows), oe), "punish_n": oe,
        "clock30_mean": round(st.mean(sh), 4) if sh else None,
        "clock30_sd": round(st.pstdev(sh), 4) if len(sh) > 1 else None, "clock_n": len(sh),
        "trouble_rate": rate(sum(tt), len(tt)),
    }


def run(per_band: int | None = None, do_discover: bool = False, workers: int | None = None) -> int:
    per_band = per_band or config.CALIB_SIDES
    tours = discover() if do_discover or not TOURS_FILE.exists() else (read_json(TOURS_FILE) or {}).get("tours", [])
    log(f"-- Kalibrierung: {len(tours)} Turniere")
    cands = candidates(tours)
    chosen = select(cands, per_band)
    log(f"   {len(cands)} geeignete Partien (lange Bedenkzeit, beide Elo), {len(chosen)} ausgewählt")
    cache = config.CACHE_DIR / "calibration" / "analysis"
    pos = engine.analyse_games([w for _, w, _ in chosen], cache, workers=workers, alt_all=True)
    by_band: dict[int, list[dict]] = {k: [] for k in range(config.CALIB_BANDS)}
    for gid, w, b in chosen:
        for rec in (w, b):
            gg = dict(rec)
            a = metrics.annotate_game(gg, pos[gid])
            by_band[band_of(rec["player_elo"])].append(side_stats(gg, a, pos[gid]))
    bands = [_agg(rows, band_center(k)) for k, rows in by_band.items() if rows]

    def curve(key_fn, names):
        out = {}
        for c in names:
            rows = []
            for k, rr in by_band.items():
                n = sum(key_fn(r)[c][0] for r in rr)
                x = sum(key_fn(r)[c][1] for r in rr)
                rows.append({"elo": band_center(k), "n": n, "x": x, "rate_per_100": round(100 * x / n, 2) if n else None})
            out[c] = {"bands": rows, "fit": _fit(rows)}
        return out
    data = {
        "meta": {"created": dt.date.today().isoformat(), "engine": engine.engine_label(),
                 "depth": config.ENGINE_DEPTH, "shallow_depth": config.ENGINE_SHALLOW_DEPTH,
                 "alt_depth": config.ENGINE_ALT_DEPTH, "only_move_gap": config.ONLY_MOVE_GAP,
                 "games": len(chosen), "sides": sum(len(v) for v in by_band.values()), "tours": tours,
                 "min_base_sec": config.CALIB_MIN_BASE_SEC},
        "classes": curve(lambda r: r["classes"], CLASSES),
        "phases": curve(lambda r: r["phases"], PHASES),
        "bands": bands,
    }
    write_json(CURVES_FILE, data)
    for c, v in data["classes"].items():
        log(f"   {c:9} " + " | ".join(f"{r['elo']}: {r['rate_per_100']} ({r['n']})" for r in v["bands"])
            + f"  Fit {v['fit']}")
    log(f"-- fertig: {CURVES_FILE}")
    return 0
