# AGENTS.md – chess-opponent-prep

Anweisungen für KI-Agenten (Claude, GPT/Codex, Gemini, …) und Menschen, die in diesem Ordner arbeiten.

## Was das ist
Eine lokale Pipeline zur Vorbereitung auf einen Schachgegner, in drei Stufen. Eingabe: FIDE-ID, Name oder Profil-Link.
Ausgabe: eine offline lauffähige HTML-Datei in `output/players/<slug>/`. Alles Rechnen macht `briefing.py`; der Agent schreibt
höchstens den Matchplan-Text.

## Welche Stufe wann
| Stufe (Skill) | Wann | Dauer | Ergebnis |
|---|---|---|---|
| [chess-opponent-scout-fast](skills/chess-opponent-scout-fast/SKILL.md) | „kurz vor der Runde“, „schneller Check“, „Steckbrief“ | < 1 min, kein Agententext | `scout_<slug>.html`: alle Partien beider Farben, Repertoire mit Score, Form |
| [chess-opponent-briefing-medium](skills/chess-opponent-briefing-medium/SKILL.md) | Vorbereitung auf eine Partie, Farbe steht fest | Programm ≤ 5 min (+ Matchplan) | `briefing_<slug>_als-weiss.html`: Engine für 20 Partien seiner Farbe, Plan für deine Farbe |
| [chess-opponent-research-deep](skills/chess-opponent-research-deep/SKILL.md) | „ausführlich“, „gründlich“, „Recherche“, beide Farben | 15–30 min | `briefing_<slug>.html`: alle Quellen, Online-Accounts, Profil, Plan für beide Farben |
| [chess-opponent-team-prep](skills/chess-opponent-team-prep/SKILL.md) | „Mannschaft vorbereiten“, Aufstellung/Link mit Brettern | je nach Stufe × Spieler | `output/teams/<mannschaft>/team_<mannschaft>_<stufe>.html`: ruft je Spieler eine Stufe auf, Spieler oben umschaltbar |

Ohne klare Angabe: nach der Zeit fragen, die der Nutzer hat. Bei scout-fast und briefing-medium die Farbe des Nutzers
erfragen, falls sie fehlt (`--color` = Farbe des **Nutzers**; „beide“ ist erlaubt: `--color both`).

## Einrichten
```bash
python -m pip install -r requirements.txt
python briefing.py setup       # Stockfish laden
python briefing.py doctor      # Umgebung prüfen
python briefing.py selftest    # Offline-Tests
```
Python ≥ 3.12, Windows/macOS/Linux. Kein Login, kein API-Schlüssel.

## Befehle
| Befehl | Stufe | Zweck |
|---|---|---|
| `python briefing.py scout "<Eingabe>" --color white\|black\|both` | scout-fast | Steckbrief ohne Engine, Zeitgrenze `--budget` (90 s) |
| `python briefing.py brief "<Eingabe>" --color white\|black\|both` | briefing-medium | eine Farbe (oder beide, je 10 Partien), Engine für `--games 20`, Zeitgrenze `--budget` (300 s) |
| `python briefing.py prepare "<Eingabe>"` | research-deep | Daten sammeln, analysieren, Dossier + `brief.md` |
| `python briefing.py team "<Aufstellung>" --stage scout\|medium\|research [--boards 101-108]` | team-prep | je Spieler eine Stufe, Mannschaftsseite |
| `python briefing.py team-render <mannschaft> --stage …` | team-prep | Mannschaftsseite nach neuen Matchplänen neu bauen |
| `python briefing.py receive "<Spieler>"` | alle | ChessBase-PGN aus dem Browser übernehmen (ohne Dialog, direkt nach `inbox/`) |
| `python briefing.py line <ordner> "<SAN>" --scope white\|black` | medium, deep | Eröffnungslinie mit Stockfish prüfen → Beleg E… |
| `python briefing.py validate <ordner> [--restamp]` | medium, deep | Matchplan prüfen |
| `python briefing.py render <ordner> [...]` | alle | HTML erzeugen |
| `python briefing.py course-add …`, `calibrate`, `pack` | Pflege | Kurs-Bibliothek, Vergleichskurven, Weitergabe-Zip |

`<ordner>` = `<slug>` (research-deep), `<slug>/medium_als-weiss` bzw. `<slug>/medium_als-schwarz` (briefing-medium),
`<slug>/scout` (scout-fast).

## Regeln für Agenten
- Nur über `briefing.py` rechnen; keine Zahlen selbst erfinden. Jede Zahl im Matchplan braucht eine Beleg-ID.
- Perspektive: `as_white` = der **Nutzer** hat Weiß → Belege über den Gegner mit Schwarz (scope `black`/`all`).
- Keine Passwörter eingeben, keine CAPTCHAs oder Bot-Prüfungen selbst lösen. Logins macht der Nutzer.
- Online-Accounts (nur research-deep) sind Vermutungen (Konfidenz). Nie als sicher darstellen; Online-Inhalte getrennt halten.
- Die schnellen Stufen nicht „aufwerten“: scout-fast ohne Engine und Text, briefing-medium ohne Online-Suche und ohne
  zweite Farbe. Wer mehr will, startet die nächste Stufe.
- Nach Code-Änderungen: `python briefing.py selftest` muss OK sein.

## Aufbau
Siehe [skills/chess-opponent-research-deep/references/architecture.md](skills/chess-opponent-research-deep/references/architecture.md).
Private Daten liegen in `output/`, `cache/`, `pgn/`, `.env`, `me.json` und gehören nicht in Weitergaben.
