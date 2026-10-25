"""Die drei Stufen der Gegnervorbereitung (je ein Skill):

  scout   -> chess-opponent-scout-fast        Steckbrief ohne Engine, alle Partien beider Farben (Sekunden)
  briefing-> chess-opponent-briefing-medium   eine Farbe oder beide, Engine fuer die 20 juengsten Partien, kurzer Matchplan
  research-> chess-opponent-research-deep     volle Recherche (pipeline.prepare), unveraendert
  team    -> chess-opponent-team-prep          ganze Mannschaft: je Spieler eine der drei Stufen (modes/team.py)

Neue Stufen: Modul hier anlegen (run(...) -> int), Befehl in briefing.py, Skill unter skills/, Ansicht in render/.
"""
STAGES = {
    "scout": {"skill": "chess-opponent-scout-fast", "command": "scout", "data_dir": "scout"},
    "briefing": {"skill": "chess-opponent-briefing-medium", "command": "brief", "data_dir": "briefing[_ich-weiss|_ich-schwarz]"},
    "research": {"skill": "chess-opponent-research-deep", "command": "prepare", "data_dir": "research"},
}
# Ueber den Stufen: team (chess-opponent-team-prep, Befehl "team") ruft je Spieler eine Stufe auf -> output/teams/
