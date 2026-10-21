---
name: chess-opponent-research-deep
description: "Volle Gegnerrecherche für Schach (Stufe 3 von 3, dauert 15–30 min). Aus FIDE-ID, Name oder Profil-Link (ChessBase, FIDE, Lichess, Chess.com) entsteht ein belegter Matchplan für beide Farben als offline-fähige HTML-Datei. Sammelt alle Quellen (ChessBase, Lichess-Übertragungen, chess-results, NSV), analysiert alle Partien mit Stockfish, sucht vermutliche Online-Accounts, gleicht Chessable-Kurse ab und zeigt ein Spielerprofil. Auslöser: „ausführliche Vorbereitung gegen …“, „Gegner gründlich analysieren“, „Recherche zu …“. Für schnell → chess-opponent-scout-fast, für eine Partie mit fester Farbe → chess-opponent-briefing-medium."
version: 1.0.0
---

# chess-opponent-research-deep

Stufe 3 von 3. Die anderen Stufen: [chess-opponent-scout-fast](../chess-opponent-scout-fast/SKILL.md) (Steckbrief ohne
Engine, Sekunden) und [chess-opponent-briefing-medium](../chess-opponent-briefing-medium/SKILL.md) (eine Farbe, 20 Partien
mit Engine, wenige Minuten). Welche Stufe wann: [AGENTS.md](../../AGENTS.md).

Dieser Skill ist modellunabhängig geschrieben (Claude, GPT/Codex, Gemini, …). Alles Rechnen erledigt das
Programm `briefing.py`; der Agent übernimmt nur drei klar umrissene Aufgaben: **Browser-Schritt** (falls nötig),
**Account-Checkliste** und **Matchplan schreiben**. Deterministisch und reproduzierbar ist alles außer dem Text.

Ergebnis je Gegner: `output/players/<slug>/briefing_<slug>.html` (eine Datei, offline, hell/dunkel, mobil).

## 0. Voraussetzungen (einmalig)
```bash
python -m pip install -r requirements.txt
python briefing.py setup      # lädt Stockfish (offizielles GitHub-Release) nach tools/stockfish
python briefing.py doctor     # muss "Alles bereit." melden
python briefing.py selftest   # Offline-Tests, müssen OK sein
python briefing.py calibrate  # einmalig, 1–2 h: Vergleichskurven für das Spielerprofil (Teil-Elo)
```
Python ≥ 3.12. Kein Login, kein API-Schlüssel nötig. Optional `.env` mit `LICHESS_TOKEN=` (persönlicher Lichess-Token
ohne Schreibrechte, höchstens `team:read`): schaltet die Team-Mitgliederliste frei und hebt das Ratenlimit.

## Ablauf in 6 Schritten (plus optional Schritt 0)

| # | Schritt | Wer | Fertig, wenn |
|---|---|---|---|
| 0 | Eigenprofil (optional) | Agent | `output/players/<slug>/me.json`, wenn der Nutzer etwas über sich sagt |
| 1 | `prepare` | Programm | „fertig: …dossier.json“ |
| 2 | ChessBase-PGN holen | Agent mit Browser (oder Nutzer) | Datei in `output/players/<slug>/inbox/`, `prepare` erneut |
| 3 | Account-Checkliste | Agent | Top-Kandidat bestätigt/abgelehnt in `research.json` oder bewusst offen gelassen |
| 3b | Datengrundlage prüfen | Agent | < 5 Turnierpartien und kein Account mit ≥ 20 Partien → Abbruch mit Meldung (kein Matchplan) |
| 4 | Matchplan schreiben | Agent | `briefing.json` vorhanden |
| 5 | `validate` + `render` | Programm | „✓ Briefing gültig“, HTML erzeugt |
| 6 | Abschlussbericht | Agent | Nutzer kennt Pfad, Datenbasis, Unsicherheiten |

### 0. Eigenprofil (nur wenn der Nutzer etwas über sich sagt)
Beispiel: „ich: 1900 DWZ, eher strategisch, 1.e4 / gegen 1.e4 Caro-Kann / gegen 1.d4 1…d5, Schwäche Mittelspiel,
verteidige nicht zäh, Remis reicht“. Schreibe daraus `output/players/<slug>/me.json` (gilt nur für dieses Briefing; den
Ordner gibt es nach dem ersten `prepare`, sonst vorher anlegen). Sagt der Nutzer, es gelte allgemein, oder fehlt
`me.json` in der Projektwurzel, schreibe es zusätzlich dorthin. Nur Felder, die der Nutzer nennt:
```json
{"rating": {"value": 1900, "system": "DWZ"}, "style": 2,
 "repertoire": {"white": "1.e4", "vs_e4": "1.e4 c6", "vs_d4": "1.d4 d5"},
 "strengths": [], "weaknesses": ["Mittelspiel", "Verteidigung"], "goal": "remis_ok", "note": "pragmatisch"}
```
`style` 1 = sehr ruhig … 5 = sehr scharf. Stärken/Schwächen aus: Eröffnung, Mittelspiel, Endspiel, Taktik, Strategie,
Verteidigung, Verwertung, Zeit. `goal`: `sieg` | `remis_ok` | leer. Eigene Partien werden nicht analysiert.

### 1. Vorbereiten
```bash
python briefing.py prepare "<FIDE-ID | Name | Profil-Link>"     # mehrere Gegner: mehrere Argumente
```
- Mehrdeutiger Name → Programm listet Kandidaten → erneut mit `--fide-id N` (oder `--fed GER`, `--birth-year 2000`).
- „Feeder-ID“ meint die FIDE-ID.
- Erster Lauf etwa 7–8 s je Partie (Stockfish auf allen Kernen, gemessen auf 8 Kernen), Neuläufe aus dem Cache in
  Sekunden. Mehrere Gegner in einem Aufruf laufen parallel (Log-Kennzeichen [1], [2]); die Online-Suche läuft neben der
  Engine. Langläufer im Hintergrund starten; mehrere `prepare` gleichzeitig teilen sich die Engine-Plätze.
- Achte auf diese Zeilen der Ausgabe:
  - `! ChessBase braucht den Browser` → Schritt 2
  - `! chess-results.com braucht den Browser` → wie Schritt 2, aber ohne Konsole: `hint.open` (Partiesuche) öffnen,
    `hint.steps` ausführen, Datei als `hint.save_as` speichern; Bot-Prüfung/CAPTCHA löst nur der Nutzer
  - `online: … N Partien (…), Stichprobe 100 …` → Online-Account übernommen (≥ 50 %)
  - `! Quelle … fehlgeschlagen` → im Abschlussbericht nennen, Lauf ist trotzdem gültig

### 2. ChessBase-Partien (nur wenn gemeldet)
ChessBase lässt Skripte nicht durch (Bot-Prüfung). Die Pipeline umgeht das nicht, sondern meldet
`ChessBase braucht den Browser`; ein normaler Browser lädt die Seite ohne Interaktion.
1. Profilseite öffnen: `output/players/<slug>/sources.json` → `hint.open`.
2. CAPTCHA? **Nicht selbst lösen** – den Nutzer bitten, es anzuklicken.
3. Schnellster Weg: in der Seite `hint.download_in_page` ausführen (Download `chessbase_<slug>.pgn` in den
   Download-Ordner, siehe [scout-fast](../chess-opponent-scout-fast/SKILL.md#chessbase-pgn-beschaffen)); dann die Datei nach
   `hint.save_as` verschieben (oder `scout`/`brief` übernehmen sie automatisch). Sonst wie bisher: `hint.fetch_in_page`,
   also `await (await fetch('/games/<Nachname>_<Vorname>.pgn')).text()`.
4. Text unverändert speichern als `hint.save_as` (`output/players/<slug>/inbox/chessbase_<slug>.pgn`);
   nur `0-0`→`O-O` und `d8Q`→`d8=Q` normieren.
5. `prepare` erneut.

Ohne Browser-Werkzeug: den Nutzer bitten, die Profilseite zu öffnen, die PGN per Browser-Konsole oder
„Speichern unter“ abzulegen. Die Pipeline läuft auch ohne ChessBase (dann mit weniger Partien).

### 3. Account-Checkliste (nur Top-3 aus `brief.md` → „Online-Accounts“)
Das Programm hat Kandidaten gefunden und per fester Formel bewertet (Verein, Eröffnungs-Fingerabdruck, Profil).
Für jeden der drei besten Kandidaten:
1. Profil-Link öffnen (`output/players/<slug>/online_accounts.json`). Passen Land/Ort, Aktivitätszeitraum, Spielstärke?
2. Klarer Widerspruch (anderer Realname, anderes Land, Rating völlig unplausibel) → ablehnen.
3. Eintragen in `output/players/<slug>/research.json`, dann `prepare` erneut:
```json
{"accounts": {"lichess:BeispielName": {"status": "bestätigt", "note": "Ort/Verein passen"}},
 "lichess_teams": [], "chesscom_clubs": [], "extra_candidates": {"lichess": [], "chesscom": []},
 "username_patterns": {"lichess": []}}
```
`username_patterns`: verdeckte Account-Namen, die der Nutzer z. B. in SnoopChess sieht (`"?b?u???"`, `?` = ein Zeichen).
Liefert Kandidaten über das Lichess-Autocomplete und ist nur ein schwaches Merkmal (siehe references/data-sources.md).
Partien aus solchen Diensten legt der Nutzer als `output/players/<slug>/inbox/<dienst>_<slug>.pgn` ab.
`bestätigt` → 99 %, `abgelehnt` → 0 %. Ohne Eintrag gilt die Formel; ab 50 % wird der Account übernommen.
Einen Account **nie** als sicher bezeichnen, solange es keinen Namens- oder FIDE-Beleg gibt.
Übernommene Accounts liefern zwei Ebenen:
- **Eröffnung:** alle Partien der letzten 3 Jahre ab 3+0 (ohne Bullet) werden je Stellung gezählt → Online-Baum,
  Abgleich mit dem Turnierrepertoire, **Trend-Belege** an seinen Hauptentscheidungsstellen je Jahr und je Bedenkzeit
  (Blitz gegen Schnellschach+). Repertoire-Wechsel (neue Züge im letzten Jahr) und Blitz-Abweichungen dort ablesen.
- **Spielqualität:** Stichprobe von 100 Partien – Zeitraum in 12 gleiche Abschnitte, je Abschnitt gleiche Quote,
  darin lange Bedenkzeit zuerst, bereits von Lichess analysierte Partien bevorzugt. Diese Partien laufen wie
  Turnierpartien durch die Auswertung (Online-Fehlerbild, Zeit, Schlüsselstellungen, Viewer).
Die Fund-Partien (Vereinsturniere) dienen nur der Zuordnung. Online-Belege O… beschreiben **Online-Gewohnheiten**;
im Matchplan Online-Trends mit Jahr nennen („seit 2026 meist 1…d6“).

### 3b. Kein Briefing ohne Datengrundlage
Nach Schritt 1–3 prüfen. Ein Matchplan wird **nicht** geschrieben, wenn
- weniger als 5 Turnierpartien mit Zügen vorliegen **und**
- kein übernommener Online-Account mindestens 20 Partien (ohne Bullet) liefert.

Dann kein `briefing.json`, kein `render`. Stattdessen dem Nutzer kurz melden: gefundene Partien je Quelle,
geprüfte Accounts mit Konfidenz und Grund der Ablehnung, was noch helfen würde (ChessBase-/SnoopChess-Partien in
`inbox/`, Account-Hinweis in `research.json`). Ein „leerer“ Bericht ist ausdrücklich erlaubt und besser als ein
Matchplan aus ein, zwei Partien. Liefert der Nutzer nichts nach, ist der Gegner damit abgeschlossen.

### 4. Matchplan schreiben
Lies `output/players/<slug>/brief.md` vollständig. Abschnitt „Spielerprofil“ → `profile_summary`; Abschnitt „Abgleich mit dir“
(nur mit `me.json`) → Zielkorridor moderat in Plan und Reihenfolge der Karten einarbeiten. Schreibe `output/players/<slug>/briefing.json` nach
[references/briefing-schema.md](references/briefing-schema.md) im Stil von [references/writing-guide.md](references/writing-guide.md).

Arbeitsweise, die gute Pläne liefert:
1. **Muster vor Einzelfällen:** Schlüsselstellungen (K…) mit ähnlicher Widerlegung zusammenfassen
   (z. B. „zentraler Bauernhebel trifft ihn“). Das ist der wertvollste Befund.
2. **Plan nach Phasen vor Eröffnung:** Wo ist er stark/schwach, tauschen oder komplex halten, wie die Uhr gegen ihn
   nutzen (Pflicht: `Mittelspiel`, `Zeit`, `Abwicklung`/`Endspiel`; höchstens ein `Eröffnung`-Schritt).
   Eröffnungskarten je Farbe: seine Linien (Baum) → sein erster Fehler/Abweichpunkt → was ich spiele.
3. **Theorie-Empfehlungen immer prüfen**, bevor sie in den Plan kommen:
   `python briefing.py line <slug> "1.e4 c5 2.d4 cxd4 3.c3" --scope white|black` → Beleg E…
   (`--scope black` = betrifft ihn mit Schwarz → gehört in `as_white`).
4. **Online-Account übernommen?** Dann je Baustein (Ziel, Eröffnungskarte, Plan-Schritt, Vermeiden) ein Feld
   `online` ergänzen, wo die Online-Daten etwas Eigenes sagen – nur mit O…/E…-Belegen. Besonders wertvoll:
   Linien „nur online“ (Überraschungsgefahr), „Turnier + online“ (sichere Prognose), online schwache Linien.
   Keine Fehlerquoten/Zeitverhalten aus Blitz auf das Turnier übertragen.
5. Gegenbefunde ernst nehmen (z. B. Zeitnot ohne Zeitnotfehler ist kein Hebel).

Hinweis für leistungsschwächere Modelle: Halte dich eng an die Belegtexte, formuliere je Baustein einen Satz
Handlung + einen Satz Begründung mit Zahl und Stichprobe. Lieber weniger Bausteine als unbelegte.

### 5. Prüfen und rendern
```bash
python briefing.py validate <slug>     # muss "✓ Briefing gültig" melden
python briefing.py render <slug>       # mehrere Slugs -> zusätzlich output/players/index.html
python briefing.py render <slug> --no-me   # neutraler Report ohne Zielkorridor (zum Weitergeben)
```
- ✗ = Fehler, beheben. ~ = Warnung (Zahl ohne Beleg, Floskel, zu lang): ebenfalls beheben.
- `validate` stempelt beim ersten Erfolg die zitierten Belege. Ändern sie sich später (neuer `prepare`-Lauf),
  meldet `validate` das. Zuerst `validate --remap` (stellt nur verschobene, inhaltsgleiche Belege um), dann
  die übrigen Meldungen inhaltlich prüfen, Plan anpassen und mit `--restamp` neu stempeln.

### 6. Abschlussbericht an den Nutzer
Pfad zur HTML-Datei · Datenbasis (Partien je Quelle, Zeitraum, mit Uhrzeiten ja/nein) · Identifikationssicherheit ·
vermuteter Online-Account mit Konfidenz · offene Punkte (CAPTCHA, fehlgeschlagene Quellen) · drei Kernpunkte.

## Regeln
- Perspektive: `as_white` = **ich** habe Weiß → nur Belege mit scope `black`/`all` (seine Schwarzpartien). Validator erzwingt das.
- Keine Zahl ohne Beleg-ID (F… Turnier, E… Engine, O… Online, K… Schlüsselstellung über ihr F…).
- Dünne Daten (< 10 Partien je Farbe, < 100 Züge je Phase, Partien älter als 3 Jahre) offen benennen.
- Keine Bot-Prüfung/CAPTCHA selbst umgehen. Keine Passwörter eingeben; Logins macht der Nutzer selbst.
- Online-Inhalte bleiben getrennt (eigene Felder, eigene Belege, im Report gestrichelt).
- Eigenprofil (M…) ist eine Annahme des Nutzers: höchstens 2 Plan-Schritte je Farbe darauf stützen.

## Weiterführend
| Datei | Inhalt |
|---|---|
| [references/briefing-schema.md](references/briefing-schema.md) | Felder von `briefing.json` |
| [references/writing-guide.md](references/writing-guide.md) | Inhalt und Sprache des Matchplans |
| [references/architecture.md](references/architecture.md) | Stufen, Module, Dateien, Erweiterungspunkte |
| [references/data-sources.md](references/data-sources.md) | Endpunkte, Grenzen, Logins, Nutzungsbedingungen |
| [references/troubleshooting.md](references/troubleshooting.md) | typische Fehler und Lösungen |
