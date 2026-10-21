"""Pfade, Schwellen und Engine-Einstellungen an einer Stelle."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"          # alles Erzeugte (privat): output/players/<slug>/, output/teams/<mannschaft>/
PLAYERS_DIR = OUTPUT_DIR / "players"
TEAMS_DIR = OUTPUT_DIR / "teams"
CACHE_DIR = ROOT / "cache"
DATA_DIR = Path(__file__).resolve().parent / "data"
ASSETS_DIR = Path(__file__).resolve().parent / "render" / "assets"
SHARED_PGN_DIR = ROOT / "pgn"          # optional: beliebige Sammel-PGNs (werden nach dem Spieler gefiltert)


def find_engine() -> Path | None:
    """Stockfish suchen: Umgebungsvariable, tools/stockfish, PATH."""
    env = os.environ.get("BRIEFING_ENGINE")
    if env and Path(env).exists():
        return Path(env)
    local = ROOT / "tools" / "stockfish"
    if local.exists():
        for p in sorted(local.rglob("stockfish*.exe")) + sorted(local.rglob("stockfish*")):
            if p.is_file() and (p.suffix in (".exe", "") and "stockfish" in p.name.lower()):
                return p
    from shutil import which
    w = which("stockfish")
    return Path(w) if w else None


# --- Engine -------------------------------------------------------------
# Tiefenlimit statt Zeitlimit: reproduzierbar (Threads=1) und auf Windows-Laptops planbar.
ENGINE_DEPTH = 18                # verdaechtige Zuege (Fehlerklassen, Schluesselstellungen)
ENGINE_SHALLOW_DEPTH = 14        # Vorab-Rechnung aller Stellungen
ENGINE_ALT_DEPTH = 14            # zweitbester Zug (MultiPV 2), wo der Spieler am Zug ist
TRIAGE_LIVE = (0.10, 0.90)       # nachgerechnet wird ein Zug aus umkaempfter Stellung ...
TRIAGE_LOSS = 0.03               # ... der vorab mehr als 3 Prozentpunkte Erwartungswert verliert
ENGINE_CHUNK_PLIES = 24          # feste Abschnitte je Partie -> auch wenige Partien nutzen alle Kerne
ENGINE_HASH_MB = 128
# Alle Kerne: die Engine laeuft mit Prioritaet "niedriger als normal", Windows bleibt bedienbar. Auf Hybrid-CPUs
# (z. B. Core Ultra: Kerne 0-3 schnell, 4-7 sparsam) war der ausgesparte Kern 0 ein schneller Kern.
ENGINE_WORKERS = max(1, int(os.environ.get("BRIEFING_WORKERS", 0) or (os.cpu_count() or 2)))
EVAL_CAP_CP = 1500           # Bewertungen werden fuer CPL auf +-15 Bauern gedeckelt (Matt-Ausreisser)
CPL_CAP_CP = 1000            # CPL je Zug maximal 10 Bauern

# --- Klassifikation (Erwartungswert, aus opponent-prep uebernommen und kalibriert) ---
EXP_INACCURACY = 0.05
EXP_MISTAKE = 0.15
EXP_BLUNDER = 0.30
LIVE_MIN, LIVE_MAX = 0.15, 0.85   # nur hier ist ein Fehler messbar
TIPPING_PERSIST = 2               # eigene Folgezuege unter 0.5 => Kipp-Punkt hat Bestand

# --- Phasen (materialbasiert, an Lichess' Divider angelehnt) --------------
PHASE_OPENING_MAX_MOVE = 15      # spaetestens hier endet die Eroeffnung
PHASE_MIDDLE_PIECES = 10         # Leichtfiguren+Schwerfiguren <= 10 => Mittelspiel
PHASE_END_PIECES = 6             # <= 6 => Endspiel

# --- Zeit ----------------------------------------------------------------
TIME_TROUBLE_SEC = 300           # Zeitnot: unter 5 Minuten Restzeit ...
TIME_TROUBLE_SHARE = 0.10        # ... bzw. unter 10 % der Grundzeit, falls das weniger ist (Schnell-/Blitzpartien)

# --- Datenlage -----------------------------------------------------------
THIN_GAMES = 10                  # darunter gilt eine Farbe als duenn belegt
THIN_MOVES_PHASE = 100
STALE_YEARS = 3

CHESSBASE_MAX_AGE_DAYS = 7       # ChessBase-PGN aus inbox/ wiederverwenden; aelter -> Hinweis zum Neuladen
TREE_MAX_PLY = 16                # Eroeffnungsbaum bis 8 Zuege

# --- Online-Accounts -----------------------------------------------------
ONLINE_WINDOW_DAYS = 3 * 365     # nur Partien der letzten 3 Jahre
ONLINE_POOL_MAX = 10000          # alle Partien des Zeitraums (ohne Bullet) fuer die Zaehlung je Stellung ...
ONLINE_SAMPLE = 100              # ... daraus 100 fuer die Analyse: gleichmaessig ueber die Zeit, lange Bedenkzeit zuerst
ONLINE_MIN_RECENT = 20           # weniger aktuelle Partien -> Rueckfall auf Fund-Partien (als veraltet markiert)
ONLINE_BUDGET_S = 240            # Zeitbudget der Kandidatensuche fuer die breiten Schritte (Vereinsmitglieder,
                                 # Chess.com-Club); Namens-, Muster- und research.json-Kandidaten immer vollstaendig

# --- Spielerprofil (profile.py) -------------------------------------------
ONLY_MOVE_GAP = 0.10             # scharf = zweitbester Zug mindestens 10 Prozentpunkte Erwartungswert schlechter
PROFILE_MIN_MOVE = 8             # Zuege davor (meist Theorie) zaehlen nicht fuer scharf/ruhig
PROFILE_MIN_CLASS_MOVES = 40     # darunter ist die Teil-Elo einer Stellungsart "duenn" (offen)
PROFILE_SHRINK_MOVES = 150       # Gewicht der eigenen Elo in Zuegen (wenige Zuege -> Teil-Elo nahe seiner Elo)
PROFILE_SPAN_FACTOR = 1.5        # Fehler streuen zwischen Amateurpartien staerker als rein zufaellig -> Spanne breiter
PROFILE_SHRINK_GAMES = 5         # dasselbe fuer Partie-Kennzahlen (Partien bzw. Faelle)
PROFILE_SKILL_DIFF = 100         # rechenstark/-schwach ab diesem Abstand der Teil-Elo scharf - ruhig
PROFILE_MIN_GAMES = 6
PROFILE_MIN_RESULTS = 8
PROFILE_MIN_CASES = 5
PROFILE_MIN_CLOCK = 5
PROFILE_MIN_COLOR_GAMES = 8
ME_ADJUST = 50                   # eigene Staerke/Schwaeche verschiebt die eigene Teil-Elo um so viel (Annahme)
ME_MAX_PLAN_STEPS = 2            # hoechstens so viele Plan-Schritte je Farbe duerfen sich auf M-Belege stuetzen

# --- Kalibrierung (calibrate.py) ------------------------------------------
CALIB_BAND_LO, CALIB_BAND_W, CALIB_BANDS = 1400, 200, 6   # 1400-1599 ... 2400-2599
CALIB_SIDES = 120                # Spielerseiten je Band
CALIB_MIN_BASE_SEC = 3600        # nur lange Bedenkzeit
