"""Offline-Tests fuer chess-opponent-team-prep und die Option beide Farben (ohne Netz, ohne Engine)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chess_briefing import config, lineup as L  # noqa: E402
from chess_briefing.modes import common as C, scout as S  # noqa: E402
from chess_briefing.validate import validate_briefing  # noqa: E402
from tests.test_pipeline import _briefing, _dossier, morphy  # noqa: E402
from tests import test_stages as TS  # noqa: E402

LIGA = """<html><head><title>BMM Hannover 2026/2027</title></head><body><h2>SK Beispiel</h2>
<table><tr><th>R</th><th>Gegner</th></tr><tr><td>1</td><td>X</td></tr></table>
<table><tr><th>Nr.</th><th>Name</th><th>DWZ</th><th>1</th></tr>
<tr><td>101</td><td><a href="/ligen/bezirk1-2627/s/1/">Muster, Max</a></td><td>2001</td><td>1</td></tr>
<tr><td>102</td><td><a href="/ligen/bezirk1-2627/s/2/">Beispiel, Bea</a></td><td>1950</td><td></td></tr>
<tr><td>103</td><td>Probe, Paul</td><td></td><td></td></tr>
<tr><td>201</td><td>Ersatz, Erik</td><td>1700</td><td></td></tr></table></body></html>"""


class Lineup(unittest.TestCase):
    def test_ligaserver_table(self):
        d = L.parse_ligaserver(LIGA, "https://nsv-online.de/ligen/bezirk1-2627/m/1/")
        self.assertEqual(d["team"], "SK Beispiel")
        self.assertEqual([(p["nr"], p["name"], p["dwz"]) for p in d["players"]][:3],
                         [(101, "Muster, Max", 2001), (102, "Beispiel, Bea", 1950), (103, "Probe, Paul", None)])
        self.assertEqual(d["players"][0]["profile"], "https://nsv-online.de/ligen/bezirk1-2627/s/1/")

    def test_boards_by_number_then_by_position(self):
        d = L.parse_ligaserver(LIGA, "https://nsv-online.de/ligen/x-2627/m/1/")
        self.assertEqual([p["nr"] for p in L.select(d, "101-102")], [101, 102])
        self.assertEqual([p["nr"] for p in L.select(d, "2,4")], [102, 201])        # keine Nr. 2/4 -> Position

    def test_colors_alternate_from_first_board(self):
        ps = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        L.assign_colors(ps, None, "black")
        self.assertEqual([p["color"] for p in ps], ["black", "white", "black"])
        ps = [{"name": "a"}]
        L.assign_colors(ps, None, None)
        self.assertEqual(ps[0]["color"], "both")                                 # Standard: beide Farben

    def test_ligaserver_url_and_list_input(self):
        self.assertTrue(L.is_ligaserver_team("https://schachbezirk-hannover.de/ligen/bezirk1-2627/m/8933/"))
        self.assertFalse(L.is_ligaserver_team("https://players.chessbase.com/de/player/mustermann_max"))
        d = L.load(["https://players.chessbase.com/de/player/a_b", "16299566"], team="Test")
        self.assertEqual([p["nr"] for p in d["players"]], [1, 2])
        self.assertEqual(L.player_input(d["players"][1]), "16299566")


class BothColors(unittest.TestCase):
    def test_opponent_colors(self):
        self.assertEqual(C.opponent_colors("white"), ["black"])
        self.assertEqual(C.opponent_colors("both"), ["white", "black"])
        self.assertEqual(C.output_dir(Path("p"), "medium", "both").name, "medium_beide")

    def test_scout_both_colors_has_both_repertoires(self):
        d, _ = S.build_scout(morphy(), TS.Scout.games(None), [], {}, [], None)
        titles = [s["title"] for s in d["briefing"]["summary"]]
        self.assertIn("Sein Repertoire mit Weiß", titles)
        self.assertIn("Sein Repertoire mit Schwarz", titles)
        self.assertIsNone(d["mode"]["opponent_color"])

    def test_medium_both_needs_both_sides(self):
        d = _dossier(online=False)
        d["mode"] = {"name": "medium", "sides": ["as_white", "as_black"], "min_plan_steps": 3}
        P_, _ = validate_briefing(_briefing(), d)
        self.assertEqual(P_, [])
        b = _briefing()
        b.pop("as_black")
        P_, _ = validate_briefing(b, d)
        self.assertTrue(any("as_black" in p for p in P_))


class TeamPage(unittest.TestCase):
    def test_team_page_embeds_reports_and_marks_missing(self):
        from chess_briefing.render.team import render_team
        old = config.PLAYERS_DIR
        with tempfile.TemporaryDirectory() as tmp:
            config.PLAYERS_DIR = Path(tmp)
            try:
                (Path(tmp) / "muster_max").mkdir()
                (Path(tmp) / "muster_max" / "scout_muster_max.html").write_text("<html>Bericht Muster</html>", encoding="utf-8")
                doc = {"team": "SK Beispiel", "source": "Liste", "stage": "scout", "generated": "2026-10-19T12:00",
                       "seconds": 12.0, "players": [
                           {"nr": 1, "name": "Muster, Max", "slug": "muster_max", "color": "white", "seconds": 3.0},
                           {"nr": 2, "name": "Probe, Paul", "slug": None, "color": "both", "note": "nicht eindeutig"}]}
                out = render_team(Path(tmp) / "_teams" / "sk_beispiel", doc)
                t = out.read_text(encoding="utf-8")
                self.assertEqual(out.name, "team_sk_beispiel_scout.html")
                self.assertIn('data-tab="p1"', t)
                self.assertIn("tm-item is-stub", t)                               # Spieler ohne Report gestrichelt
                self.assertIn("nicht eindeutig", t)
                self.assertNotIn("Bericht Muster", t)                            # eingebettet nur komprimiert
            finally:
                config.PLAYERS_DIR = old


class Names(unittest.TestCase):
    def test_title_is_not_part_of_first_name(self):
        from chess_briefing.identify import _split_fide_name
        self.assertEqual(_split_fide_name("Mustermann, Max, Dr."), ("Mustermann", "Max"))
        self.assertEqual(_split_fide_name("Drost, Dragan"), ("Drost", "Dragan"))


if __name__ == "__main__":
    unittest.main()
