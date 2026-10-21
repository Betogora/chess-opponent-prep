"""Einrichtung und Weitergabe: setup (Stockfish laden), doctor (Umgebung pruefen), pack (Zip ohne private Daten)."""
from __future__ import annotations

import io
import json
import os
import platform
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

from . import __version__, config
from .util import log, session

MIN_PY = (3, 12)
REQUIRED = ("chess", "requests", "bs4")


# ---------------------------------------------------------------- setup
def _asset_score(name: str) -> int:
    """Passendes Stockfish-Archiv fuer dieses System waehlen (hoeher = besser)."""
    n = name.lower()
    sysname = platform.system().lower()
    machine = platform.machine().lower()
    want = {"windows": "windows", "linux": "ubuntu", "darwin": "macos"}.get(sysname, sysname)
    if want not in n:
        return -1
    if sysname == "darwin":
        arm = machine in ("arm64", "aarch64")
        return 3 if (arm and ("apple-silicon" in n or "m1" in n)) or (not arm and "x86-64" in n) else -1
    if "arm" in machine or "aarch64" in machine:
        return 2 if ("arm" in n or "aarch64" in n) else -1
    for score, key in ((4, "avx2"), (3, "universal"), (2, "bmi2"), (1, "x86-64")):
        if key in n and "arm" not in n:
            return score
    return -1


def setup(force: bool = False) -> int:
    ok = doctor(quiet=True, need_engine=False) == 0
    if not ok:
        log("Bitte zuerst die Python-Pakete installieren:  python -m pip install -r requirements.txt")
        return 1
    if config.find_engine() and not force:
        log(f"Stockfish vorhanden: {config.find_engine()}")
        return 0
    log("Lade offizielles Stockfish-Release von GitHub ...")
    rel = session().get("https://api.github.com/repos/official-stockfish/Stockfish/releases/latest", timeout=60).json()
    assets = sorted(rel.get("assets", []), key=lambda a: -_asset_score(a["name"]))
    if not assets or _asset_score(assets[0]["name"]) < 0:
        log("Kein passendes Archiv gefunden. Stockfish selbst installieren und BRIEFING_ENGINE=<Pfad> setzen.")
        return 1
    a = assets[0]
    log(f"  {rel.get('tag_name')} · {a['name']} ({a['size'] // 1_000_000} MB)")
    data = session().get(a["browser_download_url"], timeout=300).content
    target = config.ROOT / "tools" / "stockfish"
    target.mkdir(parents=True, exist_ok=True)
    if a["name"].endswith(".zip"):
        zipfile.ZipFile(io.BytesIO(data)).extractall(target)
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            tf.extractall(target, filter="data")
    eng = config.find_engine()
    if eng and os.name != "nt":
        eng.chmod(eng.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    log(f"Stockfish: {eng}")
    return 0 if eng else 1


# ---------------------------------------------------------------- doctor
def doctor(quiet: bool = False, need_engine: bool = True) -> int:
    problems = []

    def say(ok: bool, text: str):
        if not ok:
            problems.append(text)
        if not quiet or not ok:
            log(f"  {'✓' if ok else '✗'} {text}")

    say(sys.version_info >= MIN_PY, f"Python {sys.version.split()[0]} (benötigt ≥ {MIN_PY[0]}.{MIN_PY[1]})")
    for mod in REQUIRED:
        try:
            __import__(mod)
            say(True, f"Paket {mod}")
        except ImportError:
            say(False, f"Paket {mod} fehlt → python -m pip install -r requirements.txt")
    if need_engine:
        name = None
        eng = config.find_engine()
        if not eng:
            say(False, "Stockfish fehlt → python briefing.py setup")
        else:
            try:
                import chess.engine
                e = chess.engine.SimpleEngine.popen_uci(str(eng))
                name = e.id.get("name")
                e.quit()
                say(True, f"Engine {name} ({eng})")
            except Exception as ex:  # noqa: BLE001
                say(False, f"Engine startet nicht: {ex}")
        for url in ("https://lichess.org/api/fide/player/1503014", "https://ratings.fide.com/",
                    "https://www.schachbund.de/", "https://api.chess.com/pub/player/hikaru"):
            try:
                r = session().get(url, timeout=20)
                say(r.status_code < 500, f"Netz {url.split('/')[2]} ({r.status_code})")
            except Exception as ex:  # noqa: BLE001
                say(False, f"Netz {url.split('/')[2]}: {type(ex).__name__}")
        from .online.platforms import check_token
        ok, msg = check_token()
        if not quiet or "ungültig" in msg:
            log(f"  {'✓' if ok else '·'} Lichess-Token: {msg}")   # optional, daher kein Fehler
        from .profile import load_curves
        curves = load_curves()
        if not curves:
            log("  · Vergleichskurven fehlen (Spielerprofil ohne Teil-Elo) → python briefing.py calibrate")
        elif eng and (curves.get("meta") or {}).get("engine") != name:
            log(f"  · Vergleichskurven mit {curves['meta'].get('engine')} gerechnet, Engine jetzt {name} "
                "→ python briefing.py calibrate (bis dahin gelten die alten Kurven)")
        else:
            say(True, f"Vergleichskurven ({curves['meta'].get('games')} Partien, {curves['meta'].get('created')})")
        try:
            config.PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
            (config.PLAYERS_DIR / ".write_test").write_text("ok")
            (config.PLAYERS_DIR / ".write_test").unlink()
            say(True, f"Schreibrechte {config.PLAYERS_DIR}")
        except OSError as ex:
            say(False, f"Keine Schreibrechte: {ex}")
    if not quiet:
        log("Alles bereit." if not problems else f"{len(problems)} Problem(e).")
    return 1 if problems else 0


# ---------------------------------------------------------------- pack
INCLUDE = ["briefing.py", "requirements.txt", "README.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".env.example",
           "chess_briefing", "skills", "tests", ".claude/skills"]
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache"}


def pack(out_dir: Path | None = None) -> int:
    """Zip zum Weitergeben: Code, Skill, Doku, Tests, Daten-Tabellen. Ohne output/, cache/, tools/, .env."""
    out_dir = out_dir or config.ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"chess-opponent-prep-{__version__}"
    zpath = out_dir / f"{name}.zip"
    files = []
    for item in INCLUDE:
        p = config.ROOT / item
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files += [f for f in p.rglob("*") if f.is_file() and not (EXCLUDE_PARTS & set(f.parts)) and f.suffix != ".pyc"]
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(files):
            z.write(f, f"{name}/{f.relative_to(config.ROOT).as_posix()}")
        for d in ("output/players", "output/teams", "pgn", "tools"):
            z.writestr(f"{name}/{d}/.keep", "")
    size = zpath.stat().st_size
    log(f"Paket: {zpath} ({len(files)} Dateien, {size / 1e6:.2f} MB)")
    log(json.dumps({"enthalten": sorted({f.relative_to(config.ROOT).parts[0] for f in files})}, ensure_ascii=False))
    return 0
