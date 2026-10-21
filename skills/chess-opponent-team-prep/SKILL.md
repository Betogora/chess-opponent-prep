---
name: chess-opponent-team-prep
description: "Ganze Mannschaft vorbereiten: liest eine Mannschaftsaufstellung (Ligaserver-Seite wie nsv-online.de oder schachbezirk-hannover.de, eine Liste von ChessBase-Links/Namen/FIDE-IDs oder team.json), wählt Bretter/Spielernummern (z. B. 101–108) und ruft für jeden Spieler eine der drei Stufen auf (scout-fast, briefing-medium, research-deep). Ergebnis ist eine Mannschaftsseite, auf der man oben zwischen den Spielern umschaltet. Auslöser: „Mannschaft vorbereiten“, „Team-Prep gegen …“, „Aufstellung von … analysieren“, „Bretter 1–8 von …“."
version: 1.0.0
---

# chess-opponent-team-prep

Ruft je Spieler einen der drei Einzel-Skills auf; deren Regeln gelten unverändert:
[scout-fast](../chess-opponent-scout-fast/SKILL.md) · [briefing-medium](../chess-opponent-briefing-medium/SKILL.md) ·
[research-deep](../chess-opponent-research-deep/SKILL.md).

Ergebnis: `output/teams/<mannschaft>/team_<mannschaft>_<stufe>.html` – oben „Übersicht“ (Brett, DWZ, Farbe, Partien,
Laufzeit, Status) und je Spieler ein Knopf; darunter der vollständige Einzelreport. Eine Datei, offline.

## 1. Klären (eine Nachricht, nur was fehlt)
- **Aufstellung:** Link auf die Mannschaftsseite, Liste von Spielern oder Mannschaftsname + Liga.
- **Bretter:** z. B. „Spielernummern 101 bis 108“ oder „Bretter 1–8“ (`--boards`).
- **Stufe:** scout (Minuten für die ganze Mannschaft), medium (je Spieler bis 5 min + Matchplan), research (je Spieler 15–30 min).
- **Farbe:** deine Farbe an allen Brettern (`--color white|black`), abwechselnd ab dem ersten gewählten Brett
  (`--board1 white|black`) oder **beide Farben** (`--color both`, Standard, wenn die Farben noch nicht feststehen).
  Bei briefing-medium mit beiden Farben werden je Spieler bis zu 10 Partien je Farbe analysiert (insgesamt 20);
  Eröffnungsbaum und Partienliste enthalten trotzdem alle verfügbaren Partien.

## 2. Aufstellung einlesen und Stufe ausführen
```bash
python briefing.py team "<Mannschaftsseite | team.json | Spieler1 Spieler2 ...>" --stage scout|medium|research \
    [--boards 101-108] [--color white|black|both | --board1 white|black] [--team "<Name>"]
```
- Ligaserver-Seiten (`…/ligen/<liga>-<saison>/m/<id>/`, z. B. von nsv-online.de oder schachbezirk-hannover.de)
  liest das Programm selbst (Nr., Name, DWZ).
- **Andere Seiten:** Seite lesen und `team.json` schreiben, dann `team team.json …`:
  ```json
  {"team": "SK Beispiel", "source": "<URL>", "players": [
    {"nr": 1, "name": "Mustermann, Max", "input": "Max Mustermann", "fide_id": null, "dwz": 1950}]}
  ```
  `input` darf ein ChessBase-Link, Name oder eine FIDE-ID sein; `color` je Spieler optional.
- Mehrdeutige Namen erscheinen als „nicht eindeutig“ – FIDE-ID in `team.json` (`fide_id`) eintragen, erneut starten.

## 3. Partien beschaffen (ChessBase)
Spieler ohne Partien stehen in der Übersicht gestrichelt mit Hinweis. ChessBase-PGNs wie in
[scout-fast](../chess-opponent-scout-fast/SKILL.md#chessbase-pgn-beschaffen) beschaffen
(eigener Browser → Download-Ordner, oder Agenten-Browser), dann `team` erneut ausführen (vorhandene Analysen kommen
aus dem Cache).

## 4. Je Stufe weiter
- **scout:** fertig. Seite und Übersicht dem Nutzer nennen.
- **medium / research:** je Spieler den Matchplan schreiben wie im Einzel-Skill (medium: `output/players/<slug>/medium_<farbe>/briefing.json`;
  research zusätzlich Account-Checkliste), `validate` und `render` je Spieler, dann
  `python briefing.py team-render <mannschaft> --stage medium|research` für die Mannschaftsseite.
  Bei research erst alle `prepare` laufen lassen (Befehl `team` erledigt das), dann die Pläne schreiben.

## 5. Bericht
Pfad der Mannschaftsseite · je Spieler: Partien, analysiert, Laufzeit, fehlende Daten · Gesamtzeit (steht in der Übersicht).
