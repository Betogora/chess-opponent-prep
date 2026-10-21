# Architektur

## Drei Stufen, ein Programm
| Stufe | Einstieg | Quellen | Engine | Text | Daten / Report |
|---|---|---|---|---|---|
| scout-fast | `modes/scout.py` (`briefing.py scout`) | inbox (ChessBase, chess-results), chess-results-Abruf mit Zeitlimit | – | Regeln im Programm | `output/players/<slug>/scout/`, `scout_<slug>.html` |
| briefing-medium | `modes/medium.py` (`briefing.py brief`) | wie scout; Lichess-Übertragungen nur als Ersatz | 20 jüngste Partien einer Farbe, Zeitgrenze | Agent, eine Seite | `output/players/<slug>/medium_als-weiss/`, `briefing_<slug>_als-weiss.html` |
| research-deep | `pipeline.prepare` (`briefing.py prepare`) | alle | alle Partien | Agent, beide Seiten | `output/players/<slug>/`, `briefing_<slug>.html` |

- `modes/common.py`: `Deadline` (Zeitgrenze ab Start), `timed()` (Netzschritt mit Zeitlimit im Hintergrund-Thread),
  `fast_sources()`, `pull_download()` (ChessBase-PGN aus dem Download-Ordner), `plain_annotation()`/`plain_viewer()`
  (Partien ohne Engine für Baum und Viewer), `write_atomic()`.
- Die Engine bekommt in briefing-medium einen Abbruchzeitpunkt (`engine.analyse_games(deadline=…)`); zurück kommen nur
  fertige Partien. Gleiche Tiefe und gleicher Cache (`output/players/<slug>/analysis/`, `cache/positions.sqlite`) wie research-deep:
  eine spätere volle Recherche rechnet diese Partien nicht noch einmal.
- `dossier.build(tree_games=…)`: Eröffnungsbaum und Linien-Belege aus allen Partien, Engine-Belege aus den analysierten.
- `dossier.mode` steuert Validator (`sides`, `min_plan_steps`) und Renderer (eine Seite, Startfarbe, Plakette).
- `render/html.py`: Abschnitte + `page()` (gemeinsamer Seitenrahmen, atomar geschrieben); `render/scout.py`: Steckbrief.
  `render_player(<ordner>)` wählt die Ansicht nach `dossier.mode`.
- Mannschaft (`modes/team.py`, Skill chess-opponent-team-prep): `lineup.py` liest die Aufstellung (Ligaserver-Seite
  `…/ligen/<liga>-<saison>/m/<id>/`, Bezirksseiten fallen auf nsv-online.de zurück; `team.json`; Liste), wählt Bretter
  (`--boards`, gegen die Spielernummer), setzt die Farbe je Brett und ruft je Spieler `scout.run_result`,
  `medium.run_result` bzw. `pipeline.prepare` auf. `render/team.py` baut daraus eine Seite: Übersicht + Spielerknöpfe,
  jeder Einzelreport gzip/base64 eingebettet und erst beim Umschalten entpackt (iframe `srcdoc`).
  Daten: `output/teams/<mannschaft>/team_<stufe>.json`.
- Beide Farben (`--color both`): scout zeigt beide gleichrangig; medium analysiert je Farbe `games/2` Partien,
  Matchplan mit beiden Seiten (`dossier.mode.sides`).
- Neue Stufe: Modul in `modes/` mit `run(...) -> int`, Befehl in `briefing.py`, Ansicht in `render/`, Skill in
  `skills/<name>/` + Verweis in `.claude/skills/<name>/`, Zeile in AGENTS.md und in `modes.STAGES`.

## research-deep im Detail

```
Eingabe (FIDE-ID | Name | Link)
  │ identify.py          FIDE (Lichess-Spiegel), DSB-Suche → Identity (Name, FIDE, Verein, DWZ)
  ▼
Quellen (sources/)       jede Quelle gekapselt; Ausfall wird protokolliert, Lauf geht weiter
  ├ lichess.py           Broadcast-Turniere des FIDE-Spielers (mit [%clk])
  ├ chessbase.py         players.chessbase.com – PGN aus inbox/ (Browser-Schritt) oder direkt
  ├ chessresults.py      chess-results.com – Turnierliste (Spielersuche) + hochgeladene Partien (Partiesuche, PGN-Download);
  │                      bei Bot-Prüfung Browser-Hinweis, PGN dann aus inbox/chessresults_*.pgn
  ├ local.py             output/players/<slug>/inbox/*.pgn (manuelle Importe, z. B. snoopchess_*.pgn), Sammelordner pgn/
  └ nsv.py               Mannschaftsergebnisse nsv-online.de (Niedersachsen; Erweiterungspunkt für andere Verbände)
  ▼
games.py                 PGN → Datensätze, Dublettenabgleich über Quellen hinweg (merge: Monat, Gegner, Farbe, 16 Halbzüge);
                         Partien ohne Datum/Ergebnis (Result "*") laufen mit, Scores zählen nur Partien mit Ergebnis
ratings.py               FIDE-Elo-Verlauf
engine.py                Stockfish: Vorab-Rechnung aller Stellungen (Tiefe 14), verdächtige Züge nachgerechnet (Tiefe 18),
                         zweitbester Zug (MultiPV 2, Tiefe 14) wo der Spieler am Zug ist; je Stellung Bewertung, WDL,
                         bester Zug, Hauptvariante; Matt ohne Engine
metrics.py               je Zug: Erwartungswert, Fehlerklasse, Kipp-Punkt, Phase, Uhr; je Farbe/Phase aggregiert
openings.py              Lichess-ECO-Namen (CC0, Stellungsvergleich), Eröffnungsbaum
online/                  Online-Accounts und Kurse
  ├ platforms.py         Lichess/Chess.com-Endpunkte, Vollexport (inkrementell), geschichtete Stichprobe, Team-Mitglieder
  ├ lichess_analysis.py  Lichess-Serveranalyse → Stellungsformat von engine.py (kein lokales Stockfish fuer online)
  ├ fingerprint.py       Eröffnungs-Fingerabdruck (Lift gegenüber allen Kandidaten)
  ├ rating_map.py        Online-Wertung → erwartete Elo (nichtlinear je Plattform/Bedenkzeit), DWZ → Elo, Plausibilität (z)
  ├ accounts.py          Kandidaten, Konfidenzformel (WEIGHTS), research.json (inkl. username_patterns), Online-Vollbaum,
  │                      Trends, Abgleich, Belege O…; läuft auch ohne Turnierpartien (dann ohne Fingerabdruck)
  └ chessable.py         Accountprüfung, Kurssuche, Kursfamilien-Abgleich (data/course_signatures.json)
profile.py               Spielerprofil: 8 Achsen (Vorliebe getrennt von Können), Teil-Elo je Stellungsart/Phase über
                         Vergleichskurven, Typ-Etikett, Belege P…; Zielkorridor aus me.json, Belege M…
calibrate.py             Vergleichskurven aus Lichess-Übertragungen (FIDE-Elo, lange Bedenkzeit) → data/elo_curves.json
dossier.py               Belege F… (mit scope white/black/all), Schlüsselstellungen K…, brief.md
  ▼
[Agent schreibt briefing.json]
  ▼
validate.py              Pflichtfelder, Perspektive, Online/Turnier-Trennung, legale Züge, Zahlen ↔ Belege, Floskeln
pipeline.validate        + Beleg-Stempel (_evidence_snapshot)
render/                  html.py (Abschnitte), charts.py (SVG), assets/ (UI-CSS, report.css, report.js)
maintenance.py           setup, doctor, pack
```

## Determinismus
- Engine: Tiefenlimit, `Threads=1`, feste Abschnitte (`ENGINE_CHUNK_PLIES`) mit `ucinewgame` je Abschnitt → gleiche Zahlen
  bei gleicher Stockfish-Version, unabhängig von der Zahl der Prozesse. Nachgerechnet wird ein Zug, der aus umkämpfter
  Stellung (`TRIAGE_LIVE`) vorab mehr als `TRIAGE_LOSS` Erwartungswert verliert; die Auswahl hängt nur von der Vorab-Rechnung ab.
- Stufen je Partie: base (alle Stellungen) → deep (verdächtige Züge) → alt. Der zweitbeste Zug (MultiPV 2) wird nur
  dort gerechnet, wo `profile.move_class` ihn auswertet (`engine.alt_positions`: eigener Zug ab `PROFILE_MIN_MOVE`,
  umkämpft, nicht Endspiel); geprüft an 91 Partien: identische Profilwerte bei 31 % der bisherigen alt-Stellungen.
- Last: `ENGINE_WORKERS` = alle Kerne (Umgebungsvariable `BRIEFING_WORKERS` überschreibt), Priorität „niedriger als
  normal“, Windows-Energiedrosselung (EcoQoS) für die Engine aus. Parallele `prepare`-Läufe (auch mehrere Gegner in einem
  Aufruf, `pipeline.prepare_many`, bis zu 3 gleichzeitig) teilen sich die Plätze über Sperrdateien in `cache/engine_slots/`.
- Stellungs-Cache `cache/positions.sqlite` (Engine, Tiefe, MultiPV, FEN ohne Zugnummer): wiederkehrende Stellungen
  (Eröffnungen, Neuläufe, andere Gegner) kosten keine Engine-Zeit. Ein Treffer stammt aus einem anderen Abschnitt mit
  anderem Hash-Inhalt; die Zahlen können daher in der letzten Stelle von einem kalten Lauf abweichen.
- Cache: Analysen in voller Tiefe 18 (ältere Läufe) bleiben gültig; fehlt der zweitbeste Zug, wird nur er ergänzt.
- Netz: Online-Kandidatensuche (`accounts.discover`) läuft in `pipeline.prepare` parallel zur Engine. Gleichzeitige
  Anfragen je Host über `util.host_gate` (Lichess 1, Chess.com 4); breite Schritte (Vereinsmitglieder, Chess.com-Club)
  enden nach `ONLINE_BUDGET_S`, Namens-, Muster- und research.json-Kandidaten werden immer vollständig geprüft.
- Sortierungen mit vollständigem Schlüssel (Gleichstand → Zugfolge/ID), damit Beleg-IDs stabil bleiben.
- Online-Stichprobe: `sample_stratified` (12 Zeitabschnitte, gleiche Quote, lange Bedenkzeit und analysierte Partien zuerst, kein Zufall).
- Online-Baum: alle Partien; Knoten unter `min(5, Partien/400)` Partien entfallen, außer sie liegen auf einer Stichprobenpartie.
- Caches: `cache/` (HTTP 1–365 Tage je nach Quelle; `cache/chessresults/` 24 h), `output/players/<slug>/analysis/` (Engine je Partie).

## Erweiterungspunkte
- Weitere Landesverbände: neues Modul in `sources/` nach dem Muster `nsv.py` (liefert PGN-Text, Ergebniszeilen, Protokoll).
- Weitere Partiequelle: Modul in `sources/` mit `collect(ident, inbox) -> (PGN-Text, Protokoll)`, in `pipeline.prepare`
  eintragen. Quellen mit Bot-Prüfung melden `status: browser_noetig` + `hint` (`open`, `fetch_in_page` oder `steps`,
  `save_as`) und lesen danach ihre Datei aus `inbox/` (Präfix in `local.py` ausschließen).
- Dienste mit Login (SnoopChess, Premium-Datenbanken): nicht anbinden, sondern manuell importieren (PGN in `inbox/`,
  Account-Hinweise als `username_patterns`).
- Neue Online-Plattform: Funktionen in `online/platforms.py` + Kandidatensuche in `online/accounts.discover`.
- Neue Kennzahl: in `metrics.color_stats` berechnen, als Beleg in `dossier.build` ausgeben, ggf. im Renderer zeigen.
- Schwellen und Gewichte: `config.py` (Fehlerklassen, Phasen, Stichprobe) und `online/accounts.WEIGHTS`.

## Ordner eines Gegners (`output/players/<slug>/`)
| Datei | Inhalt |
|---|---|
| `identity.json` | Identifikation mit Notizen und Alternativen |
| `inbox/` | manuell oder per Browser geholte PGNs (`chessbase_*`, `chessresults_*` lesen ihre Quellen, alles andere `local.py`) |
| `games.pgn` | zusammengeführte Turnierpartien |
| `analysis/` | Engine-Cache je Partie |
| `dossier.json`, `viewer.json` | Kennzahlen, Bäume, Belege / Zugdaten für den Viewer |
| `brief.md` | Schreibgrundlage für den Matchplan |
| `online_accounts.json` | Kandidaten mit Konfidenz und Begründung, Stichprobe |
| `research.json` | manuelle Entscheidungen (Accounts, Teams, Clubs, `extra_candidates`, `username_patterns`) |
| `engine_checks.json` | Belege E… |
| `briefing.json` | Matchplan (vom Agenten) |
| `briefing_<slug>.html` | fertiger Report (research-deep) |
| `scout/`, `scout_<slug>.html` | Daten und Report von scout-fast |
| `medium_als-weiss/`, `briefing_<slug>_als-weiss.html` | Daten (dossier, brief.md, briefing.json, engine_checks) und Report von briefing-medium; analog `als-schwarz` |
| `me.json` | optional: Eigenprofil nur für dieses Briefing (überlagert `me.json` in der Projektwurzel) |
| `me_used.json` | tatsächlich verwendetes Eigenprofil (Nachvollziehbarkeit) |

Projektwurzel: `me.json` (Voreinstellung Eigenprofil, privat, nicht in `pack`). `chess_briefing/data/elo_curves.json`
(Vergleichskurven, nur Durchschnittswerte, in `pack`), `data/calibration_tours.json` (Turnierliste dafür).

## Spielerprofil
- „scharf“ = Stellung mit nur einem guten Zug: der zweitbeste Zug (MultiPV 2) ist ≥ `ONLY_MOVE_GAP` schlechter;
  Endspiel eigene Klasse; Züge vor `PROFILE_MIN_MOVE` zählen nicht.
- Teil-Elo = Fehlerquote der Klasse über die Kurve `ln(Quote) = a + b·(Elo−2000)/100` in Elo übersetzt, vorher mit
  `PROFILE_SHRINK_MOVES` Zügen zur Quote seiner Elo gezogen; Spanne aus ±√(Fehler+1).
- Partie-Charakter nur aus fehlerunabhängigen Merkmalen; Vergleich mit Mittel/Streuung seines Ratingbands.
- Etikett: Angreifer/Stratege aus dem Partie-Charakter, rechenstark/-schwach ab `PROFILE_SKILL_DIFF` Abstand der
  Teil-Elo scharf − ruhig (größer als die Spannen), sonst Allrounder.
- Zielkorridor: Stellungsart mit dem kleinsten Abstand seiner Teil-Elo zu deiner Elo; je höchstens eine Stufe für
  Streuung (Sieg nötig / Remis reicht / deutlich stärker) und eigenen Stil.
- Grenzen: Gegnerstärke fließt nicht in die Kurven ein; Kurven gelten für lange Bedenkzeit.
