"""Gemeinsame Bausteine der schnellen Stufen (scout-fast, briefing-medium).

* Deadline: feste Zeitgrenze ab Programmstart; jede Stufe fragt die Restzeit ab.
* timed(): Netzschritt mit Zeitlimit in einem Hintergrund-Thread; laeuft er zu lange, geht es ohne ihn weiter.
* timed_all(): mehrere solche Schritte gleichzeitig, Ergebnisse in fester Reihenfolge.
* fast_sources(): nur Quellen, die sofort da sind (inbox/-PGNs: ChessBase, chess-results, lokale Importe), parallel.
* plain_annotation(): Partie-Kennzeichen ohne Engine (Eroeffnungsname, Struktur, Uhr) fuer Baum und Viewer.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

import chess

from .. import config, games as G
from ..openings import family, label_for_player, name_line
from ..util import log, log_tag, set_log_tag

COLOR_DE = {"white": "Weiß", "black": "Schwarz"}
COLORS = ("white", "black", "both")


def opponent_colors(color: str) -> list[str]:
    """Farbe(n) des Gegners, die betrachtet werden: Nutzer hat Weiss -> Gegner Schwarz; "both" -> beide."""
    if color == "both":
        return ["white", "black"]
    return ["black" if color == "white" else "white"]


class Deadline:
    """Zeitgrenze in Sekunden ab Erzeugung. budget=None oder 0 -> keine Grenze."""

    def __init__(self, budget: float | None):
        self.t0 = time.monotonic()
        self.budget = budget or None

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    def left(self, reserve: float = 0.0) -> float:
        if self.budget is None:
            return float("inf")
        return max(0.0, self.budget - self.elapsed() - reserve)

    def at(self, reserve: float = 0.0) -> float | None:
        """Absoluter Zeitpunkt (time.monotonic) fuer Schritte, die selbst abbrechen koennen (Engine)."""
        return None if self.budget is None else self.t0 + self.budget - reserve


class Timer:
    """Laufzeit je Stufe fuer den Abschlussbericht und die Messung der Performance."""

    def __init__(self):
        self.t = time.monotonic()
        self.steps: list[tuple[str, float]] = []

    def lap(self, name: str) -> None:
        now = time.monotonic()
        self.steps.append((name, round(now - self.t, 1)))
        self.t = now

    def report(self) -> str:
        return " · ".join(f"{n} {s:.1f} s" for n, s in self.steps) + f" · gesamt {sum(s for _, s in self.steps):.1f} s"


def timed(name: str, fn, seconds: float, srclog: list | None = None):
    """fn() mit Zeitlimit. Ergebnis oder None (Fehler/Zeitlimit werden protokolliert, der Lauf geht weiter)."""
    if seconds <= 0:
        _note(srclog, name, "uebersprungen", "kein Zeitbudget mehr")
        return None
    box: dict = {}

    def run():
        try:
            box["r"] = fn()
        except Exception as ex:  # noqa: BLE001 - eine Quelle darf den Lauf nicht abbrechen
            box["e"] = ex
    th = threading.Thread(target=run, daemon=True, name=f"timed-{name}")
    th.start()
    th.join(seconds)
    if th.is_alive():
        log(f"   ! {name}: Zeitlimit {seconds:.0f} s erreicht, ohne diese Quelle weiter")
        _note(srclog, name, "zeitlimit", f"nach {seconds:.0f} s abgebrochen")
        return None
    if "e" in box:
        log(f"   ! {name} fehlgeschlagen: {type(box['e']).__name__}: {box['e']}")
        _note(srclog, name, "fehler", f"{type(box['e']).__name__}: {box['e']}"[:200])
        return None
    return box.get("r")


def timed_all(tasks: list[tuple]) -> list[tuple]:
    """Mehrere (name, fn, Sekunden) wie timed(), aber gleichzeitig: die Quellen warten aufeinander nicht mehr.
    Rueckgabe in der Reihenfolge von tasks, unabhaengig davon, welche Quelle zuerst fertig ist:
    (Ergebnis oder None, Sekunden, Hinweise fuer das Quellenprotokoll bei Fehler oder Zeitlimit)."""
    tag = log_tag()
    out: list = [None] * len(tasks)
    notes: list[list] = [[] for _ in tasks]

    def run(k, name, fn, seconds):
        set_log_tag(tag)
        t = time.monotonic()
        r = timed(name, fn, seconds, notes[k])
        secs = round(time.monotonic() - t, 1)
        out[k] = (r, secs, [dict(n, seconds=secs) for n in notes[k]])
    ths = [threading.Thread(target=run, args=(k, *task), daemon=True, name=f"quelle-{task[0]}")
           for k, task in enumerate(tasks)]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    return out


def _note(srclog, name, status, detail):
    if srclog is not None:
        srclog.append({"source": name, "status": status, "detail": detail})


def write_atomic(path: Path, text: str) -> None:
    """Erst in eine Nachbardatei schreiben, dann umbenennen: ein Abbruch hinterlaesst nie eine halbe Datei."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        for attempt in range(10):             # Windows/OneDrive sperren die Zieldatei kurz (WinError 5)
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.2 * (attempt + 1))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, obj) -> None:
    import json
    write_atomic(path, json.dumps(obj, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- Quellen
DOWNLOAD_MAX_AGE_H = 72


def pull_download(ident, inbox: Path, downloads: Path | None = None) -> Path | None:
    """ChessBase-PGN aus dem Download-Ordner uebernehmen (im eigenen Browser gespeichert, z. B. Mustermann_Max.pgn
    oder chessbase_mustermann_max.pgn, hoechstens DOWNLOAD_MAX_AGE_H alt) -> inbox/chessbase_<slug>.pgn.
    Spart den Browser-Schritt des Agenten. Neuere Datei gewinnt; eine aeltere ersetzt nie die vorhandene."""
    from ..sources.chessbase import pgn_path_on_site
    downloads = downloads or Path.home() / "Downloads"
    if not downloads.is_dir():
        return None
    names = {Path(pgn_path_on_site(ident)).name.lower(), f"chessbase_{ident.slug}.pgn"}
    cut = time.time() - DOWNLOAD_MAX_AGE_H * 3600
    hits = sorted((f for f in downloads.glob("*.pgn") if f.name.lower() in names and f.stat().st_mtime >= cut),
                  key=lambda f: f.stat().st_mtime, reverse=True)
    if not hits:
        return None
    target = inbox / f"chessbase_{ident.slug}.pgn"
    if target.exists() and target.stat().st_mtime >= hits[0].stat().st_mtime:
        return None
    txt = hits[0].read_bytes().decode("utf-8", errors="replace")
    if "[Event " not in txt:
        return None
    write_atomic(target, txt.replace("\r\n", "\n"))
    log(f"   ChessBase-PGN aus dem Download-Ordner übernommen: {hits[0].name} ({txt.count('[Event ')} Partien)")
    return target


def fast_sources(ident, inbox: Path, dl: Deadline, srclog: list, chessresults_s: float = 45.0) -> list[dict]:
    """Partien aus Quellen, die ohne langes Laden da sind: ChessBase (inbox oder Direktabruf), chess-results
    (inbox oder kurzer Abruf mit Zeitlimit), lokale PGNs. Keine Lichess-Uebertragungen, kein NSV, keine Online-Suche."""
    from ..sources import chessbase, chessresults, local
    pull_download(ident, inbox)
    texts = []
    tasks = [("chessbase", lambda: chessbase.collect(ident, inbox), 20.0),
             ("chess-results", lambda: chessresults.collect(ident, inbox), chessresults_s),
             ("lokal", lambda: local.collect(ident, inbox), 15.0)]
    for r, secs, notes in timed_all([(n, fn, min(limit, dl.left(reserve=20))) for n, fn, limit in tasks]):
        srclog += notes
        if r:
            texts.append(r[0])
            srclog += [dict(row, seconds=secs) for row in r[1]]
    games = []
    for t in texts:
        if t:
            games += G.parse_pgn(t, ident)
    merged = G.merge(games)
    log(f"   {len(games)} Partien eingelesen -> {len(merged)} nach Dublettenabgleich")
    return merged


def browser_notes(srclog: list) -> None:
    for s in srclog:
        label = {"chessbase": "ChessBase", "chess-results": "chess-results.com"}.get(s["source"], s["source"])
        if s.get("status") == "browser_noetig":
            h = s["hint"]
            if h.get("receiver_in_page"):
                log(f"   ! {label} braucht den Browser: `{h['receive']}` starten, {h['open']} öffnen und dort ausführen "
                    f"(kein Dialog, die Datei landet direkt in inbox/):\n     {h['receiver_in_page']}")
            else:
                log(f"   ! {label} braucht den Browser: {h['open']} -> {h.get('fetch_in_page') or h.get('steps')} -> {h['save_as']}")
        elif s.get("stale"):
            log(f"   · {label}-Partien sind {s['age_days']:.0f} Tage alt (wiederverwendet). Neu laden: `{s['hint']['receive']}` "
                f"starten, {s['hint']['open']} öffnen und ausführen:\n     {s['hint']['receiver_in_page']}")
        elif s.get("source") == "chessbase" and s.get("age_days") is not None:
            fresh = s["age_days"] < 0.05
            log(f"   ChessBase: {s['games']} Partien aus inbox/ " + ("(gerade geholt)" if fresh else
                f"wiederverwendet ({s['age_days']:.1f} Tage alt)"))


def lichess_fallback(ident, dl: Deadline, srclog: list, seconds: float) -> list[dict]:
    """Lichess-Uebertragungen nur als Ersatz (zu wenige Partien), mit Zeitlimit."""
    from ..sources import lichess
    r = timed("lichess", lambda: lichess.collect(ident), min(seconds, dl.left(reserve=60)), srclog)
    if not r:
        return []
    srclog += r[1]
    return G.parse_pgn(r[0], ident) if r[0] else []


# ---------------------------------------------------------------- Partien ohne Engine
def plain_annotation(g: dict) -> dict:
    """Wie metrics.annotate_game, aber ohne Bewertungen: genug fuer Baum, Partienliste und Viewer."""
    from ..metrics import phases_for, _structure, _increment, infer_increment
    ucis = g["ucis"]
    phases = phases_for(ucis)
    inc = _increment(g.get("time_control", ""))
    clocks = g.get("clocks") or []
    if inc is None and clocks:
        inc = infer_increment(clocks)
    g["increment_s"] = inc
    moves, b = [], chess.Board()
    for i, u in enumerate(ucis):
        white = b.turn == chess.WHITE
        moves.append({"ply": i + 1, "move_no": b.fullmove_number, "white": white, "san": g["sans"][i], "uci": u,
                      "fen_before": b.fen(), "phase": phases[i], "clock": clocks[i] if i < len(clocks) else None,
                      "own": white == g["is_white"]})
        b.push(chess.Move.from_uci(u))
    eco, oname, _ = name_line(ucis)
    oname = oname or g.get("opening_header", "")
    mid = next((k for k, p in enumerate(phases) if p != "Eröffnung"), None)
    return {"id": g["id"], "moves": moves, "eco": eco or g.get("eco", ""), "opening": oname, "family": family(oname),
            "label": label_for_player(g), "accuracy": None, "opp_accuracy": None, "tipping": 0,
            "structure": _structure(chess.Board(moves[mid]["fen_before"])) if mid is not None else None,
            "plies": len(moves), "has_clock": any(m["clock"] is not None for m in moves if m["own"])}


def plain_viewer(g: dict, a: dict) -> list[dict]:
    """Viewer-Zuege ohne Engine (cp/exp leer: der Viewer zeigt dann nur Zuege und Uhr)."""
    return [{"san": m["san"], "uci": m["uci"], "fen": m["fen_before"], "cp": None, "mate": None, "exp": None,
             "lvl": "", "tip": False, "own": m["own"], "best": None, "best_uci": None, "clk": m["clock"],
             "ph": m["phase"]} for m in a["moves"]]


def game_summary(g: dict, a: dict) -> dict:
    from ..dossier import _game_summary
    return _game_summary(g, a)


def newest(games: list[dict], n: int) -> list[dict]:
    """Die n juengsten Partien (Datum absteigend, Partien ohne Datum zuletzt)."""
    return sorted(games, key=lambda g: (g["date"] or "0000", g["round"] or ""), reverse=True)[:n]


def results(gs: list[dict]) -> dict:
    """Ergebnisse einer Partieliste aus Sicht des Gegners (ohne Engine)."""
    import statistics as st
    sc = [g["player_score"] for g in gs if g["player_score"] is not None]
    opp = [g["opponent_elo"] for g in gs if g["opponent_elo"]]
    w = sum(1 for s in sc if s == 1)
    d = sum(1 for s in sc if s == 0.5)
    l_ = sum(1 for s in sc if s == 0)
    p = sum(sc) / len(sc) if sc else None
    perf = None
    if opp and p is not None:
        perf = round(st.mean(opp) + (800 * (p - 0.5) if 0 < p < 1 else (400 if p == 1 else -400)))
    return {"games": len(gs), "w": w, "d": d, "l": l_, "unscored": len(gs) - len(sc),
            "score_pct": round(100 * p, 1) if p is not None else None,
            "avg_opp_elo": round(st.mean(opp)) if opp else None, "performance": perf}


def output_dir(pdir: Path, mode: str, color: str | None = None) -> Path:
    """Datenordner der Stufe: output/players/<slug>/scout/, briefing/ bzw. briefing_ich-weiss/ (siehe paths.py)."""
    from .. import paths
    return paths.stage_dir(pdir, mode, color)


def stale_cut() -> int:
    import datetime as dt
    return dt.date.today().year - config.STALE_YEARS
