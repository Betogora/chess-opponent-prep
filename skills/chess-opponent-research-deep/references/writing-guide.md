# Schreibregeln für den Matchplan

Der Leser sitzt vor der Partie und hat zwei Minuten. Jede Zeile muss eine Entscheidung am Brett verändern.

## Inhalt
1. **Konkret statt allgemein.** Nicht „aktiv spielen“, sondern „d4–d5 zwischen Zug 9 und 20“. Züge, Felder, Zugnummern, Strukturen.
2. **Jede Empfehlung ist belegt.** Partie-Beleg (F…) oder Engine-Beleg (E…). Theorie aus dem eigenen Wissen nur mit `line`-Prüfung und Etikett `basis: "theorie"`.
3. **Muster suchen, nicht Einzelfälle aufzählen.** Mehrere Schlüsselstellungen mit derselben Widerlegung (z. B. zentraler Hebel, Springer auf Vorposten) sind der wertvollste Befund.
4. **Gegenbefunde ernst nehmen.** Zeitnot ohne Zeitnotfehler ist kein Hebel. Schwacher Endspiel-Score bei 0 Endspielfehlern heißt „Partie war vorher entschieden“.
5. **Aktualität gewichten.** Partien älter als 3 Jahre oder deutlich unter heutiger Spielstärke nur als Hinweis. Elo-Verlauf beachten.
6. **Plan nach der Eröffnung zuerst.** Die Plan-Schritte steuern die Partie: In welcher Phase ist er stark oder schwach
   (Fehler je Phase, Kipp-Punkte, Verwertung/Widerstand)? Tauschen und abwickeln oder komplex halten? Wie die Uhr
   gegen ihn einsetzen (Restzeit, Zeitnot, Fehler in Zeitnot)? Pflicht je Farbe: je ein Schritt `Mittelspiel`, `Zeit`
   und `Abwicklung` oder `Endspiel`; höchstens ein Schritt `Eröffnung`. Die Eröffnung selbst gehört in die Karten
   (`opening`) und steht ausführlich im Baum. Im Report steht der Plan vor den Eröffnungskarten.
7. **Eröffnungskarten je Farbe:** seine tatsächlichen Linien (Baum) → sein erster Fehler/Abweichpunkt → was ich dort spiele.
   Bei mehreren Möglichkeiten (er spielt mal X, mal Y) je eine Karte. Höchstens ein Kernpunkt in `summary` zur Eröffnung.
8. **Perspektive:** `as_white` beschreibt, was ICH mit Weiß tue, gestützt auf SEINE Schwarzpartien.
9. **Spielerprofil (`profile_summary`):** ein Satz Typ (Vorliebe + Können, mit Zahl aus P…), ein Satz Hebel (die eine
   Handlung, die daraus folgt). Vorliebe (Partie-Charakter) und Können (Teil-Elo scharf/ruhig) nicht vermischen.
   Teil-Elo ist eine Schätzung mit Spanne: „im Scharfen ~1850 (±120)“, nie als exakte Zahl. „Allrounder (unsicher)“
   heißt: keine klare Stilschwäche belegt – dann keinen Stil-Hebel erfinden, sondern Phase, Uhr oder Eröffnung nutzen.
10. **Eigenprofil (M…) nur moderat:** Der Zielkorridor gibt die Richtung (ruhig ↔ scharf), der Plan bleibt ein Plan gegen
   IHN. Höchstens 2 Plan-Schritte je Farbe stützen sich auf M… (Validator). Die Eröffnungskarte, die das Repertoire
   des Nutzers trifft, kommt zuerst (der Report markiert sie). Nutzerangaben sind Annahmen: „nach deiner Angabe …“.

## Sprache
- Deutsch, aktiv, Imperativ oder Infinitiv in `do` („Zentrum öffnen …“). Keine Anrede-Floskeln.
- Zahlen mit Stichprobe: „13 Kipp-Punkte bei 133 Zügen“, „5 von 5 Partien“.
- Verboten (Validator warnt): „es ist wichtig“, „im Auge behalten“, „nicht unterschätzen“, „Schlüssel zum Erfolg“, „grundsätzlich“, „durchaus“, „insgesamt“, „spannend“, „unter Druck setzen“ ohne Konkretisierung.
- Keine Wiederholung derselben Zahl in mehreren Blöcken, außer in `summary`.
- Kein Fettdruck, keine Ausrufezeichen, keine Emojis.

## Umfang
- `summary`: 3 Punkte, davon höchstens einer zur Eröffnung. `plan`: 4–6 Schritte je Farbe (siehe Punkt 6). `avoid`: 1–3.
  `watch`: 2–4. `moments`: nur Stellungen mit klarer Lehre. `caveats` weglassen (wird nicht angezeigt); Datenlage in `watch`.
