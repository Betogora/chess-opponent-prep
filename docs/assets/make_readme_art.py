"""Erzeugt die README-Grafiken (Kopf und Skill-Zeitachse) im Stil der BengtsToolBox-UI-Elemente, hell und dunkel.

    python docs/assets/make_readme_art.py

Braucht python-chess, fontTools und die Schrift Manrope (Regular, Medium, SemiBold, Bold als TTF, SIL OFL 1.1).
Gesucht wird in MANROPE_DIR und in den üblichen Schriftordnern; eingebettet werden nur die benutzten Zeichen.
"""
from __future__ import annotations

import base64
import io
import os
import re
from pathlib import Path

import chess
import chess.svg
from fontTools import subset
from fontTools.ttLib import TTFont

OUT = Path(__file__).resolve().parent
WEIGHTS = {400: "Manrope-Regular.ttf", 500: "Manrope-Medium.ttf", 600: "Manrope-SemiBold.ttf", 700: "Manrope-Bold.ttf"}
FONT = "M, Manrope, 'Segoe UI', system-ui, -apple-system, sans-serif"
MONO = "ui-monospace, 'SF Mono', 'Cascadia Code', Consolas, monospace"

THEMES = {
    "light": dict(fg="#0b1220", muted="#1f2937", subtle="#4b5563", border="#d1d5db", strong="#9ca3af", card="#ffffff",
                  primary="#236492", soft="#ebf3f9", accent="#b55b43", asoft="#f8ece8", sq_l="#f4f7fa", sq_d="#c3d9e8",
                  mark=("#f6e3b4", "#e7cf8f"), arrow="#236492", shadow="rgb(16 24 40 / 10%)"),
    "dark": dict(fg="#f0f6fc", muted="#9198a1", subtle="#7d8590", border="#30363d", strong="#3d444d", card="#161b22",
                 primary="#6cb0e0", soft="#132a3d", accent="#e08a72", asoft="#251a18", sq_l="#9fb6ca", sq_d="#5f86a5",
                 mark=("#d9bf7c", "#b99c55"), arrow="#123a58", shadow="rgb(0 0 0 / 45%)"),
}


def font_dir() -> Path:
    candidates = [os.environ.get("MANROPE_DIR", ""), Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts",
                  Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path.home() / "Library/Fonts",
                  Path.home() / ".local/share/fonts", "/usr/share/fonts/truetype/manrope"]
    for d in map(Path, filter(None, candidates)):
        if (d / WEIGHTS[700]).is_file():
            return d
    raise SystemExit("Manrope nicht gefunden – TTF-Dateien installieren oder MANROPE_DIR setzen.")


FONTS = font_dir()
_METRICS: dict = {}


def tw(text: str, size: float, weight: int = 400) -> float:
    """Textbreite in px aus den Manrope-Metriken."""
    if weight not in _METRICS:
        f = TTFont(FONTS / WEIGHTS[weight])
        _METRICS[weight] = (f.getBestCmap(), f["hmtx"].metrics, f["head"].unitsPerEm)
    cmap, hmtx, upm = _METRICS[weight]
    return sum(hmtx.get(cmap.get(ord(c), ".notdef"), (500, 0))[0] for c in text) / upm * size


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fonts_css(text: str) -> str:
    css = []
    for w, fn in WEIGHTS.items():
        f = TTFont(FONTS / fn)
        opts = subset.Options()
        opts.flavor = "woff"
        opts.layout_features = ["kern", "liga", "calt"]
        s = subset.Subsetter(opts)
        s.populate(text="".join(sorted(set(text) | {" "})))
        s.subset(f)
        f.flavor = "woff"
        buf = io.BytesIO()
        f.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        css.append(f"@font-face{{font-family:M;font-weight:{w};src:url(data:font/woff;base64,{b64}) format('woff')}}")
    return "".join(css)


def finish(body: str, W: int, H: int, title: str, desc: str) -> str:
    texts = "".join(re.findall(r">([^<]+)<", body))
    style = f"<style>{fonts_css(texts)}text{{font-family:{FONT}}}.mono{{font-family:{MONO}}}</style>"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
            f'aria-labelledby="t d"><title id="t">{esc(title)}</title><desc id="d">{esc(desc)}</desc>{style}{body}</svg>')


def shadow(uid, t, dy=8, blur=14):
    return (f'<filter id="{uid}" filterUnits="userSpaceOnUse" x="-100" y="-100" width="1200" height="800">'
            f'<feDropShadow dx="0" dy="{dy}" stdDeviation="{blur}" flood-color="{t["shadow"]}"/></filter>')


def pill(x, y, text, fg, bg, size=13, h=26, weight=600, pad=12):
    w = round(tw(text, size, weight) + 2 * pad)
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h / 2}" fill="{bg}"/>'
            f'<text x="{x + w / 2}" y="{y + h / 2 + size * 0.35:.1f}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fg}" text-anchor="middle">{esc(text)}</text>')


# Sizilianisch, Najdorf nach 5…a6; Pfeil 6.Lg5
NAJDORF = "rnbqkb1r/1p2pppp/p2p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6"


def board(t, x, y, size, uid, rx=14):
    ml, md = t["mark"]
    svg = chess.svg.board(chess.Board(NAJDORF), size=size, coordinates=False,
                          arrows=[chess.svg.Arrow(chess.C1, chess.G5, color=t["arrow"] + "d9")],
                          lastmove=chess.Move(chess.A7, chess.A6),
                          colors={"square light": t["sq_l"], "square dark": t["sq_d"], "margin": "none",
                                  "square light lastmove": ml, "square dark lastmove": md})
    svg = re.sub(r"<desc>.*?</desc>", "", svg, flags=re.S)
    svg = re.sub(r'(id|href)="(#?)([a-z-]+)"', lambda m: f'{m.group(1)}="{m.group(2)}{uid}-{m.group(3)}"', svg)
    svg = svg.replace("<svg ", f'<svg x="{x}" y="{y}" ', 1)
    return (f'<clipPath id="{uid}-clip"><rect x="{x}" y="{y}" width="{size}" height="{size}" rx="{rx}"/></clipPath>'
            f'<g clip-path="url(#{uid}-clip)">{svg}</g>'
            f'<rect x="{x + 0.5}" y="{y + 0.5}" width="{size - 1}" height="{size - 1}" rx="{rx}" fill="none" '
            f'stroke="{t["fg"]}" stroke-opacity=".10"/>')


STAGES = [("scout-fast", "< 1 min"), ("briefing-medium", "2–5 min"), ("research-deep", "15–30 min"), ("team-prep", "je Spieler")]


def header(t: dict) -> str:
    W, H = 880, 356
    bx, by, bs = 580, 16, 300
    sq = bs / 8
    o = [f"<defs>{shadow('sa', t)}</defs>", pill(0, by, "Schach · Gegnervorbereitung", t["primary"], t["soft"]),
         f'<text x="-2" y="108" font-size="50" font-weight="700" letter-spacing="-1.8" fill="{t["fg"]}">chess-opponent-prep</text>',
         f'<text x="0" y="152" font-size="18" font-weight="500" fill="{t["muted"]}">Steckbrief, Briefing, Recherche oder</text>',
         f'<text x="0" y="178" font-size="18" font-weight="500" fill="{t["muted"]}">ganze Mannschaft – offline, jede Zahl belegt.</text>']
    cw, ch = 214, 34
    for k, (name, dur) in enumerate(STAGES):
        x, y = (k % 2) * (cw + 12), by + bs - 76 + (k // 2) * 42
        col = t["accent"] if k == 3 else t["primary"]
        o.append(f'<rect x="{x + 0.5}" y="{y + 0.5}" width="{cw - 1}" height="{ch - 1}" rx="10" fill="{t["card"]}" stroke="{t["border"]}"/>'
                 f'<circle cx="{x + 16}" cy="{y + ch / 2}" r="4" fill="{col}"/>'
                 f'<text x="{x + 28}" y="{y + ch / 2 + 4.8}" font-size="13.5" font-weight="700" fill="{t["fg"]}">{name}</text>'
                 f'<text x="{x + cw - 14}" y="{y + ch / 2 + 4.5}" font-size="12.5" font-weight="500" fill="{t["subtle"]}" '
                 f'text-anchor="end">{esc(dur)}</text>')
    o.append(f'<rect x="{bx}" y="{by}" width="{bs}" height="{bs}" rx="14" fill="{t["card"]}" filter="url(#sa)"/>')
    o.append(board(t, bx, by, bs, "ba"))
    # Notiz-Karte liegt auf den leeren Feldern a4–c5
    nx, ny, nw, nh = bx - 112, by + 3 * sq + 1, 216, 2 * sq - 2
    o.append(f'<rect x="{nx}" y="{ny}" width="{nw}" height="{nh}" rx="12" fill="{t["card"]}" stroke="{t["border"]}" filter="url(#sa)"/>'
             f'<text x="{nx + 16}" y="{ny + 24}" font-size="11" font-weight="700" letter-spacing="1" fill="{t["subtle"]}">SEINE HAUPTLINIE</text>'
             f'<text x="{nx + 16}" y="{ny + 46}" font-size="15.5" font-weight="700" fill="{t["fg"]}">Sizilianisch, Najdorf</text>'
             f'<text x="{nx + 16}" y="{ny + 64}" font-size="12.5" font-weight="500" fill="{t["muted"]}">5…a6 · Weiß spielt 6.Lg5</text>')
    return finish("".join(o), W, H, "chess-opponent-prep", "Gegnervorbereitung für Schach in vier Skills: scout-fast, "
                  "briefing-medium, research-deep, team-prep.")


SKILLS = [
    ("1", "scout-fast", "< 1 min", "Steckbrief ohne Engine", ["alle Partien, beide Farben", "Repertoire mit Score je Linie"], "scout"),
    ("2", "briefing-medium", "2–5 min", "Engine für 20 Partien", ["eine Farbe oder beide", "kurzer belegter Matchplan"], "brief"),
    ("3", "research-deep", "15–30 min", "Alle Quellen und Partien", ["Online-Accounts mit Konfidenz", "Matchplan für beide Farben"], "prepare"),
]


def skills(t: dict) -> str:
    W, H = 880, 352
    cw, gap, ch = 280, 20, 192
    o = [f"<defs>{shadow('s1', t, 4, 8)}</defs>"]
    for k, (n, name, _dur, head, lines, cmd) in enumerate(SKILLS):
        x = k * (cw + gap)
        o.append(f'<rect x="{x + 0.5}" y="0.5" width="{cw - 1}" height="{ch}" rx="14" fill="{t["card"]}" stroke="{t["border"]}" filter="url(#s1)"/>'
                 f'<text x="{x + 20}" y="34" font-size="12" font-weight="700" letter-spacing="1.1" fill="{t["subtle"]}">STUFE {n}</text>'
                 f'<text x="{x + 20}" y="66" font-size="21" font-weight="700" letter-spacing="-0.4" fill="{t["fg"]}">{name}</text>'
                 f'<text x="{x + 20}" y="92" font-size="14.5" font-weight="600" fill="{t["fg"]}">{esc(head)}</text>')
        for i, ln in enumerate(lines):
            y = 117 + i * 23
            o.append(f'<path d="M{x + 21} {y - 5} l3.5 3.5 6-7" fill="none" stroke="{t["primary"]}" stroke-width="2" '
                     f'stroke-linecap="round" stroke-linejoin="round"/>'
                     f'<text x="{x + 38}" y="{y}" font-size="14" font-weight="500" fill="{t["muted"]}">{esc(ln)}</text>')
        o.append(f'<text class="mono" x="{x + 20}" y="{ch - 14}" font-size="12.5" fill="{t["subtle"]}">$ briefing.py {cmd}</text>')
    # Zeitachse mit der Dauer je Stufe
    ay = 226
    o.append(f'<line x1="0" y1="{ay}" x2="{W - 8}" y2="{ay}" stroke="{t["strong"]}" stroke-width="2" stroke-linecap="round"/>'
             f'<path d="M{W - 12} {ay - 5} l7 5 -7 5" fill="none" stroke="{t["strong"]}" stroke-width="2" '
             f'stroke-linecap="round" stroke-linejoin="round"/>')
    for k, (_, _, dur, *_rest) in enumerate(SKILLS):
        cx = k * (cw + gap) + cw / 2
        o.append(f'<line x1="{cx}" y1="{ch + 1}" x2="{cx}" y2="{ay - 7}" stroke="{t["strong"]}" stroke-width="1.5" stroke-dasharray="2 3"/>'
                 f'<circle cx="{cx}" cy="{ay}" r="6.5" fill="{t["card"]}" stroke="{t["primary"]}" stroke-width="2.5"/>'
                 f'<text x="{cx}" y="{ay + 30}" font-size="15" font-weight="700" fill="{t["primary"]}" text-anchor="middle">{esc(dur)}</text>')
    by = 284
    o.append(f'<rect x="0.5" y="{by + 0.5}" width="{W - 1}" height="62" rx="14" fill="{t["asoft"]}" stroke="{t["accent"]}" stroke-opacity=".3"/>'
             f'<text x="20" y="{by + 27}" font-size="12" font-weight="700" letter-spacing="1.1" fill="{t["accent"]}">MANNSCHAFT</text>'
             f'<text x="20" y="{by + 49}" font-size="17" font-weight="700" fill="{t["fg"]}">team-prep</text>'
             f'<text x="128" y="{by + 49}" font-size="14.5" font-weight="500" fill="{t["muted"]}">liest die Aufstellung, ruft je Spieler eine Stufe auf</text>'
             f'<text class="mono" x="{W - 20}" y="{by + 49}" font-size="12.5" fill="{t["subtle"]}" text-anchor="end">$ briefing.py team</text>')
    return finish("".join(o), W, H, "Die vier Skills", "scout-fast unter 1 Minute, briefing-medium 2 bis 5 Minuten, "
                  "research-deep 15 bis 30 Minuten; team-prep ruft je Spieler eine Stufe auf.")


if __name__ == "__main__":
    for name, t in THEMES.items():
        (OUT / f"header-{name}.svg").write_text(header(t), encoding="utf-8")
        (OUT / f"skills-{name}.svg").write_text(skills(t), encoding="utf-8")
    print("ok:", sorted(p.name for p in OUT.glob("*.svg")))
