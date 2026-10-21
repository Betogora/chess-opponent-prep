"""Die drei Stufen der Gegnervorbereitung (je ein Skill):

  scout   -> chess-opponent-scout-fast        Steckbrief ohne Engine, alle Partien beider Farben (Sekunden)
  medium  -> chess-opponent-briefing-medium   eine Farbe, Engine fuer die 20 juengsten Partien, kurzer Matchplan
  research-> chess-opponent-research-deep     volle Recherche (pipeline.prepare), unveraendert
  team    -> chess-opponent-team-prep          ganze Mannschaft: je Spieler eine der drei Stufen (modes/team.py)

Neue Stufen: Modul hier anlegen (run(...) -> int), Befehl in briefing.py, Skill unter skills/, Ansicht in render/.
"""
STAGES = {
    "scout": {"skill": "chess-opponent-scout-fast", "command": "scout", "data_dir": "scout"},
    "medium": {"skill": "chess-opponent-briefing-medium", "command": "brief", "data_dir": "medium_als-<farbe>"},
    "research": {"skill": "chess-opponent-research-deep", "command": "prepare", "data_dir": "."},
}
# Ueber den Stufen: team (chess-opponent-team-prep, Befehl "team") ruft je Spieler eine Stufe auf -> output/teams/
