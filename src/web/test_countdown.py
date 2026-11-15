import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import web.app as appmod


def _game():
    kickoff = datetime.now(timezone.utc) + timedelta(hours=3)
    game = type("FootballGame", (), {})()
    game.away = "BUF"
    game.home = "KC"
    game.status = "Scheduled"
    game.start_at = kickoff.replace(microsecond=0).isoformat()
    game.event_id = "99"
    game.away_score = 0
    game.home_score = 0
    game.date = "Nov 9"
    game.start_time = "7:00"
    return game


class CountdownPageTests(unittest.TestCase):
    def test_scores_page_offers_a_countdown_for_a_future_game(self):
        game = _game()
        settings = {
            "countdown": {
                "game_id": "",
                "away": "",
                "home": "",
                "start_at": "",
            },
            "selected_games": [],
            "hidden_games": [],
            "favorite_teams": {},
        }
        user = {"id": "1", "role": "root", "username": "brayden"}
        appmod.latest_games = [game]
        with appmod.app.test_request_context("/games"):
            with patch.object(appmod, "get_settings", return_value=settings), \
                 patch.object(appmod, "current_user", return_value=user), \
                 patch("modes.engine.mode_locked_ids", return_value=[]):
                html = appmod.games.__wrapped__()
        self.assertIn("clock-countdown", html)
        self.assertIn(">Countdown<", html)
        self.assertIn('value="nfl:99"', html)

    def test_choosing_a_game_saves_its_kickoff(self):
        game = _game()
        stored = {}

        def update(values):
            stored.update(values)
            return values

        appmod.latest_games = [game]
        with appmod.app.test_request_context(
            "/games/countdown",
            method="POST",
            data={"game": "nfl:99"},
        ):
            with patch.object(appmod, "update_settings", side_effect=update):
                response = appmod.save_game_countdown.__wrapped__()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(stored["countdown"]["game_id"], "nfl:99")
        self.assertEqual(stored["countdown"]["away"], "BUF")
        self.assertEqual(stored["countdown"]["home"], "KC")
        self.assertTrue(stored["countdown"]["start_at"])


if __name__ == "__main__":
    unittest.main()
