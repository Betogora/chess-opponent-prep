"""Mannschaftskaempfe des Niedersaechsischen Schachverbands (nsv-online.de).

Ligen sind in Familien organisiert (nsv-XXYY = Verbandsebene, bezirk<N>-XXYY = Bezirke).
Fuer jede Saison: Staffeln -> Mannschaften des Vereins -> Spielerseite /s/<id>/ mit allen
Einsaetzen (Runde, Brett, Farbe, Gegner, DWZ, Ergebnis). Runden-PGNs (/<staffel>/<runde>/pgn/)
enthalten meist nur Ergebnisse; wo Zuege erfasst sind, werden sie als Partie uebernommen.

Andere Landesverbaende nutzen andere Systeme - hier ist der Erweiterungspunkt.
"""
from __future__ import annotations

import io
import json
import re

import chess.pgn
from bs4 import BeautifulSoup

from ..util import fetch, log, name_matches, strip_accents

BASE = "https://nsv-online.de"
FAMILIES = ["nsv", "bezirk1", "bezirk2", "bezirk3", "bezirk6"]
_GENERIC = {"sk", "sv", "sf", "sc", "sg", "spvgg", "tus", "mtv", "tsv", "vfl", "schach", "schachklub",
            "schachfreunde", "schachverein", "schachclub", "verein", "ev", "e", "v", "club", "klub",
            "von", "und", "der", "die", "das", "1", "2", "3"}


def _get(path: str, ttl: float) -> str | None:
    return fetch(BASE + path, ttl_hours=ttl)


def _club_tokens(club: str) -> set[str]:
    toks = re.split(r"[\s/\-.,()]+", strip_accents(club).lower())
    return {t for t in toks if t and not t.isdigit() and t not in _GENERIC and len(t) > 2}


def _team_matches(team: str, club_toks: set[str]) -> bool:
    return bool(club_toks) and club_toks <= _club_tokens(team)


def _season_ttl(season: str, current: str) -> float:
    return 24 if season == current else 24 * 120


def _teams(fam: str, season: str, ttl: float) -> dict[str, str]:
    root = f"/ligen/{fam}-{season}/"
    html = _get(root, ttl)
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    divs = {a["href"] for a in soup.find_all("a", href=True)
            if re.fullmatch(rf"{re.escape(root)}([a-z0-9-]+/|\?staffel=\d+&r=)", a["href"])}
    teams = {}
    for d in [root, *sorted(divs)]:
        dh = _get(d, ttl) if d != root else html
        if not dh:
            continue
        for a in BeautifulSoup(dh, "html.parser").find_all("a", href=True):
            if re.search(r"/m/\d+/$", a["href"]):
                teams[a.get_text(strip=True)] = a["href"]
    return teams


def _seasons(current: str, back: int) -> list[str]:
    yy = int(current[:2])
    return [f"{(yy - i) % 100:02d}{(yy - i + 1) % 100:02d}" for i in range(back + 1)]


def _current_season() -> str:
    import datetime as dt
    t = dt.date.today()
    y = t.year if t.month >= 8 else t.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def _round_meta(fam: str, season: str, div: str, rnd: str, ttl: float) -> dict:
    txt = _get(f"/ligen/{fam}-{season}/api/divisions/{div}/rounds/{rnd}/", ttl)
    try:
        return json.loads(txt) if txt else {}
    except json.JSONDecodeError:
        return {}


def _round_games_with_moves(round_uri: str, ident, ttl: float) -> list[chess.pgn.Game]:
    txt = _get(round_uri.rstrip("/") + "/pgn/", ttl)
    if not txt:
        return []
    out, stream = [], io.StringIO(txt)
    while True:
        g = chess.pgn.read_game(stream)
        if g is None:
            break
        if g.next() is None:
            continue
        if any(name_matches(g.headers.get(c, ""), ident.last, ident.first) == "strong" for c in ("White", "Black")):
            out.append(g)
    return out


def collect(ident, seasons_back: int = 8) -> tuple[str, list[dict], list[dict]]:
    """-> (PGN mit Zuegen, Ergebniszeilen ohne Zuege, Protokoll)"""
    club = (ident.dsb or {}).get("club", "")
    if not club:
        return "", [], [{"source": "nsv", "status": "uebersprungen", "detail": "kein Verein bekannt (DSB)"}]
    club_toks = _club_tokens(club)
    cur = _current_season()
    seasons = _seasons(cur, seasons_back)

    # Familien bestimmen, in denen der Verein in den letzten zwei Saisons spielt
    fams = []
    for fam in FAMILIES:
        for s in seasons[:3]:
            if any(_team_matches(t, club_toks) for t in _teams(fam, s, _season_ttl(s, cur))):
                fams.append(fam)
                break
    if not fams:
        return "", [], [{"source": "nsv", "status": "kein_treffer", "detail": f"Verein '{club}' nicht in NSV-Ligen gefunden"}]
    if "nsv" not in fams:
        fams.insert(0, "nsv")

    rows, pgns, seen = [], [], set()
    for fam in fams:
        for s in seasons:
            ttl = _season_ttl(s, cur)
            for team, turi in _teams(fam, s, ttl).items():
                if not _team_matches(team, club_toks):
                    continue
                th = _get(turi, ttl) or ""
                plink = None
                for a in BeautifulSoup(th, "html.parser").find_all("a", href=True):
                    if "/s/" in a["href"] and name_matches(a.get_text(" ", strip=True), ident.last, ident.first) == "strong":
                        plink = a["href"]
                        break
                if not plink or plink in seen:
                    continue
                seen.add(plink)
                ph = _get(plink, ttl) or ""
                for tr in BeautifulSoup(ph, "html.parser").find_all("tr"):
                    tds = tr.find_all("td")
                    c = [td.get_text(" ", strip=True) for td in tds]
                    if len(c) < 9 or not c[0].isdigit():
                        continue
                    a = tr.find("a", href=re.compile(r"/ligen/.+/\d+/$"))
                    round_uri = a["href"] if a else ""
                    m = re.match(r"/ligen/([a-z0-9]+)-(\d{4})/([a-z0-9-]+)/(\d+)/", round_uri)
                    div = m.group(3) if m else ""
                    meta = _round_meta(fam, s, div, c[0], ttl) if m else {}
                    res = c[8].replace("�", "½")
                    row = {
                        "season": f"20{s[:2]}/{s[2:]}", "family": fam, "division": div,
                        "team": team, "round": int(c[0]), "board": int(c[1]) if c[1].isdigit() else None,
                        "color": "white" if c[2] == "W" else "black", "home": c[3] == "Heim",
                        "opponent": c[6], "opponent_team": c[5],
                        "opponent_dwz": int(c[7]) if c[7].isdigit() else None,
                        "result": res, "date": meta.get("date", ""),
                        "url": BASE + round_uri if round_uri else BASE + plink,
                    }
                    rows.append(row)
                    if round_uri and res not in ("+", "-"):
                        for g in _round_games_with_moves(round_uri, ident, ttl):
                            g.headers["Source"] = "NSV Liga-PGN"
                            g.headers["SourceURL"] = BASE + round_uri
                            pgns.append(str(g))
    log(f"  nsv: {len(rows)} Mannschaftspartien ({', '.join(fams)}), davon {len(pgns)} mit Zuegen")
    return "\n\n".join(pgns), rows, [{"source": "nsv", "status": "ok",
                                       "detail": f"Verein {club}; Familien {', '.join(fams)}",
                                       "games": len(pgns), "results": len(rows)}]
