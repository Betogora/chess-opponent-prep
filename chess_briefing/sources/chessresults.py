"""chess-results.com (Turnierserver des Swiss-Managers).

Zwei oeffentliche Formulare, kein Login:
  SpielerSuche.aspx - Turniere eines Spielers (FIDE-ID, sonst Name): nur fuers Protokoll (Turnier, Ende, Link)
  PartieSuche.aspx  - Partien, die Veranstalter hochgeladen haben; Knopf "Download as PGN-File" liefert sie als PGN
Viele Turniere haben keine Partien (nur Ergebnisse) - dann steht im Protokoll "n Turniere, 0 Partien".

Nutzungsbedingungen (Impressum): Turnierdaten und Partien duerfen nicht kopiert und auf anderen Seiten publiziert
werden. Die Partien dienen nur der privaten Vorbereitung; output/ und cache/ gehen nie in Weitergaben (pack).
robots.txt erlaubt den Abruf. Hoeflich: ehrliche App-Kennung, mindestens PAUSE s zwischen Abrufen, 24 h Cache.
Bei Bot-Pruefung oder Sperre wird nichts umgangen: Browser-Hinweis wie bei ChessBase (Partiesuche von Hand,
PGN als output/players/<slug>/inbox/chessresults_<slug>.pgn ablegen).
"""
from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path

import logging

import chess.pgn
import requests
from bs4 import BeautifulSoup

from ..config import CACHE_DIR
from ..util import log, name_matches, session

BASE = "https://chess-results.com"
GAME_SEARCH = f"{BASE}/PartieSuche.aspx?lan=1"
PLAYER_SEARCH = f"{BASE}/SpielerSuche.aspx?lan=1"
PAUSE = 3.0                  # Sekunden zwischen zwei Abrufen
TTL_HOURS = 24
MAX_ROWS = "2"               # Zeilenauswahl der Formulare: "2" = 500
_BOT = re.compile(r"captcha|cf-chl|challenge-platform|too many requests|zu viele (anfragen|zugriffe)|access denied", re.I)
_last = 0.0


class Blocked(Exception):
    """Bot-Pruefung, Sperre oder geaendertes Formular - Browser-Schritt statt Umgehung."""


def _request(method: str, url: str, data: dict | None = None) -> requests.Response:
    global _last
    wait = PAUSE - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    try:
        r = session().request(method, url, data=data, timeout=60)
    finally:
        _last = time.time()
    if r.status_code in (403, 429, 503) or _BOT.search(r.text[:20000]):
        raise Blocked(f"HTTP {r.status_code} bei {url.split('?')[0]}")
    r.raise_for_status()
    return r


def _form(soup: BeautifulSoup, url: str) -> tuple[str, dict]:
    form = soup.find("form")
    if not form or not form.find("input", attrs={"name": "__VIEWSTATE"}):
        raise Blocked("Formular nicht gefunden (Seite geaendert oder Bot-Pruefung)")
    data = {i["name"]: i.get("value", "") for i in form.find_all("input")
            if i.get("name") and i.get("type", "text") in ("hidden", "text", "date")}
    for sel in form.find_all("select"):
        opt = sel.find("option", selected=True) or sel.find("option")
        data[sel["name"]] = opt.get("value") if opt else ""
    return requests.compat.urljoin(url, form.get("action") or url), data


def _submit(page_url: str, fields: dict, button: tuple[str, str]) -> requests.Response:
    """Formular laden, Felder setzen, Knopf druecken (ASP.NET-Postback mit Viewstate)."""
    r = _request("GET", page_url)
    action, data = _form(BeautifulSoup(r.text, "html.parser"), r.url)
    data.update(fields)
    data[button[0]] = button[1]
    return _request("POST", action, data)


def _search_fields(ident, prefix: str, fide_field: str) -> dict:
    if ident.fide_id:
        return {f"{prefix}{fide_field}": str(ident.fide_id)}
    return {f"{prefix}txt_nachname": ident.last, f"{prefix}txt_vorname": (ident.first or "").split()[0] if ident.first else ""}


def _table_rows(soup: BeautifulSoup) -> list[dict]:
    """Ergebnistabelle (CRs2 bzw. GridView) -> Zeilen als {Spaltenname: Text, '_links': [...]}"""
    t = soup.find("table", id="P1_GridView1") or soup.find("table", class_="CRs2")
    if not t:
        return []
    trs = t.find_all("tr")
    if not trs:
        return []
    head = [c.get_text(" ", strip=True) for c in trs[0].find_all(["th", "td"])]
    out = []
    for tr in trs[1:]:
        cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
        if len(cells) != len(head):
            continue
        row = dict(zip(head, cells))
        row["_links"] = [a["href"] for a in tr.find_all("a", href=True)]
        out.append(row)
    return out


def player_tournaments(ident) -> list[dict]:
    r = _submit(PLAYER_SEARCH, {**_search_fields(ident, "ctl00$P1$", "txt_fideID"), "ctl00$P1$combo_anzahl_zeilen": MAX_ROWS},
                ("ctl00$P1$cb_suchen", "Search"))
    out = []
    for row in _table_rows(BeautifulSoup(r.text, "html.parser")):
        if not ident.fide_id and name_matches(row.get("Name", ""), ident.last, ident.first) != "strong":
            continue
        link = next((h for h in row["_links"] if re.match(r"tnr\d+\.aspx", h) and "snr=" not in h), "")
        out.append({"name": row.get("Tournament", ""), "end": row.get("End-Date", "").replace("/", "-"),
                    "url": f"{BASE}/{link}" if link else ""})
    return out


def game_search(ident) -> tuple[str, list[dict]]:
    """-> (PGN aller gefundenen Partien, Trefferliste mit GameID je Partie in derselben Reihenfolge)"""
    fields = {**_search_fields(ident, "ctl00$P1$", "Txt_FideID"), "ctl00$P1$combo_anzahl_zeilen": MAX_ROWS}
    r = _submit(GAME_SEARCH, fields, ("ctl00$P1$cb_SuchenPartie", "Search"))
    soup = BeautifulSoup(r.text, "html.parser")
    rows = _table_rows(soup)
    if not rows:
        return "", []
    action, data = _form(soup, r.url)
    data.update(fields)
    data["ctl00$P1$cb_DownLoadPGN"] = "Download as PGN-File"
    pgn = _request("POST", action, data)
    txt = pgn.content.decode("utf-8", errors="replace").lstrip("﻿")
    if txt.strip() and "[Event " not in txt[:2000]:
        raise Blocked("Download lieferte kein PGN")
    return txt, [{k: row.get(k, "") for k in ("dbkey", "Rd", "Tournament", "PGN", "GameID")} for row in rows]


def _cached(key: str, fn):
    path = CACHE_DIR / "chessresults" / f"{key}.json"
    if path.exists() and time.time() - path.stat().st_mtime < TTL_HOURS * 3600:
        return json.loads(path.read_text(encoding="utf-8"))
    val = fn()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(val, ensure_ascii=False), encoding="utf-8")
    return val


def _moves_prefix(s: str, n: int = 6) -> list[str]:
    return [t for t in re.sub(r"\d+\.(\.\.)?", " ", s).split() if t not in ("*", "1-0", "0-1", "1/2-1/2")][:n]


def tag_games(pgn: str, rows: list[dict], ident) -> tuple[list[str], int, int]:
    """Spielerseite markieren (FideId-Kopf, damit der Filter auch bei abweichender Schreibweise greift), Quelle und
    Link zur Partie setzen. Die Trefferliste steht in derselben Reihenfolge wie das PGN; der Link wird nur gesetzt,
    wenn Runde und Zuganfang der Zeile passen. Chess960/Aufbau-Stellungen gehoeren nicht in den Eroeffnungsbaum,
    fehlerhafte Notation wird nicht halb uebernommen. -> (Partien als PGN-Text, ohne Zuege, aussortiert)"""
    out, empty, skipped, stream = [], 0, 0, io.StringIO(pgn)
    pgn_log = logging.getLogger("chess.pgn")
    level = pgn_log.level
    pgn_log.setLevel(logging.CRITICAL)          # Notationsfehler stehen in g.errors
    try:
        for i, g in enumerate(iter(lambda: chess.pgn.read_game(stream), None)):
            h = g.headers
            if g.next() is None:
                empty += 1
                continue
            if "960" in h.get("Variant", "") or h.get("FEN") or g.errors:
                skipped += 1
                continue
            wm = name_matches(h.get("White", ""), ident.last, ident.first)
            bm = name_matches(h.get("Black", ""), ident.last, ident.first)
            if ident.fide_id and bool(wm) != bool(bm):       # FIDE-Suche: nur eindeutige Seite markieren
                h["WhiteFideId" if wm else "BlackFideId"] = str(ident.fide_id)
            elif not ident.fide_id and not ((wm == "strong") ^ (bm == "strong")):
                continue
            h["Source"] = "chess-results.com"
            row = rows[i] if i < len(rows) else None
            sans = [n.san() for n in list(g.mainline())[:4]]
            if row and row.get("GameID") and row.get("Rd", "") == h.get("Round", "").split(".")[0]                     and _moves_prefix(row.get("PGN", ""), len(sans)) == sans:
                h["SourceURL"] = f"{BASE}/PartieSuche.aspx?lan=1&art=36&id={row['GameID']}"
            out.append(str(g))
    finally:
        pgn_log.setLevel(level)
    return out, empty, skipped


def browser_hint(ident, inbox: Path) -> dict:
    by = f"FIDE-ID {ident.fide_id}" if ident.fide_id else f"Name {ident.last}, {ident.first}"
    return {"open": GAME_SEARCH, "steps": f"{by} eintragen, 'Download as PGN-File' klicken",
            "save_as": str(inbox / f"chessresults_{ident.slug}.pgn")}


def collect(ident, inbox: Path) -> tuple[str, list[dict]]:
    files = sorted(inbox.glob("chessresults_*.pgn"))
    if files:          # von Hand geladen (Browser-Schritt): kein Netzabruf
        txt = "\n\n".join(f.read_bytes().decode("utf-8", errors="replace").lstrip("﻿") for f in files)
        games, _, _ = tag_games(txt, [], ident)
        return "\n\n".join(games), [{"source": "chess-results", "status": "ok",
                                     "detail": ", ".join(f.name for f in files), "games": len(games)}]
    if not (ident.fide_id or ident.last):
        return "", [{"source": "chess-results", "status": "uebersprungen", "detail": "weder FIDE-ID noch Name"}]
    key = f"{ident.fide_id}" if ident.fide_id else re.sub(r"\W+", "_", f"{ident.last}_{ident.first}".lower())
    try:
        tours = _cached(f"tournaments_{key}", lambda: player_tournaments(ident))
        res = _cached(f"games_{key}", lambda: dict(zip(("pgn", "rows"), game_search(ident))))
    except Blocked as ex:
        log(f"  chess-results: {ex} – Browser-Schritt nötig")
        return "", [{"source": "chess-results", "status": "browser_noetig", "detail": str(ex),
                     "hint": browser_hint(ident, inbox)}]
    games, empty, skipped = tag_games(res["pgn"], res["rows"], ident)
    log(f"  chess-results: {len(tours)} Turniere, {len(games)} Partien mit Zügen" + (f", {empty} ohne Züge" if empty else "")
        + (f", {skipped} aussortiert (Chess960/Aufbau/Notationsfehler)" if skipped else ""))
    return "\n\n".join(games), [{"source": "chess-results", "status": "ok",
                                 "detail": f"{len(tours)} Turniere, {len(games)} Partien mit Zügen",
                                 "games": len(games), "without_moves": empty, "skipped": skipped, "tournaments": tours[:40],
                                 "url": GAME_SEARCH}]
