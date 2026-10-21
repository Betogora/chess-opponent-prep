"""Inline-SVG-Diagramme im BengtsToolBox-Chartstil.

Konventionen (TrainingCharts.tsx): nur horizontale Hilfslinien (gestrichelt 1 5), keine Achsenlinien,
Ticks 11 px muted, Serienname am Linienende statt Legendenbox, Balken mit 6 px Radius oben.
"""
from __future__ import annotations

import datetime as dt
from html import escape


def _nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    span = hi - lo or 1
    raw = span / n
    mag = 10 ** len(str(int(raw))) / 10 if raw >= 1 else 1
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if span / step <= n:
            break
    start = (lo // step) * step
    out, v = [], start
    while v <= hi + 1e-9:
        if v >= lo - 1e-9:
            out.append(round(v, 6))
        v += step
    return out


def line_chart(series: list[dict], *, x_domain, y_domain, x_ticks: list[tuple], y_ticks: list[float] | None = None,
               y_fmt=lambda v: f"{v:g}", unit: str = "", refs: list[dict] | None = None, dots: list[dict] | None = None,
               width: int = 960, height: int = 300, label_end: bool = True, band: tuple | None = None) -> str:
    L, R, T, B = 44, 70 if label_end else 16, 18, 26
    W, H = width - L - R, height - T - B
    x0, x1 = x_domain
    y0, y1 = y_domain

    def X(x):
        return L + (x - x0) / ((x1 - x0) or 1) * W

    def Y(y):
        return T + (1 - (y - y0) / ((y1 - y0) or 1)) * H

    o = [f'<svg viewBox="0 0 {width} {height}" role="img">']
    if band:
        o.append(f'<rect class="band" x="{L}" y="{Y(band[1]):.1f}" width="{W}" height="{Y(band[0]) - Y(band[1]):.1f}" rx="4"/>')
    for v in (y_ticks if y_ticks is not None else _nice_ticks(y0, y1)):
        o.append(f'<line class="grid" x1="{L}" x2="{L + W}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>')
        o.append(f'<text class="tick" x="{L - 8}" y="{Y(v) + 4:.1f}" text-anchor="end">{escape(y_fmt(v))}</text>')
    for xv, lab in x_ticks:
        o.append(f'<text class="tick" x="{X(xv):.1f}" y="{height - 6}" text-anchor="middle">{escape(str(lab))}</text>')
    if unit:
        o.append(f'<text class="unit" x="{L - 8}" y="10" text-anchor="end">{escape(unit)}</text>')
    for r in refs or []:
        if "y" in r:
            o.append(f'<line class="ref" x1="{L}" x2="{L + W}" y1="{Y(r["y"]):.1f}" y2="{Y(r["y"]):.1f}"/>')
            if r.get("label"):
                o.append(f'<text class="tick" x="{L + W + 6}" y="{Y(r["y"]) + 4:.1f}">{escape(r["label"])}</text>')
        if "x" in r:
            o.append(f'<line class="ref" x1="{X(r["x"]):.1f}" x2="{X(r["x"]):.1f}" y1="{T}" y2="{T + H}"/>')
            if r.get("label"):
                o.append(f'<text class="tick" x="{X(r["x"]) + 4:.1f}" y="{T + 10}">{escape(r["label"])}</text>')
    labels = []
    for s in series:
        pts = [(X(x), Y(y)) for x, y in s["points"] if y is not None]
        if not pts:
            continue
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        cls = "series" + (" series--thin" if s.get("thin") else "")
        dash = f' stroke-dasharray="{s["dash"]}"' if s.get("dash") else ""
        o.append(f'<path class="{cls}" d="{d}" stroke="{s["color"]}"{dash}><title>{escape(s.get("name", ""))}</title></path>')
        if s.get("points_visible"):
            for x, y in pts:
                o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{s["color"]}" fill-opacity=".55"/>')
        if label_end and s.get("name"):
            labels.append([pts[-1][1], pts[-1][0], s])
    # Endlabels ohne Ueberlappung
    labels.sort(key=lambda t: t[0])
    for i in range(1, len(labels)):
        if labels[i][0] - labels[i - 1][0] < 12:
            labels[i][0] = labels[i - 1][0] + 12
    for y, x, s in labels:
        o.append(f'<text class="end-label" x="{x + 8:.1f}" y="{y + 4:.1f}" fill="{s["color"]}">{escape(s["name"])}</text>')
    for dt_ in dots or []:
        o.append(f'<circle cx="{X(dt_["x"]):.1f}" cy="{Y(dt_["y"]):.1f}" r="{dt_.get("r", 3.5)}" fill="{dt_["color"]}" '
                 f'stroke="var(--card)" stroke-width="1.5"><title>{escape(dt_.get("title", ""))}</title></circle>')
    o.append("</svg>")
    return "".join(o)


def grouped_bars(groups: list[str], series: list[dict], *, y_max: float, unit: str = "", fmt=lambda v: f"{v:g}",
                 width: int = 960, height: int = 260, notes: list[str] | None = None) -> str:
    """series: [{name, color, values:[...], thin:[bool,...]}]  - duenn belegte Werte werden schraffiert/blass gezeichnet."""
    L, R, T, B = 44, 12, 18, 40
    W, H = width - L - R, height - T - B
    ticks = _nice_ticks(0, y_max)
    y_top = max(ticks[-1], y_max)

    def Y(v):
        return T + (1 - v / (y_top or 1)) * H

    o = [f'<svg viewBox="0 0 {width} {height}" role="img">',
         '<defs><pattern id="cb-hatch" width="5" height="5" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">'
         '<rect width="5" height="5" fill="var(--card)"/><line x1="0" y1="0" x2="0" y2="5" stroke="var(--border-strong)" stroke-width="2.4"/></pattern></defs>']
    for v in ticks:
        o.append(f'<line class="grid" x1="{L}" x2="{L + W}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>')
        o.append(f'<text class="tick" x="{L - 8}" y="{Y(v) + 4:.1f}" text-anchor="end">{fmt(v)}</text>')
    if unit:
        o.append(f'<text class="unit" x="{L - 8}" y="10" text-anchor="end">{escape(unit)}</text>')
    gw = W / len(groups)
    bw = min(30, gw * 0.72 / len(series))
    for gi, gname in enumerate(groups):
        cx = L + gw * gi + gw / 2
        total = bw * len(series) + 6 * (len(series) - 1)
        for si, s in enumerate(series):
            v = s["values"][gi]
            x = cx - total / 2 + si * (bw + 6)
            if v is None:
                o.append(f'<text class="tick" x="{x + bw / 2:.1f}" y="{Y(0) - 4:.1f}" text-anchor="middle">–</text>')
                continue
            y = Y(v)
            h = max(0.0, Y(0) - y)
            r = min(6, h / 2, bw / 2)
            thin = (s.get("thin") or [False] * len(groups))[gi]
            path = (f"M{x:.1f},{Y(0):.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
                    f"L{x + bw - r:.1f},{y:.1f} Q{x + bw:.1f},{y:.1f} {x + bw:.1f},{y + r:.1f} L{x + bw:.1f},{Y(0):.1f} Z")
            fill = s["color"]
            op = ' fill-opacity=".45"' if thin else ""
            o.append(f'<path d="{path}" fill="{fill}"{op}><title>{escape(s["name"])}: {fmt(v)}</title></path>')
            o.append(f'<text class="val" x="{x + bw / 2:.1f}" y="{y - 5:.1f}" text-anchor="middle">{fmt(v)}</text>')
        o.append(f'<text class="tick" x="{cx:.1f}" y="{height - 22}" text-anchor="middle" style="font-weight:600">{escape(gname)}</text>')
        if notes:
            o.append(f'<text class="tick" x="{cx:.1f}" y="{height - 8}" text-anchor="middle">{escape(notes[gi])}</text>')
    o.append("</svg>")
    return "".join(o)


def rating_chart(history: list[dict], game_dates: list[tuple[str, str]], width: int = 960, height: int = 260) -> str:
    pts = [(dt.date.fromisoformat(h["date"]), h["standard"]) for h in history if h["standard"]]
    if len(pts) < 2:
        return ""
    t0, t1 = pts[0][0], pts[-1][0]

    def tx(d):
        return (d - t0).days

    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    pad = max(20, (hi - lo) * 0.12)
    y0, y1 = (lo - pad) // 50 * 50, (hi + pad) // 50 * 50 + 50
    years = range(t0.year + 1, t1.year + 1)
    xt = [(0, t0.strftime("%m/%Y"))] + [(tx(dt.date(y, 1, 1)), str(y)) for y in years if tx(dt.date(y, 1, 1)) > 60]
    series = [{"name": f"Elo {pts[-1][1]}", "color": "var(--c-white)", "points": [(tx(d), v) for d, v in pts]}]
    dots = []
    for d_iso, title in game_dates:
        try:
            d = dt.date.fromisoformat(d_iso[:10] if len(d_iso) >= 10 else d_iso[:7] + "-01")
        except ValueError:
            continue
        before = [v for dd, v in pts if dd <= d] or [pts[0][1]]
        if d <= t1:
            dots.append({"x": max(0, tx(d)), "y": before[-1], "color": "var(--c-black)", "title": title})
    return line_chart(series, x_domain=(0, tx(t1)), y_domain=(y0, y1), x_ticks=xt, unit="Elo", dots=dots,
                      width=width, height=height)
