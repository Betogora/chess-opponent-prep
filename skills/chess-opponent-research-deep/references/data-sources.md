# Datenquellen, Grenzen, Logins

Stand 10/2026. Alle Abrufe ohne Login über offizielle bzw. öffentliche Schnittstellen. Die Pipeline meldet sich
ehrlich als Anwendung (`chess-opponent-prep/<version> (personal opening-preparation tool)`), gibt sich nicht als
Browser aus und umgeht keine Bot-Prüfung. Lichess, Chess.com und Chessable lehnen den Standard-User-Agent von
curl/python-requests ab, akzeptieren aber diese Kennung. Alle Antworten werden gecacht, Anfragen laufen nacheinander.

| Quelle | Wofür | Endpunkt / Weg | Grenze |
|---|---|---|---|
| Lichess FIDE-Spiegel | Identifikation, Elo | `lichess.org/api/fide/player/{id}`, `?q=<name>` | – |
| Lichess Broadcasts | Turnierpartien mit Uhr | Seite `lichess.org/fide/{id}/x` → Runden → `/api/broadcast/{tour}.pgn` | nur übertragene Turniere |
| ChessBase Players | Turnierpartien | `players.chessbase.com/games/<Nachname>_<Vorname>.pgn` | Bot-Prüfung für Skripte → Browser-Schritt (Seite normal im Browser öffnen) |
| chess-results.com | Turnierliste, hochgeladene Turnierpartien | `SpielerSuche.aspx` (FIDE-ID, sonst Name) → Turniere; `PartieSuche.aspx` → Knopf „Download as PGN-File“ (ASP.NET-Formular, POST mit Viewstate) | nur Partien, die Veranstalter hochgeladen haben (bei Amateuren oft keine); bis 500 Treffer; Chess960/Aufbau-Stellungen werden aussortiert. Regeln: siehe unten |
| Manueller Import | Partien aus Diensten mit Login (z. B. SnoopChess) | Nutzer legt die PGN als `output/players/<slug>/inbox/<dienst>_<slug>.pgn` ab (läuft über `local.py`) | oft ohne Datum, Event, Ergebnis (`*`): zählt nicht in Score/Verwertung, Belege nennen „ohne Datum“/„ohne Ergebnis“ |
| DSB | Verein, DWZ | `schachbund.de/dwz-spieler.html?search=` mit Cookie `dwzc=1` | DWZ-Karteikarte nur mit Login (nicht genutzt) |
| NSV | Mannschaftsergebnisse | `nsv-online.de/ligen/<familie>-<saison>/…`, Spielerseiten `/s/<id>/` | nur Niedersachsen; meist ohne Züge |
| FIDE | Elo-Verlauf | `ratings.fide.com/a_chart_data.phtml` (POST, mit Referer) | – |
| Lichess Team | Account-Kandidaten | `/api/team/{id}/arena`, `/swiss`, Turnier-Exporte | nur Vereinsturniere |
| Lichess Account (alle Partien) | vollständige Zählung je Stellung, Trends je Jahr/Bedenkzeit | `/api/games/user/{name}?since&moves&tags=false&perfType=blitz,rapid,classical` | ohne Token; erster Lauf einige Minuten (≈ 5000 Partien in 7 min), danach nur neue Partien (`cache/lichess_games/<name>_all.ndjson`). Bullet ausgeschlossen (Lichess-Blitz beginnt bei 3+0) |
| Lichess Account (analysierte IDs) | Vorrang analysierter Partien in der Stichprobe | `/api/games/user/{name}?analysed=true&moves=false` | ≈ 3 min bei großen Accounts, 24 h Cache |
| Lichess Sammelexport | Stichprobe **mit Serveranalyse**, Uhr, Eröffnung | `POST /api/games/export/_ids?evals&clocks&opening` (≤ 300 IDs) | Ratenlimit (429 → 65 s warten). Analysierte Partien ersetzen lokales Stockfish |
| Lichess Team-Mitglieder | weitere Account-Kandidaten | `/api/team/{id}/users` | private Liste: Token mit `team:read` und Teamzugehörigkeit |
| Chess.com | Clubmitglieder, Profile, Partien | `api.chess.com/pub/club/{slug}/members`, `/pub/player/{u}`, Monatsarchive | – |
| Chessable | Account, studierte Kurse | `POST chessable.com/api/graph` `user(username)`, `studiedCourses(username)` | Fehler = existiert nicht, `null` = privat |
| Chessable | Kurssuche | `chessable.com/api/v1/course/search?query=` | Kursinhalte (Züge) nur mit Login |
| Eröffnungsnamen | ECO + Name | `chess_briefing/data/eco_*.tsv` (lichess-org/chess-openings, CC0) | – |

## chess-results.com: Regeln
- robots.txt erlaubt den Abruf (gesperrt ist nur ein bestimmter fremder Bot). Die Nutzungsbedingungen im Impressum
  verbieten, Turnierdaten und Partien **zu kopieren und auf anderen Seiten zu publizieren**. Deshalb: nur private
  Vorbereitung; `output/players/` und `cache/` gehen nie in Weitergaben (`pack` lässt sie weg), ein Report mit
  chess-results-Partien wird nicht veröffentlicht.
- Höflich: ehrliche App-Kennung, mindestens 3 s zwischen zwei Abrufen (`chessresults.PAUSE`), höchstens 5 Abrufe
  je Spieler (2× Formular laden, Spielersuche, Partiesuche, PGN), Ergebnisse 24 h in `cache/chessresults/`.
- Bot-Prüfung, Sperre (403/429/503) oder geändertes Formular → keine Umgehung. `sources.json` meldet
  `browser_noetig` mit Hinweis: Partiesuche im Browser öffnen, FIDE-ID eintragen, „Download as PGN-File“, Datei als
  `output/players/<slug>/inbox/chessresults_<slug>.pgn` speichern. Liegt die Datei dort, ruft die Quelle das Netz nicht ab.

## Verdeckte Account-Hinweise (SnoopChess u. Ä.)
Kommerzielle Dienste wie SnoopChess (Login, Premium, keine öffentliche API) werden nicht abgefragt. Was der Nutzer dort
sieht, trägt er von Hand ein: Partien als PGN in die Inbox (siehe oben), verdeckte Account-Namen als Muster in
`research.json`:
```json
{"username_patterns": {"lichess": ["?b?u???"]}}
```
`?` = genau ein Zeichen, `*` = beliebig viele, Groß-/Kleinschreibung egal. Wirkung in `accounts.discover`:
- Lichess: Namenspräfixe (Vorname, Nachname, Namensvarianten), die zum Muster passen, gehen an das Autocomplete
  (`/api/player/autocomplete`, 12 Treffer je Suche, daher mehrere Präfixlängen, höchstens 24 Suchen); passende Namen
  werden Kandidaten (höchstens 15, je bis zu 60 Partien für den Fingerabdruck).
- Merkmal `pattern` (+0,7 Log-Odds) bzw. `pattern_miss` (−1,0) für alle Kandidaten der Plattform. Allein reicht das nie
  (Vorwert −3,2; mit Verein ≈ 18 %); der Hinweis ist selbst nur eine Vermutung des Dienstes.
- Chess.com hat keine Namenssuche: dort wirkt das Muster nur als Merkmal; ein Muster ohne `?`/`*` wird direkt Kandidat.
- Die Online-Suche läuft auch ohne Turnierpartien; dann entfällt nur der Eröffnungs-Fingerabdruck.

## Logins
- Die Pipeline braucht keinen Login. Ein Agent gibt **nie** Passwörter ein.
- Lichess: Ein Login per Benutzername/Passwort über die API gibt es nicht. Optional erstellt der Nutzer selbst einen
  persönlichen Token (https://lichess.org/account/oauth/token/create?description=chess-opponent-briefing) und trägt ihn
  in `.env` ein (`LICHESS_TOKEN=...`). **Rechte:** keine nötig; empfohlen höchstens `team:read` (Mitgliederliste des
  Vereinsteams). Keine Schreibrechte vergeben. Nutzen: Mitgliederliste, höheres Ratenlimit. Für Partien und Zählung je Stellung nicht nötig.
- Chessable: Mit Login des Nutzers wären die Zugfolgen **seiner eigenen** Kurse lesbar (für trennscharfe Kursstellen in
  `course_signatures.json`). Private Profile anderer bleiben privat. Die Nutzungsbedingungen von Chessable untersagen
  vermutlich automatisches Auslesen; Kursinhalte sind urheberrechtlich geschützt → höchstens einzelne Entscheidungszüge
  für den persönlichen Gebrauch eintragen, keine Kommentare/Texte übernehmen.

## Bekannte Eigenheiten
- Lichess-Export ist bei 10 000 Partien gedeckelt (`ONLINE_POOL_MAX`); darüber zählt nur der neueste Teil (im Beleg O1 ausgewiesen).
- ChessBase normiert Namen („Muster,M“); Dubletten mit Lichess werden über Monat, Gegner-Nachname, Farbe und die ersten 16 Halbzüge erkannt.
- NSV-Saisonseiten verlinken nicht alle Staffeln; die Pipeline folgt zusätzlich den `?staffel=`-Links.
