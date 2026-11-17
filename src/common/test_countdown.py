import unittest
from datetime import datetime, timedelta, timezone

from common.countdown import (
    can_countdown,
    countdown_button,
    countdown_line,
    countdown_settings_for,
    format_remaining,
    kickoff_countdown,
)


def _game(status="Scheduled", start_at="2026-11-10T01:00:00Z", event_id="99"):
    game = type("FootballGame", (), {})()
    game.away = "BUF"
    game.home = "KC"
    game.status = status
    game.start_at = start_at
    game.event_id = event_id
    return game


class CountdownTests(unittest.TestCase):
    def test_remaining_time_includes_seconds_and_days(self):
        self.assertEqual(format_remaining(3661), "1:01:01")
        self.assertEqual(format_remaining(90061), "1D 1:01:01")
        self.assertEqual(format_remaining(0), "")

    def test_line_uses_the_saved_kickoff(self):
        now = datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc)
        settings = {
            "countdown": {
                "game_id": "nfl:99",
                "away": "BUF",
                "home": "KC",
                "start_at": "2026-11-10T01:00:00Z",
            }
        }
        self.assertEqual(
            countdown_line(now=now, settings=settings),
            ("BUF KC", "2:00:00"),
        )

    def test_a_started_game_drops_the_countdown(self):
        now = datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc)
        settings = {
            "countdown": {
                "game_id": "nfl:99",
                "away": "BUF",
                "home": "KC",
                "start_at": "2026-11-10T01:00:00Z",
            }
        }
        game = _game(status="Live")
        self.assertIsNone(
            countdown_line(games=[game], now=now, settings=settings)
        )

    def test_only_a_future_game_can_be_chosen(self):
        now = datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc)
        upcoming = _game()
        self.assertTrue(can_countdown(upcoming, now=now))
        self.assertEqual(
            countdown_settings_for(upcoming)["game_id"],
            "nfl:99",
        )
        self.assertFalse(can_countdown(_game(status="Final"), now=now))
        self.assertFalse(can_countdown(_game(start_at=""), now=now))
        self.assertIn("On the clock", countdown_button("nfl:99", True))
        self.assertIn('value="nfl:99"', countdown_button("nfl:99", False))

    def test_focus_counts_down_inside_two_hours(self):
        kickoff = datetime(2026, 11, 15, 1, 0, tzinfo=timezone.utc)
        game = _game(start_at=kickoff.isoformat())
        self.assertEqual(kickoff_countdown(game, now=kickoff), "STARTING SOON")
        self.assertEqual(
            kickoff_countdown(game, now=kickoff + timedelta(minutes=5)),
            "STARTING SOON",
        )
        self.assertEqual(
            kickoff_countdown(game, now=kickoff - timedelta(hours=2)),
            "",
        )
        self.assertEqual(
            kickoff_countdown(game, now=kickoff - timedelta(hours=3)),
            "",
        )
        self.assertEqual(
            kickoff_countdown(game, now=kickoff - timedelta(hours=1)),
            "1:00:00",
        )
        self.assertEqual(
            kickoff_countdown(game, now=kickoff - timedelta(minutes=30)),
            "0:30:00",
        )
        self.assertEqual(
            kickoff_countdown(_game(start_at=""), now=kickoff - timedelta(hours=1)),
            "",
        )


if __name__ == "__main__":
    unittest.main()
