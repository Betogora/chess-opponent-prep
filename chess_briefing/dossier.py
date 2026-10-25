"""Dossier: alle Kennzahlen als JSON (fuer den Renderer) + Belegliste (Facts) + Schreib-Brief (Markdown).

Facts sind kurze, pruefbare Aussagen mit Stichprobe und ID (F1, F2, ...). Der Matchplan
(matchplan.json) zitiert sie per ID; validate.py prueft Perspektive und Zahlen dagegen.
scope: 'white' = Gegner mit Weiss (relevant, wenn ICH Schwarz habe), 'black' = Gegner mit Schwarz
(relevant, wenn ICH Weiss habe), 'all' = farbunabhaengig.
"""
from __future__ import annotations

import datetime as dt

import chess

from . import config
from .openings import build_tree, main_lines

COL = {"white": "Weiß", "black": "Schwarz"}


def _n(x, unit=""):
    return "–" if x is None else f"{x}{unit}"


class Facts:
    def __init__(self):
        self.items = []

    def add(self, text: str, scope: str = "all", topic: str = "", **data) -> str:
        fid = f"F{len(self.items) + 1}"
        self.items.append({"id": fid, "text": text, "scope": scope, "topic": topic, **data})
        return fid


def _wdl(cs):
    s = f"{cs['w']} S / {cs['d']} R / {cs['l']} N"
    return s + (f" ({cs['unscored']} ohne Ergebnis)" if cs.get("unscored") else "")


def _when(date: str) -> str:
    return date[:4] if date else "ohne Datum"


def build(ident, games, ann, team, ratings, rating_trend, sources_log, engine_name, depth, tree_games=None) -> dict:
    """tree_games: Partien fuer Eroeffnungsbaum und Linien-Belege, falls mehr als die analysierten (briefing-medium:
    Baum aus allen Partien, Engine nur fuer die juengsten). None = dieselben Partien wie die Analyse (research)."""
    facts = Facts()
    from .metrics import color_stats, time_stats, key_moments, opponent_errors, structure_stats, PHASES
    cs = {"white": color_stats(games, ann, True), "black": color_stats(games, ann, False)}
    ts = time_stats(games, ann)
    km = key_moments(games, ann, limit=12)
    oe = opponent_errors(games, ann)
    ss = structure_stats(games, ann)
    positions = ann_positions(ann)
    tg = games if tree_games is None else tree_games
    trees = {"white": build_tree(tg, True, positions), "black": build_tree(tg, False, positions)}

    dates = sorted(g["date"] for g in games if g["date"])
    today = dt.date.today()
    old = sum(1 for d in dates if int(d[:4]) < today.year - config.STALE_YEARS)
    by_year = {}
    for g in games:
        y = g["date"][:4] or "?"
        by_year[y] = by_year.get(y, 0) + 1

    # ---------------- Facts: Datenlage
    undated = by_year.pop("?", 0)
    span = f"{dates[0][:4]}–{dates[-1][:4]}" if dates else "ohne Datum"
    facts.add(f"{len(games)} Partien mit Zügen ({span})"
              + (": " + ", ".join(f"{y}: {n}" for y, n in sorted(by_year.items())) if by_year else "")
              + (f"; {undated} ohne Datum" if undated and dates else "") + ".", "all", "daten",
              games=len(games))
    if old:
        facts.add(f"{old} von {len(games)} Partien sind älter als {config.STALE_YEARS} Jahre.", "all", "daten")
    if rating_trend:
        facts.add(f"FIDE-Elo {rating_trend['first']} ({rating_trend['first_date'][:7]}) → {rating_trend['current']} heute; "
                  f"in den letzten {rating_trend['window_months']} Monaten {rating_trend['change_window']:+d}.", "all", "form")
    if ident.dsb.get("dwz"):
        facts.add(f"DWZ {ident.dsb['dwz']} (Index {ident.dsb.get('dwz_index')}), letzte Auswertung {ident.dsb.get('last_eval')}, "
                  f"Verein {ident.dsb.get('club')}.", "all", "form")

    # ---------------- Facts je Farbe
    for col in ("white", "black"):
        c = cs[col]
        if not c["games"]:
            continue
        thin = " – dünne Basis" if c["games"] < config.THIN_GAMES else ""
        res = f"{_wdl(c)} = {c['score_pct']} %" if c["score_pct"] is not None else "alle ohne Ergebnis"
        facts.add(f"Mit {COL[col]}: {c['games']} Partien, {res}"
                  + (f" gegen Ø Elo {c['avg_opp_elo']}" if c["avg_opp_elo"] else "") + thin + ".",
                  col, "ergebnis", games=c["games"])
        facts.add(f"Mit {COL[col]}: Genauigkeit {c['accuracy']} % über {c['moves']} eigene Züge; "
                  f"{c['mistakes']} Fehler + {c['blunders']} Patzer in {c['live_moves']} bewertbaren Zügen; "
                  f"{c['tipping']} Kipp-Punkte = {c['tipping_per_game']} je Partie.", col, "fehler")
        for ph in PHASES:
            p = c["phases"][ph]
            if not p["moves"]:
                continue
            thin_p = " (dünn)" if p["moves"] < config.THIN_MOVES_PHASE else ""
            facts.add(f"Mit {COL[col]}, {ph}: {p['moves']} Züge{thin_p}, Genauigkeit {p['accuracy']} %, "
                      f"{p['mistakes']} Fehler / {p['blunders']} Patzer, {p['tipping']} Kipp-Punkte, "
                      f"Ø Verlust {_n(p['loss_avg'], ' %')} je bewertbarem Zug.", col, f"phase:{ph}")
        if c["exp_after_opening_n"]:
            facts.add(f"Mit {COL[col]}: Erwartungswert nach der Eröffnungsphase Ø {c['exp_after_opening']:.2f} "
                      f"(n={c['exp_after_opening_n']}; 0.50 = ausgeglichen).", col, "eroeffnung")
        cv = c["conversion"]
        if cv["games"] or cv["unknown"]:
            out = f"{cv['won']} gewonnen, {cv['drawn']} remis, {cv['lost']} verloren"
            facts.add(f"Mit {COL[col]}: in {cv['games'] + cv['unknown']} Partien stand er klar besser (≥ 0.80) – "
                      + (f"davon {out}" if not cv["unknown"] else f"{cv['unknown']} ohne Ergebnis"
                         + (f"; von {cv['games']} mit Ergebnis {out}" if cv["games"] else "")) + ".", col, "verwertung")
        rs = c["resilience"]
        if rs["games"] or rs["unknown"]:
            out = f"{rs['saved']} gehalten ({rs['won']} sogar gewonnen)"
            facts.add(f"Mit {COL[col]}: in {rs['games'] + rs['unknown']} Partien stand er klar schlechter (≤ 0.20) – "
                      + (f"davon {out}" if not rs["unknown"] else f"{rs['unknown']} ohne Ergebnis"
                         + (f"; von {rs['games']} mit Ergebnis {out}" if rs["games"] else "")) + ".", col, "widerstand")
        s = ss[col]
        if s["structure"]:
            facts.add(f"Mit {COL[col]}, Stellungstyp zu Mittelspielbeginn: " + ", ".join(
                f"{k} {v['n']}× ({_n(v['score'], ' %')})" for k, v in sorted(s["structure"].items(), key=lambda x: -x[1]["n"])) + ".",
                col, "struktur")
        if s["endgames"]:
            facts.add(f"Mit {COL[col]}, erreichte Endspiele: " + ", ".join(
                f"{k} {v['n']}× ({_n(v['score'], ' %')})" for k, v in sorted(s["endgames"].items(), key=lambda x: -x[1]["n"])) + ".",
                col, "endspiel")
        if s["early_queen_trade"]["n"]:
            facts.add(f"Mit {COL[col]}: Damentausch bis Zug 25 in {s['early_queen_trade']['n']} von {c['games']} Partien "
                      f"(Score {_n(s['early_queen_trade']['score'], ' %')}).", col, "struktur")

    # ---------------- Eroeffnungen
    rep = {}
    for col in ("white", "black"):
        t = trees[col]["nodes"]
        root = t.get("")
        if not root or not root["n"]:
            continue
        if col == "white":
            first = [(k["san"], k["n"], t[k["path"]]) for k in root["children"]]
            facts.add("Mit Weiß, erster Zug: " + ", ".join(
                f"1.{s} {n}× ({_n(t_['score_pct'], ' %')})" for s, n, t_ in first) + f" (von {root['n']} Partien).", "white", "eroeffnung")
            rep[col] = [{"move": s, "n": n} for s, n, _ in first]
        else:
            parts = []
            for k in root["children"]:
                nd = t[k["path"]]
                answers = ", ".join(f"…{c['san']} {c['n']}×" for c in nd["children"])
                parts.append(f"gegen 1.{k['san']} ({k['n']}×): {answers}")
            facts.add("Mit Schwarz, Antworten: " + "; ".join(parts) + ".", "black", "eroeffnung")
        lines = main_lines(trees[col], max_lines=10)
        rep[col + "_lines"] = []
        for nd in lines:
            g_ids = nd["games"]
            line = _numbered(nd["path"])
            ev = nd["eval"]
            fid = facts.add(f"Mit {COL[col]}: Linie {line} – {nd['n']}× ({_n(nd['score_pct'], ' %')})"
                            + (f", {nd['name']}" if nd["name"] else "")
                            + (f", Bewertung am Ende {ev / 100:+.2f}" if ev is not None else "") + ".", col, "linie")
            rep[col + "_lines"].append({"fact": fid, "path": nd["path"], "line": line, "n": nd["n"],
                                        "score_pct": nd["score_pct"], "name": nd["name"], "eco": nd["eco"],
                                        "eval": ev, "games": g_ids})

    # Eroeffnungs-Abweichungen: erster eigener Zug mit Verlust > Ungenauigkeit in der Eroeffnung
    deviations = []
    for g in games:
        for m in ann[g["id"]]["moves"]:
            if m["own"] and m["phase"] == "Eröffnung" and m["loss"] > config.EXP_INACCURACY and m["live"]:
                deviations.append({"game": g["id"], "is_white": g["is_white"], "move_no": m["move_no"], "san": m["san"],
                                   "best": m["best_san"], "loss": m["loss"], "opening": ann[g["id"]]["opening"],
                                   "line": _numbered(" ".join(g["sans"][:m["ply"]])), "fen": m["fen_before"]})
                break
    for d in deviations[:8]:
        d["fact"] = facts.add(f"Mit {COL['white' if d['is_white'] else 'black']}: erste Eröffnungsungenauigkeit "
                              f"{d['move_no']}{'.' if d['is_white'] else '…'}{d['san']} (besser {d['best']}, −{d['loss']*100:.0f} %) in {d['opening'] or 'Partie'}.",
                              "white" if d["is_white"] else "black", "eroeffnung")

    # ---------------- Zeit
    if ts.get("games"):
        ca = ts["clock_at"]
        facts.add(f"Bedenkzeit (aus {ts['games']} Partien mit Uhrzeiten, {', '.join(ts['time_controls'])}): Restzeit Ø "
                  + ", ".join(f"Zug {k}: {v['avg_min']} min" for k, v in ca.items() if v["n"]) + ".", "all", "zeit")
        facts.add(f"Zeitnot (< {config.TIME_TROUBLE_SEC // 60} min bzw. 10 % der Grundzeit, vor Zug 40) in {ts['trouble_games']} von {ts['games']} Partien; "
                  f"Fehlerquote in Zeitnot {ts['errors_in_trouble']} von {ts['moves_in_trouble']} Zügen, sonst "
                  f"{ts['errors_normal']} von {ts['moves_normal']}.", "all", "zeit")
    else:
        facts.add("Keine Uhrzeiten in den Partien – keine Aussage zur Zeiteinteilung möglich.", "all", "zeit")

    # ---------------- Gegnerfehler
    if oe["opp_errors"]:
        facts.add(f"Auf {oe['opp_errors']} gegnerische Fehler antwortete er {oe['punished_next_move']}× sofort präzise "
                  f"(Folgezug ohne Verlust).", "all", "taktik")

    # ---------------- Schluesselstellungen
    for i, k in enumerate(km, 1):
        k["id"] = f"K{i}"
        refut = ""
        if k.get("refutation"):
            ev = "Matt" if k["mate_after"] is not None else f"{k['cp_after'] / 100:+.2f}"
            refut = f"; Widerlegung {_numbered_from(k['fen'], [k['san']] + k['refutation'][:3], skip=1)} ({ev})"
        k["fact"] = facts.add(
            f"Schlüsselstellung {k['id']}: {k['white']} – {k['black']} ({_when(k['date'])}), {k['move_no']}"
            f"{'.' if k['is_white'] else '…'}{k['san']}? ({'Patzer' if k['level'] == 'blunder' else 'Fehler'}, "
            f"{k['phase']}{', partieentscheidend' if k.get('decisive') else ''}), besser {k['best_san']}; Erwartungswert {k['exp_before']:.2f} → {k['exp_after']:.2f}"
            + (f", Restzeit {k['clock_min']} min" if k["clock_min"] is not None else "") + refut + ".",
            "white" if k["is_white"] else "black", "schluessel")

    # ---------------- Mannschaft
    if team:
        bc = team["by_color"]
        facts.add(f"Mannschaftskämpfe: {team['played']} gespielte Partien ({team['forfeits']} kampflos); mit Weiß "
                  f"{bc['white']['points']}/{bc['white']['games']} ({bc['white']['score_pct']} %), mit Schwarz "
                  f"{bc['black']['points']}/{bc['black']['games']} ({bc['black']['score_pct']} %).", "all", "mannschaft")
        if team["seasons"]:
            s0 = team["seasons"][0]
            facts.add(f"Aktuelle Saison {s0['season']}: {s0['team']}, Brett {s0['boards']}, {s0['points']}/{s0['games']}"
                      + (f" gegen Ø DWZ {s0['avg_opp_dwz']}" if s0["avg_opp_dwz"] else "") + ".", "all", "mannschaft")
        rec = team["recent"]
        facts.add("Letzte Mannschaftspartien: " + ", ".join(
            f"{r['result']} ({'W' if r['color'] == 'white' else 'S'}) vs {r['opponent'].split(',')[0]} {r['opponent_dwz'] or ''}".strip()
            for r in rec[:8]) + ".", "all", "mannschaft")

    return {
        "generated": dt.datetime.now().isoformat(timespec="minutes"),
        "identity": ident.to_dict(), "sources": sources_log,
        "engine": {"name": engine_name, "depth": depth, "shallow_depth": min(config.ENGINE_SHALLOW_DEPTH, depth)},
        "data": {"games": len(games), "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
                 "older_than_stale": old, "by_year": by_year,
                 "with_clock": sum(1 for g in games if ann[g["id"]]["has_clock"])},
        "color_stats": cs, "time": ts, "key_moments": km, "opponent_errors": oe,
        "structures": ss, "repertoire": rep, "deviations": deviations[:8],
        "trees": trees, "team": team, "ratings": ratings, "rating_trend": rating_trend,
        "games": [_game_summary(g, ann[g["id"]]) for g in games],
        "facts": facts.items,
    }


def ann_positions(ann):
    """Baum braucht Bewertungen je Halbzug in Weiss-Sicht: aus den annotierten Zuegen rekonstruiert."""
    out = {}
    for gid, a in ann.items():
        mv = a["moves"]
        pos = [{"cp": mv[0]["cp_before"], "mate": None}] + [{"cp": m["cp_after"], "mate": m["mate_after"]} for m in mv]
        out[gid] = pos
    return out


def _numbered_from(fen: str, sans: list[str], skip: int = 0) -> str:
    """SAN-Folge ab einer Stellung mit Zugnummern; die ersten `skip` Zuege werden nur ausgefuehrt."""
    b = chess.Board(fen)
    out = []
    for i, s in enumerate(sans):
        if i >= skip:
            no = b.fullmove_number
            out.append(f"{no}.{s}" if b.turn == chess.WHITE else (f"{no}…{s}" if i == skip else s))
        try:
            b.push_san(s)
        except ValueError:
            break
    return " ".join(out)


def _numbered(path: str) -> str:
    toks = path.split()
    out = []
    for i, t in enumerate(toks):
        out.append(f"{i // 2 + 1}.{t}" if i % 2 == 0 else t)
    return " ".join(out)


def _game_summary(g, a) -> dict:
    return {
        "id": g["id"], "white": g["white"], "black": g["black"], "result": g["result"], "date": g["date"],
        "event": g["event"], "round": g["round"], "white_elo": g["white_elo"], "black_elo": g["black_elo"],
        "is_white": g["is_white"], "opponent": g["opponent"], "opponent_elo": g["opponent_elo"],
        "player_score": g["player_score"], "eco": a["eco"], "opening": a["opening"], "label": a["label"],
        "accuracy": a["accuracy"], "opp_accuracy": a["opp_accuracy"], "tipping": a["tipping"],
        "sources": g["sources"], "source_urls": g["source_urls"], "has_clock": a["has_clock"],
        "plies": a["plies"],
    }


def write_brief(dossier: dict, path, mine: dict | None = None) -> None:
    """Kompakter Schreib-Brief fuer das Sprachmodell (Skill-Schritt 'Matchplan schreiben')."""
    d = dossier
    idt = d["identity"]
    L = [f"# Dossier {idt['display']}", ""]
    L.append(f"FIDE {idt.get('fide_id')} · Elo {idt.get('elo', {}).get('standard')} · DWZ {idt.get('dsb', {}).get('dwz')} · "
             f"Verein {idt.get('dsb', {}).get('club')} · Jg. {idt.get('birth_year')}")
    span = f"{d['data']['first']} – {d['data']['last']}" if d["data"]["first"] else "ohne Datum"
    L.append(f"Datenbasis: {d['data']['games']} Partien mit Zügen ({span}), "
             f"davon {d['data']['with_clock']} mit Uhrzeiten; Engine {d['engine']['name']} Tiefe {d['engine'].get('shallow_depth', d['engine']['depth'])}, "
             f"verdächtige Züge Tiefe {d['engine']['depth']}.")
    L += ["", "## Perspektive (verbindlich)",
          "- `as_white` = ICH habe Weiß → der Gegner hat Schwarz → nur Facts mit scope `black` oder `all` zitieren.",
          "- `as_black` = ICH habe Schwarz → der Gegner hat Weiß → nur Facts mit scope `white` oder `all` zitieren.", ""]
    L.append("## Facts (zitierbar per ID)")
    for f in d["facts"]:
        L.append(f"- **{f['id']}** [{f['scope']}/{f['topic']}] {f['text']}")
    prof = d.get("profile") or {}
    if prof:
        t = prof["type"]
        L += ["", "## Spielerprofil (Belege P…, farbunabhängig)",
              f"Berechneter Typ: **{t['name']}**" + (f" (≈ {t['hansen']})" if t.get("hansen") else "")
              + (" – unsicher" if t.get("unsure") else "") + ". Schreibe dazu `profile_summary` (Typ-Satz + Hebel-Satz, "
              "je 1 Satz, nur P…/F…-Belege). Vorliebe (Partie-Charakter) und Können (Teil-Elo scharf/ruhig) nicht vermischen; "
              "Teil-Elo ist eine Schätzung mit Spanne, nie als exakte Zahl verkaufen."]
        for f in prof.get("facts", []):
            L.append(f"- **{f['id']}** [{f['topic']}] {f['text']}")
    if mine:
        L += ["", "## Abgleich mit dir (Belege M…, aus me.json – Annahmen des Nutzers, nicht gemessen)",
              f"Zielkorridor: **{mine['label']}** (Stufe {mine['target']}/5). Moderat einarbeiten: höchstens "
              f"{config.ME_MAX_PLAN_STEPS} Plan-Schritte je Farbe stützen sich auf M…; der Plan bleibt ein Plan gegen IHN. "
              "Die Eröffnungskarte, die das Repertoire des Nutzers trifft, zuerst nennen."]
        for f in mine["facts"]:
            L.append(f"- **{f['id']}** [{f['scope']}/{f['topic']}] {f['text']}")
    L += ["", "## Eröffnungsbäume (Gegner-Sicht, Score = seine Punkte)"]
    for col in ("white", "black"):
        L.append(f"### Gegner mit {COL[col]}")
        nodes = d["trees"][col]["nodes"]
        def rec(path, depth):
            if path not in nodes:  # keine Partien mit dieser Farbe
                return
            nd = nodes[path]
            for c in nd["children"]:
                cn = nodes[c["path"]]
                ev = f"{cn['eval'] / 100:+.2f}" if cn["eval"] is not None else "?"
                L.append("  " * depth + f"- {_numbered(c['path']).split()[-1] if depth else _numbered(c['path'])} "
                         f"({cn['n']}×, {_n(cn['score_pct'], ' %')}, Eval {ev}{', ' + cn['name'] if cn['name'] and cn['name'] != nd['name'] else ''})")
                if depth < 13:
                    rec(c["path"], depth + 1)
        rec("", 0)
    L += ["", "## Schlüsselstellungen (je Partie höchstens 2; entscheidend = Erwartungswert kam danach nicht mehr zurück)"]
    for k in d["key_moments"]:
        L.append(f"- **{k['id']}** {k['white']} – {k['black']} {k['date'] or 'ohne Datum'}: Zug {k['move_no']} {k['san']} "
                 f"({k['level']}, {k['phase']}{', entscheidend' if k.get('decisive') else ''}), besser {k['best_san']} (PV {' '.join(k['pv'])}); "
                 f"exp {k['exp_before']:.2f}→{k['exp_after']:.2f}; FEN `{k['fen']}`")
    L += ["", "## Erste Eröffnungsungenauigkeiten"]
    for dv in d["deviations"]:
        L.append(f"- {dv['fact']}: {dv['line']} (besser {dv['best']}) – {dv['opening']}")
    if d.get("team"):
        L += ["", "## Mannschaftskämpfe (letzte)"]
        for r in d["team"]["recent"]:
            L.append(f"- {r['season']} R{r['round']} Brett {r['board']} {COL[r['color']]} vs {r['opponent']} "
                     f"({r['opponent_dwz']}, {r['opponent_team']}): {r['result']}")
    onl = d.get("online") or {}
    acc = (onl.get("accounts") or {})
    L += ["", "## Online-Accounts"]
    for c in acc.get("candidates", [])[:5]:
        L.append(f"- {c['platform']} **{c['username']}** – {round(c['confidence'] * 100)} % – " + "; ".join(c.get("reasons", [])))
    if not onl.get("active") and acc.get("ambiguous"):
        L.append(f"- Mehrdeutig: {len(acc['ambiguous'])} Kandidaten über 50 % ohne klaren Abstand, keiner übernommen. "
                 "Keine Online-Felder verwenden; der Nutzer kann einen in accounts.json bestätigen.")
    elif not onl.get("active"):
        L.append("- Kein Account mit Konfidenz >= 50 %: keine Online-Felder (`online`) in matchplan.json verwenden.")
    else:
        L += ["", "### Online-Regeln",
              "- Online-Aussagen stehen NUR in den Feldern `online` (Eröffnungskarte, Plan-Schritt, Vermeiden, Ziel) und zitieren NUR O…-Belege.",
              "- Turnier-Felder zitieren nie O…-Belege. Online-Partien sind meist Blitz/Schnell: Fehlerquoten/Zeit nicht übertragen.",
              "- Perspektive gilt auch online: `as_white.*.online` nur O-Belege mit scope black/all, `as_black.*.online` nur white/all.",
              "- Besonders wertvoll: Linien, die er online oft spielt, im Turnier aber (noch) nicht (Überraschungsgefahr), "
              "und Linien in beiden Welten (sicherste Prognose).", "", "### Online-Belege"]
        for f in onl.get("facts", []):
            L.append(f"- **{f['id']}** [{f['scope']}/{f['topic']}] {f['text']}")
        L += ["", "### Abgleich Turnier/Online (bis Zug 3)"]
        for r in onl.get("comparison", [])[:30]:
            L.append(f"- {r['color']} {r['kind']}: {_numbered(r['path'])} – Turnier {r['otb']}×, online {r['online']}× ({r['online_score']} %)")
        if onl.get("course_search"):
            L += ["", "### Chessable-Kurse zu seinen Eröffnungsfamilien (öffentliche Metadaten)"]
            for c in onl["course_search"]:
                L.append(f"- [{c['query']}] {c['name']} – {c['author']} ({c['published']}, {c['color']}) {c['url']}")
    path.write_text("\n".join(L), encoding="utf-8")
