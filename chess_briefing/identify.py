"""Spieler-Identifikation aus FIDE-ID, Profil-Link oder Name.

Quellen (ohne Login):
  * Lichess FIDE-Spiegel  https://lichess.org/api/fide/player/{id}  und  ?q=<name>
  * DSB-Spielersuche      https://www.schachbund.de/dwz-spieler.html?search=<name>  (Cookie dwzc=1)
ChessBase-Profilseiten sind hinter einer Bot-Pruefung; aus dem Link wird nur der Name gelesen.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from urllib.parse import quote, unquote

from bs4 import BeautifulSoup

from .util import fetch, name_matches, session, slugify, strip_accents


@dataclass
class Identity:
    last: str = ""
    first: str = ""
    fide_id: int | None = None
    federation: str = ""
    birth_year: int | None = None
    title: str = ""
    elo: dict = field(default_factory=dict)        # standard / rapid / blitz
    fide_inactive: bool = False
    dsb: dict = field(default_factory=dict)        # club, dwz, dwz_index, nu_id, last_eval
    chessbase_url: str = ""
    input: str = ""
    input_kind: str = ""
    confidence: str = ""                           # sicher | wahrscheinlich | unsicher
    notes: list = field(default_factory=list)
    alternatives: list = field(default_factory=list)

    @property
    def display(self) -> str:
        return f"{self.first} {self.last}".strip()

    @property
    def pgn_name(self) -> str:
        return f"{self.last}, {self.first}"

    @property
    def slug(self) -> str:
        return slugify(self.last, self.first)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["display"], d["slug"] = self.display, self.slug
        return d


class AmbiguousPlayer(Exception):
    def __init__(self, msg: str, candidates: list):
        super().__init__(msg)
        self.candidates = candidates


# ---------------------------------------------------------------- Eingabe parsen
def parse_input(text: str) -> dict:
    t = text.strip()
    if re.fullmatch(r"\d{4,10}", t):
        return {"kind": "fide_id", "fide_id": int(t)}
    m = re.search(r"ratings\.fide\.com/(?:profile|card\.phtml\?event=)/?(\d+)", t)
    if m:
        return {"kind": "fide_url", "fide_id": int(m.group(1))}
    m = re.search(r"lichess\.org/fide/(\d+)", t)
    if m:
        return {"kind": "lichess_fide_url", "fide_id": int(m.group(1))}
    m = re.search(r"players\.chessbase\.com/\w+/player/([^/?#]+)_([^/_?#]+)(?:/(\d+))?", t)   # Nummer am Ende optional
    if m:
        last, first = unquote(m.group(1)).replace("_", " "), unquote(m.group(2)).replace("_", " ")
        return {"kind": "chessbase_url", "last": last.title(), "first": first.title(), "url": t}
    m = re.search(r"chess\.com/(?:players|games)/([a-z0-9-]+)", t)
    if m:
        parts = m.group(1).split("-")
        return {"kind": "chesscom_players_url", "last": parts[-1].title(),
                "first": " ".join(parts[:-1]).title()}
    if "," in t:
        last, first = [x.strip() for x in t.split(",", 1)]
        return {"kind": "name", "last": last, "first": first}
    parts = t.split()
    if len(parts) >= 2:
        return {"kind": "name", "last": parts[-1], "first": " ".join(parts[:-1])}
    return {"kind": "name", "last": t, "first": ""}


# ---------------------------------------------------------------- FIDE (Lichess-Spiegel)
def fide_player(fide_id: int) -> dict | None:
    txt = fetch(f"https://lichess.org/api/fide/player/{fide_id}", ttl_hours=72)
    if not txt:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


def fide_search(query: str) -> list[dict]:
    txt = fetch(f"https://lichess.org/api/fide/player?q={quote(query)}", ttl_hours=72)
    try:
        return json.loads(txt) if txt else []
    except json.JSONDecodeError:
        return []


def _split_fide_name(name: str) -> tuple[str, str]:
    if "," in name:
        last, first = [x.strip() for x in name.split(",", 1)]
        first = re.sub(r"(^|[\s,]+)(Dr|Prof|Dipl\.?-?Ing)\.?(?=[\s,]|$)", " ", first).strip(" ,")   # "Dirk, Dr." -> "Dirk"
        return last, first
    parts = name.split()
    return parts[-1], " ".join(parts[:-1])


# ---------------------------------------------------------------- DSB
def dsb_search(last: str, first: str = "") -> list[dict]:
    q = f"{last},{first}" if first else last
    s = session()
    s.cookies.set("dwzc", "1", domain=".schachbund.de")
    txt = fetch(f"https://www.schachbund.de/dwz-spieler.html?search={quote(q)}", ttl_hours=24)
    if not txt or "searchresult" not in txt:
        return []
    soup = BeautifulSoup(txt[txt.find("searchresult"):], "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue
        a = tds[0].find("a", href=True)
        nu = re.search(r"(NU\d+)", a["href"]).group(1) if a and "NU" in a["href"] else ""
        dwz_raw = tds[2].get_text(" ", strip=True)
        m = re.match(r"(\d{3,4})\D*(\d+)?", dwz_raw.replace("\xa0", " "))
        rows.append({
            "name": tds[0].get_text(" ", strip=True), "nu_id": nu,
            "last_eval": tds[1].get_text(strip=True),
            "dwz": int(m.group(1)) if m else None,
            "dwz_index": int(m.group(2)) if m and m.group(2) else None,
            "elo": int(tds[3].get_text(strip=True)) if tds[3].get_text(strip=True).isdigit() else None,
            "title": tds[4].get_text(strip=True), "club": tds[5].get_text(" ", strip=True),
        })
    return rows


# ---------------------------------------------------------------- Aufloesung
def resolve(text: str, federation: str | None = None, birth_year: int | None = None,
            fide_id: int | None = None) -> Identity:
    p = parse_input(text)
    ident = Identity(input=text, input_kind=p["kind"])
    if fide_id:
        p = {**p, "fide_id": fide_id}
    if p["kind"] == "chessbase_url":
        ident.chessbase_url = p["url"]

    rec = None
    if p.get("fide_id"):
        rec = fide_player(p["fide_id"])
        if not rec:
            raise AmbiguousPlayer(f"FIDE-ID {p['fide_id']} nicht gefunden.", [])
        ident.confidence = "sicher"
        ident.notes.append(f"FIDE-ID {p['fide_id']} direkt aufgeloest.")
    else:
        last, first = p["last"], p["first"]
        cands = fide_search(f"{first} {last}".strip()) or fide_search(last)
        strong = [c for c in cands if name_matches(c["name"], last, first) == "strong"]
        if federation:
            strong = [c for c in strong if c.get("federation") == federation] or strong
        if birth_year:
            strong = [c for c in strong if c.get("year") == birth_year] or strong
        if len(strong) == 1:
            rec = strong[0]
            ident.confidence = "sicher" if p["kind"] != "name" else "wahrscheinlich"
            ident.notes.append(f"Namenssuche FIDE: eindeutiger Treffer {rec['name']} ({rec.get('federation')}, {rec.get('year')}).")
        elif len(strong) > 1:
            ger = [c for c in strong if c.get("federation") == "GER"]
            if len(ger) == 1 and not federation:
                rec = ger[0]
                ident.confidence = "wahrscheinlich"
                ident.notes.append("Mehrere FIDE-Namensgleiche; GER-Spieler gewaehlt.")
                ident.alternatives = [c for c in strong if c is not rec]
            else:
                raise AmbiguousPlayer("Mehrere Spieler passen auf den Namen.", strong)
        else:
            ident.last, ident.first = last, first
            ident.confidence = "unsicher"
            ident.notes.append("Kein FIDE-Eintrag gefunden; Identitaet nur ueber den Namen.")

    if rec:
        ident.fide_id = rec["id"]
        ident.last, ident.first = _split_fide_name(rec["name"])
        ident.federation = rec.get("federation", "")
        ident.birth_year = rec.get("year")
        ident.title = rec.get("title", "") or ""
        ident.fide_inactive = bool(rec.get("inactive"))
        ident.elo = {k: rec[k] for k in ("standard", "rapid", "blitz") if rec.get(k)}

    # DSB: Verein und DWZ (nur fuer GER oder ohne FIDE-Eintrag sinnvoll)
    if ident.federation in ("GER", "") and ident.last:
        rows = [r for r in dsb_search(ident.last, ident.first)
                if name_matches(r["name"], ident.last, ident.first) == "strong"]
        if len(rows) > 1 and ident.elo.get("standard"):
            rows = [r for r in rows if r["elo"] == ident.elo["standard"]] or rows
        if len(rows) == 1:
            ident.dsb = rows[0]
            ident.notes.append(f"DSB: {rows[0]['club']}, DWZ {rows[0]['dwz']} (Auswertung {rows[0]['last_eval']}).")
        elif len(rows) > 1:
            ident.notes.append(f"DSB: {len(rows)} Namensgleiche, nicht eindeutig zugeordnet.")
            ident.alternatives += [{"dsb": r} for r in rows]

    if not ident.chessbase_url and ident.last:
        cb_last = strip_accents(ident.last).lower().replace(" ", "-")
        cb_first = strip_accents(ident.first.split()[0] if ident.first else "").lower()
        ident.chessbase_url = f"https://players.chessbase.com/de/player/{cb_last}_{cb_first}"
    return ident
