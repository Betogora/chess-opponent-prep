---
name: chess-opponent-scout-fast
description: "Schneller Gegner-Steckbrief für Schach (Stufe 1 von 3, unter 1 Minute, sobald die ChessBase-Partien da sind). Ohne Engine, ohne Online-Suche, ohne KI-Text – alle sofort verfügbaren Turnierpartien (ChessBase, chess-results, inbox) beider Farben als HTML mit Eröffnungsbaum, Repertoire mit Score je Linie, Ergebnissen, Form und Partien-Viewer; die Farbe des Gegners in der anstehenden Partie steht oben. Auslöser: „kurz vor der Runde“, „schneller Check“, „Steckbrief zu …“, „schnell schauen, was … spielt“."
version: 1.1.0
---

# chess-opponent-scout-fast

Stufe 1 von 3 ([briefing-medium](../chess-opponent-briefing-medium/SKILL.md) · [research-deep](../chess-opponent-research-deep/SKILL.md)).
Das Programm macht alles selbst, auch den Text (feste Regeln, jede Zahl mit Beleg). Der Agent ruft nur einen Befehl auf.

Ergebnis: `output/players/<slug>/scout_<slug>.html` (Daten in `output/players/<slug>/scout/`).

## Ablauf
1. **Farbe erfragen**, falls nicht genannt: „Welche Farbe hast du in der Partie – oder beide Farben?“ (eine Frage).
   „Beide“ ist eine gültige Antwort (`--color both`): dann stehen beide Farben gleichrangig nebeneinander.
2. **Neuer Gegner ohne ChessBase-Datei** (kein `output/players/<slug>/inbox/chessbase_*.pgn` oder älter als 7 Tage):
   zuerst die Partien per Download holen (unten, Weg A). Liegt die Datei schon vor, entfällt der Schritt.
3. Ausführen:
   ```bash
   python briefing.py scout "<FIDE-ID | Name | Profil-Link>" --color white|black|both
   ```
   `--color` = Farbe des **Nutzers** (`white`, `black` oder `both`). Zeitgrenze `--budget` (Standard 90 s) hält das Programm selbst ein.
4. Meldet die Ausgabe `! ChessBase braucht den Browser`, Weg A ausführen und Schritt 3 wiederholen.
5. Dem Nutzer den Pfad der HTML-Datei und die Zeile „Zeiten: …“ nennen. **Nichts weiter tun** – kein Matchplan,
   keine Engine, keine Online-Suche.

## ChessBase-PGN beschaffen
Die Datei wird **nie** als Text durch den Agenten-Kontext kopiert (dauerte für 100 Partien über 6 Minuten).

**Weg A – Übergabe aus dem Browser (Agent, Sekunden, ohne Dialog):**
1. Empfänger starten (im Hintergrund, beendet sich nach dem Empfang): `python briefing.py receive "<Eingabe>"`.
   Die Ausgabe nennt die Profilseite und den Befehl für die Seite.
2. Profilseite im Browser öffnen. Bot-Prüfung/CAPTCHA löst nur der Nutzer.
3. Den ausgegebenen Befehl in der Seite ausführen: Er lädt `/games/<Nachname>_<Vorname>.pgn` wie ein normaler
   Besucher und schickt sie als Formular an `http://127.0.0.1:8767/`. Die Datei liegt danach in
   `output/players/<slug>/inbox/chessbase_<slug>.pgn`; die Seite zeigt „PGN übernommen“.

**Weg A2 – Download:** `download_in_page` aus der Meldung speichert `chessbase_<slug>.pgn` im Download-Ordner; das
Programm übernimmt sie beim nächsten Lauf. Der Browser fragt aber nach, wenn mehrere Downloads hintereinander kommen –
deshalb nur als Ersatz.

**Weg B – ohne Agent:** Der Nutzer speichert im eigenen Browser `players.chessbase.com/games/<Nachname>_<Vorname>.pgn`
im Download-Ordner; Übernahme wie oben.

**Wiederverwendung:** Eine ChessBase-Datei in `inbox/` wird bei jedem weiteren Lauf (auch briefing-medium,
research-deep, team-prep) ohne Browser genutzt. Ist sie älter als 7 Tage (`CHESSBASE_MAX_AGE_DAYS`), meldet das
Programm `· ChessBase-Partien sind N Tage alt` mit dem Download-Befehl; der Lauf geht mit der alten Datei weiter.

## Was drinsteht – und was nicht
- Je Farbe: Ergebnisse (S/R/N, Score, Ø Elo der Gegner, Performance), erster Zug bzw. Antworten, wiederkehrende Linien
  (mindestens 2 Partien) mit Score, schwächste/stärkste Linie, letzte 10 Ergebnisse, Elo-Verlauf.
- Nicht: Fehlerquoten, Phasen, Schlüsselstellungen, Spielerprofil, Bedenkzeit-Analyse (brauchen die Engine →
  briefing-medium), Online-Accounts (→ research-deep).
- Scores aus wenigen Partien sind Hinweise, keine Gewissheit; der Report nennt die Stichprobe je Linie.
