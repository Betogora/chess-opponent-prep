"""Stufe chess-opponent-briefing-medium: Briefing fuer eine Farbe (oder beide) mit fester Zeitgrenze.

Ablauf: Identitaet -> schnelle Quellen (ChessBase, chess-results, inbox) -> Baum und Partien aus ALLEN Partien der
betrachteten Farbe(n) -> Stockfish nur fuer die juengsten davon (eine Farbe: 20, beide Farben: je 10; gleiche Tiefe wie
research, gemeinsamer Cache) -> Dossier mit Belegen -> brief.md fuer den Agenten -> HTML (zunaechst ohne Matchplan).
Daten: output/players/<slug>/medium_als-weiss/ (bzw. _als-schwarz, _beide); Report: output/players/<slug>/briefing_<slug>_<ordner>.html
"""
from __future__ import annotations

from .. import config, engine, metrics, profile as PR, ratings as R
from ..dossier import build, write_brief
from ..identify import resolve
from ..util import log
from .common import (COLOR_DE, FOLDER, Deadline, Timer, browser_notes, fast_sources, game_summary, lichess_fallback,
                     newest, opponent_colors, output_dir, plain_annotation, plain_viewer, results, timed,
                     write_json_atomic)

RESERVE_S = 15          # Restzeit fuer Dossier, brief.md und HTML nach der Engine (gemessen 2–4 s)
SIDE = {"white": "as_white", "black": "as_black"}


def run(inp: str, color: str, n_games: int = 20, budget: float = 300, depth: int | None = None,
        workers: int | None = None, fide_id=None, federation=None, birth_year=None) -> int:
    return run_result(inp, color, n_games, budget, depth, workers, fide_id, federation, birth_year)["rc"]


def run_result(inp: str, color: str, n_games: int = 20, budget: float = 300, depth: int | None = None,
               workers: int | None = None, fide_id=None, federation=None, birth_year=None) -> dict:
    """color = Farbe des NUTZERS in der anstehenden Partie, oder "both" (beide Farben, je n_games/2 Partien analysiert).
    Rueckgabe fuer den Mannschaftslauf: rc, slug, html, timing, Partien."""
    dl, tm = Deadline(budget), Timer()
    opps = opponent_colors(color)
    per = n_games if len(opps) == 1 else max(1, n_games // 2)
    label = "beide Farben" if color == "both" else f"du hast {COLOR_DE[color]}"
    res = {"rc": 1, "slug": None, "html": None, "timing": [], "games": 0, "analysed": 0, "note": ""}
    log(f"\n== briefing-medium: {inp} · {label} · Zeitgrenze {budget:.0f} s")
    ident = timed("identität", lambda: resolve(inp, federation=federation, birth_year=birth_year, fide_id=fide_id),
                  min(45, dl.left(RESERVE_S)))
    if ident is None:
        log("!! Spieler nicht eindeutig gefunden (Name mehrdeutig oder Netz zu langsam) – mit --fide-id erneut aufrufen.")
        return dict(res, rc=2, note="Spieler nicht eindeutig gefunden")
    log(f"   {ident.display} | FIDE {ident.fide_id} | Elo {ident.elo.get('standard')} | DWZ {ident.dsb.get('dwz', '–')}")
    tm.lap("Identität")
    from ..pipeline import player_dir
    pdir = player_dir(ident.slug)
    res["slug"] = ident.slug
    inbox = pdir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    out = output_dir(pdir, "medium", color)
    write_json_atomic(pdir / "identity.json", ident.to_dict())

    srclog: list = []
    games = fast_sources(ident, inbox, dl, srclog)

    def of(c):
        return [g for g in games if g["is_white"] == (c == "white")]
    if any(len(of(c)) < per for c in opps) and dl.left(RESERVE_S) > 120:
        from .. import games as G
        extra = lichess_fallback(ident, dl, srclog, seconds=60)
        if extra:
            games = G.merge(games + extra)
            log("   + Lichess-Übertragungen: jetzt " + ", ".join(f"{len(of(c))} mit {COLOR_DE[c]}" for c in opps))
    browser_notes(srclog)
    tm.lap("Quellen")
    col = [g for g in games if ("white" if g["is_white"] else "black") in opps]
    if not col:
        note = f"keine Partien mit {' oder '.join(COLOR_DE[c] for c in opps)} (ChessBase-PGN fehlt?)"
        log(f"!! {note} – ChessBase-PGN in {inbox} ablegen (Browser-Schritt).")
        return dict(res, timing=tm.steps, note=note)
    hist = timed("fide", lambda: R.fide_history(ident.fide_id), min(15, dl.left(RESERVE_S))) if ident.fide_id else None
    hist = hist or []
    tr = R.trend(hist) if hist else {}
    for g in col:
        if not g["player_elo"] and g["date"]:
            g["player_elo_est"] = R.rating_at(hist, g["date"][:7] + "-01")
    tm.lap("Elo-Verlauf")

    pick = [g for c in opps for g in newest(of(c), per)]
    depth = depth or config.ENGINE_DEPTH
    log("-- Analyse: " + ", ".join(f"{len(newest(of(c), per))} jüngste von {len(of(c))} Partien mit {COLOR_DE[c]}" for c in opps))
    pos = engine.analyse_games(pick, pdir / "analysis", depth=depth, workers=workers, deadline=dl.at(RESERVE_S))
    analysed = [g for g in pick if g["id"] in pos]
    tm.lap("Engine")

    ann = {g["id"]: metrics.annotate_game(g, pos[g["id"]]) for g in analysed}
    d = build(ident, analysed, ann, {}, hist, tr, srclog, engine.engine_label(), depth, tree_games=col)
    d["profile"] = PR.build(ident, analysed, ann, pos, []) if analysed else None
    # Ergebnisse ueber ALLE Partien je Farbe (ohne Engine) als eigener Beleg
    for c in opps:
        r_all = results(of(c))
        if not r_all["games"]:
            continue
        d["facts"].append({"id": f"F{len(d['facts']) + 1}", "scope": c, "topic": "ergebnis",
                           "text": f"Mit {COLOR_DE[c]} alle Partien (ohne Engine): {r_all['games']}, {r_all['w']} S / "
                                   f"{r_all['d']} R / {r_all['l']} N"
                                   + (f" = {r_all['score_pct']} %" if r_all["score_pct"] is not None else "")
                                   + (f" gegen Ø Elo {r_all['avg_opp_elo']}" if r_all["avg_opp_elo"] else "") + "."})
    plain = {g["id"]: plain_annotation(g) for g in col if g["id"] not in ann}
    d["games"] = [game_summary(g, ann.get(g["id"]) or plain[g["id"]]) for g in col]
    d["data"].update(games_all=len(col), analysed=len(analysed))
    # Seiten des Matchplans: Nutzer hat Weiss -> as_white (Gegner hat Schwarz)
    sides = [SIDE["black" if c == "white" else "white"] for c in opps]
    sides.sort(key=lambda s: s != "as_white")
    d["mode"] = {"name": "medium", "color": color, "opponent_color": opps[0] if len(opps) == 1 else None,
                 "sides": sides, "folder": FOLDER[color], "label": label, "min_plan_steps": 3, "n_games": n_games,
                 "badge": f"Briefing medium · {label} · {len(analysed)} von {len(col)} Partien analysiert",
                 "timing": tm.steps}
    viewer = {g["id"]: metrics.viewer_moves(g, ann[g["id"]]) for g in analysed}
    viewer.update({gid: plain_viewer(next(g for g in col if g["id"] == gid), a) for gid, a in plain.items()})
    write_json_atomic(out / "dossier.json", d)
    write_json_atomic(out / "viewer.json", viewer)
    write_brief(d, out / "brief.md")
    _brief_header(out / "brief.md", d, sides, len(analysed), len(col))
    tm.lap("Dossier")
    from ..render.html import render_player
    html = render_player(out)
    tm.lap("HTML")
    d["mode"]["timing"] = tm.steps
    write_json_atomic(out / "dossier.json", d)
    log(f"-- fertig: {html}")
    log(f"   Zeiten: {tm.report()}")
    slug = f"{ident.slug}/{out.name}"
    log(f"   Nächster Schritt: {out / 'briefing.json'} nur mit {' und '.join(f'`{s}`' for s in sides)} schreiben "
        f"(siehe brief.md), dann `python briefing.py validate {slug}` und `python briefing.py render {slug}`")
    return dict(res, rc=0, html=str(html), timing=tm.steps, games=len(col), analysed=len(analysed),
                data_dir=str(out))


def _brief_header(path, d, sides, n_an, n_all) -> None:
    m = d["mode"]
    which = " und ".join(f"`{s}`" for s in sides)
    if m["opponent_color"]:
        who = f"- Die Farbe steht fest: der Nutzer hat {COLOR_DE[m['color']]}, der Gegner {COLOR_DE[m['opponent_color']]}."
    else:
        who = "- Beide Farben: as_white (Nutzer hat Weiß, Belege scope black/all) und as_black (scope white/all)."
    head = [f"# Stufe briefing-medium – {which} schreiben", "", who,
            f"- Engine-Belege (Fehler, Phasen, Schlüsselstellungen, Profil) stammen aus den {n_an} jüngsten Partien "
            f"(je Farbe höchstens {m['n_games'] if len(sides) == 1 else m['n_games'] // 2}); Eröffnungsbaum, Linien-Belege "
            f"und Partienliste aus allen {n_all} Partien.",
            "- Kurz halten: headline, profile_summary (falls Profil), summary (3), "
            f"{which} mit goal, 1–3 Eröffnungskarten, 3–5 Plan-Schritten, avoid (1–2), watch (2–3), moments.",
            "- Kein Online-Feld. Theorie-Empfehlungen mit `line` prüfen.", "", ""]
    path.write_text("\n".join(head) + path.read_text(encoding="utf-8"), encoding="utf-8")
