"""Mannschaftsseite (chess-opponent-team-prep): oben eine mehrspaltige Spielerliste (klappt nach der Wahl zu einer
Zeile zusammen), darunter der
vollstaendige Einzelreport der gewaehlten Stufe. Eine Datei, offline: jeder Report liegt gzip-komprimiert (base64) in der
Seite und wird erst beim Umschalten im Browser entpackt (DecompressionStream) und als iframe-srcdoc gezeigt."""
from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

from ..lineup import team_slug
from .html import A, e, icon, stat

STAGE_DE = {"scout": "Steckbrief (scout-fast)", "medium": "Briefing (briefing-medium)", "research": "Recherche (research-deep)"}
COLOR_DE = {"white": "du hast Weiß", "black": "du hast Schwarz", "both": "beide Farben"}

TEAM_CSS = """
html, body { height: 100%; }
body { margin: 0; display: flex; flex-direction: column; background: var(--background); }
.tm-bar { flex: none; border-bottom: 1px solid var(--border); background: var(--background); padding: .75rem 1rem; }
.tm-bar__top { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
.tm-bar h1 { font-size: 1.25rem; font-weight: 700; color: var(--primary); margin: 0; }
.tm-meta { color: var(--muted-foreground); font-size: .8125rem; }
.tm-current { margin-left: auto; display: inline-flex; align-items: center; gap: .5rem; border: 1px solid var(--border);
  background: var(--card); color: var(--foreground); border-radius: var(--radius-md); padding: .35rem .7rem; font: inherit;
  font-size: .8125rem; font-weight: 650; cursor: pointer; }
.tm-current .tb-chevron { transition: transform .15s; }
.tm-bar.is-open .tm-current .tb-chevron { transform: rotate(180deg); }
.tm-grid { display: none; grid-template-columns: repeat(auto-fill, minmax(13.5rem, 1fr)); gap: .4rem; margin-top: .75rem;
  max-height: 55vh; overflow: auto; }
.tm-bar.is-open .tm-grid { display: grid; }
.tm-item { display: grid; grid-template-columns: 2.4rem 1fr; align-items: center; column-gap: .5rem; text-align: left;
  border: 1px solid var(--border); background: var(--card); color: var(--foreground); border-radius: var(--radius-md);
  padding: .45rem .6rem; font: inherit; cursor: pointer; }
.tm-item:hover { border-color: var(--border-strong); }
.tm-item__nr { grid-row: span 2; font-size: .8125rem; font-weight: 700; color: var(--muted-foreground);
  font-variant-numeric: tabular-nums; }
.tm-item__name { font-size: .875rem; font-weight: 650; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tm-item__meta { display: flex; align-items: center; gap: .35rem; font-size: .75rem; color: var(--muted-foreground);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tm-item[aria-pressed="true"] { border-color: var(--primary); box-shadow: inset 0 0 0 1px var(--primary);
  background: var(--secondary); }
.tm-item.is-stub { border-style: dashed; }
.tm-item.is-stub .tm-item__name { color: var(--muted-foreground); }
.tm-item--overview .tm-item__nr { font-size: 1rem; }
.tm-pip { width: .6rem; height: .6rem; border-radius: 50%; border: 1px solid var(--border-strong); flex: none; display: inline-block; }
.tm-pip--white { background: #fff; } .tm-pip--black { background: #222; }
.tm-pip--both { background: linear-gradient(90deg, #fff 50%, #222 50%); }
.tm-main { flex: 1; min-height: 0; position: relative; }
.tm-frame { border: 0; width: 100%; height: 100%; display: block; background: var(--background); }
.tm-panel { height: 100%; overflow: auto; }
.tm-panel .tb-page { padding-top: 1rem; }
.tm-stub { max-width: 40rem; margin: 2rem auto; }
@media (max-width: 640px) { .tm-grid { grid-template-columns: 1fr 1fr; } .tm-item { grid-template-columns: 1fr; }
  .tm-item__nr { grid-row: auto; } .tm-current { margin-left: 0; } }
"""

TEAM_JS = r"""
(function () {
  var D = JSON.parse(document.getElementById("team-data").textContent);
  var bar = document.getElementById("tm-bar"), cur = document.getElementById("tm-current");
  var frame = document.getElementById("tm-frame"), over = document.getElementById("tm-overview"), stub = document.getElementById("tm-stub");
  var items = Array.prototype.slice.call(document.querySelectorAll("[data-tab]"));
  var cache = {};
  try { var t = localStorage.getItem("cb-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
  function inflate(b64) {
    var bin = Uint8Array.from(atob(b64), function (c) { return c.charCodeAt(0); });
    return new Response(new Blob([bin]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
  }
  function open(on) { bar.classList.toggle("is-open", on); cur.setAttribute("aria-expanded", on ? "true" : "false"); }
  function select(key) {
    items.forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.tab === key ? "true" : "false"); });
    var p = D.players.filter(function (x) { return String(x.key) === key; })[0];
    cur.querySelector("[data-current]").textContent = p ? p.title : "Übersicht";
    over.hidden = key !== "overview"; frame.hidden = true; stub.hidden = true;
    if (key !== "overview") {
      open(false);
      if (!p || !p.html) {
        stub.hidden = false;
        stub.querySelector("[data-stub-name]").textContent = p ? p.label : "";
        stub.querySelector("[data-stub-note]").textContent = p ? (p.note || "Kein Report vorhanden.") : "";
      } else {
        frame.hidden = false;
        (cache[key] ? Promise.resolve(cache[key]) : inflate(p.html).then(function (h) { cache[key] = h; return h; }))
          .then(function (h) { frame.srcdoc = h; });
      }
    } else { open(true); }
    try { history.replaceState(null, "", "#" + key); } catch (e) {}
  }
  frame.addEventListener("load", function () {
    try {
      frame.contentDocument.querySelectorAll('a[href^="http"]').forEach(function (a) { a.target = "_blank"; a.rel = "noopener"; });
    } catch (e) {}
  });
  cur.addEventListener("click", function () { open(!bar.classList.contains("is-open")); });
  items.forEach(function (b) { b.addEventListener("click", function () { select(b.dataset.tab); }); });
  document.querySelectorAll("[data-goto]").forEach(function (a) {
    a.addEventListener("click", function (ev) { ev.preventDefault(); select(a.dataset.goto); });
  });
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") open(false); });
  var start = (location.hash || "").slice(1);
  select(items.some(function (b) { return b.dataset.tab === start; }) ? start : "overview");
})();
"""


def _pack(path: Path) -> str:
    return base64.b64encode(gzip.compress(path.read_bytes(), 9)).decode("ascii")


def _color(c: str) -> str:
    return f'<span class="tm-pip tm-pip--{e(c)}" title="{e(COLOR_DE.get(c, c))}"></span>'


def overview(doc: dict, rows: list[dict]) -> str:
    ok = [r for r in rows if r["html"]]
    total = doc.get("seconds")
    tiles = "".join([stat("Spieler", f"{len(ok)}/{len(rows)}"), stat("Stufe", e(STAGE_DE[doc["stage"]].split(" (")[0])),
                     stat("Laufzeit", f"{total:.0f} s" if total is not None else "–")])
    body = "".join(
        f'<tr><td class="num">{e(r["nr"])}</td><td><a href="#{e(r["key"])}" data-goto="{e(r["key"])}">{e(r["label"])}</a>'
        f'<div class="tb-meta">{e(r["note"])}</div></td><td class="num">{e(r.get("dwz") or "–")}</td>'
        f'<td>{_color(r["color"])} {e(COLOR_DE.get(r["color"], ""))}</td>'
        f'<td class="num">{e(r.get("games") if r.get("games") is not None else "–")}</td>'
        f'<td class="num">{e(r.get("analysed") if r.get("analysed") is not None else "–")}</td>'
        f'<td class="num">{(str(round(r["seconds"])) + " s") if r.get("seconds") is not None else "–"}</td>'
        f'<td>{"✓" if r["html"] else "–"}</td></tr>' for r in rows)
    table = (f'<div class="tb-table-wrap"><table class="tb-table cb-table"><thead><tr><th class="num">Nr.</th><th>Spieler</th>'
             f'<th class="num">DWZ</th><th>Farbe</th><th class="num">Partien</th><th class="num">analysiert</th>'
             f'<th class="num">Zeit</th><th>Report</th></tr></thead><tbody>{body}</tbody></table></div>')
    src = doc.get("source", "")
    link = f'<a href="{e(src)}">{e(src)}</a>' if src.startswith("http") else e(src)
    return (f'<main class="tb-page cb-page"><section class="cb-section"><header><div><h2>Übersicht</h2></div></header>'
            f'<div class="cb-tiles">{tiles}</div>{table}<p class="cb-note">Quelle der Aufstellung: {link}. '
            f'Oben einen Spieler wählen; jeder Report ist vollständig und funktioniert offline.</p></section></main>')


def render_team(tdir: Path, doc: dict) -> Path:
    from ..modes.team import report_path
    rows = []
    for p in doc["players"]:
        path = report_path(p["slug"], doc["stage"], p["color"]) if p.get("slug") else None
        has = bool(path and path.exists())
        rows.append({"key": f"p{p.get('nr')}", "nr": p.get("nr"), "label": p.get("display") or p["name"],
                     "dwz": p.get("dwz"), "color": p.get("color", "both"), "games": p.get("games"),
                     "analysed": p.get("analysed"), "seconds": p.get("seconds"),
                     "note": "" if has else (p.get("note") or "kein Report"), "html": _pack(path) if has else None})
    def meta(r):
        parts = [_color(r["color"]), e(COLOR_DE.get(r["color"], ""))]
        if r.get("dwz"):
            parts.insert(0, f"DWZ {e(r['dwz'])} ·")
        if r["html"] and r.get("games") is not None:
            parts.append(f"· {e(r['games'])} Partien")
        if not r["html"]:
            parts = [e(r["note"] or "kein Report")]
        return " ".join(parts)
    tabs = ['<button class="tm-item tm-item--overview" type="button" data-tab="overview" aria-pressed="true">'
            '<span class="tm-item__nr">∑</span><span class="tm-item__name">Übersicht</span>'
            f'<span class="tm-item__meta">{len([r for r in rows if r["html"]])} von {len(rows)} Spielern mit Report</span></button>'] + [
        f'<button class="tm-item{"" if r["html"] else " is-stub"}" type="button" id="{e(r["key"])}" data-tab="{e(r["key"])}" aria-pressed="false">'
        f'<span class="tm-item__nr">{e(r["nr"])}</span><span class="tm-item__name">{e(r["label"])}</span>'
        f'<span class="tm-item__meta">{meta(r)}</span></button>' for r in rows]
    payload = {"players": [{"key": r["key"], "label": r["label"], "title": f"{r['nr']} · {r['label']}", "note": r["note"],
                            "html": r["html"]} for r in rows]}
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    css = (A / "toolbox-ui.css").read_text(encoding="utf-8") + "\n" + (A / "report.css").read_text(encoding="utf-8") + TEAM_CSS
    title = f"Mannschaftsvorbereitung {doc['team']}"
    html = f"""<!doctype html>
<html lang="de" data-theme="light">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title><style>{css}</style></head>
<body>
<header class="tm-bar is-open" id="tm-bar">
  <div class="tm-bar__top"><h1>{e(doc['team'])}</h1>
  <span class="tm-meta">{e(STAGE_DE[doc['stage']])} · {len(rows)} Spieler · Stand {e(doc['generated'].replace('T', ' '))}</span>
  <button class="tm-current" id="tm-current" type="button" aria-expanded="true" aria-controls="tm-grid">
  <span data-current>Übersicht</span>{icon("chev", "tb-icon tb-chevron")}</button></div>
  <nav class="tm-grid" id="tm-grid" aria-label="Spieler">{''.join(tabs)}</nav>
</header>
<div class="tm-main">
  <div class="tm-panel" id="tm-overview">{overview(doc, rows)}</div>
  <div class="tm-panel" id="tm-stub" hidden><div class="tm-stub tb-empty">{icon("info")}<h2 data-stub-name></h2><p data-stub-note></p>
  <p class="tb-meta">Partien nachliefern (ChessBase-PGN in output/players/&lt;slug&gt;/inbox/ oder im Download-Ordner), dann die Stufe für diesen
  Spieler erneut ausführen und <code>python briefing.py team-render {e(tdir.name)} --stage {e(doc['stage'])}</code>.</p></div></div>
  <iframe class="tm-frame" id="tm-frame" title="Report" hidden></iframe>
</div>
<script id="team-data" type="application/json">{data}</script>
<script>{TEAM_JS}</script>
</body></html>"""
    out = tdir / f"team_{team_slug(doc['team'])}_{doc['stage']}.html"
    tmp = out.with_name(f".{out.name}.tmp")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(out)
    return out

