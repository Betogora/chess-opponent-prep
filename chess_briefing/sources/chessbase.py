"""ChessBase Players (players.chessbase.com).

Die Seite liefert die Partien eines Spielers als PGN unter
    https://players.chessbase.com/games/<Nachname>_<Vorname>.pgn
Die Pipeline meldet sich ehrlich als Anwendung (kein Browser-User-Agent). ChessBase leitet solche Abrufe auf
eine Bot-Pruefung um (302 -> /bot/challenge); die wird nicht umgangen. Stattdessen laedt ein normaler Browser die PGN:
  1. (Standard) `python briefing.py receive <Spieler>` starten, Profilseite oeffnen, receiver_in_page ausfuehren:
     die Seite schickt die PGN per Formular an den lokalen Empfaenger (receiver.py) -> inbox/chessbase_<slug>.pgn.
     Kein Dialog, kein Download, kein Text durch den Agenten-Kontext.
  2. download_in_page: Download chessbase_<slug>.pgn in den Download-Ordner, den die schnellen Stufen uebernehmen
     (modes.common.pull_download). Der Browser kann dabei nachfragen (mehrere Downloads hintereinander).
  3. fetch_in_page + Speichern als inbox/chessbase_<slug>.pgn.
Ein CAPTCHA loest immer der Nutzer selbst.

Wiederverwendung: eine vorhandene inbox-Datei wird genutzt; ist sie aelter als config.CHESSBASE_MAX_AGE_DAYS,
meldet das Protokoll "veraltet" mit Hinweis (der Lauf geht mit der alten Datei weiter).
"""
from __future__ import annotations

import time
from pathlib import Path

from .. import config
from ..util import fetch, strip_accents


def pgn_path_on_site(ident) -> str:
    last = strip_accents(ident.last).replace(" ", "_")
    first = strip_accents(ident.first.split()[0] if ident.first else "")
    return f"/games/{last}_{first}.pgn"


def download_js(ident) -> str:
    """Im Browser auf der ChessBase-Profilseite ausfuehren: laedt die PGN und speichert sie als Download
    chessbase_<slug>.pgn (ohne Umweg ueber den Agenten-Kontext). Ergebnis: Zahl der Partien."""
    return ("(async () => { const t = await (await fetch('" + pgn_path_on_site(ident) + "')).text(); "
            "const a = document.createElement('a'); "
            "a.href = URL.createObjectURL(new Blob([t], {type: 'application/x-chess-pgn'})); "
            f"a.download = 'chessbase_{ident.slug}.pgn'; document.body.appendChild(a); a.click(); a.remove(); "
            "return t.split('[Event ').length - 1; })()")


def browser_hint(ident, inbox: Path) -> dict:
    from ..receiver import receiver_js
    return {
        "open": ident.chessbase_url,
        "receive": f"python briefing.py receive {ident.fide_id or ident.slug}",
        "receiver_in_page": receiver_js(ident),
        "download_in_page": download_js(ident),
        "fetch_in_page": f"await (await fetch('{pgn_path_on_site(ident)}')).text()",
        "save_as": str(inbox / f"chessbase_{ident.slug}.pgn"),
    }


def age_days(files: list[Path]) -> float:
    return (time.time() - max(f.stat().st_mtime for f in files)) / 86400


def collect(ident, inbox: Path) -> tuple[str, list[dict]]:
    files = sorted(inbox.glob("chessbase_*.pgn"))
    if files:
        # \r\r\n stammt aus aelteren Windows-Speicherungen und zerlegt sonst die Kopfzeilen
        txt = "\n\n".join(f.read_bytes().decode("utf-8", errors="replace").replace("\r\r\n", "\n").replace("\r\n", "\n")
                          for f in files)
        age = age_days(files)
        row = {"source": "chessbase", "status": "ok", "detail": ", ".join(f.name for f in files),
               "games": txt.count("[Event "), "age_days": round(age, 1)}
        if age > config.CHESSBASE_MAX_AGE_DAYS:      # weiter nutzen, aber zum Neuladen raten
            row.update(stale=True, hint=browser_hint(ident, inbox))
        return txt, [row]
    # Direktabruf mit ehrlicher Kennung; bei Bot-Pruefung folgt der Browser-Schritt (keine Umgehung)
    direct = fetch("https://players.chessbase.com" + pgn_path_on_site(ident), ttl_hours=24)
    if direct and direct.lstrip().startswith("[Event"):
        out = inbox / f"chessbase_{ident.slug}.pgn"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(direct.replace("\r\n", "\n").encode("utf-8"))
        return direct, [{"source": "chessbase", "status": "ok", "detail": "direkt geladen", "games": direct.count("[Event ")}]
    return "", [{"source": "chessbase", "status": "browser_noetig", "detail": "Bot-Pruefung",
                 "hint": browser_hint(ident, inbox)}]
