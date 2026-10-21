"""Chessable: Account-Pruefung, oeffentlich studierte Kurse, Kurssuche, Kurs-Signaturen.

Befund (Stand 10/2026, ohne Login):
  * POST https://www.chessable.com/api/graph  query user(username) ->
      Fehler  = Name existiert nicht
      null    = Account existiert, Profil privat
      Objekt  = oeffentliches Profil; studiedCourses(username) liefert Kursname, Autor, gelernte Varianten
  * GET /api/v1/course/search?query=...  -> Kurs-Metadaten (Name, Autor, Farbe, Beschreibung, Erscheinungsdatum)
  * Kursinhalte (Zuege) nur mit Login -> trennscharfe Schluesselentscheidungen kommen aus
    chess_briefing/data/course_signatures.json (gepflegt, Quelle je Eintrag angegeben).
"""
from __future__ import annotations

import datetime as dt
import json
import time
from urllib.parse import quote

import chess

from .. import config
from ..util import fetch, session

API = "https://www.chessable.com/api/graph"
Q_USER = "query GetUser($username: String){ user(username: $username){ id username isPro } }"
Q_COURSES = ("query GetStudiedCourses($username: String, $allbooks: Boolean, $offset: Int, $limit: Int){ "
             "studiedCourses(username: $username, allbooks: $allbooks, limit: $limit, offset: $offset){ "
             "id name openingsNum studiedVariations percentageStudied author{ username name title } } }")
SIG_FILE = config.DATA_DIR / "course_signatures.json"


def _graph(query: str, variables: dict) -> dict:
    cdir = config.CACHE_DIR / "chessable"
    cdir.mkdir(parents=True, exist_ok=True)
    key = (query[:20] + json.dumps(variables, sort_keys=True)).encode().hex()[:80]
    f = cdir / f"{key}.json"
    if f.exists() and time.time() - f.stat().st_mtime < 7 * 86400:
        return json.loads(f.read_text(encoding="utf-8"))
    try:
        r = session().post(API, json={"query": query, "variables": variables}, timeout=30,
                           headers={"Origin": "https://www.chessable.com", "Referer": "https://www.chessable.com/"})
        d = r.json()
    except Exception:
        return {"errors": ["netz"]}
    f.write_text(json.dumps(d), encoding="utf-8")
    return d


def check_user(username: str) -> dict:
    d = _graph(Q_USER, {"username": username})
    if d.get("errors"):
        return {"username": username, "status": "nicht vorhanden"}
    u = (d.get("data") or {}).get("user")
    if u is None:
        return {"username": username, "status": "privat"}
    c = _graph(Q_COURSES, {"username": username, "allbooks": True, "offset": 0, "limit": 100})
    courses = ((c.get("data") or {}).get("studiedCourses")) or []
    return {"username": u["username"], "status": "öffentlich", "pro": u.get("isPro"),
            "courses": [{"id": x["id"], "name": x["name"], "author": (x.get("author") or {}).get("name"),
                         "variations": x.get("openingsNum"), "studied": x.get("studiedVariations"),
                         "pct": x.get("percentageStudied")} for x in courses]}


def _txt(v) -> str:
    if isinstance(v, dict):
        return str(v.get("en") or v.get("de") or next(iter(v.values()), ""))
    return str(v or "")


def search_courses(query: str, limit: int = 12) -> list[dict]:
    txt = fetch(f"https://www.chessable.com/api/v1/course/search?query={quote(query)}&limit={limit}&wildcard=1&locale=en",
                ttl_hours=24 * 14)
    try:
        hits = json.loads(txt)["data"]["hits"] if txt else []
    except (KeyError, json.JSONDecodeError):
        return []
    out = []
    for h in hits:
        c = h["hit"]
        if c.get("type") != "opening":
            continue
        pub = c.get("published_at")
        out.append({"id": c["id"], "name": _txt(c.get("name")), "author": (c.get("user") or {}).get("author_name"),
                    "title": (c.get("user") or {}).get("chess_title"), "color": c.get("color"),
                    "url": "https://www.chessable.com/" + c.get("url", ""), "rating": round(c.get("rating") or 0, 2),
                    "rated_by": c.get("rated_by"), "elo": [c.get("elo_low"), c.get("elo_high")],
                    "published": dt.datetime.fromtimestamp(pub, dt.UTC).date().isoformat() if isinstance(pub, (int, float)) else pub,
                    "short_desc": _txt(c.get("short_desc"))[:300]})
    return out


def load_signatures() -> list[dict]:
    if SIG_FILE.exists():
        return json.loads(SIG_FILE.read_text(encoding="utf-8")).get("courses", [])
    return []


def _epd(path: str) -> tuple[str, bool]:
    b = chess.Board()
    for t in path.split():
        b.push_san(t)
    return b.epd(), b.turn


def _positions(sans: list[str], max_ply: int = 30) -> dict[str, int]:
    """EPD -> Halbzug-Index des Zuges, der aus dieser Stellung gespielt wurde."""
    b = chess.Board()
    out = {}
    for i, s in enumerate(sans[:max_ply]):
        out.setdefault(b.epd(), i)
        b.push_san(s)
    out.setdefault(b.epd(), len(sans[:max_ply]))
    return out


def match_signatures(otb_games: list[dict], online_games: list[dict], player_names: list[str]) -> list[dict]:
    """Je Kurs-Signatur (stellungsbasiert, Zugumstellungen zaehlen mit):
    family_* = Partien, in denen er mit der Kursfarbe die Grundstellung erreicht;
    decisions = an hinterlegten Kursstellen: wie oft er dort den Kurszug spielt (Treffer/erreicht);
    first_online = erstes Auftreten der Grundstellung online (Zeitachse fuer Kurs-Uebernahme)."""
    res = []
    for sig in load_signatures():
        color_white = sig["color"] == "white"
        fam_epd, _ = _epd(sig["family_line"])
        decs = []
        for d in sig.get("decisions", []):
            e, turn = _epd(d["path"])
            decs.append((d, e))
        row = {"id": sig["id"], "name": sig["name"], "author": sig.get("author"), "color": sig["color"],
               "published": sig.get("published"), "url": sig.get("url"), "source": sig.get("source"),
               "family_line": sig["family_line"], "family_otb": 0, "family_online": 0, "decisions": [], "first_online": None}
        hits = [{"path": d["path"], "move": d["move"], "note": d.get("note", ""), "otb": [0, 0], "online": [0, 0]} for d, _ in decs]
        for src, games in (("otb", otb_games), ("online", online_games)):
            for g in games:
                if g["is_white"] != color_white:
                    continue
                pos = _positions(g["sans"])
                if fam_epd not in pos:
                    continue
                row["family_" + src] += 1
                if src == "online" and (row["first_online"] is None or g["date"] < row["first_online"]):
                    row["first_online"] = g["date"]
                for h, (d, e) in zip(hits, decs):
                    if e in pos and pos[e] < len(g["sans"]):
                        h[src][1] += 1
                        h[src][0] += g["sans"][pos[e]] == d["move"]
        row["decisions"] = hits
        if row["family_otb"] or row["family_online"]:
            res.append(row)
    res.sort(key=lambda r: -(r["family_otb"] * 3 + r["family_online"]))
    return res
