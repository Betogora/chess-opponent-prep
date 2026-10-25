"""Stockfish-Analyse jeder Stellung (Bewertung, WDL, bester Zug, Hauptvariante) mit Cache.

Unterschiede zu opponent-prep:
  * Tiefenlimit statt Zeitlimit (reproduzierbar), Arbeit in festen Abschnitten auf mehrere Stockfish-Prozesse verteilt
    (je Thread eine Instanz; Python-Arbeitsprozesse mit offener Engine beenden sich unter Windows nicht sauber).
  * Matt-Stellungen werden ohne Engine korrekt bewertet (dort lag der 19.999-Bauern-Fehler).
  * Bester Zug + kurze Hauptvariante je Stellung -> konkrete Verbesserungen in den Schluesselstellungen.

Ablauf je Partie (drei Durchgaenge, jeder Abschnitt mit leerem Hash -> Ergebnis unabhaengig von der Verteilung):
  1. Vorab: alle Stellungen in ENGINE_SHALLOW_DEPTH.
  2. Nachrechnen: nur verdaechtige Zuege (umkaempfte Stellung, Verlust > TRIAGE_LOSS) beide Stellungen in ENGINE_DEPTH.
     Gemessen an 8 Partien: findet alle Fehler/Patzer der vollen Tiefe-18-Analyse bei rund einem Drittel der Zeit.
     Liegen beide Stellungen im selben Abschnitt, rechnet der Vorab-Auftrag sie gleich danach mit warmem Hash nach.
  3. Zweitbester Zug: Stellungen, in denen der Spieler am Zug ist, MultiPV 2 in ENGINE_ALT_DEPTH ("alt").
"""
from __future__ import annotations

import ctypes
import itertools
import json
import os
import queue
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import chess
import chess.engine

from . import config
from .util import log

MATE_CP = 10000


def _terminal(board: chess.Board) -> dict | None:
    if board.is_checkmate():
        white_lost = board.turn == chess.WHITE
        return {"cp": -MATE_CP if white_lost else MATE_CP, "mate": 0,
                "wdl": (0, 0, 1000) if white_lost else (1000, 0, 0), "best": None, "pv": []}
    if board.is_stalemate() or board.is_insufficient_material():
        return {"cp": 0, "mate": None, "wdl": (0, 1000, 0), "best": None, "pv": []}
    return None


# ---------------------------------------------------------------- Prozesse
class _PowerThrottling(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


def tune_process(pid: int) -> None:
    """Engine-Prozess fuer Dauerlast einstellen, ohne den Rechner zu blockieren.
    Windows: Energiedrosselung (EcoQoS) aus - sonst landen Hintergrundprozesse auf Hybrid-CPUs nur auf den
    Sparkernen -, Prioritaet "niedriger als normal" auf allen Kernen (Windows teilt die Kerne nach Prioritaet; ein fest
    ausgesparter Kern 0 kostete auf Hybrid-CPUs einen schnellen Kern). Andere Systeme: nice 10."""
    try:
        if sys.platform == "win32":
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = ctypes.c_void_p
            k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            k32.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
            k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            k32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            h = k32.OpenProcess(0x0200 | 0x0400, False, pid)      # SET_INFORMATION | QUERY_INFORMATION
            if not h:
                return
            state = _PowerThrottling(1, 0x1, 0x0)                 # EXECUTION_SPEED selbst steuern: aus
            k32.SetProcessInformation(h, 4, ctypes.byref(state), ctypes.sizeof(state))   # ProcessPowerThrottling
            k32.SetPriorityClass(h, 0x4000)                       # BELOW_NORMAL_PRIORITY_CLASS
            k32.CloseHandle(h)
        else:
            os.setpriority(os.PRIO_PROCESS, pid, 10)
    except (OSError, AttributeError, ValueError):
        pass   # reine Optimierung: ohne sie laeuft die Analyse genauso, nur langsamer


@contextmanager
def _slot(slot_dir: Path | None, n: int):
    """Rechnerweiter Engine-Platz: parallele prepare-Laeufe teilen sich ENGINE_WORKERS Plaetze (Sperrdateien)."""
    if slot_dir is None:
        yield
        return
    slot_dir.mkdir(parents=True, exist_ok=True)
    me = slot_dir / f"wait_{os.getpid()}"

    def others_waiting() -> bool:
        now = time.time()
        for w in slot_dir.glob("wait_*"):
            try:
                if w != me and now - w.stat().st_mtime < 3:
                    return True
            except OSError:
                pass
        return False
    while True:
        for k in range(n):
            f = open(slot_dir / f"slot{k}.lock", "a+b")
            try:
                f.seek(0)
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                f.close()
                continue
            me.unlink(missing_ok=True)
            try:
                yield
            finally:
                f.seek(0)
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                f.close()      # POSIX: Schliessen gibt flock frei
                if others_waiting():
                    time.sleep(0.6)   # fair teilen: ein wartender anderer Lauf bekommt den Platz zuerst
            return
        me.touch()             # "ich warte" (frisch gehalten, damit verwaiste Marken nach 3 s nicht zaehlen)
        time.sleep(0.3)


def _open_engine(engine_path: str) -> chess.engine.SimpleEngine:
    eng = chess.engine.SimpleEngine.popen_uci(engine_path)
    opts = {"Threads": 1, "Hash": config.ENGINE_HASH_MB}
    if "UCI_ShowWDL" in eng.options:
        opts["UCI_ShowWDL"] = True
    eng.configure(opts)
    tune_process(eng.transport.get_pid())
    return eng


def _wdl_white(info, board: chess.Board) -> list[int]:
    wdl = info.get("wdl")
    if wdl:
        w = wdl.white()
        return [w.wins, w.draws, w.losses]
    return list(info["score"].white().wdl(model="sf", ply=board.ply()))


def _position(info, board: chess.Board) -> dict:
    sc = info["score"].white()
    pv = info.get("pv", [])[:8]
    pv_san, b2 = [], board.copy()
    for mv in pv:
        pv_san.append(b2.san(mv))
        b2.push(mv)
    return {"cp": sc.score(mate_score=MATE_CP), "mate": sc.mate(), "wdl": _wdl_white(info, board),
            "best": pv[0].uci() if pv else None, "best_san": pv_san[0] if pv_san else None, "pv": pv_san,
            "depth": info.get("depth")}


def _alt(infos, board: chess.Board, depth: int) -> dict:
    """Beste und zweitbeste Fortsetzung (MultiPV 2); bei nur einem legalen Zug fehlt die zweite."""
    a = infos[0]
    out = {"depth": depth, "cp": a["score"].white().score(mate_score=MATE_CP), "wdl": _wdl_white(a, board),
           "best": a["pv"][0].uci() if a.get("pv") else None, "cp2": None, "wdl2": None, "best2": None}
    if len(infos) > 1 and infos[1].get("pv"):
        b = infos[1]
        out.update(cp2=b["score"].white().score(mate_score=MATE_CP), wdl2=_wdl_white(b, board),
                   best2=b["pv"][0].uci())
    return out


def _run_job(eng: chess.engine.SimpleEngine, job: tuple, slot_dir: Path | None, slots: int) -> tuple[dict, dict]:
    """Ein Abschnitt: Stellungen `indices` einer Partie in fester Tiefe, frischer Hash (ucinewgame).
    deep = (Tiefe, (erste, letzte Stellung des Abschnitts), bekannte Vorab-Ergebnisse, Stellungen mit Cache-Treffer):
    verdaechtige Zuege, deren beide Stellungen im Abschnitt liegen, gleich danach mit demselben, warmen Hash nachrechnen
    (gemessen 16 % schneller als mit leerem Hash). Rueckgabe: Vorab-Ergebnisse, Nachrechnung."""
    key, ucis, indices, depth, multipv, deep = job
    want, last = set(indices), max(indices)
    span = deep[1] if deep else (0, -1)
    out, boards, deep_out = {}, {}, {}
    with _slot(slot_dir, slots):
        board = chess.Board()
        for i in range(max(last, span[1]) + 1):
            if span[0] <= i <= span[1]:
                boards[i] = board.copy(stack=False)
            if i in want:
                t = _terminal(board)
                if multipv == 1:
                    out[i] = t or _position(eng.analyse(board, chess.engine.Limit(depth=depth), game=key), board)
                elif t is None and board.legal_moves:
                    infos = eng.analyse(board, chess.engine.Limit(depth=depth), game=key, multipv=multipv)
                    out[i] = _alt(infos, board, depth)
            if i < max(last, span[1]):
                board.push(chess.Move.from_uci(ucis[i]))
        if deep:
            deep_depth, (lo, hi), known, skip = deep
            full = [out.get(i) or known.get(i) for i in range(lo, hi + 1)]
            if all(full):
                for i in (lo + k for k in suspects(full)):   # lo ist gerade -> Weiss am Zug wie in suspects()
                    if i not in skip:
                        deep_out[i] = _position(eng.analyse(boards[i], chess.engine.Limit(depth=deep_depth), game=key),
                                                boards[i])
    return out, deep_out


def _engine_thread(engine_path: str, jobs: queue.Queue, done: queue.Queue, slot_dir: Path | None, slots: int) -> None:
    """Je Thread eine eigene Stockfish-Instanz (eigener Prozess -> echte Parallelitaet); Ende mit None."""
    try:
        eng = _open_engine(engine_path)
    except Exception as ex:  # noqa: BLE001
        done.put((None, None, ex))
        return
    try:
        while (job := jobs.get()[2]) is not None:
            try:
                done.put((job, _run_job(eng, job[1], slot_dir, slots), None))
            except Exception as ex:  # noqa: BLE001
                done.put((job, None, ex))
    finally:
        eng.quit()


# ---------------------------------------------------------------- Planung
def chunks(indices: list[int], size: int) -> list[list[int]]:
    """Feste Abschnitte nach Stellungsnummer (0..size-1, size..2*size-1, ...), unabhaengig von der Auswahl."""
    out: dict[int, list[int]] = {}
    for i in sorted(indices):
        out.setdefault(i // size, []).append(i)
    return [out[k] for k in sorted(out)]


def _exp_white(p: dict) -> float:
    w, d, l = p["wdl"]
    return (w + 0.5 * d) / ((w + d + l) or 1)


def suspects(pos: list[dict]) -> list[int]:
    """Stellungen fuer die tiefe Nachrechnung: vor und nach jedem Zug, der in einer umkaempften Stellung
    (Erwartungswert des Ziehenden TRIAGE_LIVE) nach der Vorab-Rechnung mehr als TRIAGE_LOSS verliert."""
    lo, hi = config.TRIAGE_LIVE
    idx = set()
    for i in range(len(pos) - 1):
        white = i % 2 == 0          # Partien beginnen in der Grundstellung
        eb, ea = _exp_white(pos[i]), _exp_white(pos[i + 1])
        before, after = (eb, ea) if white else (1 - eb, 1 - ea)
        if lo <= before <= hi and before - after > config.TRIAGE_LOSS:
            idx.update((i, i + 1))
    return sorted(i for i in idx if pos[i].get("depth") is not None)   # Endstellungen brauchen keine Engine


_ids: dict[str, str] = {}
_ids_lock = threading.Lock()


def engine_id(path: Path | None = None) -> str:
    """UCI-Name der Engine ("Stockfish 19"), je Binary (Pfad, Groesse, Zeitstempel) in cache/engine_id.json gemerkt.
    Schluessel fuer Stellungs- und Partie-Cache: ein neues Binary unter gleichem Dateinamen bekommt so nie die
    Bewertungen des alten. Nur beim ersten Aufruf je Binary startet ein Engine-Prozess."""
    path = path or config.find_engine()
    if not path:
        return "Stockfish"
    st = path.stat()
    key = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    f = config.CACHE_DIR / "engine_id.json"
    with _ids_lock:
        if key in _ids:
            return _ids[key]
        try:
            known = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            known = {}
        if key not in known:
            eng = chess.engine.SimpleEngine.popen_uci(str(path))
            try:
                known[key] = eng.id.get("name", path.name)
            finally:
                eng.quit()
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(known, ensure_ascii=False, indent=1), encoding="utf-8")
            except OSError:
                pass   # nur die Merkliste; naechstes Mal wird die Engine erneut gefragt
        _ids[key] = known[key]
        return known[key]


class PositionCache:
    """Stellungs-Cache ueber Partien und Spieler (SQLite, nur der Hauptthread schreibt). Schluessel: Engine-Version,
    Tiefe, MultiPV und FEN ohne Zugnummer. Wiederkehrende Eroeffnungsstellungen und Neulaeufe kosten so keine Engine-Zeit.
    legacy: frueherer Schluessel (Dateiname des Binarys statt Version); solche Eintraege stammen aus der Zeit vor der
    Versionskennung, wurden mit dem damals installierten Binary gerechnet und werden einmalig auf die Version umgestellt."""

    def __init__(self, engine_name: str, legacy: str | None = None):
        import sqlite3
        self.name = engine_name
        self.db = None
        self.hits = 0
        try:
            config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(config.CACHE_DIR / "positions.sqlite", timeout=30)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("CREATE TABLE IF NOT EXISTS pos (k TEXT PRIMARY KEY, v TEXT)")
            if legacy and legacy != engine_name:
                old = f"{legacy}|"
                self.db.execute("UPDATE OR IGNORE pos SET k = ? || substr(k, ?) WHERE k >= ? AND k < ?",
                                (f"{engine_name}|", len(old) + 1, old, f"{legacy}}}"))
                self.db.commit()
        except Exception as ex:  # noqa: BLE001 - reine Beschleunigung; ohne Cache laeuft alles wie zuvor
            log(f"  ! Stellungs-Cache nicht verfuegbar: {ex}")
            self.db = None

    def key(self, fen: str, depth: int, multipv: int) -> str:
        return f"{self.name}|d{depth}|m{multipv}|{fen.rsplit(' ', 1)[0]}"

    def get(self, fens: dict[int, str], depth: int, multipv: int) -> dict[int, dict]:
        if not self.db or not fens:
            return {}
        keys = {self.key(f, depth, multipv): i for i, f in fens.items()}
        out, ks = {}, list(keys)
        for k in range(0, len(ks), 500):
            part = ks[k:k + 500]
            q = f"SELECT k, v FROM pos WHERE k IN ({','.join('?' * len(part))})"
            for kk, v in self.db.execute(q, part):
                out[keys[kk]] = json.loads(v)
        self.hits += len(out)
        return out

    def put(self, fens: list[str], res: dict[int, dict], depth: int, multipv: int) -> None:
        if not self.db or not res:
            return
        try:
            self.db.executemany("INSERT OR REPLACE INTO pos (k, v) VALUES (?, ?)",
                                [(self.key(fens[i], depth, multipv), json.dumps(p)) for i, p in res.items()])
            self.db.commit()
        except Exception:  # noqa: BLE001 - gesperrt/voll: Ergebnis steht trotzdem im Partie-Cache
            pass

    def close(self):
        if self.db:
            self.db.close()


def alt_positions(g: dict, pos: list[dict], alt_all: bool = False) -> list[int]:
    """Stellungen, deren zweitbester Zug das Spielerprofil tatsaechlich auswertet (profile.move_class/side_stats):
    eigener Zug (alt_all: beide Seiten), umkaempft (LIVE_MIN..LIVE_MAX vor dem Zug), ab Zug PROFILE_MIN_MOVE,
    nicht im Endspiel. Alle anderen Stellungen brauchen keinen MultiPV-2-Lauf."""
    from .metrics import phases_for
    phases = phases_for(g["ucis"])
    out = []
    for i in range(len(g["ucis"])):
        white = i % 2 == 0
        if not alt_all and white != g["is_white"]:
            continue
        if i // 2 + 1 < config.PROFILE_MIN_MOVE or phases[i] == "Endspiel" or pos[i].get("depth") is None:
            continue
        e = _exp_white(pos[i])
        e = e if white else 1 - e
        if config.LIVE_MIN <= e <= config.LIVE_MAX:
            out.append(i)
    return out


def analyse_games(games: list[dict], cache_dir: Path, depth: int | None = None,
                  workers: int | None = None, force: bool = False, alt_all: bool = False,
                  deadline: float | None = None) -> dict[str, list[dict]]:
    """alt_all: zweitbester Zug fuer beide Seiten (Kalibrierung), sonst nur wo der Spieler am Zug ist.
    Je Partie nacheinander: base (alle Stellungen) -> deep (verdaechtige Zuege) -> alt (nur wo das Profil ihn nutzt).
    Bereits bekannte Stellungen kommen aus dem Stellungs-Cache.
    deadline (time.monotonic): danach keine neuen Ergebnisse mehr abwarten; zurueck kommen nur fertige Partien
    (die schnellen Stufen). None = bis alle Partien fertig sind (research, Kalibrierung)."""
    depth = depth or config.ENGINE_DEPTH
    shallow = min(config.ENGINE_SHALLOW_DEPTH, depth)
    alt_depth = config.ENGINE_ALT_DEPTH
    workers = workers or config.ENGINE_WORKERS
    size = config.ENGINE_CHUNK_PLIES
    engine = config.find_engine()
    if not engine:
        raise SystemExit("Stockfish nicht gefunden (tools/stockfish, BRIEFING_ENGINE oder PATH).")
    eid = engine_id(engine)
    cache_dir.mkdir(parents=True, exist_ok=True)
    results, todo = {}, {}
    for g in games:
        f = cache_dir / f"{g['id']}.json"
        d = json.loads(f.read_text(encoding="utf-8")) if f.exists() and not force else {}
        if d and d.get("engine") == engine.name != eid:
            d["engine"] = eid      # Dateiname statt Version: aus der Zeit vor der Versionskennung (siehe PositionCache)
            f.write_text(json.dumps(d), encoding="utf-8")
        if d.get("engine") != eid:
            d = {}                 # andere Engine-Version -> neu rechnen
        base_ok = d.get("depth", 0) >= depth and len(d.get("positions", [])) == len(g["ucis"]) + 1
        if base_ok and d.get("alt_depth", 0) >= alt_depth:
            results[g["id"]] = d["positions"]
            continue
        todo[g["id"]] = {"g": g, "cache": d if base_ok else None, "base": {}, "deep": {}, "alt": {}, "left": 0,
                         "stage": "start", "fens": None}
    if not todo:
        return results

    pcache = PositionCache(eid, legacy=engine.name)
    n_new = sum(1 for st in todo.values() if st["cache"] is None)
    plan = f"Tiefe {shallow}, verdächtige Züge {depth}" if depth > shallow else f"Tiefe {depth}"
    log(f"  {eid} ({plan}, zweitbester Zug Tiefe {alt_depth} wo das Profil ihn nutzt, "
        f"{workers} Prozesse): {n_new} Partien neu, {len(todo) - n_new} nur zweitbester Zug")
    t0, done0 = time.time(), len(results)

    def current(st) -> list[dict]:
        pos = [dict(p) for p in st["cache"]["positions"]] if st["cache"] else \
            [st["base"][i] for i in range(len(st["g"]["ucis"]) + 1)]
        for i, p in st["deep"].items():
            pos[i] = p
        return pos

    def fens(st) -> list[str]:
        if st["fens"] is None:
            b, out = chess.Board(), []
            for u in st["g"]["ucis"]:
                out.append(b.fen())
                b.push(chess.Move.from_uci(u))
            out.append(b.fen())
            st["fens"] = out
        return st["fens"]

    def finish(gid):
        st = todo.pop(gid)
        pos = current(st)
        for i, p in enumerate(pos):
            p.pop("alt", None)
            if i in st["alt"]:
                p["alt"] = st["alt"][i]
        results[gid] = pos
        (cache_dir / f"{gid}.json").write_text(json.dumps(
            {"depth": depth, "shallow_depth": st["cache"].get("shallow_depth", depth) if st["cache"] else shallow,
             "alt_depth": alt_depth, "alt_scope": "profil", "engine": eid, "positions": pos}), encoding="utf-8")
        new = len(results) - done0
        el = time.time() - t0
        rest = el / new * (len(games) - len(results)) if new else 0
        log(f"    {len(results)}/{len(games)} fertig ({el:.0f} s, Rest ~{rest:.0f} s)")

    slot_dir = config.CACHE_DIR / "engine_slots"
    # Reihenfolge: angefangene Partien zuerst (deep/alt), sonst Partie fuer Partie -> Partien werden laufend fertig
    jobq, doneq = queue.PriorityQueue(), queue.Queue()
    order = {gid: k for k, gid in enumerate(todo)}
    seq = itertools.count()
    open_jobs = 0

    def submit(kind, gid, idx, dep, mpv, deep=None):
        nonlocal open_jobs
        todo[gid]["left"] += 1
        open_jobs += 1
        jobq.put(((1 if kind == "base" else 0, order[gid]), next(seq),
                  ((kind, gid), (f"{gid}:{kind}:{idx[0]}", todo[gid]["g"]["ucis"], idx, dep, mpv, deep))))

    def stage(gid, kind, idx, dep, mpv):
        st = todo[gid]
        fl = fens(st)
        hit = pcache.get({i: fl[i] for i in idx}, dep, mpv)
        st[kind].update(hit)
        # Vorab-Rechnung: Nachrechnung im selben Auftrag (warmer Hash); Stellungen mit Tiefe-depth-Treffer auslassen
        warm = kind == "base" and depth > dep
        deep_hit = set(pcache.get({i: fl[i] for i in idx}, depth, 1)) if warm else set()
        for c in chunks([i for i in idx if i not in hit], size):
            lo = c[0] // size * size
            span = (lo, min(lo + size, len(fl)) - 1)
            submit(kind, gid, c, dep, mpv, (depth, span, {i: hit[i] for i in range(span[0], span[1] + 1) if i in hit},
                                            deep_hit) if warm else None)

    def advance(gid):
        """Naechste Stufe einer Partie, sobald die laufende keine offenen Auftraege mehr hat."""
        while gid in todo and todo[gid]["left"] == 0:
            st = todo[gid]
            g, n = st["g"], len(st["g"]["ucis"]) + 1
            if st["stage"] == "start":
                st["stage"] = "base"
                if st["cache"] is None:
                    stage(gid, "base", list(range(n)), shallow if depth > shallow else depth, 1)
            elif st["stage"] == "base":
                st["stage"] = "deep"
                if st["cache"] is None and depth > shallow:
                    # warm im Vorab-Auftrag gerechnet sind schon alle Paare innerhalb eines Abschnitts; hier bleiben
                    # Paare ueber eine Abschnittsgrenze und Stellungen aus dem Stellungs-Cache
                    stage(gid, "deep", [i for i in suspects([st["base"][i] for i in range(n)]) if i not in st["deep"]],
                          depth, 1)
            elif st["stage"] == "deep":
                st["stage"] = "alt"
                stage(gid, "alt", alt_positions(g, current(st), alt_all), alt_depth, 2)
            else:
                finish(gid)

    for gid in list(todo):
        advance(gid)
    threads = []
    if open_jobs:
        threads = [threading.Thread(target=_engine_thread, daemon=True, name=f"stockfish-{k}",
                                    args=(str(engine), jobq, doneq, slot_dir, config.ENGINE_WORKERS))
                   for k in range(workers)]
    for t in threads:
        t.start()
    try:
        while open_jobs:
            if deadline is not None:
                try:
                    job, out, err = doneq.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    log(f"  Zeitgrenze erreicht: {len(results)}/{len(games)} Partien fertig analysiert, Rest ohne Engine")
                    break
            else:
                job, out, err = doneq.get()
            if err is not None:
                raise RuntimeError(f"Stockfish-Analyse fehlgeschlagen: {type(err).__name__}: {err}") from err
            open_jobs -= 1
            (kind, gid), (_, _, _, dep, mpv, _) = job
            out, deep_out = out
            st = todo[gid]
            st["left"] -= 1
            st[kind].update(out)
            pcache.put(fens(st), out, dep, mpv)
            if deep_out:
                st["deep"].update(deep_out)
                pcache.put(fens(st), deep_out, depth, 1)
            advance(gid)
    finally:
        while not jobq.empty():          # bei Abbruch offene Auftraege verwerfen
            try:
                jobq.get_nowait()
            except queue.Empty:
                break
        for _ in threads:
            jobq.put(((9, 0), next(seq), None))
        for t in threads:
            t.join(timeout=60 if deadline is None else 1)   # mit Zeitgrenze nicht auf laufende Auftraege warten
        if pcache.hits:
            log(f"  Stellungs-Cache: {pcache.hits} Stellungen ohne Engine")
        pcache.close()
    return results


def engine_label() -> str:
    return engine_id()


def check_line(san_line: str, depth: int = 22, multipv: int = 3) -> dict:
    """Zugfolge pruefen (fuer Theorie-Empfehlungen): Bewertung + beste Fortsetzungen."""
    import re
    b = chess.Board()
    for tok in san_line.replace("…", " ").split():
        tok = re.sub(r"^\d+\.+", "", tok)
        if tok:
            b.push_san(tok)
    eng = chess.engine.SimpleEngine.popen_uci(str(config.find_engine()))
    try:
        tune_process(eng.transport.get_pid())
        eng.configure({"Threads": max(1, (config.ENGINE_WORKERS or 1)), "Hash": 256})
        infos = eng.analyse(b, chess.engine.Limit(depth=depth), multipv=multipv)
        name = eng.id.get("name", "Stockfish")
    finally:
        eng.quit()
    cands = []
    for i in infos:
        sc = i["score"].white()
        cands.append({"eval": sc.score(mate_score=10000), "mate": sc.mate(), "pv": b.variation_san(i["pv"][:8])})
    return {"line": san_line, "fen": b.fen(), "to_move": "white" if b.turn else "black",
            "depth": depth, "engine": name, "candidates": cands}
