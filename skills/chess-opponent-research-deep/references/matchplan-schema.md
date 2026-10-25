# matchplan.json – Schema

```jsonc
{
  "headline": "Ein Satz: Spielertyp + größter Hebel",              // Pflicht
  "profile_summary": {                                             // Spielerprofil ganz oben (empfohlen)
    "type": "Ein Satz: berechneter Typ in Worten, mit Zahl",
    "lever": "Ein Satz: die Handlung, die daraus folgt",
    "evidence": ["P2", "P4"]                                       // mind. ein P…
  },
  "summary": [                                                     // genau 3 Kernpunkte
    {"title": "Kurz, als Aussage", "text": "1–2 Sätze mit Zahlen", "evidence": ["F16", "F19"]}
  ],
  "as_white": {                    // ICH habe Weiß  → Belege nur scope black/all
    "goal": "Ein Satz: der Spielplan",
    "online_goal": "optional: ein Satz aus Online-Sicht",           // nur mit Online-Account
    "opening": [                   // 1–4 Karten, erste = Hauptweg
      {"title": "Hauptweg: …", "line": "1.d4 Nf6 2.c4 …",           // legale SAN-Folge mit Zugnummern
       "idea": "Was passiert, wo er abweicht, was dann",
       "basis": "partien | theorie | beides",                        // Etikett im Report
       "evidence": ["F34", "E1"],
       "online": {"title": "Online: …", "line": "1.d4 Nf6 …", "idea": "…", "evidence": ["O11", "O15"]}},  // optional
      {"online": {"title": "Online-Option: …", "line": "…", "idea": "…", "evidence": ["O24", "E7"]}}      // reine Online-Karte
    ],
    "plan": [                      // 4–6 Schritte, Reihenfolge = Partieverlauf; Pflicht: Mittelspiel, Zeit, Abwicklung|Endspiel;
                                   // höchstens 1× Eröffnung (Details in den Karten). Im Report steht der Plan vor den Karten.
      {"phase": "Eröffnung | Mittelspiel | Abwicklung | Endspiel | Zeit | Praxis | Psychologie",
       "do": "Handlung, max. 220 Zeichen",
       "why": "Begründung mit Zahlen + Stichprobe, max. 360 Zeichen",
       "evidence": ["F19", "F51"],
       "online": {"do": "…", "why": "…", "evidence": ["O11"]}}       // optional, direkt unter dem Schritt
    ],
    "avoid": [{"text": "Was ich NICHT tun soll", "evidence": ["F20"],
               "online": {"text": "…", "evidence": ["O25"]}}]        // optional
  },
  "as_black": { "…": "gleiches Schema; Belege nur scope white/all" },
  "watch": [{"text": "Gegenargumente, Datenlage, Stärken des Gegners", "evidence": ["F2"]}],
  "moments": {"K1": "Ein Satz Lehre zur Schlüsselstellung (Widerlegung aus dem Beleg zitieren)"},
  "caveats": []   // entfällt: wird nicht mehr angezeigt; Datenlage gehört in "watch" (Plaketten im Kopf kommen vom Programm)
}
```

Beleg-IDs: `F…` aus `dossier.json`/`dossier.md`, `E…` aus `python briefing.py line`, `O…` aus dem Online-Abschnitt,
`P…` Spielerprofil (farbunabhängig), `M…` Abgleich mit dem Eigenprofil (nur mit `me.json`; Annahmen des Nutzers).
`K…` sind die Schlüsselstellungen; ihr Beleg ist das jeweils zugehörige `F…`.

Regeln, die `validate` erzwingt:
- Turnier-Felder zitieren keine `O…`; `online`-Felder zitieren nur `O…`/`E…`.
- `online`-Felder nur, wenn ein Account mit Konfidenz ≥ 50 % übernommen wurde.
- Perspektive gilt für beide Quellen (scope black/all bei `as_white`, white/all bei `as_black`).
- Höchstens 2 Plan-Schritte je Farbe zitieren `M…`; `online`-Felder zitieren nie `P…`/`M…`.

## Stufe briefing-medium
Gleiches Schema, aber nur die Seite des Nutzers (`as_white` **oder** `as_black`, steht in `dossier.mode.sides`).
Die andere Seite und `online`-Felder lehnt der Validator ab; 3 Plan-Schritte genügen (`mode.min_plan_steps`).
Datei: `output/players/<slug>/briefing_ich-weiss/matchplan.json` bzw. `briefing_ich-schwarz/`, bei beiden Farben `briefing/`.
research-deep: `output/players/<slug>/research/matchplan.json`.
