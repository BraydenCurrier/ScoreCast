import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from nfl.models import FootballGame
from stocks.models import StockQuote

from modes.page import render_modes_page
from modes.engine import (
    delete_custom_mode,
    market_is_open,
    mode_focus_games,
    mode_ticker,
    save_custom_mode,
    set_mode_enabled,
)


EARLY = "2026-10-25T17:00:00Z"
LATE = "2026-10-25T20:25:00Z"
NIGHT = "2026-10-26T00:20:00Z"
SUNDAY_MORNING = datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc)
SUNDAY_LATE = datetime(2026, 10, 25, 20, 30, tzinfo=timezone.utc)
SUNDAY_NIGHT = datetime(2026, 10, 26, 0, 30, tzinfo=timezone.utc)
MONDAY = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)
MARKET_OPEN = datetime(2026, 10, 27, 14, 30, tzinfo=timezone.utc)
MARKET_CLOSED = datetime(2026, 10, 27, 21, 0, tzinfo=timezone.utc)
SATURDAY = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)


class HockeyGame:
    def __init__(self, status, event_id):
        self.status = status
        self.event_id = event_id
        self.away = "BOS"
        self.home = "NYR"


class BasketballGame:
    def __init__(self, status, event_id):
        self.status = status
        self.event_id = event_id
        self.away = "BOS"
        self.home = "NYK"


def _nfl(status, start_at, event_id, away="KC", home="BUF"):
    return FootballGame(
        away=away,
        home=home,
        status=status,
        start_time="",
        away_score=0,
        home_score=0,
        away_wins=0,
        away_losses=0,
        home_wins=0,
        home_losses=0,
        quarter=1,
        clock="10:00",
        possession="",
        down=1,
        distance=10,
        yardline_side="",
        yardline_number=25,
        event_id=event_id,
        start_at=start_at,
    )


def _settings(*enabled, favorites=None):
    return {
        "modes": {"enabled": list(enabled), "custom": []},
        "favorite_teams": favorites or {},
    }


def _ids(games):
    return [
        getattr(game, "event_id", None) or getattr(game, "symbol", "")
        for game in games
    ]


class ModeScheduleTests(unittest.TestCase):
    def setUp(self):
        self.early = _nfl("STATUS_SCHEDULED", EARLY, "early")
        self.late = _nfl("STATUS_SCHEDULED", LATE, "late", "DAL", "PHI")
        self.night = _nfl("STATUS_SCHEDULED", NIGHT, "night", "GB", "CHI")
        self.nba = BasketballGame("Scheduled", "nba")
        self.stock = StockQuote("SPY", "S&P 500", 500, 1, 0.2)
        self.all_games = [
            self.early,
            self.late,
            self.night,
            self.nba,
            self.stock,
        ]
        self.manual = [self.nba, self.stock]

    def test_sunday_morning_keeps_early_previews_only(self):
        shown = mode_ticker(
            self.all_games,
            self.manual,
            [],
            _settings("nfl-sunday"),
            SUNDAY_MORNING,
        )

        self.assertEqual(_ids(shown), ["nba", "SPY", "early"])
        self.assertEqual(mode_focus_games(
            self.all_games,
            _settings("nfl-sunday"),
            SUNDAY_MORNING,
            manual_games=self.manual,
        ), [])

    def test_later_games_appear_when_they_start_and_finals_leave(self):
        self.early.status = "STATUS_IN_PROGRESS"
        self.late.status = "STATUS_IN_PROGRESS"
        self.night.status = "STATUS_FINAL"

        shown = mode_ticker(
            self.all_games,
            self.manual,
            [],
            _settings("nfl-sunday"),
            SUNDAY_LATE,
        )

        self.assertEqual(_ids(shown), ["nba", "SPY", "early", "late"])

    def test_sunday_night_focuses_the_live_night_game(self):
        self.early.status = "STATUS_FINAL"
        self.late.status = "STATUS_FINAL"
        self.night.status = "STATUS_IN_PROGRESS"
        settings = _settings("nfl-sunday")

        shown = mode_ticker(
            self.all_games,
            self.manual,
            [],
            settings,
            SUNDAY_NIGHT,
        )
        focus = mode_focus_games(self.all_games, settings, SUNDAY_NIGHT)

        self.assertEqual(_ids(shown), ["nba", "SPY", "night"])
        self.assertEqual(focus, [self.night])

    def test_monday_leaves_the_manual_board_alone(self):
        self.assertIsNone(mode_ticker(
            self.all_games,
            self.manual,
            [],
            _settings("nfl-sunday"),
            MONDAY,
        ))

    def test_market_hours_follow_the_new_york_session(self):
        self.assertTrue(market_is_open(MARKET_OPEN))
        self.assertFalse(market_is_open(MARKET_CLOSED))
        self.assertFalse(market_is_open(SATURDAY))

        open_board = mode_ticker(
            self.all_games,
            [self.nba],
            [],
            _settings("market-hours"),
            MARKET_OPEN,
        )
        closed_board = mode_ticker(
            self.all_games,
            self.manual,
            [],
            _settings("market-hours"),
            MARKET_CLOSED,
        )

        self.assertEqual(_ids(open_board), ["nba", "SPY"])
        self.assertEqual(_ids(closed_board), ["nba"])

    def test_one_remaining_game_fills_the_screen(self):
        self.late.status = "STATUS_FINAL"
        self.night.status = "STATUS_FINAL"
        settings = _settings("nfl-sunday")

        focus = mode_focus_games(
            self.all_games,
            settings,
            SUNDAY_MORNING,
            manual_games=[self.stock],
        )

        self.assertEqual(focus, [self.early])

    def test_two_games_keep_scrolling(self):
        settings = _settings("nfl-sunday")
        focus = mode_focus_games(
            self.all_games,
            settings,
            SUNDAY_MORNING,
            manual_games=[self.nba],
        )

        self.assertEqual(focus, [])

    def test_a_league_without_a_focus_view_stays_on_the_scroll(self):
        hockey = HockeyGame("STATUS_IN_PROGRESS", "nhl")
        focus = mode_focus_games(
            [hockey],
            _settings("live-only"),
            SUNDAY_LATE,
        )

        self.assertEqual(focus, [])

    def test_live_only_drops_previews_and_leaves_stocks(self):
        self.early.status = "STATUS_IN_PROGRESS"
        shown = mode_ticker(
            self.all_games,
            self.manual + [self.late],
            [],
            _settings("live-only"),
            SUNDAY_LATE,
        )

        self.assertEqual(_ids(shown), ["SPY", "early"])

    def test_custom_mode_can_be_saved_and_removed(self):
        settings = _settings()
        stored = save_custom_mode(settings, {
            "name": "Celtics night",
            "days": ["1", "3"],
            "sports": ["nba"],
            "phases": ["live"],
            "start": "18:00",
            "end": "23:00",
            "favorites_only": True,
        })
        settings = {"modes": stored, "favorite_teams": {"nba": ["BOS"]}}
        settings["modes"] = set_mode_enabled(settings, stored["custom"][0]["id"], True)
        self.nba.status = "STATUS_IN_PROGRESS"

        with patch(
            "modes.engine.get_local_timezone",
            return_value=ZoneInfo("America/Chicago"),
        ):
            shown = mode_ticker(
                [self.nba],
                [],
                [],
                settings,
                datetime(2026, 10, 28, 0, 30, tzinfo=timezone.utc),
            )

        self.assertEqual(shown, [self.nba])
        cleared = delete_custom_mode(settings, stored["custom"][0]["id"])
        self.assertEqual(cleared["custom"], [])
        self.assertEqual(cleared["enabled"], [])

    def test_modes_page_lists_presets_and_a_custom_form(self):
        html = render_modes_page(
            "<style></style>",
            "<header>Modes</header>",
            _settings(),
        )

        self.assertIn("NFL Sunday", html)
        self.assertIn("Market Hours", html)
        self.assertIn("College Saturday", html)
        self.assertIn("NBA Tonight", html)
        self.assertIn("Live Only", html)
        self.assertIn("NFL Prime Time", html)
        self.assertIn('action="/modes/save"', html)
        self.assertIn("Add mode", html)
        self.assertIn('name="sport" value="stocks"', html)
        self.assertIn(">Off<", html)

    def test_a_mode_needs_a_name_and_something_to_show(self):
        with self.assertRaises(ValueError):
            save_custom_mode(_settings(), {"name": "", "sports": ["nfl"]})
        with self.assertRaises(ValueError):
            save_custom_mode(_settings(), {"name": "Empty", "sports": []})
