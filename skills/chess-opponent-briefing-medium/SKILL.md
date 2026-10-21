---
name: chess-opponent-briefing-medium
description: "Gegnervorbereitung für genau eine Partie mit feststehender Farbe (Stufe 2 von 3, Programm höchstens 5 min, mit Matchplan meist unter 10 min). Alle schnell verfügbaren Partien seiner Farbe (ChessBase, chess-results, inbox) für Eröffnungsbaum und Partien-Viewer, Stockfish nur für die 20 jüngsten davon, kurzer belegter Matchplan nur für die Farbe des Nutzers; keine Online-Accounts. Auslöser: „Vorbereitung auf …, ich habe Weiß/Schwarz“, „Briefing für morgen gegen …“, „mittlere Vorbereitung“."
version: 1.0.0
---

# chess-opponent-briefing-medium

Stufe 2 von 3 ([scout-fast](../chess-opponent-scout-fast/SKILL.md) · [research-deep](../chess-opponent-research-deep/SKILL.md)).
Rechnen macht `briefing.py` mit fester Zeitgrenze; der Agent schreibt nur den kurzen Matchplan.

Ergebnis: `output/players/<slug>/briefing_<slug>_als-weiss.html` bzw. `_als-schwarz.html`
(Daten in `output/players/<slug>/medium_als-weiss/`). Die Engine-Analysen landen im gemeinsamen Cache und werden von
research-deep später wiederverwendet.

## Ablauf
| # | Schritt | Fertig, wenn |
|---|---|---|
| 1 | Farbe erfragen, falls nicht genannt („Welche Farbe hast du – oder beide?“) | Farbe steht fest oder „beide“ |
| 2 | `python briefing.py brief "<Eingabe>" --color white\|black\|both` | „fertig: …html“ und „Zeiten: …“ |
| 3 | ChessBase-PGN beschaffen, nur wenn gemeldet (wie [scout-fast](../chess-opponent-scout-fast/SKILL.md#chessbase-pgn-beschaffen)), dann Schritt 2 erneut | Partien da |
| 4 | Datengrundlage prüfen: < 5 analysierte Partien → kein Matchplan, Nutzer informieren, scout-HTML genügt | – |
| 5 | `brief.md` im Datenordner lesen, `briefing.json` dort schreiben – **nur** `as_white` (Nutzer hat Weiß) bzw. `as_black`; bei `both` beide Seiten | Datei da |
| 6 | `python briefing.py validate <slug>/medium_als-weiss` und `python briefing.py render <slug>/medium_als-weiss` | „✓ Briefing gültig“, HTML |
| 7 | Bericht: Pfad, analysierte/alle Partien, Zeiten, drei Kernpunkte | – |

Beide Farben (`--color both`): je Farbe bis zu 10 Partien analysiert (insgesamt `--games`), Datenordner `medium_beide/`,
Report `briefing_<slug>_beide.html`, Matchplan mit `as_white` **und** `as_black`.
Optionen: `--games 20` (so viele jüngste Partien analysieren), `--budget 300` (Sekunden bis zur fertigen HTML,
vom Programm eingehalten: was bis dahin nicht analysiert ist, läuft ohne Engine mit).
Theorie-Empfehlungen prüfen: `python briefing.py line <slug>/medium_als-weiss "<SAN>" --scope black` (Nutzer hat Weiß)
bzw. `--scope white`.

## Matchplan kurz halten
Schema und Stil wie research-deep ([briefing-schema.md](../chess-opponent-research-deep/references/briefing-schema.md),
[writing-guide.md](../chess-opponent-research-deep/references/writing-guide.md)), aber nur eine Seite:
`headline`, `profile_summary` (falls Profil), `summary` (3), die eine Seite mit `goal`, 1–3 Eröffnungskarten,
3–5 Plan-Schritten (Pflicht: Mittelspiel, Zeit, Abwicklung/Endspiel), `avoid` 1–2, `watch` 2–3, `moments`.
Kein `online`, keine zweite Farbe (der Validator lehnt sie ab).

## Grenzen offen nennen (in `watch`)
- Engine-Belege (Fehler, Phasen, Schlüsselstellungen, Profil) stammen aus höchstens 20 Partien, oft weniger:
  Teil-Elo und Phasenwerte sind dann „dünn“.
- Eröffnungsbaum und Linien-Scores kommen aus allen Partien seiner Farbe, ohne Lichess-Übertragungen (nur als Ersatz,
  wenn ChessBase zu wenige liefert) und ohne Online-Partien.
