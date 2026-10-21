"""Lichess-Broadcasts eines FIDE-Spielers.

Die Seite https://lichess.org/fide/{id}/{slug} listet die Turniere, in denen der Spieler
uebertragen wurde. Je Turnier wird das komplette Broadcast-PGN geladen
(https://lichess.org/api/broadcast/{tourId}.pgn) und nach FIDE-ID bzw. Name gefiltert.
Broadcast-PGNs enthalten oft [%clk]-Angaben (Bedenkzeit) - die nutzt die Zeitanalyse.
"""
from __future__ import annotations

import io
import json
import re

import chess.pgn
from bs4 import BeautifulSoup

from ..util import fetch, log, name_matches


def broadcast_rounds(fide_id: int) -> list[dict]:
    html = fetch(f"https://lichess.org/fide/{fide_id}/x", ttl_hours=24)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup
    out, seen = [], set()
    for a in main.find_all("a", href=True):
        m = re.match(r"/broadcast/[^/]+/[^/]+/([A-Za-z0-9]{8})$", a["href"])
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append({"round_id": m.group(1), "name": a.get_text(" ", strip=True), "href": a["href"]})
    return out


def tour_of_round(round_id: str) -> dict | None:
    txt = fetch(f"https://lichess.org/api/broadcast/-/-/{round_id}", ttl_hours=168)
    try:
        d = json.loads(txt) if txt else None
    except json.JSONDecodeError:
        return None
    return d.get("tour") if d else None


def collect(ident) -> tuple[str, list[dict]]:
    """-> (PGN-Text der Partien des Spielers, Protokoll)"""
    report = []
    if not ident.fide_id:
        return "", [{"source": "lichess", "status": "uebersprungen", "detail": "keine FIDE-ID"}]
    pgn_parts = []
    for rnd in broadcast_rounds(ident.fide_id):
        tour = tour_of_round(rnd["round_id"])
        if not tour:
            continue
        pgn = fetch(f"https://lichess.org/api/broadcast/{tour['id']}.pgn", ttl_hours=168)
        if not pgn:
            report.append({"source": "lichess", "status": "fehler", "detail": tour.get("name")})
            continue
        hits = empty = 0
        stream = io.StringIO(pgn)
        while True:
            g = chess.pgn.read_game(stream)
            if g is None:
                break
            h = g.headers
            is_player = str(ident.fide_id) in (h.get("WhiteFideId"), h.get("BlackFideId")) or any(
                name_matches(h.get(c, ""), ident.last, ident.first) == "strong" for c in ("White", "Black"))
            if not is_player:
                continue
            if g.next() is None:
                empty += 1
                continue
            hits += 1
            if h.get("BroadcastName"):
                h["Event"] = h["BroadcastName"]
            h["Source"] = "Lichess Broadcast"
            h["SourceURL"] = h.get("GameURL") or h.get("Site", "")
            pgn_parts.append(str(g))
        report.append({"source": "lichess", "status": "ok", "detail": tour.get("name"),
                       "games": hits, "without_moves": empty,
                       "url": f"https://lichess.org/broadcast/{tour.get('slug', '-')}/{tour['id']}"})
        log(f"  lichess: {tour.get('name')}: {hits} Partien" + (f", {empty} ohne Zuege" if empty else ""))
    return "\n\n".join(pgn_parts), report
