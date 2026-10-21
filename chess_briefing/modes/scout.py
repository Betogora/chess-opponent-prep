"""Stufe chess-opponent-scout-fast: Steckbrief ohne Engine, in Sekunden.

Alle sofort verfuegbaren Partien (ChessBase, chess-results, inbox) beider Farben -> Eroeffnungsbaeume, Ergebnisse je
Linie, Form, Partien zum Durchklicken. Keine Engine, keine Lichess-Uebertragungen, keine Online-Suche, kein Agententext:
die Kernpunkte bildet das Programm nach festen Regeln aus den Belegen. Die Farbe des Gegners in der anstehenden
Partie steht oben; die andere Farbe ist ebenfalls vollstaendig enthalten.
Daten: output/players/<slug>/scout/ ; Report: output/players/<slug>/scout_<slug>.html
"""
from __future__ import annotations

import datetime as dt

from .. import config, ratings as R
from ..dossier import Facts, _numbered
from ..identify import resolve
from ..openings import build_tree, main_lines
from ..util import log
from .common import (COLOR_DE, Deadline, opponent_colors, Timer, browser_notes, fast_sources, game_summary, output_dir, plain_annotation,
                     plain_viewer, results, timed, write_json_atomic)

MIN_LINE_GAMES = 2      # schwaechste/staerkste Linie erst ab so vielen Partien
MAX_LINE_PLY = 12       # Linien hoechstens bis Zug 6


def trunk_lines(tree: dict, min_n: int = MIN_LINE_GAMES, max_ply: int = MAX_LINE_PLY, limit: int = 10) -> list[dict]:
    """Seine wiederkehrenden Linien: von der Wurzel allen Zuegen folgen, die er mindestens min_n-mal gespielt hat,
    und dort enden, wo es sich nicht mehr wiederholt. Einzelpartien werden nicht als 'Linie' ausgegeben."""
    nodes, out = tree["nodes"], []

    def walk(path):
        nd = nodes[path]
        kids = [c for c in nd["children"] if c["n"] >= min_n] if nd["ply"] < max_ply else []
        if not kids:
            if nd["ply"] >= 2:
                out.append(nd)
            return
        for c in kids:
            walk(c["path"])
    if "" in nodes:
        walk("")
    out.sort(key=lambda nd: (-nd["n"], -nd["ply"], nd["path"]))
    return out[:limit]


def _pct(v):
    return "–" if v is None else f"{v:.0f} %"


def build_scout(ident, games: list[dict], hist: list, tr: dict, srclog: list, opp: str) -> tuple[dict, dict]:
    """Dossier (gleiche Form wie research, ohne Engine-Teile) und regelbasierte Kernpunkte."""
    facts = Facts()
    ann = {g["id"]: plain_annotation(g) for g in games}
    trees = {"white": build_tree(games, True, {}), "black": build_tree(games, False, {})}
    dates = sorted(g["date"] for g in games if g["date"])
    by_year: dict = {}
    for g in games:
        y = g["date"][:4] or "?"
        by_year[y] = by_year.get(y, 0) + 1
    undated = by_year.pop("?", 0)
    old = sum(1 for x in dates if int(x[:4]) < dt.date.today().year - config.STALE_YEARS)
    span = f"{dates[0][:4]}–{dates[-1][:4]}" if dates else "ohne Datum"
    f_data = facts.add(f"{len(games)} Partien mit Zügen ({span})"
                       + (": " + ", ".join(f"{y}: {n}" for y, n in sorted(by_year.items())) if by_year else "")
                       + (f"; {undated} ohne Datum" if undated else "") + ".", "all", "daten")
    f_form = None
    if tr:
        f_form = facts.add(f"FIDE-Elo {tr['first']} ({tr['first_date'][:7]}) → {tr['current']} heute; "
                           f"in den letzten {tr['window_months']} Monaten {tr['change_window']:+d}.", "all", "form")
    if ident.dsb.get("dwz"):
        facts.add(f"DWZ {ident.dsb['dwz']} (Index {ident.dsb.get('dwz_index')}), letzte Auswertung {ident.dsb.get('last_eval')}, "
                  f"Verein {ident.dsb.get('club')}.", "all", "form")
    cs, f_res, f_first, lines, f_best, f_worst = {}, {}, {}, {}, {}, {}
    for col in ("white", "black"):
        gs = [g for g in games if g["is_white"] == (col == "white")]
        r = results(gs)
        # gleiche Felder wie metrics.color_stats, soweit ohne Engine bestimmbar (fuer die gemeinsamen Abschnitte)
        cs[col] = dict(r, phases={}, conversion={"games": 0}, resilience={"games": 0}, accuracy=None, tipping_per_game=None,
                       exp_after_opening=None, live_moves=0, mistakes=0, blunders=0)
        if not gs:
            continue
        f_res[col] = facts.add(f"Mit {COLOR_DE[col]}: {r['games']} Partien, {r['w']} S / {r['d']} R / {r['l']} N"
                               + (f" = {r['score_pct']} %" if r["score_pct"] is not None else "")
                               + (f" gegen Ø Elo {r['avg_opp_elo']}" if r["avg_opp_elo"] else "")
                               + (f", Performance {r['performance']}" if r["performance"] else "") + ".", col, "ergebnis")
        t = trees[col]["nodes"]
        root = t[""]
        if col == "white":
            f_first[col] = facts.add("Mit Weiß, erster Zug: " + ", ".join(
                f"1.{k['san']} {k['n']}× ({_pct(t[k['path']]['score_pct'])})" for k in root["children"])
                + f" (von {root['n']} Partien).", col, "eroeffnung")
        else:
            parts = [f"gegen 1.{k['san']} ({k['n']}×): " + ", ".join(f"…{c['san']} {c['n']}×" for c in t[k["path"]]["children"])
                     for k in root["children"]]
            f_first[col] = facts.add("Mit Schwarz, Antworten: " + "; ".join(parts) + ".", col, "eroeffnung")
        lines[col] = []
        for nd in trunk_lines(trees[col]) or main_lines(trees[col], max_lines=5):
            fid = facts.add(f"Mit {COLOR_DE[col]}: Linie {_numbered(nd['path'])} – {nd['n']}× ({_pct(nd['score_pct'])})"
                            + (f", {nd['name']}" if nd["name"] else "") + ".", col, "linie")
            lines[col].append({"fact": fid, "path": nd["path"], "line": _numbered(nd["path"]), "n": nd["n"],
                               "score_pct": nd["score_pct"], "name": nd["name"], "eco": nd["eco"]})
        # Linien mit Ergebnis: Knoten ab seinem 2. eigenen Zug bzw. ab der Antwort, genug Partien, eindeutig bewertet
        cand = [nd for nd in t.values() if 2 <= nd["ply"] <= 10 and nd["n"] >= MIN_LINE_GAMES and nd["score_pct"] is not None]
        if cand:
            lo = min(cand, key=lambda n: (n["score_pct"], -n["n"], n["ply"]))
            hi = max(cand, key=lambda n: (n["score_pct"], n["n"], -n["ply"]))
            if lo["score_pct"] < (r["score_pct"] or 0):
                f_worst[col] = (lo, facts.add(f"Mit {COLOR_DE[col]}: schwächste Linie (ab {MIN_LINE_GAMES} Partien) "
                                              f"{_numbered(lo['path'])} – {lo['n']}×, {_pct(lo['score_pct'])}"
                                              + (f", {lo['name']}" if lo["name"] else "") + ".", col, "linie"))
            if hi["score_pct"] >= 50 and hi["score_pct"] > (r["score_pct"] or 0) and hi is not lo:
                f_best[col] = (hi, facts.add(f"Mit {COLOR_DE[col]}: stärkste Linie (ab {MIN_LINE_GAMES} Partien) "
                                             f"{_numbered(hi['path'])} – {hi['n']}×, {_pct(hi['score_pct'])}"
                                             + (f", {hi['name']}" if hi["name"] else "") + ".", col, "linie"))
    recent = sorted((g for g in games if g["date"]), key=lambda g: g["date"], reverse=True)[:10]
    f_recent = None
    if recent:
        sym = {1: "1", 0.5: "½", 0: "0", None: "*"}
        f_recent = facts.add("Letzte Partien (neueste zuerst): " + ", ".join(
            f"{sym[g['player_score']]} ({'W' if g['is_white'] else 'S'})" for g in recent)
            + f"; {sum(g['player_score'] or 0 for g in recent):g} aus {len(recent)}.", "all", "form")

    # ---------------- Kernpunkte nach festen Regeln (Farbe der anstehenden Partie zuerst; opp=None: beide Farben)
    def repertoire_point(col):
        main = lines[col][0] if lines.get(col) else None
        if main and col in f_worst and f_worst[col][0]["path"] == main["path"]:
            main = None          # steht schon als schwächste Linie da
        return {"title": f"Sein Repertoire mit {COLOR_DE[col]}",
                "text": _first_text(trees[col], col) + (f" Häufigste Linie: {main['line']} ({main['n']}×, "
                                                         f"{_pct(main['score_pct'])})." if main else ""),
                "evidence": [f_first[col]] + ([main["fact"]] if main else [])}

    def line_point(title, entry):
        nd, fid = entry
        return {"title": title, "text": f"{_numbered(nd['path'])}: {nd['n']} Partien, {_pct(nd['score_pct'])}"
                                        + (f" ({nd['name']})" if nd["name"] else "") + ".", "evidence": [fid]}
    summary = []
    if opp is None:
        summary += [repertoire_point(c) for c in ("white", "black") if c in f_first]
        worst = sorted(f_worst.values(), key=lambda x: (x[0]["score_pct"], -x[0]["n"]))
        if worst:
            summary.append(line_point("Hier punktet er am schwächsten", worst[0]))
    else:
        if opp in f_first:
            summary.append(repertoire_point(opp))
        if opp in f_worst:
            summary.append(line_point("Hier punktet er am schwächsten", f_worst[opp]))
        elif opp in f_res:
            r = cs[opp]
            summary.append({"title": f"Ergebnisse mit {COLOR_DE[opp]}",
                            "text": f"{r['games']} Partien, {_pct(r['score_pct'])}"
                                    + (f" gegen Ø Elo {r['avg_opp_elo']}" if r["avg_opp_elo"] else "") + ".",
                            "evidence": [f_res[opp]]})
        if opp in f_best:
            summary.append(line_point("Hier ist er erfolgreich", f_best[opp]))
    if f_recent and len(summary) < 3:
        summary.append({"title": "Form", "text": facts.items[int(f_recent[1:]) - 1]["text"], "evidence": [f_recent]})
    if f_form and len(summary) < 3:
        summary.append({"title": "Elo-Trend", "text": facts.items[int(f_form[1:]) - 1]["text"], "evidence": [f_form]})
    if opp is None:
        headline = " · ".join(f"Mit {COLOR_DE[c]}: {cs[c]['games']} Partien, {_pct(cs[c]['score_pct'])}"
                              for c in ("white", "black") if cs[c]["games"]) + " (Schnellcheck ohne Engine)."
    else:
        r = cs[opp]
        headline = (f"Mit {COLOR_DE[opp]}: {r['games']} Partien, {_pct(r['score_pct'])}"
                    + (f"; meist {lines[opp][0]['line']}" if lines.get(opp) else "") + " (Schnellcheck ohne Engine).")
    b = {"headline": headline, "summary": summary[:3]}

    d = {
        "generated": dt.datetime.now().isoformat(timespec="minutes"), "identity": ident.to_dict(), "sources": srclog,
        "engine": None,
        "data": {"games": len(games), "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
                 "older_than_stale": old, "by_year": by_year, "with_clock": sum(1 for a in ann.values() if a["has_clock"])},
        "color_stats": cs, "trees": trees, "repertoire": {f"{c}_lines": lines.get(c, []) for c in ("white", "black")},
        "team": {}, "ratings": hist, "rating_trend": tr, "key_moments": [], "online": None,
        "games": [game_summary(g, ann[g["id"]]) for g in games], "facts": facts.items, "briefing": b,
        "mode": {"name": "scout", "opponent_color": opp, "data_ref": f_data,
                 "badge": f"Schnellcheck · ohne Engine · {len(games)} Partien"},
    }
    viewer = {g["id"]: plain_viewer(g, ann[g["id"]]) for g in games}
    return d, viewer


def _first_text(tree: dict, col: str) -> str:
    t = tree["nodes"]
    root = t[""]
    if col == "white":
        return "Erster Zug: " + ", ".join(f"1.{k['san']} {k['n']}×" for k in root["children"][:3]) + "."
    parts = []
    for k in root["children"][:3]:
        ans = t[k["path"]]["children"]
        if ans:
            parts.append(f"gegen 1.{k['san']} meist …{ans[0]['san']} ({ans[0]['n']} von {k['n']})")
    return ("; ".join(parts) + ".") if parts else ""


def run(inp: str, color: str, budget: float = 90, fide_id=None, federation=None, birth_year=None) -> int:
    return run_result(inp, color, budget, fide_id, federation, birth_year)["rc"]


def run_result(inp: str, color: str, budget: float = 90, fide_id=None, federation=None, birth_year=None) -> dict:
    """color = Farbe des NUTZERS (der Gegner hat die andere; sie steht oben) oder "both" (beide gleichrangig)."""
    dl, tm = Deadline(budget), Timer()
    opps = opponent_colors(color)
    opp = opps[0] if len(opps) == 1 else None
    label = "beide Farben" if color == "both" else f"du hast {COLOR_DE[color]}"
    res = {"rc": 1, "slug": None, "html": None, "timing": [], "games": 0, "note": ""}
    log(f"\n== scout-fast: {inp} · {label} · Zeitgrenze {budget:.0f} s")
    ident = timed("identität", lambda: resolve(inp, federation=federation, birth_year=birth_year, fide_id=fide_id),
                  min(45, dl.left(10)))
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
    write_json_atomic(pdir / "identity.json", ident.to_dict())
    srclog: list = []
    games = fast_sources(ident, inbox, dl, srclog, chessresults_s=min(30.0, budget / 3))
    browser_notes(srclog)
    tm.lap("Quellen")
    if not games:
        log(f"!! Keine Partien gefunden – ChessBase-PGN in {inbox} ablegen (Browser-Schritt) und erneut starten.")
        return dict(res, timing=tm.steps, note="keine Partien (ChessBase-PGN fehlt?)")
    hist = timed("fide", lambda: R.fide_history(ident.fide_id), min(10, dl.left(10))) if ident.fide_id else None
    hist = hist or []
    tr = R.trend(hist) if hist else {}
    tm.lap("Elo-Verlauf")
    d, viewer = build_scout(ident, games, hist, tr, srclog, opp)
    if opp is None:
        d["mode"]["badge"] = f"Schnellcheck · ohne Engine · beide Farben · {len(games)} Partien"
    out = output_dir(pdir, "scout")
    write_json_atomic(out / "dossier.json", d)
    write_json_atomic(out / "viewer.json", viewer)
    tm.lap("Auswertung")
    from ..render.html import render_player
    html = render_player(out)
    tm.lap("HTML")
    d["mode"]["timing"] = tm.steps
    write_json_atomic(out / "dossier.json", d)
    log(f"-- fertig: {html}")
    log(f"   Zeiten: {tm.report()}")
    return dict(res, rc=0, html=str(html), timing=tm.steps, games=len(games), data_dir=str(out))
