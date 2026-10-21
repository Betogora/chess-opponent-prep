"""Steckbrief der Stufe scout-fast: gleiche Bausteine und Optik wie der research-Report, ohne Engine-Abschnitte."""
from __future__ import annotations

from pathlib import Path

from ..util import read_json
from .html import (COL, e, ev_buttons, form_section, games_section, keys_section, openings_section, page, payload_for,
                   pct, section, stat, wdl_bar)


def results_section(d: dict, order: list[str]) -> str:
    cols = []
    for col in order:
        c = d["color_stats"][col]
        if not c["games"]:
            continue
        tiles = "".join([stat("Partien", str(c["games"])), stat("Score", pct(c["score_pct"])),
                         stat("Ø Elo Gegner", e(c["avg_opp_elo"] or "–")), stat("Performance", e(c["performance"] or "–"))])
        cols.append(f'<div class="cb-figure"><div class="cb-colhead"><span class="cb-colorpip cb-colorpip--{col[0]}"></span>'
                    f'Er hat {COL[col]}</div>{wdl_bar(c["w"], c["d"], c["l"])}<div class="cb-tiles">{tiles}</div></div>')
    return section("ergebnisse", "Ergebnisse", f'<div class="cb-twocol">{"".join(cols)}</div>') if cols else ""


def repertoire_section(d: dict, order: list[str]) -> str:
    """Seine häufigsten Linien je Farbe mit Anzahl und Score (Farbe der anstehenden Partie zuerst)."""
    blocks = []
    for col in order:
        rows = "".join(
            f'<tr><td><span class="cb-line">{e(x["line"])}</span><div class="tb-meta">{e(x["eco"])} {e(x["name"])}</div></td>'
            f'<td class="num">{x["n"]}</td><td class="num">{pct(x["score_pct"])}</td><td>{ev_buttons([x["fact"]])}</td></tr>'
            for x in d["repertoire"].get(f"{col}_lines", []))
        if rows:
            blocks.append(f'<div><h3 class="cb-sub"><span class="cb-colorpip cb-colorpip--{col[0]}"></span> Er hat {COL[col]}</h3>'
                          f'<div class="tb-table-wrap"><table class="tb-table cb-table"><thead><tr><th>Linie</th>'
                          f'<th class="num">Partien</th><th class="num">Score</th><th></th></tr></thead><tbody>{rows}</tbody>'
                          f'</table></div></div>')
    return section("repertoire", "Repertoire", "".join(blocks)) if blocks else ""


def render_scout(pdir: Path, d: dict) -> Path:
    viewer = read_json(pdir / "viewer.json", {})
    b = d.get("briefing") or {}
    opp = d["mode"]["opponent_color"]          # None = beide Farben gleichrangig
    order = [opp, "white" if opp == "black" else "black"] if opp else ["white", "black"]
    sections = [
        ("kern", "Auf einen Blick", keys_section(b)),
        ("eroeffnungen", "Eröffnungen", openings_section(d)),
        ("repertoire", "Repertoire", repertoire_section(d, order)),
        ("partien", "Partien", games_section(d, viewer)),
        ("ergebnisse", "Ergebnisse", results_section(d, order)),
        ("form", "Form", form_section(d)),
    ]
    slug = d["identity"]["slug"]
    return page(d, b, sections, payload_for(pdir, d, viewer, with_me=False), f"Steckbrief {d['identity']['display']}",
                pdir.parent / f"scout_{slug}.html", "chess-opponent-scout-fast")
