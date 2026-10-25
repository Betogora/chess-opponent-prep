"""Account-Erkennung + Online-Repertoire.

Ablauf (deterministisch, Research-Eingaben nur ueber output/players/<slug>/research/accounts.json):
  1. Kandidaten: Lichess-Vereinsteam (Turnierteilnehmer), Chess.com-Vereinsclub (Mitglieder),
     Namensvarianten auf beiden Plattformen, extra_candidates aus accounts.json.
  2. Partien je Kandidat: Lichess-Vereinsturniere (+ Komplettexport mit LICHESS_TOKEN fuer die Top-Kandidaten),
     Chess.com-Archive (24 Monate).
  3. Fingerabdruck (fingerprint.py) + Profilmerkmale -> Konfidenz per Log-Odds-Formel (WEIGHTS).
  4. accounts.json: "accounts": {"lichess:Name": {"status": "bestaetigt"|"abgelehnt", "note": "..."}} uebersteuert.
     "username_patterns": {"lichess": ["?b?u???"]} = verdeckter Account-Hinweis (z. B. aus SnoopChess abgeschrieben,
     ? = ein Zeichen, * = beliebig viele): liefert Kandidaten ueber Lichess-Autocomplete und ist ein schwaches Merkmal.
  5. Accounts mit Konfidenz >= ACCEPT werden uebernommen: Online-Baum, Abgleich mit Turnier-Baum, Belege O1...
"""
from __future__ import annotations

import datetime as dt
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait
from collections import Counter

import chess
import chess.engine

from .. import config, paths as P
from ..openings import build_tree, main_lines
from ..util import name_matches, read_json, strip_accents, write_json
from .. import metrics
from ..dossier import ann_positions
from . import chessable, fingerprint as FP, lichess_analysis as LA, platforms as P, rating_map as RM

ACCEPT = 0.50
MARGIN = 1.0                # Log-Odds-Abstand zum Zweiten, wenn mehrere ueber ACCEPT liegen (Faktor e)
PRIOR = -3.2
WEIGHTS = {
    "club": 1.0,            # im Vereinsteam/-club gefunden
    "name_real": 3.0,       # Realname im Profil = Spieler
    "name_user": 1.5,       # Nachname (>= 4 Zeichen) im Benutzernamen
    "first_user": 0.5,      # nur Vorname (>= 3 Zeichen) als eigener Namensteil im Benutzernamen; schwach, haeufige Vornamen
    "fide": 2.0,            # FIDE-Feld im Profil = Elo (+-10; Feld ist selbst eingetragen)
    "name_conflict": -2.5,  # Realname im Profil vorhanden, aber ein anderer Name
    "location": 0.3,        # Ort im Profil enthaelt Vereinsort
    "fp": 1.0,              # je Standardabweichung Fingerabdruck-Lift ueber dem Kandidatenmittel (gekappt -1..3)
    "created": 0.4,         # Account-Alter passt zur Turnierkarriere (+-24 Monate um den ersten FIDE-Eintrag)
    "rating_ok": 0.3,       # Online-Wertung plausibel (|z| <= 1, rating_map: nichtlinear, Elo oder DWZ als Referenz)
    "rating_bad": -0.7,     # unplausibel (|z| > 2; nach oben 1,3-fach toleranter)
    "crosslink": 1.0,       # anderer Plattform-Account verweist darauf
    "same_name_elsewhere": 0.2,
    "pattern": 0.7,         # passt zum verdeckten Account-Hinweis (accounts.json username_patterns); allein nie ausreichend
    "pattern_miss": -1.0,   # Hinweis fuer die Plattform vorhanden, Benutzername passt nicht (Hinweis selbst ist eine Vermutung)
}
MIN_EVENTS = 8
MAX_MEMBER_FETCH = 30        # weitere Teammitglieder (nur mit lesbarer Mitgliederliste)
MEMBER_GAMES = 60
MAX_CLUB_MEMBERS = 300       # Chess.com-Club: Profil + Statistik je Mitglied (2 Abrufe)
MAX_SHORTLIST = 60           # Kandidaten mit Fingerabdruck / Chess.com-Partien (grosse Vereinsteams: Tausende)
MAX_PATTERN_QUERIES = 24     # Lichess-Autocomplete-Abrufe je Lauf fuer username_patterns
MAX_PATTERN_CANDIDATES = 15  # davon hoechstens so viele Kandidaten (je bis zu MEMBER_GAMES Partien fuer den Fingerabdruck)


def _sig(x):
    return 1 / (1 + math.exp(-x))


def select_accounts(ranked: list[dict]) -> tuple[list[dict], list[dict]]:
    """Hoechstens ein Account je Plattform. Liegen mehrere ueber ACCEPT, wird der beste nur uebernommen, wenn er
    mindestens MARGIN Log-Odds vor dem zweiten liegt; sonst keiner (mehrdeutig, typisch fuer grosse Vereine mit
    gaengigem Repertoire). Ein in accounts.json bestaetigter Account gilt immer."""
    accepted, ambiguous = [], []
    for plat in sorted({c["platform"] for c in ranked}):
        over = [c for c in ranked if c["platform"] == plat and c["confidence"] >= ACCEPT]
        confirmed = [c for c in over if str((c.get("override") or {}).get("status", "")).lower().startswith("best")]
        if confirmed:
            accepted.append(confirmed[0])
        elif len(over) == 1 or (len(over) > 1 and _lo(over[0]) - _lo(over[1]) >= MARGIN):
            accepted.append(over[0])
        elif over:
            ambiguous += over
            for c in over:
                c["reasons"] = c.get("reasons", []) + [f"mehrdeutig: {len(over)} Kandidaten auf {plat} über "
                                                       f"{round(ACCEPT * 100)} % ohne klaren Abstand – nicht übernommen"]
    return accepted, ambiguous


def _lo(c) -> float:
    p = min(max(c["confidence"], 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def first_in_username(first: str, username: str) -> bool:
    """Vorname als eigener Teil des Benutzernamens: 'erster-Theo', 'TheoK', 'theo_2011' ja; 'Theodora', 'atheon' nein.
    Teile entstehen an Nicht-Buchstaben und an Klein-gross-Wechseln."""
    fn = strip_accents((first or "").split()[0] if first else "").lower()
    if len(fn) < 3:
        return False
    parts = re.split(r"[^A-Za-z]+|(?<=[a-z])(?=[A-Z])", strip_accents(username))
    return any(p.lower() == fn for p in parts if p)


def _pattern_re(pattern: str) -> re.Pattern:
    """'?b?u???' -> ein Zeichen je '?', '*' beliebig viele; Gross-/Kleinschreibung egal."""
    return re.compile("".join("." if ch == "?" else ".*" if ch == "*" else re.escape(ch) for ch in pattern), re.I)


def pattern_matches(pattern: str, username: str) -> bool:
    return bool(_pattern_re(pattern.strip()).fullmatch(username or ""))


def pattern_prefixes(pattern: str, words: list[str]) -> list[str]:
    """Namenspraefixe (>= 3 Zeichen), die zum Muster passen, als Suchbegriffe fuer das Lichess-Autocomplete.
    Das Autocomplete liefert nur 12 Treffer (kuerzeste zuerst), daher je Wort mehrere Laengen: bis zum letzten
    festen Zeichen des Musters sowie Musterlaenge -2, -1 und volle Laenge (bei fester Laenge ohne '*')."""
    pat = pattern.strip().split("*")[0]
    fixed = [i for i, ch in enumerate(pat) if ch != "?"]
    lengths = {max(3, fixed[-1] + 1 if fixed else 3)}
    if "*" not in pattern:
        lengths |= {len(pat) - 2, len(pat) - 1, len(pat)}
    out = []
    for w in words:
        w = re.sub(r"[^a-z0-9_-]", "", strip_accents(w or "").lower())
        for n in sorted(lengths):
            if 3 <= n <= min(len(w), len(pat)) and all(pc in ("?", wc) for pc, wc in zip(pat[:n].lower(), w[:n])):
                out.append(w[:n])
    return list(dict.fromkeys(out))


def _otb_for_fp(games):
    return [{"sans": g["sans"], "is_white": g["is_white"]} for g in games]


def _club_city(club: str) -> list[str]:
    return [t for t in re.split(r"[\s/\-.,()]+", strip_accents(club).lower())
            if len(t) > 3 and t not in {"schachklub", "schachverein", "schachfreunde", "schachclub", "verein"}]


def _parallel(fn, items: list, deadline: float, workers: int = 6) -> set:
    """fn(item) parallel bis zur Frist; gibt die fertigen items zurueck (offene werden verworfen)."""
    done = set()
    if not items:
        return done
    ex = ThreadPoolExecutor(max_workers=workers)
    futs = {ex.submit(fn, it): it for it in items}
    finished, _ = wait(futs, timeout=max(0.0, deadline - time.time()))
    for f in finished:
        if not f.exception():
            done.add(futs[f])
    ex.shutdown(wait=False, cancel_futures=True)
    return done


def discover(ident, otb_games: list[dict], pdir) -> dict:
    research = read_json(P.file(pdir, P.ACCOUNTS), {}) or {}
    deadline = time.time() + config.ONLINE_BUDGET_S       # nur fuer die breiten Schritte (Verein), siehe config
    skipped = []
    club = (ident.dsb or {}).get("club", "")
    city = _club_city(club)
    cand: dict[str, dict] = {}          # key "lichess:Name" / "chesscom:name"
    games_by: dict[str, list] = {}

    def add(platform, name, via):
        k = f"{platform}:{name}"
        c = cand.setdefault(k, {"platform": platform, "username": name, "via": [], "features": {}})
        if via not in c["via"]:
            c["via"].append(via)
        return c

    # ---- Lichess: Vereinsteams
    li_pool = []
    teams = P.lichess_find_teams(club, research.get("lichess_teams", [])) if club else []
    for t in teams:
        tg = P.lichess_team_games(t["id"])
        # Team-Battles bringen Spieler fremder Teams mit: nur Spieler ohne Teamangabe (Vereinsturnier) oder mit
        # diesem Team zaehlen; Partien ohne solchen Spieler fallen weg (Speicher bei grossen Teams).
        own = lambda g, side: g[side] and g.get(f"{side}_team") in (None, "", t["id"])
        tg = [g for g in tg if own(g, "white") or own(g, "black")]
        P.note(f"Lichess-Team {t['id']}: {len(tg)} Turnierpartien mit Teamspielern")
        li_pool += tg
        for g in tg:
            for side in ("white", "black"):
                if own(g, side):
                    add("lichess", g[side], f"Lichess-Team {t['name']}")["features"]["club"] = 1
    for g in li_pool:
        for side in ("white", "black"):
            if f"lichess:{g[side]}" in cand:
                games_by.setdefault(f"lichess:{g[side]}", []).append(g)
    # Mitglieder, die nie an Vereinsturnieren teilnehmen (Liste meist privat -> LICHESS_TOKEN mit team:read)
    for t in teams:
        new = [m for m in P.lichess_team_members(t["id"]) if f"lichess:{m}" not in cand][:MAX_MEMBER_FETCH]
        if new:
            P.note(f"Lichess-Team {t['id']}: {len(new)} weitere Mitglieder, lade je bis zu {MEMBER_GAMES} Partien")
        for k, m in enumerate(new):
            if time.time() > deadline:
                skipped.append(f"{len(new) - k} Lichess-Teammitglieder ohne Partien")
                break
            add("lichess", m, f"Lichess-Team {t['name']} (Mitglied)")["features"]["club"] = 1
            games_by[f"lichess:{m}"] = P.lichess_user_games(m, config.ONLINE_WINDOW_DAYS, MEMBER_GAMES)

    # ---- Chess.com: Vereinsclub
    cc_club = None
    if club:
        for slug in P.chesscom_club_slugs(club, research.get("chesscom_clubs", [])):
            info, members = P.chesscom_club_members(slug)
            if info:
                cc_club = {"slug": slug, "name": info.get("name"), "members": len(members)}
                P.note(f"Chess.com-Club {slug}: {len(members)} Mitglieder"
                       + (f", die {MAX_CLUB_MEMBERS} zuletzt aktiven werden geprüft" if len(members) > MAX_CLUB_MEMBERS else ""))
                for m in members[:MAX_CLUB_MEMBERS]:   # Reihenfolge: diese Woche, diesen Monat, jemals aktiv
                    add("chesscom", m, f"Chess.com-Club {info.get('name')}")["features"]["club"] = 1
                break

    # ---- Namensvarianten auf beiden Plattformen
    variants = P.name_variants(ident.first, ident.last, ident.birth_year)
    li_auto = {n.lower(): n for n in P.lichess_autocomplete(strip_accents(ident.last).lower())}
    for v in variants:
        if v in li_auto:
            add("lichess", li_auto[v], "Namensvariante")
        p = P.chesscom_player(v)
        if p:
            add("chesscom", p["username"], "Namensvariante")
    for plat, names in (research.get("extra_candidates") or {}).items():
        for n in names:
            add(plat, n, "accounts.json")

    # ---- Verdeckte Account-Hinweise (accounts.json "username_patterns", z. B. aus SnoopChess): Kandidaten ueber das
    # Lichess-Autocomplete mit Namenspraefixen, die zum Muster passen. Chess.com hat keine Namenssuche: dort wirkt das
    # Muster nur als Merkmal (ein Muster ohne ? und * ist ein vollstaendiger Name und wird direkt Kandidat).
    patterns = {plat: [str(x).strip() for x in (v if isinstance(v, list) else [v]) if x and str(x).strip()]
                for plat, v in (research.get("username_patterns") or {}).items()}
    for plat, pats in patterns.items():
        for pat in pats:
            if not re.search(r"[?*]", pat):
                add(plat, pat, f"Muster {pat}")
    li_pats = patterns.get("lichess", [])
    if li_pats:
        words = [ident.first.split()[0] if ident.first else "", ident.last] + variants
        queries = list(dict.fromkeys(q for pat in li_pats for q in pattern_prefixes(pat, words)))[:MAX_PATTERN_QUERIES]
        found = {}
        for q in queries:
            for n in P.lichess_autocomplete(q):
                hit = next((pat for pat in li_pats if pattern_matches(pat, n)), None)
                if hit:
                    found.setdefault(n.lower(), (n, hit))
        P.note(f"Muster {', '.join(li_pats)}: {len(queries)} Autocomplete-Suchen ({', '.join(queries) or '–'}), "
               f"{len(found)} passende Lichess-Namen" + (f", die ersten {MAX_PATTERN_CANDIDATES} werden geprüft"
                                                       if len(found) > MAX_PATTERN_CANDIDATES else ""))
        for n, pat in list(found.values())[:MAX_PATTERN_CANDIDATES]:
            add("lichess", n, f"Muster {pat}")

    # ---- Profile (Chess.com parallel vorab in den Cache; reine Vereinsmitglieder nur bis zur Frist)
    cc_core = [c["username"] for c in cand.values() if c["platform"] == "chesscom"
               and not all(v.startswith("Chess.com-Club") for v in c["via"])]
    cc_club = [c["username"] for c in cand.values() if c["platform"] == "chesscom" and c["username"] not in cc_core]
    fetch_cc = lambda u: (P.chesscom_player(u), P.chesscom_stats(u))
    _parallel(fetch_cc, cc_core, time.time() + 600)
    cc_ok = set(cc_core) | _parallel(fetch_cc, cc_club, deadline)
    if len(cc_ok) < len(cc_core) + len(cc_club):
        skipped.append(f"{len(cc_core) + len(cc_club) - len(cc_ok)} Chess.com-Clubmitglieder ohne Profil")
    li_names = [c["username"] for c in cand.values() if c["platform"] == "lichess"]
    li_prof = P.lichess_users(li_names)
    elo = (ident.elo or {}).get("standard")
    ref = RM.reference(ident)       # Elo, sonst DWZ auf Elo-Niveau
    first_rating = None
    hist = []
    try:
        from ..ratings import fide_history
        hist = fide_history(ident.fide_id) if ident.fide_id else []
        first_rating = dt.date.fromisoformat(hist[0]["date"]) if hist else None
    except Exception:
        pass
    for c in cand.values():
        f = c["features"]
        if c["platform"] == "lichess":
            u = li_prof.get(c["username"].lower(), {})
            pr = u.get("profile") or {}
            real = pr.get("realName") or " ".join(x for x in (pr.get("firstName"), pr.get("lastName")) if x)
            c["profile"] = {"real_name": real, "location": pr.get("location"), "fide": pr.get("fideRating"),
                            "bio": (pr.get("bio") or "")[:140], "links": pr.get("links") or "",
                            "created": _d(u.get("createdAt")), "seen": _d(u.get("seenAt")),
                            "ratings": {k: v.get("rating") for k, v in (u.get("perfs") or {}).items()
                                        if isinstance(v, dict) and k in ("blitz", "rapid", "classical")
                                        and v.get("games", 0) >= RM.MIN_GAMES and not v.get("prov")},
                            "url": f"https://lichess.org/@/{c['username']}"}
        else:
            ok = c["username"] in cc_ok
            u = (P.chesscom_player(c["username"]) or {}) if ok else {}
            st = P.chesscom_stats(c["username"]) if ok else {}
            c["profile"] = {"real_name": u.get("name") or "", "location": u.get("location"), "fide": st.get("fide"),
                            "bio": "", "links": "", "created": _d(u.get("joined", 0) * 1000 if u.get("joined") else None),
                            "seen": _d(u.get("last_online", 0) * 1000 if u.get("last_online") else None),
                            "ratings": {k.replace("chess_", ""): (v.get("last") or {}).get("rating") for k, v in st.items()
                                        if k in ("chess_blitz", "chess_rapid", "chess_daily") and isinstance(v, dict)
                                        and sum((v.get("record") or {}).get(x, 0) for x in ("win", "loss", "draw"))
                                        >= RM.MIN_GAMES},
                            "url": u.get("url") or f"https://www.chess.com/member/{c['username']}"}
        prof = c["profile"]
        if prof["real_name"] and name_matches(prof["real_name"], ident.last, ident.first) == "strong":
            f["name_real"] = 1
        if len(ident.last) >= 4 and strip_accents(ident.last).lower() in c["username"].lower():
            f["name_user"] = 1
        elif first_in_username(ident.first, c["username"]):
            f["first_user"] = 1
        if prof["real_name"] and not f.get("name_real") and len(prof["real_name"].split()) >= 2                 and name_matches(prof["real_name"], ident.last, "") != "strong":
            f["name_conflict"] = 1
        pats = patterns.get(c["platform"])
        if pats:
            hit = next((pat for pat in pats if pattern_matches(pat, c["username"])), None)
            f["pattern" if hit else "pattern_miss"] = 1
            c["pattern"] = hit or ", ".join(pats)
        if elo and str(prof.get("fide") or "").isdigit() and abs(int(prof["fide"]) - elo) <= 10:
            f["fide"] = 1
        if prof.get("location") and any(t in strip_accents(str(prof["location"])).lower() for t in city):
            f["location"] = 1
        if first_rating and prof.get("created"):
            if abs((dt.date.fromisoformat(prof["created"]) - first_rating).days) <= 730:
                f["created"] = 1
        rc = RM.check(c["platform"], prof["ratings"], ref)
        c["rating_check"] = rc
        if rc and rc["verdict"] == "plausibel":
            f["rating_ok"] = 1
        elif rc and rc["verdict"] == "unplausibel":
            f["rating_bad"] = 1

    # ---- Vorauswahl: teure Schritte (Chess.com-Partien, Fingerabdruck) nur fuer die besten MAX_SHORTLIST nach
    # Profilmerkmalen; Namensvarianten und accounts.json immer. Gleichstand: mehr Fund-Partien, dann Name.
    always = {k for k, c in cand.items()
              if {"Namensvariante", "accounts.json"} & set(c["via"]) or c["features"].get("pattern")}
    ranked_pre = sorted(cand, key=lambda k: (-_logit(cand[k]["features"]), -len(games_by.get(k, [])), k.lower()))
    shortlist = set(ranked_pre[:MAX_SHORTLIST]) | always
    if len(cand) > len(shortlist):
        P.note(f"{len(cand)} Kandidaten, Fingerabdruck für die {len(shortlist)} besten nach Profilmerkmalen")

    # ---- Partien fuer Chess.com-Kandidaten und Muster-Kandidaten ohne Vereinsturniere (Fingerabdruck)
    # Reihenfolge: Namens-/Muster-/accounts.json-Kandidaten zuerst (immer), danach nach Profilmerkmalen bis zur Frist
    cc_keys = [k for k in ranked_pre if cand[k]["platform"] == "chesscom" and k in shortlist]
    cc_keys = [k for k in cc_keys if k in always] + [k for k in cc_keys if k not in always]
    for n, k in enumerate(cc_keys):
        if k not in always and time.time() > deadline:
            skipped.append(f"{len(cc_keys) - n} Chess.com-Kandidaten ohne Partien")
            break
        games_by[k] = P.chesscom_games(cand[k]["username"], months=24, cap=300)
    for k, c in cand.items():
        if c["platform"] == "lichess" and k not in games_by and any(v.startswith("Muster ") for v in c["via"]):
            games_by[k] = P.lichess_user_games(c["username"], config.ONLINE_WINDOW_DAYS, MEMBER_GAMES)
    if skipped:
        P.note(f"Zeitbudget {config.ONLINE_BUDGET_S} s erreicht, übersprungen: " + "; ".join(skipped))

    # ---- Fingerabdruck
    otb = _otb_for_fp(otb_games)
    tables = {k: FP.node_table(games_by.get(k, []), cand[k]["username"]) for k in shortlist}
    scores = FP.score_candidates(otb, tables)
    lifts = [s["lift"] for k, s in scores.items() if s["covered"] >= MIN_EVENTS]
    mu = sum(lifts) / len(lifts) if lifts else 0
    sd = (sum((x - mu) ** 2 for x in lifts) / len(lifts)) ** 0.5 if len(lifts) > 1 else 0
    for k, c in cand.items():
        s = scores.get(k, {"events": 0, "covered": 0, "lift": 0.0, "agreement": 0.0, "distinctive": []})
        c["fingerprint"] = s
        if s["covered"] >= MIN_EVENTS and sd > 0:
            c["features"]["fp"] = round(max(-1.0, min(3.0, (s["lift"] - mu) / sd)), 2)

    # ---- Querverweise und gleicher Name auf anderen Plattformen (nur fuer die besten 5)
    pre = sorted(cand.values(), key=lambda c: -_logit(c["features"]))[:5]
    cross = {}
    for c in pre:
        other = "chesscom" if c["platform"] == "lichess" else "lichess"
        links = (c["profile"].get("links") or "") + " " + (c["profile"].get("bio") or "")
        for m in re.finditer(r"chess\.com/member/([A-Za-z0-9_-]+)|lichess\.org/@/([A-Za-z0-9_-]+)", links):
            target = m.group(1) or m.group(2)
            cross[f"{'chesscom' if m.group(1) else 'lichess'}:{target}"] = c["username"]
        same = P.chesscom_player(c["username"]) if other == "chesscom" else None
        cb = chessable.check_user(c["username"])
        c["elsewhere"] = {"chesscom": bool(same), "chessable": cb["status"]}
        if same or cb["status"] in ("privat", "öffentlich"):
            c["features"]["same_name_elsewhere"] = 1
        c["chessable"] = cb
    for k, src in cross.items():
        if k in cand:
            cand[k]["features"]["crosslink"] = 1

    # ---- Konfidenz + accounts.json
    overrides = research.get("accounts", {})
    for k, c in cand.items():
        lo = _logit(c["features"])
        c["confidence"] = round(_sig(lo), 3)
        c["reasons"] = _reasons(c)
        ov = overrides.get(k) or overrides.get(k.lower())
        if ov:
            c["override"] = ov
            st = str(ov.get("status", "")).lower()
            c["confidence"] = 0.99 if st.startswith("best") else 0.0 if st.startswith("abg") else c["confidence"]
    ranked = sorted(cand.values(), key=lambda c: (-c["confidence"], c["platform"], c["username"].lower()))
    accepted, ambiguous = select_accounts(ranked)

    # ---- Partien der uebernommenen Accounts
    # Die Fund-Partien (Vereinsturniere) dienen nur der Zuordnung. Fuer das Repertoire zaehlt eine aktuelle
    # Stichprobe: die neuesten bis zu ONLINE_POOL_MAX Partien der letzten ONLINE_WINDOW_DAYS, davon
    # ONLINE_SAMPLE gleichmaessig ueber die Zeit verteilt.
    # pool  = ALLE Partien der letzten ONLINE_WINDOW_DAYS (nur Zuege) -> vollstaendige Zaehlung je Stellung, Trends
    # games = Stichprobe von ONLINE_SAMPLE Partien gleichmaessig ueber den ganzen Zeitraum, mit Lichess-Analyse
    online_games, online_pool, sampling = [], [], []
    for c in accepted:
        k = f"{c['platform']}:{c['username']}"
        if c["platform"] == "lichess":
            pool = P.lichess_all_games(c["username"], config.ONLINE_WINDOW_DAYS, config.ONLINE_POOL_MAX)
        else:
            pool = P.chesscom_games(c["username"], months=config.ONLINE_WINDOW_DAYS // 30, cap=config.ONLINE_POOL_MAX)
        fallback = len(pool) < config.ONLINE_MIN_RECENT
        if fallback:
            P.note(f"{c['username']}: nur {len(pool)} aktuelle Partien – nutze die Fund-Partien (älter)")
            pool = list(games_by.get(k, []))
        pool = [_own_view(g, c["username"]) for g in pool if g["speed"] not in ("bullet", "ultraBullet")]
        done = P.lichess_analysed_ids(c["username"], config.ONLINE_WINDOW_DAYS) if c["platform"] == "lichess" else set()
        gs = P.sample_stratified(pool, config.ONLINE_SAMPLE, analysed=done)
        if c["platform"] == "lichess" and not fallback:
            full = P.lichess_games_by_ids([g["id"][3:] for g in gs])
            gs = [_own_view(P._lichess_rec(full[g["id"][3:]]) or g, c["username"]) if g["id"][3:] in full else g for g in gs]
        dates = sorted(g["date"] for g in pool)
        sampling.append({"platform": c["platform"], "username": c["username"], "pool": len(pool), "sample": len(gs),
                         "analysed": sum(1 for g in gs if g.get("analysis")),
                         "window_days": config.ONLINE_WINDOW_DAYS, "fallback": fallback,
                         "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
                         "speeds": dict(Counter(g["speed"] for g in pool)),
                         "sample_speeds": dict(Counter(g["speed"] for g in gs))})
        P.note(f"{c['username']}: {len(pool)} Partien ({dates[0] if dates else '?'} bis {dates[-1] if dates else '?'}), "
               f"Stichprobe {len(gs)} über den ganzen Zeitraum, davon {sampling[-1]['analysed']} mit Lichess-Analyse")
        online_games += gs
        online_pool += pool
    online_games.sort(key=lambda g: g["date"], reverse=True)

    # ---- Chessable
    cb_user = None
    for v in [ident.last, ident.first + ident.last] + P.name_variants(ident.first, ident.last, ident.birth_year)[:6]:
        r = chessable.check_user(v)
        if r["status"] != "nicht vorhanden":
            cb_user = r
            break
    out = {
        "generated": dt.datetime.now().isoformat(timespec="minutes"),
        "club": club, "lichess_teams": teams, "chesscom_club": cc_club,
        "token": bool(P._token()), "accept_threshold": ACCEPT, "weights": WEIGHTS, "prior": PRIOR,
        "username_patterns": patterns,
        "candidates": [_slim(c) for c in ranked[:25]], "n_candidates": len(ranked),
        "accepted": [_slim(c) for c in accepted], "ambiguous": [_slim(c) for c in ambiguous], "sampling": sampling,
        "chessable_name_check": cb_user,
    }
    write_json(pdir / "online_accounts.json", out)
    return {"summary": out, "games": online_games, "pool": online_pool}


def _own_view(g: dict, username: str) -> dict:
    g = dict(g)
    g["is_white"] = g["white"].lower() == username.lower()
    sc = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(g["result"])
    g["player_score"] = None if sc is None else (sc if g["is_white"] else 1 - sc)
    g["opponent"] = g["black"] if g["is_white"] else g["white"]
    g["opponent_elo"] = g["black_rating"] if g["is_white"] else g["white_rating"]
    g["account"] = username
    return g


def _d(ms):
    if not ms:
        return None
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).date().isoformat()


def _logit(f: dict) -> float:
    lo = PRIOR
    for k, v in f.items():
        lo += WEIGHTS.get(k, 0) * (v if k == "fp" else 1)
    return lo


def _reasons(c) -> list[str]:
    f, fp, pr = c["features"], c.get("fingerprint", {}), c.get("profile", {})
    r = []
    if f.get("club"):
        r.append(f"im Vereinsumfeld ({', '.join(c['via'])})")
    if f.get("fp") is not None:
        r.append(f"Eröffnungs-Fingerabdruck {f['fp']:+.1f} SD über dem Kandidatenmittel "
                 f"({fp.get('covered')} von {fp.get('events')} Entscheidungsstellen vergleichbar)")
    if fp.get("distinctive"):
        r.append("Übereinstimmungen: " + "; ".join(fp["distinctive"][:4]))
    if f.get("name_real"):
        r.append(f"Realname im Profil: {pr.get('real_name')}")
    if f.get("name_user"):
        r.append("Nachname im Benutzernamen")
    if f.get("first_user"):
        r.append("Vorname als Namensteil im Benutzernamen (schwach)")
    if f.get("fide"):
        r.append(f"FIDE-Feld im Profil {pr.get('fide')}")
    if f.get("created"):
        r.append(f"angelegt {pr.get('created')} – passt zum Beginn der Turnierkarriere")
    rc = c.get("rating_check")
    if rc:
        ref = f"Elo {rc['ref_value']}" if rc["ref_kind"] == "Elo" else f"DWZ {rc['ref_value']} ≈ Elo {rc['ref_elo']}"
        r.append(f"Online-Wertung {rc['verdict']}: "
                 f"{', '.join(f'{k} {v}' for k, v in pr.get('ratings', {}).items() if k in rc['per_speed'])} "
                 f"→ erwartet Elo ≈ {rc['expected_elo']}, Turnier {ref}, z {rc['z']:+.1f}")
    if f.get("pattern"):
        r.append(f"passt zum verdeckten Account-Hinweis {c.get('pattern')} (accounts.json; selbst nur eine Vermutung)")
    if f.get("pattern_miss"):
        r.append(f"passt nicht zum verdeckten Account-Hinweis {c.get('pattern')}")
    if f.get("name_conflict"):
        r.append(f"Realname im Profil passt nicht ({pr.get('real_name')})")
    if f.get("crosslink"):
        r.append("Querverweis von anderem Plattform-Account")
    if f.get("same_name_elsewhere"):
        r.append(f"gleicher Name auf weiterer Plattform ({', '.join(k for k, v in c.get('elsewhere', {}).items() if v and v != 'nicht vorhanden')})")
    if not (f.get("name_real") or f.get("fide") or f.get("crosslink")):
        r.append("kein direkter Namens- oder FIDE-Beleg")
    return r


def _slim(c) -> dict:
    return {k: c.get(k) for k in ("platform", "username", "via", "features", "confidence", "reasons", "profile",
                                  "rating_check", "fingerprint", "elsewhere", "chessable", "override", "pattern")}


# ---------------------------------------------------------------- Online-Repertoire fuer Dossier/Report
def compare_trees(otb: dict, onl: dict, ply: int = 6, min_online: int = 2, max_online_only: int = 6) -> list[dict]:
    """Linien bis `ply` Halbzuege: in beiden / nur online / nur Turnier. "Nur online" zaehlt erst ab 1 % seiner
    Online-Partien mit der Farbe und hoechstens `max_online_only` je Farbe (sonst Hunderte Zeilen bei Tausenden Partien)."""
    rows = []
    for col in ("white", "black"):
        a = {p: nd for p, nd in otb[col]["nodes"].items() if nd["ply"] == ply}
        b = {p: nd for p, nd in onl[col]["nodes"].items() if nd["ply"] == ply}
        floor = max(min_online, round(0.01 * onl[col]["nodes"].get("", {}).get("n", 0)))
        only = 0
        # Gleichstand nach Zugfolge aufloesen: Mengen-Reihenfolge ist je Prozess zufaellig, die Beleg-IDs muessen stabil sein
        for p in sorted(set(a) | set(b), key=lambda p: (-((b.get(p) or {}).get("n", 0) * 2 + (a.get(p) or {}).get("n", 0)), p)):
            na, nb = (a.get(p) or {}).get("n", 0), (b.get(p) or {}).get("n", 0)
            if na == 0 and (nb < floor or only >= max_online_only):
                continue
            only += na == 0
            kind = "beide" if na and nb else "nur online" if nb else "nur Turnier"
            nd = b.get(p) or a.get(p)
            rows.append({"color": col, "path": p, "kind": kind, "otb": na, "online": nb,
                         "online_score": (b.get(p) or {}).get("score_pct"), "otb_score": (a.get(p) or {}).get("score_pct"),
                         "name": nd.get("name", ""), "eco": nd.get("eco", "")})
    return rows


def annotate_otb_tree_with_online(otb_trees: dict, onl_trees: dict) -> None:
    for col in ("white", "black"):
        on = onl_trees[col]["nodes"]
        for nd in otb_trees[col]["nodes"].values():
            o = on.get(nd["path"])
            nd["online_n"] = o["n"] if o else 0


def move_trends(pool: list[dict], trees: dict) -> list[dict]:
    """Wahl an den wichtigsten eigenen Entscheidungsstellen, getrennt nach Jahr und nach Bedenkzeit
    (Blitz gegen Schnellschach und laenger) - zeigt Repertoire-Wechsel und ob er im Blitz anders spielt."""
    out = []
    for col in ("white", "black"):
        nodes = trees[col]["nodes"]
        if col == "white":
            first = nodes[""]["children"][:1]
            spots = [""] + [k["path"] for c in first for k in nodes[c["path"]]["children"][:3]]
        else:
            spots = [c["path"] for c in nodes[""]["children"][:3]]
        for path in spots:
            nd = nodes.get(path)
            if not nd or nd["n"] < 20:
                continue
            ply = nd["ply"]
            pre = path.split() if path else []
            by_year, by_speed = {}, {}
            for g in pool:
                if g["is_white"] != (col == "white") or len(g["sans"]) <= ply or g["sans"][:ply] != pre:
                    continue
                mv = g["sans"][ply]
                by_year.setdefault(g["date"][:4], Counter())[mv] += 1
                by_speed.setdefault("Blitz" if g["speed"] == "blitz" else "Schnellschach+", Counter())[mv] += 1
            tot = Counter()
            for c in by_year.values():
                tot.update(c)
            ranked = sorted(tot.items(), key=lambda x: (-x[1], x[0]))
            if len(ranked) < 2 or ranked[1][1] < 0.03 * nd["n"]:
                continue        # keine echte Alternative -> steht schon im Baum-Beleg
            top = [m for m, _ in ranked[:3]]
            out.append({"color": col, "path": path, "ply": ply, "moves": top,
                        "by_year": {y: {m: c[m] for m in top} | {"_n": sum(c.values())} for y, c in sorted(by_year.items())},
                        "by_speed": {s: {m: c[m] for m in top} | {"_n": sum(c.values())} for s, c in sorted(by_speed.items())}})
    return out


def _mv(ply: int, san: str) -> str:
    return f"{ply // 2 + 1}.{san}" if ply % 2 == 0 else f"{ply // 2 + 1}…{san}"


def online_facts(acc: list[dict], games: list[dict], trees: dict, comparison: list[dict], sigs: list[dict],
                 sampling: list[dict] | None = None, quality: dict | None = None,
                 trends: list[dict] | None = None) -> list[dict]:
    """games = alle gezaehlten Partien (Pool); Stichprobe und Analyse stecken in sampling/quality."""
    from ..dossier import _numbered
    facts = []

    def add(text, scope="all", topic="online"):
        facts.append({"id": f"O{len(facts) + 1}", "text": text, "scope": scope, "topic": topic})
    names = ", ".join(f"{a['platform'].replace('chesscom', 'Chess.com').replace('lichess', 'Lichess')} „{a['username']}“ "
                      f"({round(a['confidence'] * 100)} %)" for a in acc)
    sp = Counter(g["speed"] for g in games)
    dates = sorted(g["date"] for g in games)
    samp = "; ".join(
        ("keine aktuellen Partien gefunden – ältere Fund-Partien" if s["fallback"] else
         f"Analyse-Stichprobe {s['sample']} Partien gleichmäßig über die Zeit, lange Bedenkzeit bevorzugt "
         f"({', '.join(f'{k} {v}' for k, v in sorted(s.get('sample_speeds', {}).items(), key=lambda x: -x[1]))}), "
         f"davon {s.get('analysed', 0)} mit Lichess-Analyse") for s in (sampling or []))
    add(f"Vermutlicher Online-Account: {names}. Gezählt: alle {len(games)} Partien ab 3+0 (ohne Bullet) "
        f"{dates[0][:7] if dates else '?'} bis {dates[-1][:7] if dates else '?'}: "
        f"{', '.join(f'{k} {v}' for k, v in sp.most_common())}" + (f"; {samp}" if samp else "") + ".",
        "all", "konto")
    for col, label in (("white", "Weiß"), ("black", "Schwarz")):
        gs = [g for g in games if g["is_white"] == (col == "white")]
        if not gs:
            continue
        sc = [g["player_score"] for g in gs if g["player_score"] is not None]
        add(f"Online mit {label}: {len(gs)} Partien, Score {round(100 * sum(sc) / len(sc)) if sc else '–'} %.", col, "ergebnis")
        root = trees[col]["nodes"].get("")
        if col == "white" and root:
            add("Online mit Weiß, erster Zug: " + ", ".join(
                f"1.{c['san']} {c['n']}× ({trees[col]['nodes'][c['path']]['score_pct']} %)" for c in root["children"][:4])
                + f" (von {root['n']}).", col, "eroeffnung")
            for c in root["children"][:2]:
                nd = trees[col]["nodes"][c["path"]]
                if nd["children"]:
                    add(f"Online mit Weiß nach 1.{c['san']}: " + "; ".join(
                        f"gegen …{k['san']} ({k['n']}×) " + ", ".join(
                            f"{(trees[col]['nodes'][kk['path']]['ply'] + 1) // 2}.{kk['san']} {kk['n']}×"
                            for kk in trees[col]["nodes"][k["path"]]["children"][:2])
                        for k in nd["children"][:3]) + ".", col, "eroeffnung")
        if col == "black" and root:
            parts = []
            for c in root["children"][:4]:
                nd = trees[col]["nodes"][c["path"]]
                parts.append(f"gegen 1.{c['san']} ({c['n']}×): " + ", ".join(f"…{k['san']} {k['n']}×" for k in nd["children"][:3]))
            add("Online mit Schwarz, Antworten: " + "; ".join(parts) + ".", col, "eroeffnung")
        for nd in main_lines(trees[col], min_games=2, max_lines=5):
            if nd["n"] < 2:
                continue
            ev = f", Engine {nd['eval'] / 100:+.2f}" if nd.get("eval") is not None else ""
            add(f"Online mit {label}: Linie {_numbered(nd['path'])} – {nd['n']}× ({nd['score_pct']} %)"
                + (f", {nd['name']}" if nd["name"] else "") + ev + ".", col, "linie")
    for r in comparison:
        if r["kind"] == "nur online" and r["online"] >= 3:
            add(f"Nur online gespielt ({'mit Weiß' if r['color'] == 'white' else 'mit Schwarz'}): {_numbered(r['path'])} – "
                f"{r['online']}× ({r['online_score']} %), im Turnier 0×.", r["color"], "abgleich")
        if r["kind"] == "beide" and r["online"] >= 2:
            add(f"Turnier und online gleich ({'mit Weiß' if r['color'] == 'white' else 'mit Schwarz'}): {_numbered(r['path'])} – "
                f"Turnier {r['otb']}×, online {r['online']}× ({r['online_score']} %).", r["color"], "abgleich")
    for t in trends or []:
        where = f"nach {_numbered(t['path'])}" if t["path"] else "erster Zug"
        mvs = [_mv(t["ply"], m) for m in t["moves"]]

        def row(c):
            return " / ".join(f"{m} {c.get(s, 0)}" for m, s in zip(mvs, t["moves"])) + f" (von {c['_n']})"
        years = "; ".join(f"{y}: {row(c)}" for y, c in t["by_year"].items())
        speeds = "; ".join(f"{s}: {row(c)}" for s, c in t["by_speed"].items())
        add(f"Online-Trend {'mit Weiß' if t['color'] == 'white' else 'mit Schwarz'}, {where} – je Jahr {years}. "
            f"Je Bedenkzeit {speeds}.", t["color"], "trend")
    if quality:
        n = quality["n"]
        for col, label in (("white", "Weiß"), ("black", "Schwarz")):
            c = quality["color_stats"][col]
            if not c["games"]:
                continue
            per100 = round(100 * (c["mistakes"] + c["blunders"]) / c["live_moves"]) if c["live_moves"] else None
            ph = [(p, v["errors_per_100"], v["live"]) for p, v in c["phases"].items() if v["errors_per_100"] is not None and v["live"] >= 15]
            worst = max(ph, key=lambda x: x[1]) if ph else None
            add(f"Online mit {label} (Lichess-Analyse, {c['games']} von {n} analysierten Partien): Genauigkeit {c['accuracy']} %, "
                f"{c['mistakes']} Fehler + {c['blunders']} Patzer in {c['live_moves']} bewertbaren Zügen"
                + (f" = {per100} je 100" if per100 is not None else "") + f", {c['tipping_per_game']} Kipp-Punkte je Partie"
                + (f"; fehleranfälligste Phase {worst[0]} ({worst[1]:.0f} je 100, {worst[2]} Züge)" if worst else "") + ".",
                col, "qualitaet")
        ts = quality["time"]
        if ts.get("games"):
            add(f"Online-Bedenkzeit ({ts['games']} Partien, {', '.join(ts['time_controls'][:3])}): Zeitnot (< 10 % der Grundzeit) vor Zug 40 in "
                f"{ts['trouble_games']} Partien; Fehler in Zeitnot {ts['errors_in_trouble']} von {ts['moves_in_trouble']} Zügen, "
                f"sonst {ts['errors_normal']} von {ts['moves_normal']}.", "all", "zeit")
        for k in quality["key_moments"]:
            mv = f"{k['move_no']}{'.' if k['is_white'] else '…'}{k['san']}"
            add(f"Online-Schlüsselstellung: {k['white']} – {k['black']} ({k['date']}), {mv}? "
                f"({'Patzer' if k['level'] == 'blunder' else 'Fehler'}, {k['phase']}), besser {k['best_san'] or '?'}; "
                f"Erwartungswert {k['exp_before']:.2f} → {k['exp_after']:.2f}.", "white" if k["is_white"] else "black", "schluessel")
    for s in sigs[:6]:
        if s["family_online"] or s["family_otb"]:
            dec = "; ".join(f"{d['path']} → {d['move']}: Turnier {d['otb'][0]}/{d['otb'][1]}, online {d['online'][0]}/{d['online'][1]}"
                            for d in s["decisions"] if d["otb"][1] or d["online"][1])
            add(f"Kursfamilie „{s['name']}“ ({s['author']}, {s['published'] or '?'}): passende Grundlinie Turnier "
                f"{s['family_otb']}×, online {s['family_online']}×" + (f", erstmals online {s['first_online']}" if s["first_online"] else "")
                + (f"; Entscheidungsstellen: {dec}" if dec else "; keine trennscharfen Kursstellen hinterlegt") + ".",
                s["color"], "kurs")
    return facts


def build_online_section(ident, otb_games, otb_trees, pdir, discovered: dict | None = None) -> dict | None:
    """discovered: Ergebnis von discover(), wenn die Suche schon parallel zur Engine lief (pipeline.prepare)."""
    res = discovered if discovered is not None else discover(ident, otb_games, pdir)
    summ, games, pool = res["summary"], res["games"], res["pool"]
    if not summ["accepted"] or not games:
        return {"accounts": summ, "active": False}
    # Lichess-Serveranalyse statt lokalem Stockfish: analysierte Partien laufen durch dieselbe Auswertung wie Turnierpartien
    ann, analysed = {}, []
    for g in games:
        if g.get("platform") == "lichess" and g.get("analysis"):
            gg = LA.as_game(g)
            pos = LA.positions(gg)
            if pos:
                ann[g["id"]] = metrics.annotate_game(gg, pos)
                analysed.append(gg)
    positions = ann_positions(ann)
    # Vollbaum aus ALLEN Partien (Zaehlung wie der Spieler-Explorer), Bewertungen aus den analysierten Stichprobenpartien
    min_n = max(1, min(5, len(pool) // 400))
    sample_ids = {g["id"] for g in games}
    trees = {c: build_tree(pool, c == "white", positions, keep_games=False, min_n=min_n, keep_ids=sample_ids)
             for c in ("white", "black")}
    trends = move_trends(pool, trees)
    quality = None
    if len(analysed) >= 10:
        quality = {"n": len(analysed),
                   "color_stats": {"white": metrics.color_stats(analysed, ann, True), "black": metrics.color_stats(analysed, ann, False)},
                   "time": metrics.time_stats(analysed, ann), "key_moments": metrics.key_moments(analysed, ann, limit=6)}
    cmp = compare_trees(otb_trees, trees)
    annotate_otb_tree_with_online(otb_trees, trees)
    sigs = chessable.match_signatures(otb_games, pool, [a["username"] for a in summ["accepted"]])
    facts = online_facts(summ["accepted"], pool, trees, cmp, sigs, summ.get("sampling"), quality, trends)
    viewer, cards = {}, []
    for g in games[:config.ONLINE_SAMPLE]:
        if g["id"] in ann:
            viewer[g["id"]] = metrics.viewer_moves(g, ann[g["id"]])
        else:
            b = chess.Board()
            mv = []
            for san, u in zip(g["sans"], g["ucis"]):
                mv.append({"san": san, "uci": u, "fen": b.fen(), "cp": None, "mate": None, "exp": None, "lvl": "",
                           "tip": False, "own": b.turn == (chess.WHITE if g["is_white"] else chess.BLACK),
                           "best": None, "best_uci": None, "clk": None, "ph": ""})
                b.push(chess.Move.from_uci(u))
            viewer[g["id"]] = mv
        cards.append({k: g.get(k) for k in ("id", "white", "black", "result", "date", "is_white", "opponent", "opponent_elo",
                                             "player_score", "speed", "url", "platform", "account", "event")})
    return {"active": True, "accounts": summ, "trees": trees, "comparison": cmp, "signatures": sigs,
            "facts": facts, "games": cards, "viewer": viewer, "n_games": len(pool), "n_sample": len(games), "quality": quality,
            "trends": trends, "tree_min_n": min_n,
            "course_search": _course_candidates(otb_trees)}


def _course_candidates(otb_trees) -> list[dict]:
    """Oeffentliche Chessable-Kurse zu seinen Haupt-Eroeffnungsfamilien (nur Metadaten)."""
    fams = Counter()
    for col in ("white", "black"):
        for nd in otb_trees[col]["nodes"].values():
            if nd["ply"] in (4, 6, 8, 10) and nd.get("name") and nd["n"] >= 1:
                nm = nd["name"]
                fam, _, var = nm.partition(":")
                fam = fam.replace("Defense", "").replace("Opening", "").replace("Game", "").strip()
                var = var.split(",")[0].replace("Variation", "").replace("Accepted", "").replace("Declined", "").strip()
                generic = {"", "Main Line", "Normal", "Classical", "Modern", "Open", "Closed", "Orthodox"}
                fams[(col, f"{fam} {var}".strip() if var not in generic else fam)] += nd["n"]
    out = []
    for (col, fam), _ in fams.most_common(5):
        common = {"sicilian", "gambit", "english", "indian", "attack", "system", "french", "queen's", "king's", "pawn", "game"}
        words = [w.lower() for w in fam.replace("-", " ").split() if len(w) > 3]
        words = [w for w in words if w not in common] or words
        for c in chessable.search_courses(fam, limit=8):
            if c["color"] in (col, "both") and any(w in c["name"].lower().replace("-", " ") for w in words):
                c["query"] = fam
                out.append(c)
    return out[:12]
