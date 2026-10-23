import unittest
from unittest.mock import patch

from mlb.models import BaseballGame
from nfl.models import FootballGame

import web.app as appmod


def _nfl():
    return FootballGame(
        away="GB",
        home="DET",
        status="STATUS_SCHEDULED",
        start_time="7:20",
        away_score=0,
        home_score=0,
        away_wins=1,
        away_losses=0,
        home_wins=1,
        home_losses=0,
        quarter=0,
        clock="",
        possession="",
        down=0,
        distance=0,
        yardline_side="",
        yardline_number=0,
    )


def _mlb():
    return BaseballGame(
        "NYY",
        "BOS",
        "Scheduled",
        "7:08",
        0,
        0,
        1,
        0,
        1,
        0,
        0,
        True,
        False,
        False,
        False,
        0,
    )


class FocusPageTests(unittest.TestCase):
    def test_page_shows_one_league(self):
        settings = {
            "focus_mode": {
                "enabled": True,
                "nfl_game_ids": [],
                "mlb_game_ids": [],
                "rotation_seconds": 30,
            }
        }
        with appmod.app.test_request_context("/focus?league=mlb"):
            with patch.object(appmod, "get_settings", return_value=settings), \
                 patch.object(appmod, "latest_games", [_nfl(), _mlb()]):
                html = appmod.focus_page.__wrapped__()

        self.assertIn('id="focus_league"', html)
        self.assertIn('value="mlb" selected', html)
        self.assertIn('name="focus_mlb_game"', html)
        self.assertIn("NYY", html)
        self.assertNotIn('name="focus_nfl_game"', html)
        self.assertNotIn(">GB<", html)

    def test_save_updates_only_the_open_league(self):
        stored = {}
        mlb = _mlb()
        mlb_id = appmod.get_game_id(mlb)

        def update(values):
            stored.update(values)
            return values

        with appmod.app.test_request_context(
            "/save_focus",
            method="POST",
            data={
                "league": "mlb",
                "focus_enabled": "on",
                "focus_rotation_seconds": "45",
                "focus_mlb_game": mlb_id,
            },
        ):
            with patch.object(appmod, "update_settings", side_effect=update), \
                 patch.object(appmod, "latest_games", [_nfl(), mlb]):
                appmod.save_focus.__wrapped__()

        focus = stored["focus_mode"]
        self.assertEqual(focus["mlb_game_ids"], [mlb_id])
        self.assertNotIn("nfl_game_ids", focus)
        self.assertNotIn("cfb_game_ids", focus)
        self.assertTrue(focus["enabled"])
        self.assertEqual(focus["rotation_seconds"], 45)


if __name__ == "__main__":
    unittest.main()
