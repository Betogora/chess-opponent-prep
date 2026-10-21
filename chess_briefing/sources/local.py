"""Lokale PGNs: output/players/<slug>/inbox/*.pgn (ausser chessbase_* und chessresults_*, die liest die jeweilige Quelle)
und der Sammelordner pgn/. Manuelle Importe wie snoopchess_*.pgn (oft ohne Datum, Event, Ergebnis "*") laufen hier.

Sammel-PGNs werden nach dem Spieler gefiltert (Name stark oder FIDE-ID).
"""
from __future__ import annotations

import io
from pathlib import Path

import chess.pgn

from ..config import SHARED_PGN_DIR
from ..util import name_matches


def _filter(text: str, ident, source: str) -> list[str]:
    out, stream = [], io.StringIO(text)
    while True:
        g = chess.pgn.read_game(stream)
        if g is None:
            break
        h = g.headers
        fid = str(ident.fide_id or "")
        if (fid and fid in (h.get("WhiteFideId"), h.get("BlackFideId"))) or any(
                name_matches(h.get(c, ""), ident.last, ident.first) == "strong" for c in ("White", "Black")):
            h.setdefault("Source", source)
            out.append(str(g))
    return out


def collect(ident, inbox: Path) -> tuple[str, list[dict]]:
    parts, report = [], []
    files = [f for f in sorted(inbox.glob("*.pgn")) if not f.name.startswith(("chessbase_", "chessresults_"))]
    if SHARED_PGN_DIR.exists():
        files += sorted(SHARED_PGN_DIR.rglob("*.pgn"))
    for f in files:
        games = _filter(f.read_text(encoding="utf-8", errors="replace"), ident, f"Lokal: {f.name}")
        if games:
            parts += games
            report.append({"source": "lokal", "status": "ok", "detail": f.name, "games": len(games)})
    return "\n\n".join(parts), report
