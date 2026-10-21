#!/usr/bin/env python3
"""chess-opponent-prep - Kommandozeile fuer die drei Stufen der Gegnervorbereitung.

Einrichten (einmalig):
  python -m pip install -r requirements.txt
  python briefing.py setup        Stockfish (offizielles Release) nach tools/stockfish laden
  python briefing.py doctor       Python, Pakete, Engine, Netz, Schreibrechte pruefen
  python briefing.py selftest     Offline-Tests

Stufe 1 - chess-opponent-scout-fast (Steckbrief ohne Engine, Sekunden):
  python briefing.py scout "<FIDE-ID | Name | Profil-Link>" --color white|black [--budget 90]
      --color = DEINE Farbe. Alle schnell verfuegbaren Partien (ChessBase, chess-results, inbox) beider Farben,
      seine Farbe oben -> output/players/<slug>/scout_<slug>.html

Stufe 2 - chess-opponent-briefing-medium (eine Farbe, Engine fuer die juengsten Partien, Zeitgrenze):
  python briefing.py brief "<FIDE-ID | Name | Profil-Link>" --color white|black [--games 20] [--budget 300]
      -> output/players/<slug>/medium_als-weiss/ (dossier.json, brief.md) + output/players/<slug>/briefing_<slug>_als-weiss.html;
      danach briefing.json schreiben, validate/render mit <slug>/medium_als-weiss

Mannschaft - chess-opponent-team-prep (ruft je Spieler eine der drei Stufen auf):
  python briefing.py team "<Ligaserver-Mannschaftsseite | team.json | Spieler ...>" --stage scout|medium|research
      [--boards 101-108] [--color white|black|both | --board1 white|black]
      -> output/teams/<mannschaft>/team_<mannschaft>_<stufe>.html (Spieler oben umschaltbar)
  python briefing.py team-render <mannschaft> --stage ...   Mannschaftsseite nach neuen Matchplaenen neu bauen

ChessBase-Partien (alle Stufen):
  python briefing.py receive "<Spieler>" [--timeout 180]
      lokaler Empfaenger; den ausgegebenen Befehl auf der ChessBase-Profilseite im Browser ausfuehren ->
      output/players/<slug>/inbox/chessbase_<slug>.pgn (kein Dialog). Vorhandene Dateien werden wiederverwendet (7 Tage).

Stufe 3 - chess-opponent-research-deep (volle Recherche):
  python briefing.py prepare "<FIDE-ID | Name | Profil-Link>" [...] [--fide-id N] [--fed GER] [--depth 18]
      Identifizieren, Partien sammeln, Stockfish, Kennzahlen, Online-Accounts -> output/players/<slug>/dossier.json + brief.md
  python briefing.py line <slug> "1.e4 c5 2.d4 ..." --scope white|black|all
      Theorie-Linie mit Stockfish pruefen und als Beleg E<n> ablegen
  python briefing.py profile <slug> [...]
      nur das Spielerprofil neu rechnen (aus dem Cache, z. B. nach calibrate)
  python briefing.py validate <slug>[/medium_als-weiss] [--remap] [--restamp]
      output/players/<slug>/briefing.json pruefen (Perspektive, Belege, Online/Turnier-Trennung, geaenderte Belege)
  python briefing.py render <slug>[/scout | /medium_als-weiss] [...] [--no-me]
      output/players/<slug>/briefing_<slug>.html erzeugen;
      --no-me: ohne Zielkorridor aus me.json (zum Weitergeben)

Pflege und Weitergabe:
  python briefing.py calibrate [--discover] [--sides 120]
      Vergleichskurven fuer das Spielerprofil (Lichess-Uebertragungen, einmalig, ca. 1 Stunde) -> data/elo_curves.json
  python briefing.py course-add "<Suche>" --family "e4 c5 d4 cxd4 c3" --color white [--id N] [--decision "..."]
  python briefing.py pack         Zip ohne private Daten nach dist/
"""
from __future__ import annotations

import argparse
import sys

if sys.version_info < (3, 12):
    sys.exit(f"Python 3.12 oder neuer wird benötigt (gefunden: {sys.version.split()[0]}).")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="briefing", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--fide-id", type=int)
    p.add_argument("--fed")
    p.add_argument("--birth-year", type=int)
    p.add_argument("--depth", type=int)
    p.add_argument("--workers", type=int)
    p.add_argument("--force", action="store_true", help="Engine-Cache ignorieren")
    p.add_argument("--no-nsv", action="store_true")
    p.add_argument("--seasons", type=int, default=8)
    p.add_argument("--no-online", action="store_true", help="Online-Account-Suche ueberspringen")
    for name, budget, hlp in (("scout", 90, "Stufe scout-fast: Steckbrief ohne Engine"),
                              ("brief", 300, "Stufe briefing-medium: eine Farbe, Engine fuer die juengsten Partien")):
        q = sub.add_parser(name, help=hlp)
        q.add_argument("input")
        q.add_argument("--color", required=True, choices=["white", "black", "both"],
                       help="DEINE Farbe in der anstehenden Partie; both = beide Farben (brief: je 10 Partien analysiert)")
        q.add_argument("--budget", type=float, default=budget, help=f"Zeitgrenze in Sekunden (Standard {budget})")
        q.add_argument("--fide-id", type=int)
        q.add_argument("--fed")
        q.add_argument("--birth-year", type=int)
        if name == "brief":
            q.add_argument("--games", type=int, default=20, help="so viele juengste Partien analysieren (Standard 20)")
            q.add_argument("--depth", type=int)
            q.add_argument("--workers", type=int)
    tm = sub.add_parser("team", help="Skill chess-opponent-team-prep: ganze Mannschaft mit einer Stufe vorbereiten")
    tm.add_argument("sources", nargs="+", help="Ligaserver-Mannschaftsseite, team.json oder mehrere Spieler-Eingaben")
    tm.add_argument("--stage", required=True, choices=["scout", "medium", "research"])
    g = tm.add_mutually_exclusive_group()
    g.add_argument("--color", choices=["white", "black", "both"], help="DEINE Farbe an allen Brettern (Standard: both)")
    g.add_argument("--board1", choices=["white", "black"], help="DEINE Farbe am ersten gewählten Brett, danach abwechselnd")
    tm.add_argument("--boards", help="Spielernummern bzw. Bretter, z. B. 101-108 oder 1-8 oder 3,5,7")
    tm.add_argument("--team", default="", help="Mannschaftsname (überschreibt den erkannten)")
    tm.add_argument("--budget", type=float, help="Zeitgrenze je Spieler in Sekunden (scout 90, medium 300)")
    tm.add_argument("--games", type=int, default=20, help="medium: analysierte Partien je Spieler (beide Farben: je die Hälfte)")
    rc = sub.add_parser("receive", help="ChessBase-PGN aus dem Browser entgegennehmen (ohne Download-Dialog)")
    rc.add_argument("input")
    rc.add_argument("--fide-id", type=int)
    rc.add_argument("--timeout", type=float, default=180)
    tr = sub.add_parser("team-render", help="Mannschaftsseite neu bauen (nach neuen Matchplänen)")
    tr.add_argument("team", help="Ordnername unter output/teams/")
    tr.add_argument("--stage", required=True, choices=["scout", "medium", "research"])
    ln = sub.add_parser("line", help="Zugfolge mit Stockfish pruefen -> Beleg E<n>")
    ln.add_argument("slug")
    ln.add_argument("moves")
    ln.add_argument("--scope", choices=["white", "black", "all"], default="all",
                    help="white = betrifft ihn mit Weiss (fuer as_black), black = ihn mit Schwarz (fuer as_white)")
    ln.add_argument("--depth", type=int, default=22)
    ca = sub.add_parser("course-add", help="Chessable-Kurs in die Signatur-Bibliothek aufnehmen")
    ca.add_argument("query")
    ca.add_argument("--family", required=True, help='Grundlinie in SAN, z. B. "e4 c5 d4 cxd4 c3"')
    ca.add_argument("--color", required=True, choices=["white", "black"])
    ca.add_argument("--id", type=int)
    ca.add_argument("--decision", action="append", help='"<Pfad> => <Zug> | Notiz" (nur mit Quelle)')
    ca.add_argument("--source", default="")
    pr = sub.add_parser("profile", help="nur Spielerprofil neu rechnen (aus dem Cache, z. B. nach calibrate)")
    pr.add_argument("slugs", nargs="+")
    v = sub.add_parser("validate")
    v.add_argument("slug")
    v.add_argument("--restamp", action="store_true", help="geänderte Belege nach inhaltlicher Prüfung neu stempeln")
    v.add_argument("--remap", action="store_true", help="nur verschobene Belege (gleicher Text, neue ID) automatisch umstellen")
    r = sub.add_parser("render")
    r.add_argument("slugs", nargs="+")
    r.add_argument("--no-me", action="store_true", help="neutraler Report ohne Eigenprofil (zum Weitergeben)")
    s = sub.add_parser("setup", help="Stockfish laden")
    s.add_argument("--force", action="store_true")
    sub.add_parser("doctor", help="Umgebung pruefen")
    sub.add_parser("selftest", help="Offline-Tests")
    sub.add_parser("pack", help="Zip zum Weitergeben nach dist/")
    cal = sub.add_parser("calibrate", help="Vergleichskurven fuer das Spielerprofil")
    cal.add_argument("--discover", action="store_true", help="Turnierliste aus den Uebertragungen der Gegner ergaenzen")
    cal.add_argument("--sides", type=int, help="Spielerseiten je Elo-Band (Standard 120)")
    cal.add_argument("--workers", type=int)
    a = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    if a.cmd in ("setup", "doctor", "pack"):
        from chess_briefing import maintenance
        return {"setup": lambda: maintenance.setup(a.force), "doctor": maintenance.doctor, "pack": maintenance.pack}[a.cmd]()
    if a.cmd == "selftest":
        import unittest
        suite = unittest.defaultTestLoader.discover("tests", top_level_dir=".")
        return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1

    if a.cmd == "calibrate":
        from chess_briefing import calibrate
        return calibrate.run(a.sides, a.discover, a.workers)
    if a.cmd == "scout":
        from chess_briefing.modes import scout
        return scout.run(a.input, a.color, a.budget, a.fide_id, a.fed, a.birth_year)
    if a.cmd == "brief":
        from chess_briefing.modes import medium
        return medium.run(a.input, a.color, a.games, a.budget, a.depth, a.workers, a.fide_id, a.fed, a.birth_year)
    if a.cmd == "team":
        from chess_briefing.modes import team
        return team.run(a.sources, a.stage, a.color, a.board1, a.boards, a.team, a.budget, a.games)
    if a.cmd == "receive":
        from chess_briefing import receiver
        return receiver.run(a.input, a.timeout, a.fide_id)
    if a.cmd == "team-render":
        from chess_briefing import config
        from chess_briefing.modes import team
        log_out = team.render(config.TEAMS_DIR / a.team, a.stage)
        print(f"   -> {log_out}")
        return 0
    from chess_briefing import pipeline
    if a.cmd == "prepare":
        return pipeline.prepare_many(a.inputs, fide_id=a.fide_id, federation=a.fed, birth_year=a.birth_year,
                                     depth=a.depth, workers=a.workers, force=a.force,
                                     use_nsv=not a.no_nsv, seasons=a.seasons, use_online=not a.no_online)
    if a.cmd == "line":
        return pipeline.line(a.slug, a.moves, a.scope, a.depth)
    if a.cmd == "course-add":
        return pipeline.course_add(a.query, a.family, a.color, a.id, a.decision, a.source)
    if a.cmd == "profile":
        return max(pipeline.reprofile(s) for s in a.slugs)
    if a.cmd == "validate":
        return pipeline.validate(a.slug, a.restamp, a.remap)
    if a.cmd == "render":
        return pipeline.render(a.slugs, with_me=not a.no_me)
    return 1


if __name__ == "__main__":
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # Aufruf aus beliebigem Ordner
    sys.exit(main())
