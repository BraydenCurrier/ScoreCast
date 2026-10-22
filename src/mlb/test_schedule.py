import unittest
from datetime import date
from unittest.mock import patch

from mlb.api import choose_baseball_slate, get_today_games
from mlb.models import BaseballGame


def _game(status, away="TB", home="MIL"):
    return BaseballGame(
        away,
        home,
        status,
        "7:08",
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        True,
        False,
        False,
        False,
        0,
    )


def _raw(status, away_id, home_id, game_pk):
    return {
        "gamePk": game_pk,
        "gameDate": "2026-10-23T23:08:00Z",
        "status": {"abstractGameState": status},
        "teams": {
            "away": {"team": {"id": away_id, "name": "Away"}, "score": 0},
            "home": {"team": {"id": home_id, "name": "Home"}, "score": 0},
        },
        "linescore": {},
    }


class BaseballSlateTests(unittest.TestCase):
    def test_today_still_to_play_stays_today(self):
        today = [_game("Live", "NYY", "BOS")]
        later = [("2026-10-23", [_game("Preview")])]
        chosen = choose_baseball_slate(today, later)
        self.assertEqual(chosen[0].away, "NYY")

    def test_finished_today_uses_the_next_game(self):
        today = [_game("Final", "LAD", "TOR")]
        later = [
            ("2026-10-23", [_game("Postponed", "ATH", "SEA")]),
            ("2026-10-24", [_game("Preview", "TB", "MIL")]),
        ]
        chosen = choose_baseball_slate(today, later)
        self.assertEqual((chosen[0].away, chosen[0].home), ("TB", "MIL"))

    def test_off_day_fetches_the_next_slate(self):
        today_payload = {"dates": []}
        upcoming_payload = {
            "dates": [
                {
                    "date": "2026-10-23",
                    "games": [_raw("Preview", 139, 158, 775293)],
                }
            ]
        }

        with (
            patch("mlb.api.datetime") as clock,
            patch("mlb.api._fetch_schedule", return_value=today_payload) as today_fetch,
            patch("mlb.api._fetch_schedule_between", return_value=upcoming_payload) as ahead,
            patch("mlb.api._enrich_live_at_bats", side_effect=lambda games: games),
        ):
            clock.now.return_value.date.return_value = date(2026, 10, 22)
            games = get_today_games()

        today_fetch.assert_called_once()
        ahead.assert_called_once()
        self.assertEqual(len(games), 1)
        self.assertEqual((games[0].away, games[0].home, games[0].status), ("TB", "MIL", "Preview"))


class StartupSlateTests(unittest.TestCase):
    def test_boot_does_not_fill_sample_games(self):
        from main import SPORT_DISPLAY_ORDER, combine_sports_results

        empty = {sport: [] for sport in SPORT_DISPLAY_ORDER}
        failed = combine_sports_results(
            empty,
            sports_errors={"nfl": RuntimeError("dns")},
            previous_games=[],
        )
        quiet = combine_sports_results(empty, previous_games=[])

        self.assertEqual(failed, [])
        self.assertEqual(quiet, [])


if __name__ == "__main__":
    unittest.main()
