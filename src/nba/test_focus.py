import unittest

from PIL import Image

from nba.api import (
    _bonus_flags,
    _details_from_payload,
    _last_play,
    _points_leader,
    _quarter_scores,
)
from nba.focus_renderer import play_line, render_nba_focus
from nba.models import BasketballGame


def _live(**overrides):
    game = BasketballGame(
        away="HOU",
        home="SA",
        status="Live",
        start_time="",
        date="",
        away_score=96,
        home_score=88,
        away_wins=2,
        away_losses=1,
        home_wins=1,
        home_losses=2,
        quarter=4,
        clock="8:17",
        possession="HOU",
        away_timeouts=4,
        home_timeouts=3,
        bonus="SA",
        away_leader="A. Thompson",
        away_leader_points="18",
        home_leader="V. Wembanyama",
        home_leader_points="22",
        last_play_text="Brook Lopez makes free throw 1 of 2",
        last_play_type="Free Throw - 1 of 2",
        last_play_athlete="B. Lopez",
        last_play_points=1,
        away_quarters=(28, 24, 22, 22),
        home_quarters=(20, 26, 24, 18),
    )
    for key, value in overrides.items():
        setattr(game, key, value)
    return game


class NbaPlayLineTests(unittest.TestCase):
    def test_common_play_descriptions(self):
        self.assertEqual(
            play_line(
                "Brook Lopez makes free throw 1 of 2",
                "Free Throw - 1 of 2",
                "B. Lopez",
            ),
            "LOPEZ FT",
        )
        self.assertEqual(
            play_line("Zach Edey loose ball foul", "Loose Ball Foul", "Z. Edey"),
            "EDEY FOUL",
        )
        self.assertEqual(
            play_line("Pelicans Full timeout", "Full Timeout", ""),
            "TIMEOUT",
        )
        self.assertEqual(
            play_line("Rockets Coach's Challenge", "Challenge", ""),
            "CHALLENGE",
        )
        self.assertEqual(
            play_line(
                "Jalen Green makes 26-foot three pointer",
                "Jump Shot",
                "J. Green",
            ),
            "GREEN 3PT",
        )


class NbaScoreboardParseTests(unittest.TestCase):
    def test_leader_quarters_and_last_play(self):
        competitor = {
            "id": "10",
            "team": {"id": "10", "abbreviation": "HOU"},
            "leaders": [
                {
                    "name": "points",
                    "leaders": [
                        {
                            "displayValue": "18",
                            "athlete": {"shortName": "A. Thompson"},
                        }
                    ],
                }
            ],
            "linescores": [
                {"value": 28.0},
                {"displayValue": "24"},
            ],
        }
        self.assertEqual(_points_leader(competitor), ("A. Thompson", "18"))
        self.assertEqual(_quarter_scores(competitor), (28, 24))
        text, kind, team, athlete, points = _last_play(
            {
                "lastPlay": {
                    "text": "Amen Thompson makes layup",
                    "type": {"text": "Layup Shot"},
                    "scoreValue": 2,
                    "team": {"id": "10"},
                    "athletesInvolved": [{"shortName": "A. Thompson"}],
                }
            },
            {"id": "1", "team": {"id": "1", "abbreviation": "SA"}},
            competitor,
        )
        self.assertEqual(text, "Amen Thompson makes layup")
        self.assertEqual(kind, "Layup Shot")
        self.assertEqual(team, "HOU")
        self.assertEqual(athlete, "A. Thompson")
        self.assertEqual(points, 2)

    def test_both_teams_can_be_in_the_bonus(self):
        away, home = _bonus_flags(
            {"awayInBonus": True, "homeInBonus": True}
        )
        self.assertEqual((away, home), (True, True))
        self.assertEqual(_bonus_flags({"inBonus": "away"}), (True, False))
        self.assertEqual(_bonus_flags({}), (False, False))

    def test_core_situation_has_timeouts_bonus_and_possession(self):
        home = {"id": "13", "team": {"id": "13", "abbreviation": "LAL"}}
        away = {"id": "12", "team": {"id": "12", "abbreviation": "LAC"}}
        details = _details_from_payload(
            {
                "homeTimeouts": {
                    "timeoutsCurrent": 1,
                    "timeoutsRemainingCurrent": 3,
                },
                "awayTimeouts": {
                    "timeoutsCurrent": 2,
                    "timeoutsRemainingCurrent": 0,
                },
                "homeFouls": {"bonusState": "NONE"},
                "awayFouls": {"bonusState": "DOUBLE"},
            },
            {
                "possessionTeam": {
                    "$ref": "http://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/2027/teams/12?lang=en"
                }
            },
            home,
            away,
        )
        self.assertEqual(details["possession"], "LAC")
        self.assertEqual(details["home_timeouts"], 3)
        self.assertEqual(details["away_timeouts"], 0)
        self.assertFalse(details["home_in_bonus"])
        self.assertTrue(details["away_in_bonus"])


class NbaFocusRenderTests(unittest.TestCase):
    def test_score_change_rolls(self):
        from common import football_focus

        game = _live(event_id="slide-1", away_score=10, home_score=8)
        for side in ("away", "home"):
            football_focus._score_slides.pop(("nba:slide-1", side), None)

        render_nba_focus(game, {})
        render_nba_focus(game, {})
        game.away_score = 12
        sliding = render_nba_focus(game, {})
        settled = render_nba_focus(
            _live(event_id="slide-settled", away_score=12, home_score=8),
            {},
        )
        self.assertNotEqual(sliding.tobytes(), settled.tobytes())

        football_focus._score_slides[("nba:slide-1", "away")]["start"] -= 1
        finished = render_nba_focus(game, {})
        self.assertEqual(finished.tobytes(), settled.tobytes())

        game.away_score = 15
        held = render_nba_focus(
            game,
            {"developer": {"score_slide": False}},
        )
        jumped = render_nba_focus(
            _live(event_id="slide-off", away_score=15, home_score=8),
            {"developer": {"score_slide": False}},
        )
        self.assertEqual(held.tobytes(), jumped.tobytes())

    def test_boards_are_full_width(self):
        live = render_nba_focus(_live(), {})
        final = render_nba_focus(_live(status="Final", clock="", quarter=4), {})
        scheduled = render_nba_focus(
            _live(status="Scheduled", start_time="7:30", date="Oct 23"),
            {},
        )
        for image in (live, final, scheduled):
            self.assertEqual(image.size, (384, 32))
        self.assertNotEqual(live.tobytes(), final.tobytes())
        self.assertNotEqual(live.tobytes(), scheduled.tobytes())


if __name__ == "__main__":
    unittest.main()
