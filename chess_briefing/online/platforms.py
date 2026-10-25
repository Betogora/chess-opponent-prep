"""Lichess- und Chess.com-Zugriffe (nur oeffentliche Endpunkte; optional LICHESS_TOKEN aus der Umgebung/.env).

Einheitliches Partieformat:
  {id, platform, white, black, sans, ucis, result, date, speed, url, white_rating, black_rating}
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import re
import time

import chess
import chess.pgn

from .. import config
from ..util import fetch, host_gate, log, session, strip_accents

LI = "https://lichess.org"
CC = "https://api.chess.com/pub"
_ABBR = {"sk": "schachklub", "sv": "schachverein", "sf": "schachfreunde", "sc": "schachclub", "sg": "schachgemeinschaft"}


_TOKEN_KEY = re.compile(r"^LICHESS_TOKEN(_\w+)?$")
_tok_idx = 0      # aktiver Token; bei 429 wird auf den naechsten gewechselt


def _tokens() -> list[tuple[str, str]]:
    """Alle Lichess-Tokens als (Name, Wert): LICHESS_TOKEN zuerst, dann LICHESS_TOKEN_2, _3, … aus Umgebung und .env
    (Umgebung gewinnt). Leere Werte und Dubletten fallen weg."""
    found: dict[str, str] = {}
    env = config.ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and _TOKEN_KEY.match(k.strip()):
                found[k.strip()] = v.strip().strip('"')
    found.update({k: v.strip() for k, v in os.environ.items() if _TOKEN_KEY.match(k)})
    order = sorted(found, key=lambda k: (k != "LICHESS_TOKEN", len(k), k))
    out, seen = [], set()
    for k in order:
        if found[k] and found[k] not in seen:
            seen.add(found[k])
            out.append((k, found[k]))
    return out


def _token() -> str | None:
    toks = _tokens()
    return toks[_tok_idx % len(toks)][1] if toks else None


def _rotate_token() -> bool:
    """Naechsten Token aktivieren. False, wenn es keinen weiteren gibt (dann warten).
    Hilft nur gegen Limits je Token/Account; Limits je IP-Adresse bleiben."""
    global _tok_idx
    n = len(_tokens())
    if n < 2 or _tok_idx >= n - 1:
        return False
    _tok_idx += 1
    note(f"Lichess-Ratenlimit, wechsle auf {_tokens()[_tok_idx][0]}")
    return True


def _ndjson(txt: str | None) -> list[dict]:
    out = []
    for line in (txt or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _json(txt):
    try:
        return json.loads(txt) if txt else None
    except json.JSONDecodeError:
        return None


def _ucis(sans: list[str]) -> list[str] | None:
    b = chess.Board()
    out = []
    try:
        for s in sans:
            mv = b.parse_san(s)
            out.append(mv.uci())
            b.push(mv)
    except ValueError:
        return None
    return out


def name_variants(first: str, last: str, birth_year: int | None) -> list[str]:
    f = re.sub(r"[^a-z]", "", strip_accents(first.split()[0] if first else "").lower())
    l = re.sub(r"[^a-z]", "", strip_accents(last).lower())
    yy = f"{birth_year % 100:02d}" if birth_year else ""
    v = [f + l, l + f, f"{f}_{l}", f"{l}_{f}", f"{f}-{l}", f"{f}.{l}", f[:1] + l, l + f[:1], f + l[:1], l]
    if birth_year:
        v += [f + l + yy, l + yy, f + l + str(birth_year), l + str(birth_year), f[:1] + l + yy, f + yy]
    return [x for x in dict.fromkeys(v) if len(x) >= 3]


# ---------------------------------------------------------------- Lichess
def lichess_find_teams(club: str, extra: list[str]) -> list[dict]:
    toks = [t for t in re.split(r"[\s/\-.,()]+", strip_accents(club).lower())
            if len(t) > 2 and not t.isdigit() and t not in _ABBR and t not in {"schach", "verein", "club", "e", "v"}]
    teams = {t: {"id": t, "name": t, "via": "accounts.json"} for t in extra}
    for tok in toks:
        d = _json(fetch(f"{LI}/api/team/search?text={tok}", ttl_hours=168)) or {}
        for t in d.get("currentPageResults", []):
            name = strip_accents(t["name"]).lower()
            extra_toks = [x for x in re.split(r"[\s/\-.,()]+", name) if len(x) > 2 and x not in toks
                          and x not in _ABBR and x not in _ABBR.values() and not x.isdigit()]
            if all(x in name for x in toks) and len(extra_toks) <= 1 and t["id"] not in teams:
                teams[t["id"]] = {"id": t["id"], "name": t["name"], "members": t.get("nbMembers"), "via": "Teamsuche"}
    return list(teams.values())


def lichess_team_games(team_id: str) -> list[dict]:
    hdr = {"Accept": "application/x-ndjson"}
    games = []
    arenas = _ndjson(fetch(f"{LI}/api/team/{team_id}/arena?max=300", ttl_hours=72, headers=hdr))
    swiss = _ndjson(fetch(f"{LI}/api/team/{team_id}/swiss?max=300", ttl_hours=72, headers=hdr))
    for kind, tours in (("tournament", arenas), ("swiss", swiss)):
        for t in tours:
            finished = t.get("status") in (30, "finished")
            txt = fetch(f"{LI}/api/{kind}/{t['id']}/games?moves=true", ttl_hours=24 * 365 if finished else 24, headers=hdr)
            for g in _ndjson(txt):
                rec = _lichess_rec(g)
                if rec:
                    rec["event"] = t.get("fullName") or t.get("name") or ""
                    games.append(rec)
            time.sleep(0.15)
    return games


def _lichess_rec(g: dict) -> dict | None:
    if g.get("variant", "standard") != "standard" or not g.get("moves"):
        return None
    sans = g["moves"].split()
    ucis = _ucis(sans)
    if not ucis or len(sans) < 4:
        return None
    w = (g["players"]["white"].get("user") or {}).get("name", "")
    b = (g["players"]["black"].get("user") or {}).get("name", "")
    winner = g.get("winner")
    if winner:
        res = "1-0" if winner == "white" else "0-1"
    else:
        res = "1/2-1/2" if g.get("status") in ("draw", "stalemate", "outoftime", "insufficientMaterialClaim") else "*"
    return {"id": "li_" + g["id"], "platform": "lichess", "white": w, "black": b, "sans": sans, "ucis": ucis,
            "result": res, "date": dt.datetime.fromtimestamp(g["createdAt"] / 1000, dt.UTC).date().isoformat(),
            "speed": g.get("speed", ""), "url": f"{LI}/{g['id']}",
            "white_rating": g["players"]["white"].get("rating"), "black_rating": g["players"]["black"].get("rating"),
            # Team-Battles: Team des Spielers (sonst fehlt das Feld)
            "white_team": g["players"]["white"].get("team"), "black_team": g["players"]["black"].get("team"),
            # nur beim Account-Export gesetzt (evals/clocks/opening=true); Tournier-Exporte lassen sie leer
            "analysis": g.get("analysis"), "clocks_cs": g.get("clocks"), "opening": g.get("opening"),
            "time_control": f"{g['clock']['initial']}+{g['clock']['increment']}" if g.get("clock") else ""}


def lichess_team_members(team_id: str) -> list[str]:
    """Mitgliederliste eines Teams. Bei privater Liste nur mit LICHESS_TOKEN (Recht team:read) und Teamzugehoerigkeit."""
    text = _lichess_request("GET", f"{LI}/api/team/{team_id}/users", timeout=60)
    if not text:
        return []
    return [u.get("name") or u.get("username") or u.get("id") for u in _ndjson(text)
            if (u.get("name") or u.get("username") or u.get("id"))]


def lichess_users(names: list[str]) -> dict[str, dict]:
    """Profile per Sammelabfrage (POST /api/users), mit Datei-Cache."""
    out, todo = {}, []
    cdir = config.CACHE_DIR / "lichess_users"
    cdir.mkdir(parents=True, exist_ok=True)
    for n in names:
        f = cdir / f"{n.lower()}.json"
        if f.exists() and time.time() - f.stat().st_mtime < 7 * 86400:
            out[n.lower()] = json.loads(f.read_text(encoding="utf-8"))
        else:
            todo.append(n)
    for i in range(0, len(todo), 100):
        try:
            with host_gate(LI):
                r = session().post(f"{LI}/api/users", data=",".join(todo[i:i + 100]), timeout=40)
            for u in r.json():
                out[u["id"]] = u
                (cdir / f"{u['id']}.json").write_text(json.dumps(u), encoding="utf-8")
        except Exception:
            pass
    return out


def lichess_autocomplete(term: str) -> list[str]:
    d = _json(fetch(f"{LI}/api/player/autocomplete?term={term}&object=1", ttl_hours=168)) or {}
    return [x["name"] for x in d.get("result", [])]


ANALYSIS_PARAMS = {"evals": "true", "clocks": "true", "opening": "true"}


def _lichess_request(method: str, url: str, **kw) -> str:
    """Eine Lichess-Anfrage (offizielle API) mit optionalem Token. Bei 429 erst auf den naechsten Token wechseln,
    erst wenn keiner mehr frei ist einmal 65 s warten."""
    base = {"Accept": "application/x-ndjson", **kw.pop("headers", {})}
    timeout = kw.pop("timeout", 600)
    waited = False
    for _ in range(len(_tokens()) + 2):
        hdr = dict(base)
        tok = _token()
        if tok:
            hdr["Authorization"] = f"Bearer {tok}"
        try:
            with host_gate(url):
                r = session().request(method, url, headers=hdr, timeout=timeout, **kw)
        except Exception:
            return ""
        if r.status_code == 429:
            if _rotate_token():
                continue
            if waited:
                return ""
            note("Lichess-Ratenlimit, warte 65 s")
            time.sleep(65)
            waited = True
            continue
        return r.text if r.status_code == 200 else ""
    return ""


def lichess_user_games(username: str, since_days: int, max_games: int) -> list[dict]:
    """Neueste Partien (nur Zuege), z. B. fuer den Fingerabdruck weiterer Teammitglieder. 24 h Cache."""
    cache = config.CACHE_DIR / "lichess_games" / f"{username.lower()}_recent_{since_days}_{max_games}.ndjson"
    if cache.exists() and time.time() - cache.stat().st_mtime < 24 * 3600:
        txt = cache.read_text(encoding="utf-8")
    else:
        since = int((time.time() - since_days * 86400) * 1000)
        txt = _lichess_request("GET", f"{LI}/api/games/user/{username}",
                               params={"max": max_games, "since": since, "moves": "true", "perfType": "blitz,rapid,classical"})
        if txt:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(txt, encoding="utf-8")
    return [x for x in (_lichess_rec(g) for g in _ndjson(txt)) if x]


def lichess_all_games(username: str, since_days: int, cap: int) -> list[dict]:
    """ALLE Partien (Blitz/Schnell/Klassisch, nur Zuege) der letzten since_days Tage - Grundlage fuer die
    vollstaendige Zaehlung je Stellung (wie der Spieler-Explorer im Analysebrett, aber ohne Token).

    Rohdaten werden je Account gespeichert; spaetere Laeufe laden nur Partien seit der neuesten bekannten nach.
    Offizieller Export-Endpunkt; util.session() meldet sich als Anwendung."""
    cache = config.CACHE_DIR / "lichess_games" / f"{username.lower()}_all.ndjson"
    rows = {g["id"]: g for g in _ndjson(cache.read_text(encoding="utf-8"))} if cache.exists() else {}
    window_start = int((time.time() - since_days * 86400) * 1000)
    newest = max((g["createdAt"] for g in rows.values()), default=0)
    since = max(window_start, newest + 1)
    fresh = cache.exists() and time.time() - cache.stat().st_mtime < 3600
    if not fresh:
        if not rows:
            note(f"{username}: lade alle Partien der letzten {since_days // 365} Jahre (einmalig, kann Minuten dauern)")
        txt = _lichess_request("GET", f"{LI}/api/games/user/{username}",
                               params={"since": since, "max": cap, "moves": "true", "tags": "false",
                                       "perfType": "blitz,rapid,classical"})
        new = _ndjson(txt)
        for g in new:
            rows[g["id"]] = g
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("\n".join(json.dumps(g) for g in rows.values()), encoding="utf-8")
        if rows:
            note(f"{username}: {len(new)} neue Partien, gesamt {len(rows)}")
    keep = sorted((g for g in rows.values() if g["createdAt"] >= window_start), key=lambda g: -g["createdAt"])[:cap]
    return [x for x in (_lichess_rec(g) for g in keep) if x]


def lichess_games_by_ids(ids: list[str]) -> dict[str, dict]:
    """Partien mit Serveranalyse, Uhr und Eroeffnung per ID nachladen (offizieller Sammelexport, <= 300 je Anfrage)."""
    out = {}
    cdir = config.CACHE_DIR / "lichess_games" / "analysed"
    cdir.mkdir(parents=True, exist_ok=True)
    todo = []
    for i in ids:
        f = cdir / f"{i}.json"
        if f.exists():
            out[i] = json.loads(f.read_text(encoding="utf-8"))
        else:
            todo.append(i)
    for k in range(0, len(todo), 300):
        txt = _lichess_request("POST", f"{LI}/api/games/export/_ids", data=",".join(todo[k:k + 300]),
                               params={"moves": "true", **ANALYSIS_PARAMS})
        for g in _ndjson(txt):
            out[g["id"]] = g
            if g.get("analysis") or g.get("status") not in ("started", "created"):
                (cdir / f"{g['id']}.json").write_text(json.dumps(g), encoding="utf-8")
    return out


def lichess_analysed_ids(username: str, since_days: int) -> set[str]:
    """IDs der Partien mit Lichess-Serveranalyse (Export mit analysed=true, ohne Zuege). 24 h Cache."""
    cache = config.CACHE_DIR / "lichess_games" / f"{username.lower()}_analysed_{since_days}.txt"
    if cache.exists() and time.time() - cache.stat().st_mtime < 24 * 3600:
        return set(cache.read_text(encoding="utf-8").split())
    since = int((time.time() - since_days * 86400) * 1000)
    rows = _ndjson(_lichess_request("GET", f"{LI}/api/games/user/{username}",
                                    params={"since": since, "analysed": "true", "moves": "false", "tags": "false",
                                            "perfType": "blitz,rapid,classical"}))
    ids = {"li_" + g["id"] for g in rows}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("\n".join(sorted(ids)), encoding="utf-8")
    return ids


def check_token() -> tuple[bool, str]:
    """Prueft alle LICHESS_TOKEN*; meldet je Variable gueltig/ungueltig und den Account, nie den Wert."""
    toks = _tokens()
    if not toks:
        return False, "kein LICHESS_TOKEN (optional; Team-Mitgliederliste und höheres Ratenlimit)"
    parts, ok_any = [], False
    for name, tok in toks:
        try:
            r = session().get(f"{LI}/api/account", headers={"Authorization": f"Bearer {tok}"}, timeout=20)
        except Exception as ex:  # noqa: BLE001
            parts.append(f"{name}: Prüfung fehlgeschlagen ({type(ex).__name__})")
            continue
        if r.status_code != 200:
            parts.append(f"{name}: ungültig (HTTP {r.status_code})")
            continue
        ok_any = True
        parts.append(f"{name}: gültig (Account {r.json().get('username')})")
    return ok_any, "; ".join(parts)


# Bedenkzeit-Rang fuer die Stichprobe: lange Partien zuerst (Bullet ist schon beim Laden ausgeschlossen)
SPEED_RANK = {"correspondence": 0, "daily": 0, "classical": 0, "rapid": 1, "blitz": 2}


def sample_stratified(games: list[dict], n: int, bins: int = 12, analysed: set[str] | frozenset = frozenset()) -> list[dict]:
    """Deterministische Stichprobe: Zeitraum in `bins` gleich lange Abschnitte, je Abschnitt gleiche Quote
    (Rest wandert in Abschnitte mit genug Partien). Innerhalb eines Abschnitts lange Bedenkzeit zuerst,
    bei gleicher Bedenkzeit bereits analysierte Partien; jede Gruppe wieder gleichmaessig ueber die Zeit."""
    if len(games) <= n:
        return sorted(games, key=lambda g: (g["date"], g["id"]), reverse=True)
    gs = sorted(games, key=lambda g: (g["date"], g["id"]))
    day = [dt.date.fromisoformat(g["date"]).toordinal() for g in gs]
    lo, width = day[0], (day[-1] - day[0] + 1) / bins
    buckets = [[] for _ in range(bins)]
    for g, d in zip(gs, day):
        buckets[min(bins - 1, int((d - lo) / width))].append(g)
    quota, left = [0] * bins, n
    while left:
        for i in reversed(range(bins)):
            if left and quota[i] < len(buckets[i]):
                quota[i] += 1
                left -= 1
    out = []
    for b, q in zip(buckets, quota):
        groups: dict[tuple, list] = {}
        for g in b:
            groups.setdefault((SPEED_RANK.get(g["speed"], 3), g["id"] not in analysed), []).append(g)
        for key in sorted(groups):
            if q <= 0:
                break
            take = sample_evenly(groups[key], min(q, len(groups[key])))
            out += take
            q -= len(take)
    return sorted(out, key=lambda g: (g["date"], g["id"]), reverse=True)


def sample_evenly(games: list[dict], n: int) -> list[dict]:
    """Deterministische Stichprobe: n Partien gleichmaessig ueber die Zeit (neueste zuerst sortiert)."""
    gs = sorted(games, key=lambda g: (g["date"], g["id"]), reverse=True)
    if len(gs) <= n:
        return gs
    if n == 1:
        return [gs[len(gs) // 2]]
    return [gs[round(i * (len(gs) - 1) / (n - 1))] for i in range(n)]


# ---------------------------------------------------------------- Chess.com
def chesscom_player(u: str) -> dict | None:
    d = _json(fetch(f"{CC}/player/{u.lower()}", ttl_hours=168))
    return d if d and d.get("username") else None


def chesscom_stats(u: str) -> dict:
    return _json(fetch(f"{CC}/player/{u.lower()}/stats", ttl_hours=168)) or {}


def chesscom_club_slugs(club: str, extra: list[str]) -> list[str]:
    toks = [t for t in re.split(r"[\s/\-.,()]+", strip_accents(club).lower()) if t and not t.isdigit()]
    if not toks:
        return extra
    long = [_ABBR.get(t, t) for t in toks]
    base = [t for t in toks if t not in _ABBR]
    cands = ["-".join(toks), "-".join(long), "-".join(base), "".join(toks), "-".join(base + ["schach"]),
             "schach-" + "-".join(base)]
    return list(dict.fromkeys(extra + cands))


def chesscom_club_members(slug: str) -> tuple[dict | None, list[str]]:
    info = _json(fetch(f"{CC}/club/{slug}", ttl_hours=168))
    if not info or "name" not in info:
        return None, []
    mem = _json(fetch(f"{CC}/club/{slug}/members", ttl_hours=168)) or {}
    names = [m["username"] for k in ("weekly", "monthly", "all_time") for m in mem.get(k, [])]
    return info, list(dict.fromkeys(names))


CC_PARALLEL = 4       # Monatsarchive je Chess.com-Spieler gleichzeitig (host_gate begrenzt global)


def chesscom_games(u: str, months: int = 24, cap: int = 400) -> list[dict]:
    arch = (_json(fetch(f"{CC}/player/{u.lower()}/games/archives", ttl_hours=24)) or {}).get("archives", [])
    out = []
    months_urls = list(reversed(arch[-months:]))
    this_month = dt.date.today().strftime("%Y/%m")

    def month(url):
        return (_json(fetch(url, ttl_hours=24 if url.endswith(this_month) else 24 * 365)) or {}).get("games", [])

    # Monate in kleinen Paketen parallel laden (neueste zuerst), bis cap erreicht ist; Reihenfolge bleibt erhalten
    from concurrent.futures import ThreadPoolExecutor
    batches = [months_urls[k:k + CC_PARALLEL] for k in range(0, len(months_urls), CC_PARALLEL)]
    with ThreadPoolExecutor(max_workers=CC_PARALLEL) as ex:
        month_games = (g for b in batches for gs in ex.map(month, b) for g in gs)
        for g in month_games:
            if g.get("rules") != "chess" or g.get("time_class") not in ("blitz", "rapid", "daily") or not g.get("pgn"):
                continue
            pg = chess.pgn.read_game(io.StringIO(g["pgn"]))
            if pg is None:
                continue
            b = pg.board()
            sans, ucis = [], []
            for mv in pg.mainline_moves():
                sans.append(b.san(mv)); ucis.append(mv.uci()); b.push(mv)
            if len(sans) < 4:
                continue
            res = pg.headers.get("Result", "*")
            out.append({"id": "cc_" + hashlib.sha1(g["url"].encode()).hexdigest()[:10], "platform": "chesscom",
                        "white": g["white"]["username"], "black": g["black"]["username"], "sans": sans, "ucis": ucis,
                        "result": res, "date": dt.datetime.fromtimestamp(g.get("end_time", 0), dt.UTC).date().isoformat(),
                        "speed": g.get("time_class", ""), "url": g["url"], "event": "Chess.com",
                        "white_rating": g["white"].get("rating"), "black_rating": g["black"].get("rating")})
            if len(out) >= cap:
                return out
    return out


def note(msg: str) -> None:
    log("  online: " + msg)
