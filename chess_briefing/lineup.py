"""Mannschaftsaufstellungen einlesen (fuer chess-opponent-team-prep).

Quellen:
  * Ligaserver-Mannschaftsseite (nsv-online.de, schachbezirk-hannover.de und andere Seiten mit derselben Software):
    .../ligen/<liga>-<saison>/m/<id>/ -> Tabelle "Nr. | Name | DWZ | Runden ..."
  * team.json (vom Agenten aus beliebigen Seiten geschrieben oder von Hand):
    {"team": "...", "source": "...", "players": [{"nr": 1, "name": "Nachname, Vorname", "input": "<Link|Name|FIDE-ID>",
      "fide_id": null, "dwz": 1900, "color": "white|black|both"}]}
  * Liste einzelner Eingaben (ChessBase-Links, Namen, FIDE-IDs), Reihenfolge = Brett.
Auswahl: boards="101-108" bzw. "3-6" (gegen die Nummer der Tabelle, sonst gegen die Position 1..n).
"""
from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from .util import fetch, read_json, strip_accents

LIGASERVER = re.compile(r"/ligen/[a-z0-9-]+-\d{4}/m/\d+/?")


def is_ligaserver_team(src: str) -> bool:
    return bool(re.match(r"https?://", src)) and bool(LIGASERVER.search(src))


def from_ligaserver(url: str) -> dict:
    """Aufstellung einer Mannschaft vom Ligaserver: Nr., Name, DWZ, Spielerseite."""
    url = url if url.endswith("/") else url + "/"
    html = fetch(url, ttl_hours=12)
    if not html:   # Bezirksseiten (z. B. schachbezirk-hannover.de) verlinken relativ, die Seite liegt auf nsv-online.de
        alt = re.sub(r"^https?://[^/]+", "https://nsv-online.de", url)
        html = fetch(alt, ttl_hours=12) if alt != url else None
        url = alt if html else url
    if not html:
        raise ValueError(f"Mannschaftsseite nicht erreichbar: {url}")
    return parse_ligaserver(html, url)


def parse_ligaserver(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find(["h1", "h2"])
    team = title.get_text(" ", strip=True) if title else ""
    players = []
    for table in soup.find_all("table"):
        head = [c.get_text(" ", strip=True) for c in table.find_all("tr")[0].find_all(["th", "td"])] if table.find("tr") else []
        if "Name" not in head or "DWZ" not in head:
            continue
        i_nr, i_name, i_dwz = (head.index("Nr.") if "Nr." in head else 0), head.index("Name"), head.index("DWZ")
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(i_nr, i_name, i_dwz):
                continue
            nr, name = cells[i_nr].get_text(strip=True), cells[i_name].get_text(" ", strip=True)
            if not name or not nr.isdigit():
                continue
            a = cells[i_name].find("a", href=True)
            dwz = cells[i_dwz].get_text(strip=True)
            players.append({"nr": int(nr), "name": name, "input": name, "dwz": int(dwz) if dwz.isdigit() else None,
                            "profile": _abs(url, a["href"]) if a else None})
        break
    if not players:
        raise ValueError(f"Keine Aufstellung (Nr./Name/DWZ) gefunden: {url}")
    # Mannschaftsname: Ueberschrift ist oft die Liga; der Name steht dann im Seitentitel/Brotkrumen
    crumbs = [x.get_text(" ", strip=True) for x in soup.select("h1, h2, h3, .breadcrumb li, title")]
    name = next((c for c in crumbs if c and not re.search(r"\d{4}/\d{4}", c) and len(c) < 60), team)
    return {"team": name, "source": url, "players": players}


def _abs(base: str, href: str) -> str:
    m = re.match(r"(https?://[^/]+)", base)
    return href if href.startswith("http") else (m.group(1) if m else "") + href


def from_file(path: Path) -> dict:
    d = read_json(path)
    if not d or not d.get("players"):
        raise ValueError(f"{path}: keine Spieler (Schlüssel 'players')")
    for k, p in enumerate(d["players"], 1):
        p.setdefault("nr", k)
        p.setdefault("input", p.get("name"))
        if not p.get("name"):
            p["name"] = str(p["input"])
    return d


def from_inputs(inputs: list[str], team: str = "") -> dict:
    return {"team": team or "Aufstellung", "source": "Liste",
            "players": [{"nr": k, "name": x, "input": x} for k, x in enumerate(inputs, 1)]}


def load(sources: list[str], team: str = "") -> dict:
    """Eine Quelle: Ligaserver-URL oder team.json; mehrere Quellen: Liste einzelner Spieler-Eingaben."""
    if len(sources) == 1 and is_ligaserver_team(sources[0]):
        d = from_ligaserver(sources[0])
    elif len(sources) == 1 and sources[0].lower().endswith(".json") and Path(sources[0]).exists():
        d = from_file(Path(sources[0]))
    else:
        d = from_inputs(sources, team)
    if team:
        d["team"] = team
    return d


def select(lineup: dict, boards: str | None) -> list[dict]:
    """Bretter/Spielernummern 'X-Y' oder 'X,Y,Z' gegen die Nummer der Tabelle; passt keine, gegen die Position 1..n."""
    ps = lineup["players"]
    if not boards:
        return ps
    want = set()
    for part in boards.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            want |= set(range(int(a), int(b) + 1))
        elif part:
            want.add(int(part))
    by_nr = [p for p in ps if p.get("nr") in want]
    return by_nr or [p for k, p in enumerate(ps, 1) if k in want]


def assign_colors(players: list[dict], color: str | None, board1: str | None) -> None:
    """Farbe des NUTZERS je Brett: fest (color: white|black|both), abwechselnd ab Brett 1 (board1) oder aus team.json."""
    for k, p in enumerate(players):
        if board1:
            p["color"] = board1 if k % 2 == 0 else ("black" if board1 == "white" else "white")
        elif color:
            p["color"] = color
        p.setdefault("color", "both")


def team_slug(name: str) -> str:
    s = strip_accents(name).lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:60] or "team"


def player_input(p: dict) -> str:
    """Eingabe fuer die Stufe: FIDE-ID vor Link vor Name ('Nachname, Vorname' versteht identify)."""
    return str(p.get("fide_id") or p.get("input") or p["name"])

