import unittest
from datetime import datetime, timedelta, timezone

from common.refresh import (
    HIDDEN_LIVE_REFRESH_SECONDS,
    PREGAME_REFRESH_SECONDS,
    QUIET_REFRESH_SECONDS,
    due_sports,
    next_kickoff,
    schedule_is_current,
    sport_refresh_seconds,
)


class FootballGame:
    def __init__(self, status, start_at, event_id="1"):
        self.status = status
        self.start_at = start_at
        self.event_id = event_id


KICKOFF = datetime(2026, 11, 17, 1, 15, tzinfo=timezone.utc)


def _settings(selected=("nfl:1",)):
    return {
        "refresh_interval": 30,
        "selected_games": list(selected),
        "hidden_games": [],
    }


class RefreshCadenceTests(unittest.TestCase):
    def test_a_scheduled_game_stays_slow_until_it_starts(self):
        game = FootballGame("STATUS_SCHEDULED", KICKOFF.isoformat())
        before = KICKOFF - timedelta(minutes=30)
        self.assertEqual(
            sport_refresh_seconds("nfl", [game], _settings(), before),
            PREGAME_REFRESH_SECONDS,
        )
        self.assertEqual(
            sport_refresh_seconds("nfl", [game], _settings(), KICKOFF),
            30,
        )

    def test_a_game_without_a_start_time_keeps_the_pregame_interval(self):
        game = FootballGame("STATUS_SCHEDULED", "")
        self.assertEqual(
            sport_refresh_seconds("nfl", [game], _settings(), KICKOFF),
            PREGAME_REFRESH_SECONDS,
        )

    def test_a_postponed_game_does_not_become_live_at_its_old_start(self):
        game = FootballGame(
            "STATUS_POSTPONED",
            (KICKOFF - timedelta(hours=1)).isoformat(),
        )
        self.assertEqual(
            sport_refresh_seconds("nfl", [game], _settings(), KICKOFF),
            QUIET_REFRESH_SECONDS,
        )

    def test_kickoff_makes_a_recently_fetched_feed_due(self):
        game = FootballGame("STATUS_SCHEDULED", KICKOFF.isoformat())
        settings = _settings()
        before = KICKOFF - timedelta(minutes=2)
        waiting = {
            "nfl": sport_refresh_seconds("nfl", [game], settings, before),
        }
        until = next_kickoff([game], before)

        self.assertEqual(waiting["nfl"], PREGAME_REFRESH_SECONDS)
        self.assertEqual(until, KICKOFF)
        self.assertTrue(schedule_is_current(1, "mark", until, 1, "mark", before))
        self.assertFalse(schedule_is_current(1, "mark", until, 1, "mark", KICKOFF))

        fetched = {"nfl": 1000}
        self.assertNotIn("nfl", due_sports(fetched, waiting, 1100))

        started = {
            "nfl": sport_refresh_seconds("nfl", [game], settings, KICKOFF),
        }
        self.assertEqual(started["nfl"], 30)
        self.assertIn("nfl", due_sports(fetched, started, 1100))

    def test_a_hidden_game_uses_the_slower_live_interval_at_kickoff(self):
        game = FootballGame("STATUS_SCHEDULED", KICKOFF.isoformat(), event_id="9")
        self.assertEqual(
            sport_refresh_seconds(
                "nfl",
                [game],
                _settings(selected=("nfl:1",)),
                KICKOFF,
            ),
            HIDDEN_LIVE_REFRESH_SECONDS,
        )
