import unittest

from PIL import Image, ImageDraw

from cbb.models import CollegeBasketballGame
from cbb.renderer import CARD_STRIP, render_game_strip_onto
from nba.api import games_from_scoreboard
from nba.focus_renderer import render_cbb_focus
from players.cards import _cbb_search_hit, stored_card_players


def _event(abbreviation="DUKE"):
    return {
        "id": "401800001",
        "date": "2026-11-05T23:00Z",
        "competitions": [
            {
                "status": {
                    "period": 0,
                    "displayClock": "",
                    "type": {
                        "state": "pre",
                        "name": "STATUS_SCHEDULED",
                        "shortDetail": "7:00 PM",
                    },
                },
                "competitors": [
                    {
                        "homeAway": "away",
                        "score": "0",
                        "team": {"abbreviation": abbreviation},
                    },
                    {
                        "homeAway": "home",
                        "score": "0",
                        "team": {"abbreviation": "UNC"},
                    },
                ],
            }
        ],
    }


class CollegeBasketballBoardTests(unittest.TestCase):
    def test_scoreboard_builds_a_college_game(self):
        games = games_from_scoreboard({"events": [_event("UTAH")]}, "cbb")

        self.assertEqual(len(games), 1)
        game = games[0]
        self.assertIsInstance(game, CollegeBasketballGame)
        self.assertEqual(game.away, "UTAH")
        self.assertEqual(game.home, "UNC")
        self.assertEqual(game.timeout_slots, 4)
        self.assertEqual(game.status, "Scheduled")

    def test_nba_still_shortens_utah(self):
        games = games_from_scoreboard({"events": [_event("UTAH")]}, "nba")

        self.assertEqual(games[0].__class__.__name__, "BasketballGame")
        self.assertEqual(games[0].away, "UTA")

    def test_scroll_card_is_wider_than_the_nba_card(self):
        game = CollegeBasketballGame(
            away="DUKE",
            home="CONN",
            status="Live",
            start_time="",
            date="",
            away_score=70,
            home_score=68,
            quarter=2,
            clock="1:04",
            away_timeouts=3,
            home_timeouts=2,
        )
        image = Image.new("RGB", (CARD_STRIP, 32), (0, 0, 0))
        render_game_strip_onto(
            image,
            ImageDraw.Draw(image),
            game,
            0,
            {},
        )

        self.assertEqual(image.size, (148, 32))
        self.assertEqual(CARD_STRIP, 148)

    def test_focus_card_fills_the_board(self):
        game = CollegeBasketballGame(
            away="DUKE",
            home="UNC",
            status="Live",
            start_time="",
            date="",
            away_score=42,
            home_score=38,
            quarter=1,
            clock="8:12",
            away_timeouts=4,
            home_timeouts=3,
            event_id="cbb-focus",
        )
        image = render_cbb_focus(game, {})

        self.assertEqual(image.size, (384, 32))

    def test_player_search_keeps_college_basketball(self):
        hit = _cbb_search_hit({
            "id": "4711256",
            "displayName": "Caleb Foster",
            "league": "mens-college-basketball",
            "sport": "basketball",
            "isActive": True,
            "position": {"abbreviation": "G"},
            "teamRelationships": [
                {"core": {"abbreviation": "DUKE"}},
            ],
        })

        self.assertEqual(hit["id"], "cbb:4711256")
        self.assertEqual(hit["team"], "DUKE")
        self.assertIsNone(_cbb_search_hit({
            "id": "1",
            "displayName": "Pro Player",
            "league": "nba",
            "sport": "basketball",
            "isActive": True,
            "position": {"abbreviation": "G"},
        }))

        saved = stored_card_players(
            ["cbb:4711256"],
            [{
                "league": "cbb",
                "name": "Caleb Foster",
                "team": "DUKE",
                "position": "G",
                "espn_id": "4711256",
            }],
            [],
        )

        self.assertEqual(saved[0]["league"], "cbb")
        self.assertEqual(saved[0]["team"], "DUKE")


if __name__ == "__main__":
    unittest.main()
