# Fehlerbehebung

| Symptom | Ursache | Lösung |
|---|---|---|
| `Python 3.12 oder neuer wird benötigt` | ältere Python-Version | Python ≥ 3.12 installieren |
| `Paket … fehlt` | Abhängigkeiten fehlen | `python -m pip install -r requirements.txt` |
| `Stockfish nicht gefunden` | Engine fehlt | `python briefing.py setup` oder `BRIEFING_ENGINE=<Pfad>` setzen |
| `Mehrere Spieler passen auf den Namen` | Namensgleiche bei der FIDE | `--fide-id N` oder `--fed GER` / `--birth-year` |
| `ChessBase braucht den Browser` | Bot-Prüfung bei ChessBase | Schritt 2 im Skill; ohne Browser: Nutzer speichert die PGN |
| `chess-results.com braucht den Browser` | Bot-Prüfung/Sperre bei chess-results | Partiesuche im Browser, FIDE-ID, „Download as PGN-File“ → `inbox/chessresults_<slug>.pgn` |
| Belege „ohne Datum“, „ohne Ergebnis“ | manueller Import (z. B. SnoopChess) ohne Kopfdaten | normal; Score/Verwertung zählen nur Partien mit Ergebnis |
| `! Quelle … fehlgeschlagen` | Netz/Seite geändert | Lauf ist gültig, Quelle fehlt; später erneut `prepare` |
| `Lichess-Ratenlimit, warte 65 s` | 429 von Lichess | abwarten; optional `LICHESS_TOKEN` |
| `kein Account mit Konfidenz >= 50 %` | keine passende Online-Spur | ggf. `research/accounts.json` → `extra_candidates` oder `lichess_teams` ergänzen |
| Falscher Account übernommen | Formel irrt | `research/accounts.json`: `"lichess:<Name>": {"status": "abgelehnt"}` |
| `Beleg … hat sich seit dem Schreiben geändert` | neuer `prepare`-Lauf, andere Daten | Plan an neue Belege anpassen, dann `validate --restamp` |
| `Perspektivfehler` | Weiß-Plan zitiert seine Weiß-Partien | Beleg mit scope `black`/`all` verwenden |
| `Online-Feld zitiert Turnier-Beleg` | Quellen gemischt | Online nur O…/E…, Turnier nur F…/E… |
| Report zeigt keine Online-Teile | kein Account ≥ 50 % | erwartet; Online-Felder in `matchplan.json` weglassen |
| Konsole zeigt `�` statt Umlauten | Windows-Codepage | Ausgaben sind UTF-8; Datei-Inhalte sind korrekt |
| HTML sehr groß (> 3 MB) | viele Partien im Viewer | normal; die Datei bleibt offline lauffähig |
