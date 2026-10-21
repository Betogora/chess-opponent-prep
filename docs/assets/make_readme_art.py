"""Erzeugt die README-Grafiken (Kopf und Skill-Karten) im Stil der BengtsToolBox-UI-Elemente, hell und dunkel.

    python docs/assets/make_readme_art.py
"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent
FONT = "Manrope, Inter, 'Segoe UI', system-ui, -apple-system, sans-serif"
MONO = "ui-monospace, 'Cascadia Code', Consolas, monospace"

THEMES = {
    "light": dict(page="#f6f7f8", card="#ffffff", border="#e5e7eb", fg="#111827", muted="#4b5563", subtle="#6b7280",
                  track="#f3f4f6", primary="#236492", primary_soft="#ebf3f9", accent="#b55b43", accent_soft="#f8ece8",
                  sq_light="#ffffff", sq_dark="#ebf3f9", mark="#f3d9a4", shadow="rgb(16 24 40 / 8%)", active="#ffffff"),
    "dark": dict(page="#0d1117", card="#161b22", border="#30363d", fg="#f0f6fc", muted="#9198a1", subtle="#7d8590",
                 track="#0d1117", primary="#6cb0e0", primary_soft="#16324a", accent="#e08a72", accent_soft="#3a2119",
                 sq_light="#1c2430", sq_dark="#16324a", mark="#5a4a26", shadow="rgb(0 0 0 / 40%)", active="#21262d"),
}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pill(x, y, text, fg, bg, size=14, pad=14, h=28, weight=650, w=None):
    w = w or int(len(text) * size * 0.58 + 2 * pad)
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h / 2}" fill="{bg}"/>'
            f'<text x="{x + w / 2}" y="{y + h / 2 + size * 0.36:.1f}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fg}" text-anchor="middle">{esc(text)}</text>'), w


def header(t: dict) -> str:
    W, H = 1200, 430
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
         f'aria-labelledby="t d"><title id="t">chess-opponent-prep</title><desc id="d">Gegnervorbereitung für Schach in vier '
         f'Skills: scout-fast, briefing-medium, research-deep, team-prep.</desc>',
         f'<defs><filter id="sh" x="-10%" y="-10%" width="120%" height="140%"><feDropShadow dx="0" dy="1" stdDeviation="1.5" '
         f'flood-color="{t["shadow"]}"/></filter></defs>',
         f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="20" fill="{t["card"]}" stroke="{t["border"]}" stroke-width="2"/>',
         f'<g font-family="{FONT}">']
    p, _ = pill(56, 52, "Schach · Gegnervorbereitung", t["primary"], t["primary_soft"], size=14)
    o.append(p)
    o.append(f'<text x="54" y="150" font-size="66" font-weight="800" letter-spacing="-2.6" fill="{t["fg"]}">chess-opponent-prep</text>')
    o.append(f'<text x="56" y="194" font-size="21" fill="{t["muted"]}">Vom Steckbrief vor der Runde bis zur ganzen Mannschaft –</text>')
    o.append(f'<text x="56" y="222" font-size="21" fill="{t["muted"]}">offline, mit Belegen, in Sekunden bis Minuten.</text>')
    # Segment-Umschalter wie tb-seg
    items = ["scout-fast", "briefing-medium", "research-deep", "team-prep"]
    widths = [128, 172, 160, 124]
    x0, y0 = 56, 250
    tw = sum(widths) + 6 + 4 * (len(items) - 1)
    o.append(f'<rect x="{x0}" y="{y0}" width="{tw}" height="44" rx="12" fill="{t["track"]}" stroke="{t["border"]}"/>')
    x = x0 + 3
    for k, (it, w) in enumerate(zip(items, widths)):
        if k == 0:
            o.append(f'<rect x="{x}" y="{y0 + 3}" width="{w}" height="38" rx="9" fill="{t["active"]}" stroke="{t["border"]}" filter="url(#sh)"/>')
        col = t["fg"] if k == 0 else t["muted"]
        o.append(f'<text x="{x + w / 2}" y="{y0 + 28}" font-size="15" font-weight="650" fill="{col}" text-anchor="middle">{it}</text>')
        x += w + 4
    # Kennzahlen wie tb-stat
    stats = [("Skills", "4"), ("Steckbrief", "< 1 min"), ("Briefing", "2–5 min"), ("Report", "Offline-HTML")]
    sx, sy, sw, sh_, gap = 56, 318, 254, 82, 18
    for k, (lab, val) in enumerate(stats):
        x = sx + k * (sw + gap)
        o.append(f'<rect x="{x}" y="{sy}" width="{sw}" height="{sh_}" rx="14" fill="{t["card"]}" stroke="{t["border"]}" filter="url(#sh)"/>')
        o.append(f'<circle cx="{x + 22}" cy="{sy + 27}" r="4" fill="{t["accent"] if k == 0 else t["primary"]}"/>')
        o.append(f'<text x="{x + 34}" y="{sy + 32}" font-size="14" font-weight="600" fill="{t["muted"]}">{esc(lab)}</text>')
        o.append(f'<text x="{x + 18}" y="{sy + 64}" font-size="26" font-weight="700" letter-spacing="-0.5" fill="{t["fg"]}">{esc(val)}</text>')
    # Mini-Brett mit markiertem letzten Zug (Lichess-Stil)
    bx, by, sq = 930, 52, 26
    o.append(f'<g transform="translate({bx} {by})">')
    o.append(f'<rect x="-2" y="-2" width="{8 * sq + 4}" height="{8 * sq + 4}" rx="12" fill="{t["border"]}"/>')
    o.append(f'<clipPath id="bc"><rect width="{8 * sq}" height="{8 * sq}" rx="10"/></clipPath><g clip-path="url(#bc)">')
    marks = {(4, 6), (4, 4)}
    for r in range(8):
        for c in range(8):
            fill = t["mark"] if (c, r) in marks else (t["sq_dark"] if (r + c) % 2 else t["sq_light"])
            o.append(f'<rect x="{c * sq}" y="{r * sq}" width="{sq}" height="{sq}" fill="{fill}"/>')
    # Zugpfeil e2-e4 wie die Lichess-Pfeile im Report (Schaft + Spitze)
    cx, y1, y2 = 4 * sq + sq / 2, 6 * sq + sq / 2, 4 * sq + sq / 2
    o.append(f'</g><g fill="{t["primary"]}" opacity=".85"><rect x="{cx - 4}" y="{y2 + 12}" width="8" height="{y1 - y2 - 12}" rx="4"/>'
             f'<path d="M{cx} {y2 - 2} L{cx + 12} {y2 + 16} L{cx - 12} {y2 + 16} Z"/></g></g>')
    o.append("</g></svg>")
    return "\n".join(o)


SKILLS = [
    ("Stufe 1", "scout-fast", "< 1 min", ["Steckbrief ohne Engine", "alle Partien, beide Farben", "Repertoire mit Score"], "briefing.py scout", False),
    ("Stufe 2", "briefing-medium", "2–5 min", ["Engine für 20 Partien", "eine Farbe oder beide", "kurzer belegter Matchplan"], "briefing.py brief", False),
    ("Stufe 3", "research-deep", "15–30 min", ["alle Quellen und Partien", "Online-Accounts, Profil", "Matchplan für beide Farben"], "briefing.py prepare", False),
    ("Mannschaft", "team-prep", "Stufe × Spieler", ["Aufstellung einlesen", "je Spieler eine Stufe", "eine Seite, Spieler wählbar"], "briefing.py team", True),
]


def skills(t: dict) -> str:
    W, H, cw, gap = 1200, 330, 282, 24
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">'
         f'<title id="t">Die vier Skills</title><desc id="d">scout-fast unter 1 Minute ohne Engine; briefing-medium 2 bis 5 Minuten '
         f'mit Engine für 20 Partien; research-deep 15 bis 30 Minuten mit allen Quellen; team-prep ruft je Spieler eine Stufe auf.</desc>',
         f'<defs><filter id="sh" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="1" stdDeviation="1.5" '
         f'flood-color="{t["shadow"]}"/></filter></defs><g font-family="{FONT}">']
    for k, (eyebrow, name, dur, lines, cmd, team) in enumerate(SKILLS):
        x = 1 + k * (cw + gap) - (1 if k == 3 else 0)
        col, soft = (t["accent"], t["accent_soft"]) if team else (t["primary"], t["primary_soft"])
        o.append(f'<rect x="{x}" y="1" width="{cw - 2}" height="{H - 4}" rx="14" fill="{t["card"]}" stroke="{t["border"]}" '
                 f'stroke-width="1.5" filter="url(#sh)"/>')
        o.append(f'<circle cx="{x + 28}" cy="38" r="5" fill="{col}"/>')
        o.append(f'<text x="{x + 42}" y="43" font-size="13" font-weight="700" letter-spacing="1.2" fill="{t["subtle"]}">{eyebrow.upper()}</text>')
        o.append(f'<text x="{x + 22}" y="86" font-size="26" font-weight="750" letter-spacing="-0.6" fill="{t["fg"]}">{name}</text>')
        p, _ = pill(x + 22, 104, dur, col, soft, size=14)
        o.append(p)
        for i, ln in enumerate(lines):
            yy = 172 + i * 30
            o.append(f'<circle cx="{x + 28}" cy="{yy - 5}" r="2.6" fill="{t["subtle"]}"/>')
            o.append(f'<text x="{x + 40}" y="{yy}" font-size="15.5" fill="{t["muted"]}">{esc(ln)}</text>')
        o.append(f'<rect x="{x + 22}" y="{H - 64}" width="{cw - 46}" height="34" rx="9" fill="{t["track"]}" stroke="{t["border"]}"/>')
        o.append(f'<text x="{x + 36}" y="{H - 42}" font-size="14" fill="{t["fg"]}" font-family="{MONO}">$ {cmd}</text>')
    o.append("</g></svg>")
    return "\n".join(o)


if __name__ == "__main__":
    for name, t in THEMES.items():
        (OUT / f"header-{name}.svg").write_text(header(t), encoding="utf-8")
        (OUT / f"skills-{name}.svg").write_text(skills(t), encoding="utf-8")
    print("ok:", sorted(p.name for p in OUT.glob("*.svg")))
