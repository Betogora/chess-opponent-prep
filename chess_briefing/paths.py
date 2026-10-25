"""Alle Datei- und Ordnernamen im Ausgabeordner an einer Stelle.

output/players/<slug>/                    gemeinsam: identity.json, inbox/, analysis/, me.json, die Reports
  scout_<slug>.html       + scout/           scout-fast
  briefing_<slug>[_ich-weiss|_ich-schwarz].html + briefing[_ich-weiss|_ich-schwarz]/   briefing-medium
  research_<slug>.html    + research/        research-deep
  je Stufenordner: dossier.json, viewer.json, dossier.md (Vorlage fuer den Agenten), matchplan.json (vom Agenten)
output/teams/<team>/team_<team>_<stufe>.html + team_<team>_<stufe>.json

Die Farbe steht nur im Namen, wenn sie den Inhalt einschraenkt: ich-weiss / ich-schwarz = Farbe des NUTZERS.
Alte Namen (vor 1.1: medium_als-weiss/, briefing.json, research.json, brief.md, research-Daten im Spielerordner)
werden weiter gelesen und mit migrate_player() umgestellt.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import config

STAGES = ("scout", "briefing", "research")
STAGE_ALIASES = {"medium": "briefing"}                 # alter Name der mittleren Stufe
COLOR_SUFFIX = {"white": "ich-weiss", "black": "ich-schwarz", "both": ""}

MATCHPLAN = "matchplan.json"                           # vom Agenten geschrieben
AGENT_BRIEF = "dossier.md"                             # Vorlage fuer den Agenten
ACCOUNTS = "accounts.json"                             # Account-Entscheidungen des Nutzers (research-deep)
LEGACY = {MATCHPLAN: "briefing.json", AGENT_BRIEF: "brief.md", ACCOUNTS: "research.json"}

# Dateien von research-deep, die frueher direkt im Spielerordner lagen
RESEARCH_FILES = ("dossier.json", "viewer.json", "brief.md", "dossier.md", "briefing.json", "matchplan.json",
                  "engine_checks.json", "games.pgn", "sources.json", "team_results.json", "online_accounts.json",
                  "research.json", "accounts.json", "me_used.json")
LEGACY_FOLDERS = {"medium_als-weiss": "briefing_ich-weiss", "medium_als-schwarz": "briefing_ich-schwarz",
                  "medium_beide": "briefing"}


def stage(name: str) -> str:
    return STAGE_ALIASES.get(name, name)


def suffix(color: str | None) -> str:
    s = COLOR_SUFFIX.get(color or "both", "")
    return f"_{s}" if s else ""


def player_dir(slug: str) -> Path:
    return config.PLAYERS_DIR / slug


def stage_dir(pdir: Path, name: str, color: str | None = None) -> Path:
    """Datenordner einer Stufe: scout/, briefing[_ich-weiss]/, research/."""
    name = stage(name)
    return pdir / (f"briefing{suffix(color)}" if name == "briefing" else name)


def report_path(pdir: Path, name: str, color: str | None = None) -> Path:
    """Report einer Stufe im Spielerordner: scout_<slug>.html, briefing_<slug>[_ich-weiss].html, research_<slug>.html."""
    name = stage(name)
    return pdir / f"{name}_{pdir.name}{suffix(color) if name == 'briefing' else ''}.html"


def player_root(d: Path) -> Path:
    """Spielerordner zu einem Stufenordner (oder dem Spielerordner selbst)."""
    return d if d.parent == config.PLAYERS_DIR else d.parent


def file(d: Path, name: str) -> Path:
    """Pfad zum Lesen: neuer Name, sonst der alte (LEGACY), falls nur dieser existiert."""
    p = d / name
    old = d / LEGACY.get(name, name)
    return old if not p.exists() and old.exists() else p


def data_dir(arg: str) -> Path:
    """Ordner-Argument der Befehle validate/render/line: <slug> = research-deep, sonst <slug>/<stufenordner>.
    Alte Ordnernamen (medium_als-weiss) werden auf die neuen abgebildet."""
    parts = arg.replace("\\", "/").strip("/").split("/")
    pdir = player_dir(parts[0])
    migrate_player(pdir)
    if len(parts) == 1:
        return pdir / "research"
    sub = LEGACY_FOLDERS.get(parts[1], parts[1])
    return pdir / sub


def migrate_player(pdir: Path) -> list[str]:
    """Alte Namen im Spielerordner umstellen (idempotent). Rueckgabe: was geaendert wurde."""
    done: list[str] = []
    if not pdir.is_dir():
        return done
    for old, new in LEGACY_FOLDERS.items():
        if (pdir / old).is_dir() and not (pdir / new).exists():
            (pdir / old).rename(pdir / new)
            done.append(f"{old}/ -> {new}/")
    if (pdir / "dossier.json").exists():                 # research-Daten aus dem Spielerordner in research/
        rdir = pdir / "research"
        rdir.mkdir(exist_ok=True)
        for f in RESEARCH_FILES:
            if (pdir / f).exists() and not (rdir / f).exists():
                shutil.move(str(pdir / f), str(rdir / f))
                done.append(f"{f} -> research/")
    for sub in [p for p in pdir.iterdir() if p.is_dir() and p.name not in ("inbox", "analysis")]:
        for new, old in LEGACY.items():
            if (sub / old).exists() and not (sub / new).exists():
                (sub / old).rename(sub / new)
                done.append(f"{sub.name}/{old} -> {new}")
    return done


def legacy_report(pdir: Path, color: str | None) -> Path:
    """Alter Name des briefing-medium-Reports (vor 1.1); render loescht ihn, sobald der neue geschrieben ist."""
    old = {"white": "als-weiss", "black": "als-schwarz"}.get(color or "both", "beide")
    return pdir / f"briefing_{pdir.name}_{old}.html"


def migrate_team(tdir: Path) -> list[str]:
    team_slug = tdir.name
    done: list[str] = []
    for old_stage in ("scout", "medium", "research"):
        new_stage = stage(old_stage)
        old = tdir / f"team_{old_stage}.json"
        new = tdir / f"team_{team_slug}_{new_stage}.json"
        if old.exists() and not new.exists():
            old.rename(new)
            done.append(f"{old.name} -> {new.name}")
    return done


def migrate_all() -> int:
    """Befehl `migrate`: alle Spieler- und Mannschaftsordner auf die Namen ab 1.1 umstellen und Reports neu rendern."""
    from .render.html import render_player
    from .util import log
    for pdir in sorted(p for p in config.PLAYERS_DIR.glob("*") if p.is_dir()):
        done = migrate_player(pdir)
        for sub in sorted(d for d in pdir.iterdir() if d.is_dir() and (d / "dossier.json").exists()):
            try:
                render_player(sub)
            except Exception as ex:  # noqa: BLE001 - ein kaputter Ordner haelt die anderen nicht auf
                log(f"   ! {pdir.name}/{sub.name}: {type(ex).__name__}: {ex}")
        if done:
            log(f"   {pdir.name}: " + "; ".join(done))
    from .modes.team import render as render_team
    for tdir in sorted(p for p in config.TEAMS_DIR.glob("*") if p.is_dir()):
        done = migrate_team(tdir)
        for f in sorted(tdir.glob(f"team_{tdir.name}_*.json")):
            render_team(tdir, f.stem.rsplit("_", 1)[1])
        old = tdir / f"team_{tdir.name}_medium.html"
        if old.exists():
            old.unlink()
            done.append(f"{old.name} entfernt")
        if done:
            log(f"   {tdir.name}: " + "; ".join(done))
    log("-- Namen umgestellt")
    return 0
