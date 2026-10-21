"""Skill chess-opponent-team-prep: eine ganze Mannschaft mit einer der drei Stufen vorbereiten.

Aufstellung (Ligaserver-Seite, team.json oder Liste) -> Auswahl der Bretter -> Farbe je Brett -> je Spieler die Stufe
scout (scout-fast), medium (briefing-medium) oder research (research-deep) -> Mannschaftsseite mit Umschalter oben.
Daten: output/teams/<mannschaft>/team_<stufe>.json ; Seite: output/teams/<mannschaft>/team_<mannschaft>_<stufe>.html
(die Einzelreports bleiben in output/players/<slug>/)
"""
from __future__ import annotations

import datetime as dt
import time

from .. import config, lineup as L
from ..util import log, read_json
from .common import FOLDER, timed, write_json_atomic

STAGES = ("scout", "medium", "research")


def report_path(slug: str, stage: str, color: str):
    """Report einer Stufe im Gegnerordner (dieselben Dateien wie bei den Einzel-Skills)."""
    pdir = config.PLAYERS_DIR / slug
    return {"scout": pdir / f"scout_{slug}.html", "medium": pdir / f"briefing_{slug}_{FOLDER[color]}.html",
            "research": pdir / f"briefing_{slug}.html"}[stage]


def team_dir(team: str):
    return config.TEAMS_DIR / L.team_slug(team)


def run(sources: list[str], stage: str, color: str | None = None, board1: str | None = None, boards: str | None = None,
        team: str = "", budget: float | None = None, n_games: int = 20) -> int:
    t0 = time.monotonic()
    lu = L.load(sources, team)
    players = L.select(lu, boards)
    L.assign_colors(players, color, board1)
    tdir = team_dir(lu["team"])
    log(f"== Mannschaft {lu['team']} · Stufe {stage} · {len(players)} Spieler · Quelle {lu['source']}")
    from ..identify import resolve
    for p in players:                         # Identitaet vorab (eindeutig per FIDE-ID weiter an die Stufe)
        ident = timed(f"identität {p['name']}", lambda p=p: resolve(L.player_input(p), federation="GER" if lu.get("source", "").startswith("https://nsv") else None), 45)
        if ident is None:
            p.update(status="stub", note="nicht eindeutig gefunden – FIDE-ID in team.json eintragen (Feld fide_id)")
            continue
        p.update(slug=ident.slug, fide_id=ident.fide_id, display=ident.display,
                 dwz=p.get("dwz") or ident.dsb.get("dwz"), elo=ident.elo.get("standard"))

    todo = [p for p in players if p.get("slug")]
    if stage == "research":
        from ..pipeline import prepare
        for p in todo:
            ts = time.monotonic()
            rc = prepare(str(p["fide_id"] or p["slug"]), fide_id=p["fide_id"])
            p.update(seconds=round(time.monotonic() - ts, 1), rc=rc)
    else:
        from . import medium, scout
        for p in todo:
            ts = time.monotonic()
            if stage == "scout":
                r = scout.run_result(str(p["fide_id"] or L.player_input(p)), p["color"], budget or 90, fide_id=p["fide_id"])
            else:
                r = medium.run_result(str(p["fide_id"] or L.player_input(p)), p["color"], n_games, budget or 300,
                                      fide_id=p["fide_id"])
            p.update(seconds=round(time.monotonic() - ts, 1), rc=r["rc"], timing=r.get("timing"), games=r.get("games"),
                     analysed=r.get("analysed"), note=r.get("note") or p.get("note", ""))
    for p in todo:
        p["status"] = "ok" if report_path(p["slug"], stage, p["color"]).exists() else "stub"
        if p["status"] == "stub" and not p.get("note"):
            p["note"] = "kein Report (ChessBase-PGN fehlt?)"
    total = round(time.monotonic() - t0, 1)
    doc = {"team": lu["team"], "source": lu["source"], "stage": stage, "boards": boards, "generated":
           dt.datetime.now().isoformat(timespec="minutes"), "seconds": total, "players": players}
    write_json_atomic(tdir / f"team_{stage}.json", doc)
    out = render(tdir, stage)
    ok = sum(p["status"] == "ok" for p in players)
    log(f"-- Mannschaft fertig: {ok} von {len(players)} Spielern mit Report, {total:.0f} s")
    for p in players:
        log(f"   {p.get('nr'):>4} {p.get('display') or p['name']:<28} {p['color']:<5} {p['status']:<4} "
            f"{p.get('seconds', 0):>6.1f} s  {p.get('note', '')}")
    log(f"   Seite: {out}")
    if stage in ("medium", "research"):
        log("   Nächster Schritt: je Spieler den Matchplan schreiben (siehe Skill der Stufe), dann "
            f"`python briefing.py team-render {tdir.name} --stage {stage}`")
    return 0 if ok else 1


def render(tdir, stage: str):
    from ..render.team import render_team
    return render_team(tdir, read_json(tdir / f"team_{stage}.json"))
