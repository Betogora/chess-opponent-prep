"""Report-HTML (eine Datei, offline) aus dossier.json + briefing.json + viewer.json."""
from __future__ import annotations

import datetime as dt
import json
from html import escape
from pathlib import Path

import chess
import chess.svg

from .. import config
from ..util import read_json
from . import charts

A = config.ASSETS_DIR
COL = {"white": "Weiß", "black": "Schwarz"}
PLAT = {"lichess": "Lichess", "chesscom": "Chess.com"}
PH_COLOR = {"Eröffnung": "var(--swim)", "Mittelspiel": "var(--bike)", "Abwicklung": "var(--run)", "Endspiel": "var(--run)",
            "Zeit": "var(--strength)", "Praxis": "var(--strength)", "Psychologie": "var(--strength)"}

ICON = {
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "ban": '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "chev": '<path d="m6 9 6 6 6-6"/>',
    "first": '<path d="m11 17-5-5 5-5"/><path d="m18 17-5-5 5-5"/>',
    "prev": '<path d="m15 18-6-6 6-6"/>',
    "next": '<path d="m9 18 6-6-6-6"/>',
    "last": '<path d="m6 17 5-5-5-5"/><path d="m13 17 5-5-5-5"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "activity": '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
    "zap": '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
}


def icon(name: str, cls: str = "tb-icon") -> str:
    return (f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICON[name]}</svg>')


def e(x) -> str:
    return escape("" if x is None else str(x))


def pct(v, digits=0):
    return "–" if v is None else f"{v:.{digits}f} %".replace(".", ",")


def num(v, digits=1):
    return "–" if v is None else f"{v:.{digits}f}".replace(".", ",")


# ---------------------------------------------------------------- Figuren-Sprite
def piece_sprite() -> str:
    out = ['<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>']
    for sym, svg in chess.svg.PIECES.items():
        cid = ("w" if sym.isupper() else "b") + sym.upper()
        out.append(f'<symbol id="p-{cid}" viewBox="0 0 45 45">{svg}</symbol>')
    out.append("</defs></svg>")
    return "".join(out)


# ---------------------------------------------------------------- Helfer
def ev_buttons(ids) -> str:
    if not ids:
        return ""
    return '<div class="cb-ev">' + "".join(f'<button type="button" data-f="{e(i)}">{e(i)}</button>' for i in ids) + "</div>"


def line_to_fen(line: str) -> tuple[str, str | None]:
    b = chess.Board()
    last = None
    for tok in line.replace("…", " ").split():
        tok = tok.split(".")[-1] if "." in tok else tok
        if not tok or tok in ("...",):
            continue
        try:
            mv = b.parse_san(tok)
        except ValueError:
            break
        b.push(mv)
        last = mv.uci()
    return b.fen(), last


def wdl_bar(w, d, l) -> str:
    n = (w + d + l) or 1
    return (f'<div class="cb-wdl"><div class="tb-bar tb-bar--stack">'
            f'<i style="--w:{100 * w / n:.1f}%;--c:var(--success)"></i>'
            f'<i style="--w:{100 * d / n:.1f}%;--c:var(--border-strong)"></i>'
            f'<i style="--w:{100 * l / n:.1f}%;--c:var(--destructive)"></i></div>'
            f'<div class="cb-wdl__legend"><span>{w} S</span><span>{d} R</span><span>{l} N</span></div></div>')


def stat(label, value, dot=None) -> str:
    """Kachel mit zwei Zeilen: Bezeichnung (mit Einheit) und groß der Wert."""
    d = f'<span class="tb-dot" style="--c:{dot}"></span>' if dot else ""
    return (f'<div class="tb-stat"><div class="tb-stat__label">{d}{e(label)}</div>'
            f'<div class="tb-stat__value">{value}</div></div>')


def fmt_eval(cp, mate=None) -> str:
    """Engine-Bewertung aus Weiß-Sicht: +0.28, -1.30, #3."""
    if mate is not None:
        return f"#{mate}" if mate else "Matt"
    return "–" if cp is None else f"{cp / 100:+.2f}".replace("-", "−")


def eval_chip(cp, mate=None, title="Engine-Bewertung aus Sicht von Weiß") -> str:
    """Engine-Bewertung als Chip (tb-chip): Icon + Zahl, ohne Beschriftung."""
    if cp is None and mate is None:
        return ""
    return (f'<span class="tb-chip cb-eval" title="{e(title)}">{icon("activity")}'
            f'<span class="cb-eval__value">{fmt_eval(cp, mate)}</span></span>')


def section(sid, title, body, right="") -> str:
    return (f'<section class="cb-section" id="{sid}"><header><div><h2>{e(title)}</h2></div>{right}</header>'
            f"{body}</section>")


def seg(group, items, active) -> str:
    btns = "".join(f'<button class="tb-seg__item" type="button" role="tab" data-value="{v}" '
                   f'aria-selected="{"true" if v == active else "false"}">{e(lbl)}</button>' for v, lbl in items)
    return f'<div class="tb-seg" role="tablist" data-seg="{group}">{btns}</div>'


# ---------------------------------------------------------------- Abschnitte
# Flaggen als SVG (Emoji-Flaggen zeigt Windows nur als Buchstaben). Streifen: (Richtung, Farben)
FLAGS = {
    "GER": ("h", "#000000", "#dd0000", "#ffce00"), "AUT": ("h", "#ed2939", "#ffffff", "#ed2939"),
    "NED": ("h", "#ae1c28", "#ffffff", "#21468b"), "FRA": ("v", "#0055a4", "#ffffff", "#ef4135"),
    "ITA": ("v", "#009246", "#ffffff", "#ce2b37"), "BEL": ("v", "#000000", "#fdda24", "#ef3340"),
    "POL": ("h", "#ffffff", "#dc143c"), "UKR": ("h", "#0057b7", "#ffd700"), "RUS": ("h", "#ffffff", "#0039a6", "#d52b1e"),
    "HUN": ("h", "#ce2939", "#ffffff", "#477050"), "LUX": ("h", "#ed2939", "#ffffff", "#00a1de"),
    "IRL": ("v", "#169b62", "#ffffff", "#ff883e"), "EST": ("h", "#0072ce", "#000000", "#ffffff"),
    "LTU": ("h", "#fdb913", "#006a44", "#c1272d"), "ARM": ("h", "#d90012", "#0033a0", "#f2a800"),
    "ROU": ("v", "#002b7f", "#fcd116", "#ce1126"), "BUL": ("h", "#ffffff", "#00966e", "#d62612"),
}


def flag(fed: str) -> str:
    f = FLAGS.get((fed or "").upper())
    if not f:
        return e(fed)
    d, *cols = f
    n = len(cols)
    rects = "".join((f'<rect y="{i * 12 / n:.2f}" width="18" height="{12 / n + .05:.2f}" fill="{c}"/>' if d == "h" else
                     f'<rect x="{i * 18 / n:.2f}" width="{18 / n + .05:.2f}" height="12" fill="{c}"/>') for i, c in enumerate(cols))
    return (f'<svg class="cb-flag" viewBox="0 0 18 12" role="img" aria-label="{e(fed)}"><title>{e(fed)}</title>{rects}</svg>')


def _profile_link(d) -> str:
    """Link „Lichess“/„Chess.com“ ins Spielerprofil: übernommener Online-Account, sonst Lichess-FIDE-Seite."""
    onl = d.get("online") or {}
    acc = (onl.get("accounts") or {}).get("accepted") or [] if onl.get("active") else []
    if acc:
        return " · ".join(f'<a href="{e(a["profile"]["url"])}">{PLAT[a["platform"]]}</a>' for a in acc)
    fid = d["identity"].get("fide_id")
    if fid and any(s["source"] == "lichess" and s.get("games") for s in d["sources"]):
        return f'<a href="https://lichess.org/fide/{fid}">Lichess</a>'
    return ""


def head(d, b) -> str:
    idt = d["identity"]
    elo = idt.get("elo", {})
    dsb = idt.get("dsb", {})
    data = d["data"]
    chips = []
    if idt.get("title"):
        chips.append(f'<span class="tb-badge">{e(idt["title"])}</span>')
    if dsb.get("club"):
        chips.append(f'<span class="tb-badge tb-badge--secondary">{e(dsb["club"])}</span>')
    if idt.get("birth_year"):
        chips.append(f'<span class="tb-badge tb-badge--secondary">Jg. {idt["birth_year"]}</span>')
    if idt.get("federation"):
        chips.append(f'<span class="tb-badge tb-badge--secondary cb-fed">{flag(idt["federation"])}</span>')
    if data["older_than_stale"] and data["games"] and data["older_than_stale"] / data["games"] > 0.5:
        chips.append(f'<span class="tb-badge tb-badge--warning">{data["older_than_stale"]} von {data["games"]} Partien älter als {config.STALE_YEARS} Jahre</span>')
    if data["games"] < config.THIN_GAMES:
        chips.append(f'<span class="tb-badge tb-badge--warning">dünne Datenbasis: {data["games"]} Partien</span>')
    mode = d.get("mode") or {}
    if mode.get("badge"):
        chips.insert(0, f'<span class="tb-badge cb-badge--mode">{e(mode["badge"])}</span>')
    # caveats aus briefing.json werden nicht mehr angezeigt: die Datenlage steht in den Plaketten oben und in "watch"
    # Kacheln oben rechts: nur Bezeichnung und Zahl
    ratings = []
    if elo.get("standard"):
        ratings.append(stat("Elo", e(elo["standard"])))
    if dsb.get("dwz"):
        ratings.append(stat("DWZ", e(dsb["dwz"])))
    y1, y2 = (data["first"] or "")[:4], (data["last"] or "")[:4]
    years = y1 if y1 == y2 else f"{y1}–{y2}"
    fide = f'<a href="https://ratings.fide.com/profile/{idt["fide_id"]}">FIDE</a>' if idt.get("fide_id") else ""
    cb = f'<a href="{e(idt["chessbase_url"])}">ChessBase</a>' if idt.get("chessbase_url") else ""
    stand = dt.date.fromisoformat(d["generated"][:10]).strftime("%d.%m.%Y")
    basis = " · ".join(x for x in [f"{data['games']} Partien", e(years), f"Stand {stand}", fide, cb, _profile_link(d)] if x)
    headline = f'<p class="cb-headline">{e(b["headline"])}</p>' if b and b.get("headline") else ""
    onl = d.get("online") or {}
    panel = ""
    if onl.get("active"):
        acc = onl["accounts"]["accepted"]
        for a in acc:
            chips.insert(0, f'<button type="button" class="tb-badge cb-onlinebadge" data-acct-toggle aria-expanded="false" '
                            f'aria-controls="cb-acct">{icon("globe")}{PLAT[a["platform"]]} „{e(a["username"])}“ · '
                            f'{round(a["confidence"] * 100)} %{icon("chev", "tb-chevron")}</button>')
        confirmed = all(str((a.get("override") or {}).get("status", "")).lower().startswith("best") for a in acc)
        links = " · ".join(f'<a href="{e(a["profile"]["url"])}">Profil {PLAT[a["platform"]]} „{e(a["username"])}“ öffnen</a>' for a in acc)
        reasons = "".join(f"<li>{e(r)}</li>" for a in acc for r in
                          ([f"manuell bestätigt: {a['override'].get('note', '')}"] if a.get("override") else []) + a["reasons"])
        panel = (f'<div class="cb-acct" id="cb-acct" hidden><div class="cb-acct__link">{links}</div>'
                 f'<h3>Warum dieser Account <span class="tb-meta">· {"manuell bestätigt" if confirmed else "vermutet, nicht bestätigt"}</span></h3>'
                 f'<ul>{reasons}</ul></div>')
    return f"""
<header class="cb-head">
  <div class="cb-head__top">
    <h1>{e(idt['display'])}</h1>
    <div class="cb-ratings">{''.join(ratings)}</div>
  </div>
  {headline}
  <div class="cb-chips">{''.join(chips)}</div>
  {panel}
  <div class="cb-sources">{basis}</div>
</header>"""


def nav(items) -> str:
    toggle = (f'<button class="tb-btn tb-btn--ghost tb-btn--icon tb-btn--sm cb-theme" type="button" data-theme-toggle '
              f'aria-label="Hell/Dunkel umschalten" title="Hell/Dunkel">{icon("moon", "tb-icon cb-ic-moon")}{icon("sun", "tb-icon cb-ic-sun")}</button>')
    return ('<nav class="cb-nav" aria-label="Abschnitte"><div class="cb-nav__row"><div class="cb-nav__inner">' + "".join(
        f'<a href="#{i}">{e(t)}</a>' for i, t in items) + f"</div>{toggle}</div></nav>")


def keys_section(b) -> str:
    if not b or not b.get("summary"):
        return ""
    cards = "".join(
        f'<article class="cb-key"><span class="cb-key__n">{i}</span><h3>{e(s["title"])}</h3><p>{e(s["text"])}</p>{ev_buttons(s.get("evidence"))}</article>'
        for i, s in enumerate(b["summary"], 1))
    return section("kern", "Auf einen Blick", f'<div class="cb-keys">{cards}</div>')


POLES = {"charakter": ("ruhig", "scharf"), "koennen": ("stärker scharf", "stärker ruhig"),
         "ambition": ("remisfreudig", "kämpferisch"), "verwertung": ("lässt liegen", "verwertet"),
         "zaehigkeit": ("bricht ein", "zäh"), "uhr": ("schnell", "langsam"), "repertoire": ("eng", "breit")}


def _seg5(step: int | None, label: str) -> str:
    """Fünf Stufen als Segmentleiste; keine Stufe gefüllt = offen."""
    cells = "".join(f'<i class="{"is-on" if step is not None and k - 2 == step else ""}"></i>' for k in range(5))
    return f'<div class="cb-seg5" role="img" aria-label="{e(label)}" title="{e(label)}">{cells}</div>'


def _scale(ax: dict) -> str:
    """Eine Achse: Titel, Segmentleiste, Pole. Zahlen, Fallzahl und Beleg stehen in brief.md."""
    left, right = POLES.get(ax["key"], (ax["labels"][0], ax["labels"][4]))
    return (f'<div class="cb-scale"><div class="cb-scale__title">{e(ax["title"])}</div>{_seg5(ax.get("step"), ax["label"])}'
            f'<div class="cb-scale__poles"><span>{e(left)}</span><span>{e(right)}</span></div></div>')


def _teil_chip(name: str, t: dict, weakest: bool = False) -> str:
    v = "offen" if t.get("elo") is None else f'~{t["elo"]}'
    return (f'<div class="cb-teil{" cb-teil--weak" if weakest else ""}"><div class="cb-teil__label">{e(name)}</div>'
            f'<div class="cb-teil__value">{v}</div></div>')


QUADRANTS = [  # (x-Seite, y-Seite, Vorliebe, Koennen, Hansen)
    (-1, 1, "Stratege", "rechenstark", "Pragmatiker"), (1, 1, "Angreifer", "rechenstark", "Aktivist"),
    (-1, -1, "Stratege", "rechenschwach", "Reflektor/Theoretiker"), (1, -1, "Angreifer", "rechenschwach", ""),
]


def style_map(prof: dict, who: str) -> str:
    """Stil-Karte: x = Vorliebe (mag ruhig .. mag scharf), y = Können (Teil-Elo scharf - ruhig).
    Spieler als Punkt mit 1- und 2-Sigma-Wolke; Mittelkreuz = Allrounder-Zone (unterhalb der Schwellen)."""
    m = prof.get("map")
    if not m:
        return ""
    W, H, L, R, T, B = 440, 360, 30, 8, 8, 30
    w, h = W - L - R, H - T - B
    XR, YR = 1.0, 300.0                                       # Achsenbereich: ±1 Streuung, ±300 Elo

    def X(x):
        return L + (max(-XR, min(XR, x)) + XR) / (2 * XR) * w

    def Y(y):
        return T + (1 - (max(-YR, min(YR, y)) + YR) / (2 * YR)) * h
    xc, yc = m["x_cut"], m["y_cut"]
    t = prof["type"]
    name = t["name"]
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="cb-map-t"><title id="cb-map-t">Stil-Karte: {e(who)} '
         f'liegt bei Vorliebe {m["x"]:+.2f} (Streuungen gegenüber gleich Starken) und Können {m["y"]:+.0f} Elo '
         f'(scharf minus ruhig); Einordnung {e(name)}</title>',
         '<defs><clipPath id="cb-map-clip"><rect x="%d" y="%d" width="%d" height="%d" rx="10"/></clipPath></defs>' % (L, T, w, h),
         f'<rect class="map-bg" x="{L}" y="{T}" width="{w}" height="{h}" rx="10"/>',
         f'<g clip-path="url(#cb-map-clip)">',
         f'<rect class="map-zone" x="{X(-xc):.1f}" y="{T}" width="{X(xc) - X(-xc):.1f}" height="{h}"/>',
         f'<rect class="map-zone" x="{L}" y="{Y(yc):.1f}" width="{w}" height="{Y(-yc) - Y(yc):.1f}"/>']
    for v in (-200, 200):
        o.append(f'<line class="grid" x1="{L}" x2="{L + w}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>')
    for v in (-0.6, 0.6):
        o.append(f'<line class="grid" x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{T}" y2="{T + h}"/>')
    o.append(f'<line class="axis0" x1="{L}" x2="{L + w}" y1="{Y(0):.1f}" y2="{Y(0):.1f}"/>'
             f'<line class="axis0" x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{T}" y2="{T + h}"/>')
    # Wolke (2 sigma blass, 1 sigma deutlicher) und Punkt
    px, py = X(m["x"]), Y(m["y"])
    rx1, ry1 = m["sx"] / (2 * XR) * w, m["sy"] / (2 * YR) * h
    o.append(f'<ellipse class="map-cloud2" cx="{px:.1f}" cy="{py:.1f}" rx="{2 * rx1:.1f}" ry="{2 * ry1:.1f}"/>'
             f'<ellipse class="map-cloud1" cx="{px:.1f}" cy="{py:.1f}" rx="{rx1:.1f}" ry="{ry1:.1f}"/></g>')
    # Quadranten-Beschriftung (der eigene hervorgehoben); liegt der Punkt auf der Ecke, rückt sie an die Mittelzone
    for sx, sy, pref, comp, hansen in QUADRANTS:
        on = name == f"{pref}, {comp}"
        tx = L + 12 if sx < 0 else L + w - 12
        anchor = "start" if sx < 0 else "end"
        lines = 2
        ty = T + 20 if sy > 0 else T + h - 13 * (lines - 1) - 12
        box_x = (tx, tx + 120) if sx < 0 else (tx - 120, tx)
        if box_x[0] - 14 <= px <= box_x[1] + 14 and ty - 26 <= py <= ty + 13 * lines + 4:
            ty = Y(yc) - 13 * (lines - 1) - 10 if sy > 0 else Y(-yc) + 22
        sub = f'<tspan x="{tx}" dy="14">{e(comp)}</tspan>'
        o.append(f'<text class="map-q{" is-on" if on else ""}" x="{tx}" y="{ty}" text-anchor="{anchor}">{e(pref)}{sub}</text>')
    near = abs(px - X(0)) < 70 and abs(py - Y(0)) < 30
    ax_, ay_ = (X(0), Y(-yc) + 14) if near else (X(0), Y(0) + 4)
    o.append(f'<text class="map-all{" is-on" if name == "Allrounder" else ""}" x="{ax_:.1f}" y="{ay_:.1f}" text-anchor="middle">Allrounder</text>')
    lx = px + 10 if px < L + w - 80 else px - 10
    o.append(f'<g class="map-dot"><title>{e(who)}: Vorliebe {m["x"]:+.2f} ±{m["sx"]:.2f}, Können {m["y"]:+.0f} ±{m["sy"]:.0f} Elo'
             f'</title><circle cx="{px:.1f}" cy="{py:.1f}" r="12" class="map-hit"/><circle cx="{px:.1f}" cy="{py:.1f}" r="5.5"/></g>'
             f'<text class="map-who" x="{lx:.1f}" y="{py + 4:.1f}" text-anchor="{"start" if lx > px else "end"}">{e(who)}</text>')
    # Achsen-Pole außen
    o.append(f'<text class="tick" x="{L}" y="{H - 10}">← mag ruhig</text>'
             f'<text class="tick" x="{L + w}" y="{H - 10}" text-anchor="end">mag scharf →</text>'
             f'<text class="tick" transform="translate({L - 12} {T + h}) rotate(-90)">← stärker im Ruhigen</text>'
             f'<text class="tick" transform="translate({L - 12} {T}) rotate(-90)" text-anchor="end">stärker im Scharfen →</text>')
    o.append("</svg>")
    return f'<figure class="cb-map cb-chart">{"".join(o)}</figure>'


def profile_section(d, b, mine: dict | None) -> str:
    prof = d.get("profile")
    if not prof:
        return ""
    ax, te, t = prof["axes"], prof["teil"], prof["type"]
    ps = (b or {}).get("profile_summary") or {}
    hansen = f'<span class="cb-prof__hansen">≈ {e(t["hansen"])} (Hansen)</span>' if t.get("hansen") else ""
    lever = (f'<div class="cb-goal cb-prof__lever">{icon("target")}<span>{e(ps["lever"])}</span></div>'
             if ps.get("lever") else "")
    # Endspiel steht in der Zeile "je Phase"; hier nur die Stellungsarten des Mittelspiels
    teil = "".join(_teil_chip(lbl, te[k]) for k, lbl in (("scharf", "Scharf"), ("ruhig", "Ruhig")))
    ph = ax["phasen"]
    phases = "".join(_teil_chip(p, tt, ph.get("weakest") == p) for p, tt in ph["teil"].items())
    order = ("charakter", "koennen", "ambition", "verwertung", "zaehigkeit", "uhr", "repertoire")
    scales = "".join(_scale(ax[k]) for k in order if k in ax)
    corr = ""
    if mine:
        items = "".join(f"<li>{e(r)}</li>" for r in mine["reasons"] + mine["hints"])
        mids = [f["id"] for f in mine["facts"][:2]]
        corr = (f'<div class="cb-corr"><div class="cb-corr__head"><span class="cb-corr__k">Dein Zielkorridor</span>'
                f'<span class="cb-corr__v">{e(mine["label"])}</span></div>'
                f'<div class="cb-corr__bar">{_seg5(mine["target"] - 3, mine["label"])}'
                f'<div class="cb-scale__poles"><span>ruhig</span><span>scharf</span></div></div>'
                f'<ul class="cb-corr__list">{items}</ul>'
                f'<div class="cb-corr__foot">Aus deinen Angaben (Annahmen, nicht gemessen){ev_buttons(mids)}</div></div>')
    who = d["identity"].get("last") or d["identity"].get("display", "")
    body = f"""<div class="cb-prof">
  <div class="cb-prof__main">
    <div class="cb-prof__name"><span>{e(t["name"])}</span>{hansen}</div>
    {lever}
    <div class="cb-prof__k">Teil-Elo je Stellungsart</div><div class="cb-teils">{teil}</div>
    <div class="cb-prof__k">je Phase</div><div class="cb-teils">{phases}</div>
  </div>
  {style_map(prof, who)}
  <div class="cb-scales">{scales}</div>
  {corr}
</div>"""
    return section("profil", "Spielerprofil", body)


def _online_tag(d) -> str:
    acc = ((d.get("online") or {}).get("accounts") or {}).get("accepted") or []
    a = acc[0] if acc else {}
    return (f'<span class="cb-ontag">{icon("globe")}Online · {e(a.get("username", ""))} · '
            f'{round((a.get("confidence") or 0) * 100)} %</span>')


def _line_eval(o: dict, fen: str, checks: dict, d: dict):
    """Engine-Wert der Zielstellung: zitierte Engine-Prüfung (E…) mit gleicher Stellung, sonst Eröffnungsbaum."""
    for ev in o.get("evidence") or []:
        c = checks.get(ev)
        if c and c.get("candidates") and c.get("fen", "").split(" ")[:4] == fen.split(" ")[:4]:
            return c["candidates"][0].get("eval"), c["candidates"][0].get("mate")
    for tr in ((d.get("trees") or {}), ((d.get("online") or {}).get("trees") or {})):
        for t in tr.values():
            for nd in t["nodes"].values():
                if nd.get("fen", "").split(" ")[:4] == fen.split(" ")[:4] and nd.get("eval") is not None:
                    return nd["eval"], None
    return None, None


def _opening_card(o: dict, me: str, online: bool, tag: str, checks: dict, d: dict, mine_hit: bool = False) -> str:
    fen, last = line_to_fen(o.get("line", ""))
    basis = {"partien": ("Turnierpartie", "tb-badge--success"), "theorie": ("Theorie", "tb-badge--secondary"),
             "beides": ("Turnierpartie", "tb-badge--success")}.get(o.get("basis", ""), ("", ""))
    if online:
        basis = ("Online-Partien", "cb-badge--online")
    bb = f'<span class="tb-badge {basis[1]}">{basis[0]}</span>' if basis[0] else ""
    if mine_hit:
        bb += '<span class="tb-badge cb-badge--mine">trifft dein Repertoire</span>'
    cp, mate = _line_eval(o, fen, checks, d) if o.get("line") else (None, None)
    board = (f'<div class="cb-boardwrap"><div class="cb-board" data-fen="{e(fen)}" data-last="{e(last or "")}" data-flip="{"1" if me == "black" else "0"}" '
             f'data-label="Zielstellung"></div>{eval_chip(cp, mate)}</div>') if o.get("line") else "<div></div>"
    line = f'<div class="cb-line">{e(o.get("line", ""))}</div>' if o.get("line") else ""
    return (f'<div class="cb-oprep{" cb-oprep--online" if online else ""}">{board}<div class="cb-oprep__body">'
            f'{tag if online else ""}<h4>{e(o.get("title", ""))} {bb}</h4>{line}<p>{e(o.get("idea", ""))}</p>'
            f'{ev_buttons(o.get("evidence"))}</div></div>')


def _repertoire_paths(mine: dict | None, side: str) -> list[str]:
    from ..profile import _san_path
    r = (mine or {}).get("repertoire") or {}
    keys = ("white",) if side == "as_white" else ("vs_e4", "vs_d4", "vs_other")
    return [_san_path(r[k]) for k in keys if r.get(k)]


def plan_panel(side: str, p: dict, d: dict, checks: dict, mine: dict | None = None) -> str:
    from ..profile import _san_path
    me = "white" if side == "as_white" else "black"
    tag = _online_tag(d)
    paths = _repertoire_paths(mine, side)

    def hit(o):
        lp = _san_path(o.get("line", ""))
        return bool(o.get("line")) and any(lp == x or lp.startswith(x + " ") for x in paths)
    out = []
    if p.get("goal"):
        out.append(f'<div class="cb-goal">{icon("target")}<span>{e(p["goal"])}</span></div>')
    if p.get("online_goal"):
        out.append(f'<div class="cb-goal cb-goal--online">{icon("globe")}<span>{e(p["online_goal"])}</span></div>')
    ops = []
    for o in sorted(p.get("opening", []), key=lambda o: not hit(o)):   # stabil: Treffer zuerst, sonst Reihenfolge des Plans
        pair = []
        if o.get("line"):
            pair.append(_opening_card(o, me, False, tag, checks, d, hit(o)))
        if o.get("online"):
            pair.append(_opening_card(o["online"], me, True, tag, checks, d))
        ops.append(f'<div class="cb-pair">{"".join(pair)}</div>')
    steps = []
    for st in p.get("plan", []):
        c = PH_COLOR.get(st.get("phase", ""), "var(--strength)")
        on = st.get("online")
        online = (f'<div class="cb-online">{tag}<div class="cb-step__do">{e(on.get("do"))}</div>'
                  f'<div class="cb-step__why">{e(on.get("why", ""))}</div>{ev_buttons(on.get("evidence"))}</div>') if on else ""
        steps.append(f"""<div class="cb-step"><div class="cb-step__phase"><span class="tb-dot" style="--c:{c}"></span>{e(st.get('phase'))}</div>
<div><div class="cb-step__do">{e(st.get('do'))}</div><div class="cb-step__why">{e(st.get('why'))}</div>{ev_buttons(st.get('evidence'))}{online}</div></div>""")
    if steps:
        out.append(f'<h3 class="cb-sub">Plan nach Phasen</h3><div class="cb-steps">{"".join(steps)}</div>')
    if ops:
        out.append(f'<h3 class="cb-sub">Eröffnung</h3><div class="cb-openings">{"".join(ops)}</div>')
    av = p.get("avoid", [])
    if av:
        items = []
        for a in av:
            on = a.get("online")
            online = (f'<div class="cb-online cb-online--inline">{tag}<div>{e(on.get("text"))}</div>{ev_buttons(on.get("evidence"))}</div>') if on else ""
            main = f'{e(a["text"])}{ev_buttons(a.get("evidence"))}' if a.get("text") else ""
            items.append(f'<li>{icon("ban")}<div>{main}{online}</div></li>')
        out.append(f'<h3 class="cb-sub">Vermeiden</h3><ul class="cb-avoid">{"".join(items)}</ul>')
    return "".join(out)


def plan_section(b, d, checks, mine: dict | None = None) -> str:
    if not b:
        return section("plan", "Matchplan", '<div class="tb-empty">Noch kein Matchplan (briefing.json fehlt). '
                       'Die Datenabschnitte unten sind vollständig.</div>')
    cs = d["color_stats"]
    sides = tuple((d.get("mode") or {}).get("sides") or ("as_white", "as_black"))
    default = sides[0] if len(sides) == 1 else (
        "as_white" if (cs["black"]["games"] or 0) >= (cs["white"]["games"] or 0) else "as_black")
    toggle = seg("plan", [("as_white", "Ich habe Weiß"), ("as_black", "Ich habe Schwarz")], default) if len(sides) > 1 else         f'<span class="tb-badge">{"Ich habe Weiß" if default == "as_white" else "Ich habe Schwarz"}</span>'
    panels = "".join(
        f'<div class="cb-plan cb-planpanel" data-panel-group="plan" data-panel="{side}"{"" if side == default else " hidden"}>'
        f'{plan_panel(side, b.get(side) or {}, d, checks, mine)}</div>' for side in sides)
    watch = ""
    if b.get("watch"):
        items = "".join(f'<li>{icon("alert")}<div>{e(w["text"])}{ev_buttons(w.get("evidence"))}</div></li>' for w in b["watch"])
        watch = f'<h3 class="cb-sub">Achtung</h3><ul class="cb-avoid cb-watch">{items}</ul>'
    return section("plan", "Matchplan", panels + watch, toggle)


def openings_section(d) -> str:
    cs = d["color_stats"]
    focus = (d.get("mode") or {}).get("opponent_color")
    start = focus or ("black" if cs["black"]["games"] >= cs["white"]["games"] else "white")
    has = [c for c in ("white", "black") if (d["trees"].get(c) or {}).get("nodes", {}).get("", {}).get("n")]
    toggle = seg("tree", [("white", "Er hat Weiß"), ("black", "Er hat Schwarz")], start) if len(has) > 1 else         f'<span class="tb-badge">Er hat {COL[start]}</span>'

    onl = d.get("online") or {}
    if onl.get("active"):
        toggle = f'<div class="cb-segs">{seg("src", [("otb", "Turnier"), ("online", "Online")], "otb")}{toggle}</div>'
    explorer = f"""<div class="cb-explorer" id="cb-explorer" data-start="{start}">
  <div class="cb-boardwrap cb-boardwrap--side"><div class="cb-board"></div><span class="tb-chip cb-eval" data-eval hidden title="Engine-Bewertung aus Sicht von Weiß">{icon("activity")}<span class="cb-eval__value"></span></span></div>
  <div class="cb-vside">
    <div class="cb-crumbs"></div>
    <div><div class="cb-opname"></div></div>
    <div class="cb-moves"></div>
    <div class="cb-vctl cb-tree-actions"><button class="tb-btn tb-btn--outline tb-btn--icon tb-btn--sm" data-t="first" type="button" aria-label="Ausgangsstellung" title="Ausgangsstellung">{icon('first')}</button>
    <button class="tb-btn tb-btn--outline tb-btn--icon tb-btn--sm" data-t="prev" type="button" aria-label="Zug zurück" title="Zug zurück (←)">{icon('prev')}</button>
    <button class="tb-btn tb-btn--outline tb-btn--icon tb-btn--sm" data-t="next" type="button" aria-label="Häufigste Fortsetzung" title="Häufigste Fortsetzung (→)">{icon('next')}</button>
    <button class="tb-btn tb-btn--outline tb-btn--icon tb-btn--sm" data-t="last" type="button" aria-label="Häufigste Linie bis zum Ende" title="Häufigste Linie bis zum Ende">{icon('last')}</button></div>
  </div>
</div>"""
    return section("eroeffnungen", "Eröffnungen", explorer, toggle)


def phases_section(d) -> str:
    cs = d["color_stats"]
    groups = ["Eröffnung", "Mittelspiel", "Endspiel"]
    ser = []
    for col in ("white", "black"):
        if not cs[col]["games"]:
            continue
        ph = cs[col]["phases"]
        ser.append({"name": f"mit {COL[col]}", "color": f"var(--c-{col})",
                    "values": [ph[g]["errors_per_100"] for g in groups],
                    "thin": [ph[g]["live"] < 40 for g in groups]})
    notes = [" · ".join(f"{COL[c][0]} {cs[c]['phases'][g]['live']}" for c in ("white", "black") if cs[c]["games"]) for g in groups]
    ymax = max([v for s in ser for v in s["values"] if v is not None] + [5])
    chart = charts.grouped_bars(groups, ser, y_max=ymax * 1.15, unit="je 100", fmt=lambda v: f"{v:.0f}", notes=notes)
    legend = "".join(f'<span><span class="tb-dot" style="--c:var(--c-{c})"></span>Er hat {COL[c]}</span>' for c in ("white", "black") if cs[c]["games"])
    fig = (f'<figure class="cb-figure"><h3>Fehler und Patzer je 100 bewertbare Züge</h3><div class="tb-legend">{legend}</div>'
           f'<div class="cb-chart">{chart}</div></figure>')
    cols = []
    for col in ("white", "black"):
        c = cs[col]
        if not c["games"]:
            continue
        cv, rs = c["conversion"], c["resilience"]
        tiles = "".join([
            stat("Performance", e(c["performance"] or "–")),
            stat("Genauigkeit", pct(c["accuracy"], 1)),
            stat("Kipp-Punkte je Partie", num(c["tipping_per_game"], 2)),
            stat("Erwartung nach Eröffnung", num(c["exp_after_opening"], 2) if c["exp_after_opening"] is not None else "–"),
            stat("Gewinnstellung verwertet", f"{cv['won']}/{cv['games']}" if cv["games"] else "–"),
            stat("Verluststellung gehalten", f"{rs['saved']}/{rs['games']}" if rs["games"] else "–"),
        ])
        cols.append(f'<div class="cb-figure"><div class="cb-colhead"><span class="cb-colorpip cb-colorpip--{col[0]}"></span>Er hat {COL[col]}</div>'
                    f'{wdl_bar(c["w"], c["d"], c["l"])}<div class="cb-tiles">{tiles}</div></div>')
    return section("phasen", "Spielphasen & Fehlerbild", f'<div class="cb-twocol">{"".join(cols)}</div>{fig}{_online_quality(d)}')


def _online_quality(d) -> str:
    """Online-Fehlerbild aus der Lichess-Analyse, getrennt und gestrichelt (Schnell/Blitz, nicht mit Turnier mischen)."""
    q = (d.get("online") or {}).get("quality")
    if not q:
        return ""
    cols = []
    for col in ("white", "black"):
        c = q["color_stats"][col]
        if not c["games"]:
            continue
        per100 = round(100 * (c["mistakes"] + c["blunders"]) / c["live_moves"]) if c["live_moves"] else None
        ph = [(p, v["errors_per_100"]) for p, v in c["phases"].items() if v["errors_per_100"] is not None and v["live"] >= 15]
        worst = max(ph, key=lambda x: x[1]) if ph else None
        tiles = "".join([
            stat("Score", pct(c["score_pct"])),
            stat("Genauigkeit", pct(c["accuracy"], 1)),
            stat("Fehler je 100 Züge", "–" if per100 is None else str(per100)),
            stat("Kipp-Punkte je Partie", num(c["tipping_per_game"], 2)),
            stat("Schwächste Phase", e(worst[0]) if worst else "–"),
        ])
        cols.append(f'<div><div class="cb-colhead"><span class="cb-colorpip cb-colorpip--{col[0]}"></span>Er hat {COL[col]}</div>'
                    f'<div class="cb-tiles">{tiles}</div></div>')
    return (f'<div class="cb-online cb-onlineq">{_online_tag(d)}<h3 class="cb-sub">Online-Fehlerbild '
            f'</h3>'
            f'<div class="cb-twocol">{"".join(cols)}</div></div>')


def moments_section(d, b) -> str:
    km = d["key_moments"]
    if not km:
        return ""
    notes = (b or {}).get("moments", {})
    cards = []
    for k in km:
        lvl = "Patzer" if k["level"] == "blunder" else "Fehler"
        badge = f"cb-lvlbadge cb-g-{k['level']}"
        dec = '<span class="tb-badge tb-badge--destructive">partieentscheidend</span>' if k.get("decisive") else ""
        mv = f"{k['move_no']}{'.' if k['is_white'] else '…'}"
        take = notes.get(k["id"])
        clk = f" · Uhr: {k['clock_min']:.0f} min" if k.get("clock_min") is not None else ""
        cards.append(f"""<article class="cb-moment" id="{k['id']}">
<div class="cb-moment__head"><span class="cb-moment__title">{k['id']} · {e(k['opponent'].split(',')[0])} {e(k['date'][:4])}</span><span class="cb-moment__badges">{dec}<span class="tb-badge {badge}">{lvl}</span></span></div>
<div class="cb-boardwrap"><div class="cb-board" data-fen="{e(k['fen'])}" data-lvl="{e(k['level'])}" data-played="{e(k['uci'])}" data-best="{e(k['best_uci'] or '')}" data-flip="{'0' if k['is_white'] else '1'}" data-label="Stellung vor {mv}{e(k['san'])}"></div>{eval_chip(k.get('cp_after'), k.get('mate_after'), 'Engine-Bewertung nach dem Zug, Sicht von Weiß')}</div>
<dl class="cb-moment__moves"><dt>gespielt</dt><dd class="cb-g-{k['level']}-text">{mv}{e(k['san'])}{GLYPH[k['level']]}</dd>
<dt>besser</dt><dd style="color:var(--success)">{e(' '.join(k['pv'][:5]) or k['best_san'])}</dd></dl>
<div class="cb-exp" title="Erwartungswert für ihn vor und nach dem Zug"><span>{round(k['exp_before'] * 100)} %</span><div class="tb-bar cb-expbar"><i style="--w:{k['exp_before'] * 100:.0f}%;--c:var(--border-strong)"></i><i style="--w:{k['exp_after'] * 100:.0f}%;--c:var(--destructive)"></i></div><span>{round(k['exp_after'] * 100)} %</span></div>
<div class="cb-moment__meta">{e(k['phase'])} · {'mit Weiß' if k['is_white'] else 'mit Schwarz'}{clk} · <a href="#partien" data-open-game="{e(k['game'])}" data-ply="{k['ply'] - 1}">in der Partie</a></div>
{f'<p class="cb-moment__take">{e(take)}</p>' if take else ''}</article>""")
    return section("stellungen", "Schlüsselstellungen", f'<div class="cb-moments">{"".join(cards)}</div>')


def time_section(d, viewer) -> str:
    ts = d["time"]
    if not ts.get("games"):
        return section("zeit", "Bedenkzeit", '<div class="tb-empty">Keine Partien mit Uhrzeiten vorhanden.</div>')
    series, dots, mx, legend_items = [], [], 0, []
    palette = ["var(--brand-primary)", "var(--bike)", "var(--brand-accent)", "var(--success)", "var(--strength)", "var(--team-yellow)"]
    gi = 0
    for g in d["games"]:
        if not g["has_clock"]:
            continue
        mv = viewer[g["id"]]
        pts = [(i // 2 + 1, m["clk"] / 60) for i, m in enumerate(mv) if m["own"] and m["clk"] is not None]
        if not pts:
            continue
        mx = max(mx, max(p[1] for p in pts))
        color = palette[gi % len(palette)]
        gi += 1
        series.append({"name": g["opponent"].split(",")[0], "color": color, "points": pts, "thin": True})
        legend_items.append(f'<span><span class="tb-dot" style="--c:{color}"></span>{e(g["opponent"].split(",")[0])} {e(g["date"][:4])}</span>')
        for i, m in enumerate(mv):
            if m["own"] and m["clk"] is not None and m["lvl"] in ("mistake", "blunder"):
                dots.append({"x": i // 2 + 1, "y": m["clk"] / 60, "color": "var(--destructive)", "title": f"{m['san']} ({m['lvl']})"})
    max_move = max(p[0] for s in series for p in s["points"])
    xt = [(x, str(x)) for x in range(10, max_move + 1, 10)]
    chart = charts.line_chart(series, x_domain=(1, max_move), y_domain=(0, (mx // 15 + 1) * 15), x_ticks=xt,
                              y_ticks=[v for v in range(0, int((mx // 15 + 1) * 15) + 1, 15)], unit="min",
                              refs=[{"y": config.TIME_TROUBLE_SEC / 60, "label": "5 min"}, {"x": 40, "label": "Zug 40"}],
                              dots=dots, band=(0, config.TIME_TROUBLE_SEC / 60), label_end=False)
    ca = ts["clock_at"]
    tiles = "".join([
        stat("Partien mit Zeitnot vor Zug 40", f"{ts['trouble_games']}/{ts['games']}"),
        *[stat(f"Ø Restzeit Zug {k}", f"{num(v['avg_min'], 0)} min") for k, v in ca.items() if v["n"]],
        stat("Fehler in Zeitnot / Züge", f"{ts['errors_in_trouble']}/{ts['moves_in_trouble']}"),
    ])
    fig = (f'<figure class="cb-figure"><h3>Seine Restzeit je Zug</h3><div class="tb-legend">{"".join(legend_items)}<span><span class="tb-dot" style="--c:var(--destructive)"></span>eigener Fehler/Patzer</span></div><div class="cb-chart">{chart}</div>'
           f'</figure>')
    return section("zeit", "Bedenkzeit", f'<div class="cb-tiles">{tiles}</div>{fig}')


def form_section(d) -> str:
    parts = []
    hist = d.get("ratings") or []
    if hist:
        gd = [(g["date"], f"{g['white']} – {g['black']} {g['result']}") for g in d["games"] if g["date"]]
        rc = charts.rating_chart(hist, gd)
        if rc:
            legend = ('<div class="tb-legend"><span><span class="tb-dot" style="--c:var(--c-white)"></span>FIDE-Elo (Standard)</span>'
                      '<span><span class="tb-dot" style="--c:var(--c-black)"></span>analysierte Partien</span></div>')
            parts.append(f'<figure class="cb-figure"><h3>Elo-Verlauf</h3>{legend}<div class="cb-chart">{rc}</div></figure>')
    t = d.get("team") or {}
    if t:
        rec = t["recent"]
        chips = "".join(
            f'<span class="cb-res cb-res--{"w" if r["result"] in ("1", "+") else "l" if r["result"] in ("0", "-") else "d"}" '
            f'title="{e(r["season"])} R{r["round"]} Brett {r["board"]}: {e(r["opponent"])} ({r["opponent_dwz"] or "–"}, {e(r["opponent_team"])})">'
            f'{e(r["result"])}</span>' for r in reversed(rec))
        bc = t["by_color"]
        tiles = "".join([
            stat("Punkte mit Weiß", f"{num(bc['white']['points'], 1)}/{bc['white']['games']}", "var(--c-white)"),
            stat("Punkte mit Schwarz", f"{num(bc['black']['points'], 1)}/{bc['black']['games']}", "var(--c-black)"),
        ])
        rows = "".join(f'<tr><td>{e(s["season"])}</td><td>{e(s["team"])}</td><td>{e(s["division"].replace("-", " ").title())}</td>'
                       f'<td class="num">{e(s["boards"])}</td><td class="num">{num(s["points"], 1)}/{s["games"]}</td>'
                       f'<td class="num">{s["avg_opp_dwz"] or "–"}</td></tr>' for s in t["seasons"])
        recent_rows = "".join(
            f'<tr><td>{e(r["season"])} R{r["round"]}</td><td class="num">{r["board"] or ""}</td>'
            f'<td><span class="cb-colorpip cb-colorpip--{r["color"][0]}"></span></td><td>{e(r["opponent"])}<div class="tb-meta">{e(r["opponent_team"])}</div></td>'
            f'<td class="num">{r["opponent_dwz"] or "–"}</td><td class="num"><b>{e(r["result"])}</b></td></tr>' for r in rec)
        parts.append(f"""<div class="cb-figure"><h3>Mannschaftskämpfe</h3><div class="cb-form">{chips}</div>
<p class="cb-note">Letzte {len(rec)} Partien, älteste links. Ergebnisse vom Ligaserver; Züge sind dort nicht erfasst.</p>
<div class="cb-tiles">{tiles}</div></div>
<div class="cb-twocol"><div><h3 class="cb-sub">Saisons</h3><div class="tb-table-wrap"><table class="tb-table cb-table"><thead><tr><th>Saison</th><th>Team</th><th>Liga</th><th class="num">Brett</th><th class="num">Punkte</th><th class="num">Ø DWZ</th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div><h3 class="cb-sub">Zuletzt</h3><div class="tb-table-wrap"><table class="tb-table cb-table"><thead><tr><th>Runde</th><th class="num">Brett</th><th></th><th>Gegner</th><th class="num">DWZ</th><th class="num">Erg.</th></tr></thead><tbody>{recent_rows}</tbody></table></div></div></div>""")
    if not parts:
        return ""
    return section("form", "Form & Mannschaft", "".join(parts))


GLYPH = {"inaccuracy": "?!", "mistake": "?", "blunder": "??"}


def _err_counts(moves) -> str:
    out = []
    for lvl in ("inaccuracy", "mistake", "blunder"):
        n = sum(1 for m in moves if m["own"] and m["lvl"] == lvl)
        if n:
            out.append(f'<span class="cb-glyphcount cb-g-{lvl}" title="{n} × {LVL_DE[lvl]}"><i>{GLYPH[lvl]}</i>{n}</span>')
    return "".join(out) or '<span class="tb-meta">fehlerfrei</span>'


LVL_DE = {"inaccuracy": "Ungenauigkeit", "mistake": "Fehler", "blunder": "Patzer"}


def _analysed(moves) -> bool:
    return bool(moves) and moves[0].get("cp") is not None


def games_section(d, viewer) -> str:
    onl = d.get("online") or {}
    games = [dict(g, src="otb") for g in d["games"]]
    if onl.get("active"):
        games += [dict(g, src="online", eco="", opening=g.get("speed", "")) for g in onl["games"] if g["id"] in viewer]
    games = sorted(games, key=lambda g: g["date"], reverse=True)
    years = []
    for g in games:
        y = g["date"][:4] or "?"
        if y not in years:
            years.append(y)
    cards, opts = [], {}
    for g in games:
        sc = g["player_score"]
        res = "w" if sc == 1 else "l" if sc == 0 else "d" if sc == 0.5 else "?"
        lab = {"w": "Sieg", "l": "Niederlage", "d": "Remis", "?": "ohne Ergebnis"}[res]
        y = g["date"][:4] or "?"
        col = "w" if g["is_white"] else "b"
        srcbadge = f'<span class="cb-ontag cb-ontag--sm">{icon("globe")}{e(g.get("account", ""))}</span>' if g["src"] == "online" else ""
        cards.append(f"""<button class="cb-gcard{' cb-gcard--online' if g['src'] == 'online' else ''}" type="button" data-id="{g['id']}" data-year="{y}" data-col="{col}" data-src="{g['src']}" aria-pressed="false">
<span class="cb-gcard__top"><span><span class="cb-colorpip cb-colorpip--{col}"></span> {e(g['date'] or 'ohne Datum')}</span><span class="tb-badge {'tb-badge--success' if res == 'w' else 'tb-badge--destructive' if res == 'l' else 'tb-badge--secondary'}">{lab}</span></span>
<span class="cb-gcard__opp">{e(g['opponent'])}{f" ({g['opponent_elo']})" if g['opponent_elo'] else ''}</span>
<span class="cb-gcard__op">{e(g['eco'])} {e(g['opening'])}</span>
<span class="cb-gcard__err">{_err_counts(viewer.get(g['id'], [])) if _analysed(viewer.get(g['id'], [])) else srcbadge}</span></button>""")
        opts.setdefault(y, []).append(
            f'<option value="{g["id"]}" data-src="{g["src"]}">{"Online · " if g["src"] == "online" else ""}{e(g["date"])} · {"W" if g["is_white"] else "S"} · {e(g["opponent"])} · {e(g["result"])}</option>')
    select = "".join(f'<optgroup label="{y} ({len(o)})">{"".join(o)}</optgroup>' for y, o in opts.items())
    ychips = (f'<button class="tb-chip" type="button" data-year="all" aria-pressed="true">Alle <b>{len(games)}</b></button>'
              + "".join(f'<button class="tb-chip" type="button" data-year="{y}" aria-pressed="false">{y} <b>{len(opts[y])}</b></button>' for y in years))
    n_otb = sum(1 for g in games if g["src"] == "otb")
    srcseg = ((f'<div class="tb-seg" role="tablist" data-srcfilter>'
               f'<button class="tb-seg__item" type="button" data-src="otb" aria-selected="true">Turnier {n_otb}</button>'
               f'<button class="tb-seg__item" type="button" data-src="online" aria-selected="false">Online {len(games) - n_otb}</button></div>')
              if len(games) > n_otb else "")
    colseg = ('<div class="tb-seg" role="tablist" data-colfilter>'
              '<button class="tb-seg__item" type="button" data-col="all" aria-selected="true">Alle</button>'
              '<button class="tb-seg__item" type="button" data-col="w" aria-selected="false">Er mit Weiß</button>'
              '<button class="tb-seg__item" type="button" data-col="b" aria-selected="false">Er mit Schwarz</button></div>')
    legend = "".join(f'<span><span class="cb-glyph cb-g-{l}">{GLYPH[l]}</span>{LVL_DE[l]}</span>' for l in ("inaccuracy", "mistake", "blunder"))
    viewer_html = f"""<div id="cb-viewer" class="cb-vside">
<div class="cb-gpicker">
  <div class="cb-gfilter">{srcseg}<div class="cb-chips cb-years">{ychips}</div>{colseg}
  <label class="cb-gselect"><span class="tb-sr-only">Partie wählen</span><select class="tb-select" data-gselect>{select}</select></label></div>
  <div class="cb-gamegrid">{''.join(cards)}</div>
  <p class="cb-note cb-gcount"></p>
</div>
<div class="cb-viewer">
  <div class="cb-vside"><div class="cb-boardwrap cb-boardwrap--side"><div class="cb-board"></div><span class="tb-chip cb-eval" data-eval hidden title="Engine-Bewertung aus Sicht von Weiß">{icon("activity")}<span class="cb-eval__value"></span></span></div>
  <div class="cb-vctl"><button class="tb-btn tb-btn--outline tb-btn--icon tb-btn--sm" data-v="first" type="button" aria-label="Anfang">{icon('first')}</button>
  <button class="tb-btn tb-btn--outline tb-btn--icon tb-btn--sm" data-v="prev" type="button" aria-label="Zurück">{icon('prev')}</button>
  <button class="tb-btn tb-btn--outline tb-btn--icon tb-btn--sm" data-v="next" type="button" aria-label="Weiter">{icon('next')}</button>
  <button class="tb-btn tb-btn--outline tb-btn--icon tb-btn--sm" data-v="last" type="button" aria-label="Ende">{icon('last')}</button>
  <button class="tb-btn tb-btn--secondary tb-btn--sm" data-v="err" type="button">{icon('zap')}Nächster Fehler</button></div></div>
  <div class="cb-vside"><div class="cb-vhead"></div><div class="cb-graph"></div>
  <div class="cb-lvl-legend">{legend}</div>
  <div class="cb-vinfo"></div><div class="cb-mlist"></div></div>
</div></div>"""
    return section("partien", "Partien", viewer_html)


def facts_section(d) -> str:
    cs = d["color_stats"]
    focus = (d.get("mode") or {}).get("opponent_color")      # briefing-medium: nur seine Farbe in dieser Partie
    cols = (focus,) if focus else ("white", "black")

    def row(label, f, thin_key=None):
        tds = []
        for c in (cs[k] for k in cols):
            v = f(c) if c["games"] else "–"
            tds.append(f'<td class="num">{v}</td>')
        return f"<tr><td>{e(label)}</td>{''.join(tds)}</tr>"

    def errors_per_100(c):
        return round(100 * (c["mistakes"] + c["blunders"]) / c["live_moves"]) if c["live_moves"] else None

    def weakest_phase(c):
        ph = [(p, v["errors_per_100"]) for p, v in c["phases"].items() if v["errors_per_100"] is not None and v["live"] >= 15]
        if not ph:
            return "–"
        p, v = max(ph, key=lambda x: x[1])
        return f"{p} ({v:.0f})"

    # Kennzahlen je Farbe fuer die Matchplanung: Staerke, Fehlerneigung, wo die Fehler liegen
    rows = [
        row("Partien (S / R / N)", lambda c: f"{c['games']} ({c['w']} / {c['d']} / {c['l']})"),
        row("Performance", lambda c: e(c["performance"] or "–")),
        row("Genauigkeit", lambda c: pct(c["accuracy"], 1)),
        row("Fehler + Patzer je 100 bewertbare Züge", lambda c: errors_per_100(c) if errors_per_100(c) is not None else "–"),
        row("Kipp-Punkte je Partie", lambda c: num(c["tipping_per_game"], 2)),
        row("Fehleranfälligste Phase (je 100)", weakest_phase),
        row("Erwartungswert nach der Eröffnung", lambda c: num(c["exp_after_opening"], 2) if c["exp_after_opening"] is not None else "–"),
    ]
    heads = "".join(f'<th class="num">Er hat {COL[k]}</th>' for k in cols)
    table = (f'<div class="tb-table-wrap"><table class="tb-table cb-table"><thead><tr><th>Kennzahl</th>{heads}'
             f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    return section("kennzahlen", "Kennzahlen", table)


# ---------------------------------------------------------------- Zusammenbau
def _slim_trees(tr):
    if not tr:
        return None
    return {col: {"nodes": {k: {kk: v[kk] for kk in ("fen", "n", "score_pct", "eval", "eco", "name", "children", "uci", "online_n") if kk in v}
                            for k, v in t["nodes"].items()}} for col, t in tr.items()}


def payload_for(pdir: Path, d: dict, viewer: dict, with_me: bool = True) -> dict:
    """Daten fuer report.js: Belege, Baeume, Viewer, Endstellungen, Partienliste."""
    final_fen = {}
    for g in d["games"]:
        mv = viewer.get(g["id"], [])
        if mv:
            bb = chess.Board(mv[-1]["fen"])
            bb.push(chess.Move.from_uci(mv[-1]["uci"]))
            final_fen[g["id"]] = bb.fen()
    from ..pipeline import all_facts
    return {
        "facts": [{"id": f["id"], "text": f["text"]} for f in all_facts(pdir, with_me=with_me)],
        "trees": _slim_trees(d["trees"]), "viewer": viewer, "final_fen": final_fen,
        "games": [{k: g.get(k) for k in ("id", "white", "black", "result", "date", "event", "round", "is_white")} for g in d["games"]]
                 + [dict({k: g.get(k) for k in ("id", "white", "black", "result", "date", "is_white", "url")},
                         event=f"{PLAT.get(g.get('platform'), '')} {g.get('speed', '')} · {g.get('event') or ''}", round="", online=True)
                    for g in (d.get("online") or {}).get("games", []) if g["id"] in viewer],
        "trees_online": _slim_trees((d.get("online") or {}).get("trees")) if (d.get("online") or {}).get("active") else None,
        "player_short": d["identity"]["last"],
    }


def page(d: dict, b: dict | None, sections: list[tuple[str, str, str]], payload: dict, title: str, out: Path,
         product: str = "chess-opponent-research-deep") -> Path:
    """Eine offline lauffaehige HTML-Seite im gemeinsamen Design (alle Stufen)."""
    sections = [s for s in sections if s[2]]
    css = (A / "toolbox-ui.css").read_text(encoding="utf-8") + "\n" + (A / "report.css").read_text(encoding="utf-8")
    js = (A / "report.js").read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = f"""<!doctype html>
<html lang="de" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<style>{css}</style>
</head>
<body>
{piece_sprite()}
<main class="tb-page cb-page">
{head(d, b)}
{nav([(sid, t) for sid, t, _ in sections])}
{''.join(s for _, _, s in sections)}
<footer class="cb-foot">{e(product)} · erstellt {e(d['generated'].replace('T', ' '))} · Figuren: Colin M. L. Burnett (GPL/CC BY-SA) via python-chess · Eröffnungsnamen: lichess-org/chess-openings (CC0)</footer>
</main>
<script id="cb-data" type="application/json">{data}</script>
<script>{js}</script>
</body>
</html>"""
    tmp = out.with_name(f".{out.name}.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(out)                       # atomar: nie eine halbe HTML-Datei
    return out


def render_player(pdir: Path, with_me: bool = True) -> Path:
    """Report einer Stufe aus ihrem Datenordner: research (Gegnerordner), briefing-medium (Unterordner medium_*),
    scout-fast (Unterordner scout). Die Stufe steht in dossier.mode."""
    d = read_json(pdir / "dossier.json")
    mode = (d.get("mode") or {}).get("name", "research")
    if mode == "scout":
        from .scout import render_scout
        return render_scout(pdir, d)
    b = read_json(pdir / "briefing.json")
    viewer = read_json(pdir / "viewer.json", {})
    checks = {c["id"]: c for c in read_json(pdir / "engine_checks.json", []) or []}
    from ..profile import corridor, load_me
    me = load_me(pdir) if with_me else None
    mine = corridor(d, me) if me and d.get("profile") else None
    sections = [
        ("profil", "Profil", profile_section(d, b, mine)),
        ("kern", "Auf einen Blick", keys_section(b)),
        ("plan", "Matchplan", plan_section(b, d, checks, mine)),
        ("eroeffnungen", "Eröffnungen", openings_section(d)),
        ("partien", "Partien", games_section(d, viewer)),
        ("phasen", "Phasen", phases_section(d)),
        ("stellungen", "Schlüsselstellungen", moments_section(d, b)),
        ("zeit", "Bedenkzeit", time_section(d, viewer)),
        ("form", "Form", form_section(d)),
        ("kennzahlen", "Kennzahlen", facts_section(d)),
    ]
    slug = d["identity"]["slug"]
    if mode == "medium":
        m = d["mode"]
        return page(d, b, sections, payload_for(pdir, d, viewer, with_me), f"Briefing {d['identity']['display']} ({m['label']})",
                    pdir.parent / f"briefing_{slug}_{m['folder']}.html", "chess-opponent-briefing-medium")
    return page(d, b, sections, payload_for(pdir, d, viewer, with_me), f"Briefing {d['identity']['display']}",
                pdir / f"briefing_{slug}.html")
