"""Ablaufsteuerung der Stufen."""
from __future__ import annotations

import threading


from . import config, engine, games as G, metrics, profile as PR, ratings as R
from .dossier import build, write_brief
from .identify import AmbiguousPlayer, resolve
from .sources import chessbase, chessresults, lichess, local, nsv
from .util import log, log_tag, read_json, set_log_tag, write_json


def player_dir(slug: str):
    return config.PLAYERS_DIR / slug


def prepare(inp: str, fide_id=None, federation=None, birth_year=None, depth=None, workers=None,
            force=False, use_nsv=True, seasons=8, use_online=True) -> int:
    log(f"\n== {inp}")
    try:
        ident = resolve(inp, federation=federation, birth_year=birth_year, fide_id=fide_id)
    except AmbiguousPlayer as e:
        log(f"!! {e}")
        for c in e.candidates:
            log(f"   - {c.get('name')} | FIDE {c.get('id')} | {c.get('federation')} | Jg. {c.get('year')} | Elo {c.get('standard')}")
        log("   -> erneut mit --fide-id <ID> oder --fed/--birth-year aufrufen.")
        return 2
    pdir = player_dir(ident.slug)
    inbox = pdir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    log(f"   {ident.display} | FIDE {ident.fide_id} | {ident.federation} | Jg. {ident.birth_year} | "
        f"Elo {ident.elo.get('standard')} | {ident.dsb.get('club', '–')} DWZ {ident.dsb.get('dwz', '–')} "
        f"| Sicherheit: {ident.confidence}")
    for n in ident.notes:
        log(f"   · {n}")
    write_json(pdir / "identity.json", ident.to_dict())

    # ---------- Quellen
    log("-- Quellen")
    srclog, pgn_texts, team_rows = [], [], []

    def guarded(name, fn):
        """Eine ausgefallene Quelle (Netz, geaenderte Seite) darf den Lauf nicht abbrechen."""
        try:
            return fn()
        except Exception as ex:  # noqa: BLE001 - bewusst breit, Fehler wird protokolliert
            log(f"   ! Quelle {name} fehlgeschlagen: {type(ex).__name__}: {ex}")
            srclog.append({"source": name, "status": "fehler", "detail": f"{type(ex).__name__}: {ex}"[:200]})
            return None

    for name, fn in (("lichess", lambda: lichess.collect(ident)), ("chessbase", lambda: chessbase.collect(ident, inbox)),
                     ("chess-results", lambda: chessresults.collect(ident, inbox)), ("lokal", lambda: local.collect(ident, inbox))):
        r = guarded(name, fn)
        if r:
            pgn_texts.append(r[0]); srclog += r[1]
    if use_nsv:
        r = guarded("nsv", lambda: nsv.collect(ident, seasons_back=seasons))
        if r:
            pgn_texts.append(r[0]); team_rows = r[1]; srclog += r[2]
    all_games = []
    for txt in pgn_texts:
        if txt:
            all_games += G.parse_pgn(txt, ident)
    games = G.merge(all_games)
    log(f"   {len(all_games)} Partien eingelesen -> {len(games)} nach Dublettenabgleich")
    (pdir / "games.pgn").write_text("\n\n".join(G.to_pgn(g) for g in games), encoding="utf-8")
    write_json(pdir / "team_results.json", team_rows)
    write_json(pdir / "sources.json", srclog)
    need_browser = [s for s in srclog if s.get("status") == "browser_noetig"]
    for s in need_browser:
        h = s["hint"]
        label = {"chessbase": "ChessBase", "chess-results": "chess-results.com"}.get(s["source"], s["source"])
        log(f"   ! {label} braucht den Browser: {h['open']} -> {h.get('fetch_in_page') or h.get('steps')} -> {h['save_as']}")

    if not games:
        log("!! Keine Partien mit Zuegen gefunden. Dossier enthaelt nur Identitaet/Mannschaftsdaten.")

    # ---------- Ratings
    hist = (guarded("fide", lambda: R.fide_history(ident.fide_id)) or []) if ident.fide_id else []
    tr = R.trend(hist) if hist else {}
    for g in games:
        if not g["player_elo"] and g["date"]:
            g["player_elo_est"] = R.rating_at(hist, g["date"][:7] + "-01")

    # ---------- Online-Kandidatensuche (nur Netz) parallel zur Engine
    disc, disc_thread = {}, None
    if use_online:
        from .online.accounts import discover
        tag = log_tag()

        def _discover():
            set_log_tag(tag)
            try:
                disc["res"] = discover(ident, games, pdir)
            except Exception as ex:  # noqa: BLE001 - wird unten wie ein Fehler der Online-Suche gemeldet
                disc["err"] = ex
        disc_thread = threading.Thread(target=_discover, daemon=True, name="online-discover")
        disc_thread.start()

    # ---------- Engine
    log("-- Analyse")
    depth = depth or config.ENGINE_DEPTH
    pos = engine.analyse_games(games, pdir / "analysis", depth=depth, workers=workers, force=force) if games else {}
    ann = {g["id"]: metrics.annotate_game(g, pos[g["id"]]) for g in games}
    team = metrics.team_stats(team_rows)

    dossier = build(ident, games, ann, team, hist, tr, srclog, engine.engine_label(), depth)
    dossier["profile"] = PR.build(ident, games, ann, pos, team_rows)
    t = dossier["profile"]["type"]
    log(f"-- Profil: {t['name']}{' (unsicher)' if t['unsure'] else ''}"
        + ("" if dossier["profile"]["calibrated"] else " – ohne Vergleichskurven (python briefing.py calibrate)"))
    online_viewer = {}
    if use_online:
        # auch ohne Turnierpartien: Kandidaten ueber Verein, Namen und research.json; nur der Fingerabdruck entfaellt
        log("-- Online-Accounts" + ("" if games else " (ohne Turnierpartien: kein Eröffnungs-Fingerabdruck)"))
        from .online.accounts import build_online_section
        disc_thread.join()
        try:
            if "err" in disc:
                raise disc["err"]
            onl = build_online_section(ident, games, dossier["trees"], pdir, discovered=disc.get("res"))
        except Exception as ex:  # noqa: BLE001
            log(f"   ! Online-Suche fehlgeschlagen: {type(ex).__name__}: {ex}")
            onl = {"active": False, "accounts": {"candidates": [], "accepted": []}, "error": str(ex)[:200]}
        acc = onl["accounts"]
        for c in acc["candidates"][:3]:
            log(f"   {c['platform']:8} {c['username']:20} {round(c['confidence'] * 100):3d} %  {', '.join(c['via'])}")
        if onl.get("active"):
            online_viewer = onl.pop("viewer")
            log(f"   übernommen: {', '.join(a['username'] for a in acc['accepted'])} – {onl['n_games']} Online-Partien, "
                f"{len(onl['facts'])} Belege O…")
        elif acc.get("ambiguous"):
            log(f"   mehrdeutig, nichts übernommen: {', '.join(a['username'] for a in acc['ambiguous'])} "
                f"(in research.json bestätigen oder ablehnen)")
        else:
            log("   kein Account mit Konfidenz >= 50 %")
        dossier["online"] = onl
    # Viewer-Daten (Zuege + Bewertungen) getrennt, damit dossier.json lesbar bleibt
    viewer = {g["id"]: metrics.viewer_moves(g, ann[g["id"]]) for g in games}
    viewer.update(online_viewer)
    write_json(pdir / "dossier.json", dossier)
    write_json(pdir / "viewer.json", viewer)
    me = PR.load_me(pdir)
    PR.me_snapshot(pdir, me)
    write_brief(dossier, pdir / "brief.md", PR.corridor(dossier, me) if me else None)
    log(f"-- fertig: {pdir / 'dossier.json'}  ({len(dossier['facts'])} Facts)")
    log(f"   Naechster Schritt: briefing.json schreiben (siehe brief.md), dann `python briefing.py validate {ident.slug}`")
    return 0


PARALLEL_PLAYERS = 3   # Gegner gleichzeitig: Netzschritte ueberlappen, die Engine teilt sich die Plaetze (engine_slots)


def prepare_many(inputs: list[str], **kw) -> int:
    """Mehrere Gegner parallel: Quellen und Online-Suche des einen laufen, waehrend die Engine fuer den anderen rechnet.
    Die Engine-Plaetze sind rechnerweit begrenzt (engine._slot), die Kerne bleiben also voll, aber nicht ueberbucht.
    Logzeilen tragen das Kennzeichen [1], [2], ... in der Reihenfolge der Eingaben."""
    if len(inputs) == 1:
        return prepare(inputs[0], **kw)
    from concurrent.futures import ThreadPoolExecutor

    def run(k_inp):
        k, inp = k_inp
        set_log_tag(str(k + 1))
        try:
            return prepare(inp, **kw)
        except Exception as ex:  # noqa: BLE001 - ein Gegner darf die anderen nicht abbrechen
            log(f"!! Abbruch: {type(ex).__name__}: {ex}")
            return 1
        finally:
            set_log_tag(None)
    with ThreadPoolExecutor(max_workers=min(PARALLEL_PLAYERS, len(inputs))) as ex:
        rcs = list(ex.map(run, enumerate(inputs)))
    rc = 0
    for r in rcs:
        rc |= r
    return rc


def reprofile(slug: str) -> int:
    """Nur das Spielerprofil neu rechnen (z. B. nach `calibrate`): Partien, Engine-Cache, Mannschaftsergebnisse und
    Elo-Verlauf aus dem Gegnerordner, keine Quellen, keine Online-Suche."""
    import dataclasses
    from .identify import Identity
    pdir = player_dir(slug)
    d = read_json(pdir / "dossier.json")
    idt = read_json(pdir / "identity.json")
    if not d or not idt or not (pdir / "games.pgn").exists():
        log(f"!! {slug}: zuerst prepare ausführen")
        return 1
    names = {f.name for f in dataclasses.fields(Identity)}
    ident = Identity(**{k: v for k, v in idt.items() if k in names})
    games = G.merge(G.parse_pgn((pdir / "games.pgn").read_text(encoding="utf-8"), ident))
    hist = d.get("ratings") or []
    for g in games:
        if not g["player_elo"] and g["date"]:
            g["player_elo_est"] = R.rating_at(hist, g["date"][:7] + "-01")
    pos = engine.analyse_games(games, pdir / "analysis") if games else {}
    ann = {g["id"]: metrics.annotate_game(g, pos[g["id"]]) for g in games}
    d["profile"] = PR.build(ident, games, ann, pos, read_json(pdir / "team_results.json", []))
    write_json(pdir / "dossier.json", d)
    me = PR.load_me(pdir)
    PR.me_snapshot(pdir, me)
    write_brief(d, pdir / "brief.md", PR.corridor(d, me) if me else None)
    t = d["profile"]["type"]
    log(f"   {slug}: {t['name']}{' (unsicher)' if t['unsure'] else ''} – brief.md aktualisiert")
    return 0


def line(slug: str, san_line: str, scope: str, depth: int = 22) -> int:
    """Theorie-Linie mit Stockfish pruefen und als zitierbaren Beleg E<n> ablegen."""
    pdir = player_dir(slug)
    checks = read_json(pdir / "engine_checks.json", [])
    r = engine.check_line(san_line, depth=depth)
    r["id"] = f"E{len(checks) + 1}"
    r["scope"] = scope
    best = r["candidates"][0]
    ev = f"{best['eval'] / 100:+.2f}" if best["mate"] is None else f"Matt in {best['mate']}"
    alts = "; ".join(f"{c['eval'] / 100:+.2f} {c['pv']}" for c in r["candidates"])
    r["text"] = (f"Engine-Prüfung ({r['engine']}, Tiefe {depth}): nach {san_line} steht es {ev} "
                 f"({'Weiß' if r['to_move'] == 'white' else 'Schwarz'} am Zug). Kandidaten: {alts}.")
    checks.append(r)
    write_json(pdir / "engine_checks.json", checks)
    log(f"   {r['id']}: {r['text']}")
    return 0


def all_facts(pdir, with_me: bool = True) -> list[dict]:
    """F (Turnier), E (Engine-Pruefung), O (online), P (Profil), M (Eigenprofil aus me.json, falls vorhanden)."""
    d = read_json(pdir / "dossier.json") or {}
    extra = [{"id": c["id"], "text": c["text"], "scope": c.get("scope", "all"), "topic": "engine"}
             for c in read_json(pdir / "engine_checks.json", [])]
    onl = (d.get("online") or {})
    prof = (d.get("profile") or {}).get("facts", [])
    me = PR.load_me(pdir) if with_me else None
    mine = PR.corridor(d, me)["facts"] if me and d.get("profile") else []
    return d.get("facts", []) + extra + (onl.get("facts", []) if onl.get("active") else []) + prof + mine


def course_add(query: str, family: str, color: str, course_id: int | None = None, decisions: list[str] | None = None,
               source: str = "") -> int:
    """Kurs aus der oeffentlichen Chessable-Suche in die Signatur-Bibliothek uebernehmen.
    decisions: ["<Pfad SAN> => <Zug> | Notiz", ...] (nur mit belegter Quelle eintragen)."""
    import json
    from .online import chessable
    hits = chessable.search_courses(query, limit=10)
    if course_id:
        hits = [h for h in hits if h["id"] == course_id]
    if not hits:
        log("   kein Kurs gefunden")
        return 1
    c = hits[0]
    lib = read_json(chessable.SIG_FILE, {"courses": []})
    lib["courses"] = [x for x in lib["courses"] if x["id"] != c["id"]]
    entry = {"id": c["id"], "name": c["name"], "author": c["author"], "color": color, "published": c["published"],
             "url": c["url"], "family_line": " ".join(t for t in family.split() if not t.rstrip(".").isdigit()),
             "decisions": [], "source": source or "Chessable-Suche (Metadaten); Grundlinie aus Kursname/-beschreibung"}
    for d in decisions or []:
        path, rest = d.split("=>", 1)
        mv, _, note = rest.partition("|")
        entry["decisions"].append({"path": path.strip(), "move": mv.strip(), "note": note.strip()})
    lib["courses"].append(entry)
    write_json(chessable.SIG_FILE, lib)
    log(f"   {c['id']} {c['name']} ({c['author']}, {c['published']}) -> {chessable.SIG_FILE.name}")
    log("   " + json.dumps(entry, ensure_ascii=False)[:300])
    return 0


def _cited(obj, out=None) -> set[str]:
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "evidence" and isinstance(v, list):
                out.update(v)
            elif k != "_evidence_snapshot":
                _cited(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _cited(v, out)
    return out


def _remap(b: dict, texts: dict[str, str]) -> dict[str, str]:
    """Verweise umstellen, deren gestempelter Text unveraendert unter einer neuen ID steht (nur verschobene Belege)."""
    snap = b.get("_evidence_snapshot") or {}
    by_text = {t: fid for fid, t in texts.items()}
    mapping = {fid: by_text[old] for fid, old in snap.items() if texts.get(fid) != old and old in by_text}

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "evidence" and isinstance(v, list):
                    x[k] = [mapping.get(i, i) for i in v]
                elif k != "_evidence_snapshot":
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(b)
    if mapping:
        b["_evidence_snapshot"] = {mapping.get(k, k): v for k, v in snap.items()}
    return mapping


def validate(slug: str, restamp: bool = False, remap: bool = False) -> int:
    """Prueft briefing.json. Beim ersten fehlerfreien Lauf wird der Text jedes zitierten Belegs als
    `_evidence_snapshot` gespeichert; aendert sich ein Beleg spaeter (neue Partien, neue IDs), ist das ein Fehler.
    Nach inhaltlicher Pruefung mit --restamp neu stempeln."""
    from .validate import validate_briefing
    pdir = player_dir(slug)
    d = read_json(pdir / "dossier.json")
    b = read_json(pdir / "briefing.json")
    if d:
        d["facts"] = all_facts(pdir)
        PR.me_snapshot(pdir, PR.load_me(pdir))
    if remap and b and d:
        moved = _remap(b, {f["id"]: f["text"] for f in d["facts"]})
        if moved:
            write_json(pdir / "briefing.json", b)
            log("   umgestellt: " + ", ".join(f"{k}→{v}" for k, v in sorted(moved.items())))
    problems, warnings = validate_briefing(b, d)
    if b and d:
        texts = {f["id"]: f["text"] for f in d["facts"]}
        snap = b.get("_evidence_snapshot") or {}
        if snap and not restamp:
            for fid, old in sorted(snap.items()):
                if texts.get(fid) != old:
                    problems.append(f"Beleg {fid} hat sich seit dem Schreiben geändert: „{old[:90]}“ → „{(texts.get(fid) or 'fehlt')[:90]}“")
        if not problems and (restamp or not snap or set(snap) != _cited(b)):
            b["_evidence_snapshot"] = {fid: texts[fid] for fid in sorted(_cited(b)) if fid in texts}
            write_json(pdir / "briefing.json", b)
            log(f"   Belege gestempelt ({len(b['_evidence_snapshot'])})")
    for w in warnings:
        log(f"   ~ {w}")
    for p in problems:
        log(f"   ✗ {p}")
    log("   ✓ Briefing gültig" if not problems else f"   {len(problems)} Problem(e)")
    return 1 if problems else 0


def render(slugs: list[str], with_me: bool = True) -> int:
    from .render.html import render_player
    outs = []
    for s in slugs:
        pdir = player_dir(s)
        out = render_player(pdir, with_me=with_me)
        log(f"   -> {out}")
        outs.append(out)
    return 0
