import unittest

from nhl.api import (
    _apply_live_advantage,
    _box_shots,
    _on_ice_lineups,
    _power_play_state,
    _recent_play,
)
from nhl.focus_renderer import (
    CLOCK_AMBER,
    ICE,
    META_Y,
    PP_ORANGE,
    SIREN_ON,
    WHITE,
    YELLOW,
    _goal_celebrations,
    render_nhl_focus,
)
from nhl.models import HockeyGame
from nhl.colors import team_color


def _live(**overrides):
    game = HockeyGame(
        away="DAL",
        home="COL",
        status="Live",
        start_time="",
        date="",
        away_score=1,
        home_score=0,
        away_wins=48,
        away_losses=22,
        away_ot_losses=12,
        home_wins=50,
        home_losses=21,
        home_ot_losses=11,
        period=1,
        clock="12:41",
        away_sog=8,
        home_sog=6,
        possession="DAL",
        away_goalie="Oettinger",
        home_goalie="Blackwood",
        away_save_pct=".921",
        home_save_pct=".908",
        event_id="nhl-live",
    )
    for key, value in overrides.items():
        setattr(game, key, value)
    return game


def _summary():
    def player(athlete_id, jersey, position, group):
        return group, {
            "athlete": {
                "id": athlete_id,
                "jersey": jersey,
                "position": {"abbreviation": position},
            }
        }

    away_rows = [
        player("1", "61", "RW", "forwards"),
        player("2", "9", "C", "forwards"),
        player("3", "49", "LW", "forwards"),
        player("4", "27", "D", "defenses"),
        player("5", "3", "D", "defenses"),
        player("6", "79", "G", "goalies"),
        player("7", "8", "C", "forwards"),
    ]
    groups = {}
    for group, athlete in away_rows:
        groups.setdefault(group, []).append(athlete)
    return {
        "header": {
            "competitions": [
                {
                    "competitors": [
                        {"homeAway": "away", "team": {"id": "37"}},
                        {"homeAway": "home", "team": {"id": "1"}},
                    ]
                }
            ]
        },
        "boxscore": {
            "players": [
                {
                    "team": {"id": "37"},
                    "statistics": [
                        {"name": name, "athletes": athletes}
                        for name, athletes in groups.items()
                    ],
                }
            ]
        },
        "onIce": [
            {
                "teamId": "37",
                "entries": [
                    {"athleteid": "4", "whereabouts": {"name": "ROSTER_WHEREABOUTS_IN_PLAY"}},
                    {"athleteid": "1", "whereabouts": {"name": "ROSTER_WHEREABOUTS_IN_PLAY"}},
                    {"athleteid": "5", "whereabouts": {"name": "ROSTER_WHEREABOUTS_IN_PLAY"}},
                    {"athleteid": "3", "whereabouts": {"name": "ROSTER_WHEREABOUTS_IN_PLAY"}},
                    {"athleteid": "2", "whereabouts": {"name": "ROSTER_WHEREABOUTS_IN_PLAY"}},
                    {"athleteid": "6", "whereabouts": {"name": "ROSTER_WHEREABOUTS_IN_PLAY"}},
                    {"athleteid": "7", "whereabouts": {"name": "ROSTER_WHEREABOUTS_ON_BENCH"}},
                ],
            }
        ],
    }


def _penalty(clock, team, minutes="2", kind="Minor", text="Tripping", period=2):
    return {
        "clock": {"displayValue": clock},
        "period": {"number": period},
        "type": {
            "text": text,
            "penaltyMinutes": minutes,
            "penaltyType": kind,
        },
        "team": {"id": team},
        "scoringPlay": False,
    }


def _pp_goal(clock, team, period=2):
    return {
        "clock": {"displayValue": clock},
        "period": {"number": period},
        "type": {"text": "Goal"},
        "team": {"id": team},
        "scoringPlay": True,
        "strength": {"text": "Power Play", "abbreviation": "power-play"},
    }


def _pp_summary(plays):
    return {
        "header": {
            "competitions": [
                {
                    "competitors": [
                        {"homeAway": "away", "team": {"id": "5"}},
                        {"homeAway": "home", "team": {"id": "26"}},
                    ]
                }
            ]
        },
        "plays": plays,
    }


class NhlPowerPlayTests(unittest.TestCase):
    def test_minor_shows_the_time_left(self):
        side, clock, strength = _power_play_state(
            _pp_summary([_penalty("6:17", "26")]),
            2,
            "12:36",
        )
        self.assertEqual((side, clock, strength), ("away", "0:53", "5-4"))

    def test_expired_minor_is_not_a_power_play(self):
        self.assertEqual(
            _power_play_state(_pp_summary([_penalty("6:17", "26")]), 2, "11:25"),
            ("", "", ""),
        )

    def test_power_play_goal_ends_the_minor(self):
        self.assertEqual(
            _power_play_state(
                _pp_summary([_penalty("6:17", "26"), _pp_goal("6:47", "5")]),
                2,
                "12:36",
            ),
            ("", "", ""),
        )

    def test_two_minors_show_both_clocks(self):
        side, clock, strength = _power_play_state(
            _pp_summary([_penalty("6:00", "26"), _penalty("7:00", "26")]),
            2,
            "12:40",
        )
        self.assertEqual((side, clock, strength), ("away", "0:40  1:40", "5-3"))

    def test_matching_penalties_are_not_a_power_play(self):
        self.assertEqual(
            _power_play_state(
                _pp_summary([_penalty("6:00", "26"), _penalty("6:10", "5")]),
                2,
                "12:40",
            ),
            ("", "", ""),
        )

    def test_misconduct_does_not_create_a_power_play(self):
        self.assertEqual(
            _power_play_state(
                _pp_summary([
                    _penalty("6:17", "26", "10", "Game", "Game Misconduct"),
                ]),
                2,
                "12:36",
            ),
            ("", "", ""),
        )

    def test_goal_during_a_double_minor_leaves_two_minutes(self):
        side, clock, strength = _power_play_state(
            _pp_summary([
                _penalty("6:00", "26", "4", "Double Minor", "High Sticking"),
                _pp_goal("6:30", "5"),
            ]),
            2,
            "13:20",
        )
        self.assertEqual((side, clock, strength), ("away", "1:50", "5-4"))

    def test_a_power_play_already_on_when_the_clock_is_behind(self):
        summary = _pp_summary([
            _penalty("0:21", "26", period=3),
            {
                "clock": {"displayValue": "0:40"},
                "period": {"number": 3},
                "type": {"text": "Face Off"},
                "team": {"id": "5"},
                "strength": {"text": "Power Play", "abbreviation": "power-play"},
                "scoringPlay": False,
            },
        ])
        summary["header"]["competitions"][0]["status"] = {
            "period": 2,
            "displayClock": "0:00",
        }
        side, clock, strength = _power_play_state(summary, 2, "0:00")
        self.assertEqual((side, strength), ("away", "5-4"))
        self.assertEqual(clock, "1:41")

    def test_missing_penalty_still_shows_the_power_play(self):
        summary = _pp_summary([
            {
                "clock": {"displayValue": "0:40"},
                "period": {"number": 3},
                "type": {"text": "Face Off"},
                "team": {"id": "5"},
                "strength": {"text": "Power Play", "abbreviation": "power-play"},
                "scoringPlay": False,
            },
        ])
        self.assertEqual(
            _power_play_state(summary, 3, "18:50"),
            ("away", "", ""),
        )

    def test_an_even_faceoff_clears_a_finished_power_play(self):
        summary = _pp_summary([
            {
                "clock": {"displayValue": "0:40"},
                "period": {"number": 3},
                "type": {"text": "Face Off"},
                "team": {"id": "5"},
                "strength": {"text": "Power Play", "abbreviation": "power-play"},
                "scoringPlay": False,
            },
            {
                "clock": {"displayValue": "2:40"},
                "period": {"number": 3},
                "type": {"text": "Face Off"},
                "team": {"id": "5"},
                "strength": {"text": "Even Strength", "abbreviation": "even-strength"},
                "scoringPlay": False,
            },
        ])
        self.assertEqual(
            _power_play_state(summary, 3, "16:00"),
            ("", "", ""),
        )

    def test_on_ice_shows_a_power_play_the_penalties_missed(self):
        self.assertEqual(
            _apply_live_advantage(
                ("", "", ""),
                ("33", "93", "23", "58", "53"),
                ("21", "13", "5", "42"),
                True,
            ),
            ("away", "", "5-4"),
        )

    def test_box_score_shots_are_shots_on_goal(self):
        payload = {
            "header": {
                "competitions": [
                    {
                        "competitors": [
                            {"homeAway": "away", "team": {"id": "37"}},
                            {"homeAway": "home", "team": {"id": "1"}},
                        ]
                    }
                ]
            },
            "boxscore": {
                "teams": [
                    {
                        "team": {"id": "37"},
                        "statistics": [
                            {"name": "shotsTotal", "displayValue": "21"},
                            {"name": "shootoutGoals", "abbreviation": "SOG", "displayValue": "0"},
                        ],
                    },
                    {
                        "team": {"id": "1"},
                        "statistics": [
                            {"name": "shotsTotal", "displayValue": "24"},
                        ],
                    },
                ]
            },
        }
        self.assertEqual(_box_shots(payload), (21, 24))

    def test_recent_play_skips_the_faceoff_and_keeps_the_goal(self):
        plays = [
            {
                "type": {"text": "Goal"},
                "scoringPlay": True,
                "participants": [{"athlete": {"displayName": "Carter Mazur"}}],
            },
            {
                "type": {"text": "Face Off"},
                "participants": [{"athlete": {"displayName": "Sam Bennett"}}],
            },
        ]
        self.assertEqual(_recent_play(plays), ("Mazur", "GOAL", True))

    def test_recent_play_names_the_goalie_on_a_save(self):
        plays = [
            {
                "type": {"text": "Shot"},
                "scoringPlay": False,
                "participants": [
                    {"athlete": {"displayName": "Michael Rasmussen"}},
                    {"athlete": {"displayName": "Jacob Markstrom"}},
                ],
            },
        ]
        self.assertEqual(_recent_play(plays), ("Markstrom", "SAVE", False))

    def test_recent_play_shortens_a_penalty(self):
        plays = [
            {
                "type": {"text": "High-sticking", "penaltyMinutes": "2"},
                "participants": [{"athlete": {"displayName": "Lars Eller"}}],
            },
        ]
        self.assertEqual(_recent_play(plays), ("Eller", "HIGH STICK", False))

    def test_on_ice_without_the_flag_is_not_a_power_play(self):
        self.assertEqual(
            _apply_live_advantage(
                ("", "", ""),
                ("33", "93", "23", "58", "53"),
                ("21", "13", "5", "42"),
                False,
            ),
            ("", "", ""),
        )


class NhlOnIceTests(unittest.TestCase):
    def test_on_ice_is_forwards_then_defense_then_goalie(self):
        away, home = _on_ice_lineups(_summary())
        self.assertEqual(away, ("61", "49", "9", "27", "3"))
        self.assertEqual(home, ())


class NhlFocusRenderTests(unittest.TestCase):
    def test_boards_cover_every_hockey_state(self):
        live = render_nhl_focus(_live(), {})
        final = render_nhl_focus(
            _live(status="Final", clock="", away_score=5, home_score=2),
            {},
        )
        scheduled = render_nhl_focus(
            _live(status="Scheduled", start_time="6:00", date="Oct 7", broadcast=""),
            {},
        )
        intermission = render_nhl_focus(
            _live(status="Intermission", intermission=True, clock="0:00", period=1),
            {},
        )
        overtime = render_nhl_focus(
            _live(status="Overtime", overtime=True, period=4, clock="3:08"),
            {},
        )
        shootout = render_nhl_focus(
            _live(
                status="Shootout",
                shootout=True,
                away_so_goals=2,
                home_so_goals=1,
            ),
            {},
        )
        power_play = render_nhl_focus(
            _live(power_play="DAL", strength="5-4", possession="DAL"),
            {},
        )
        boards = (
            live,
            final,
            scheduled,
            intermission,
            overtime,
            shootout,
            power_play,
        )
        for image in boards:
            self.assertEqual(image.size, (384, 32))
        self.assertEqual(len({image.tobytes() for image in boards}), len(boards))

    def test_team_rails_use_team_colors(self):
        image = render_nhl_focus(_live(), {})
        self.assertEqual(image.getpixel((1, 16)), team_color("DAL"))
        self.assertEqual(image.getpixel((383, 16)), team_color("COL"))

    def test_live_score_is_yellow_and_scheduled_is_not(self):
        live = render_nhl_focus(_live(), {})
        scheduled = render_nhl_focus(
            _live(
                status="Scheduled",
                start_time="6:00",
                date="Oct 7",
                broadcast="",
                away_score=0,
                home_score=0,
            ),
            {},
        )
        self.assertIn(YELLOW, live.get_flattened_data())
        self.assertNotIn(YELLOW, scheduled.get_flattened_data())

    def test_power_play_clock_paints_the_center_orange(self):
        image = render_nhl_focus(
            _live(power_play="DAL", power_play_clock="0:53", strength="5-4"),
            {},
        )
        even = render_nhl_focus(_live(), {})
        center = [
            image.getpixel((x, y))
            for y in range(10, 20)
            for x in range(140, 250)
        ]
        badge = [
            image.getpixel((x, y))
            for y in range(3, 8)
            for x in range(90, 120)
        ]
        goalie_row = [
            image.getpixel((x, y))
            for y in range(META_Y, META_Y + 5)
            for x in range(40, 120)
        ]
        self.assertIn(PP_ORANGE, center)
        self.assertIn(PP_ORANGE, badge)
        self.assertNotIn(PP_ORANGE, goalie_row)
        self.assertNotEqual(image.tobytes(), even.tobytes())

    def test_power_play_paints_the_center_orange(self):
        image = render_nhl_focus(
            _live(power_play="VGK", strength="5-3", away="VGK", home="LA"),
            {},
        )
        center = [
            image.getpixel((x, y))
            for y in range(10, 20)
            for x in range(150, 234)
        ]
        self.assertIn(PP_ORANGE, center)

    def test_small_pp_sits_beside_the_abbreviation(self):
        home = render_nhl_focus(
            _live(power_play="COL", strength="4-5", possession=""),
            {},
        )
        badge = [
            home.getpixel((x, y))
            for y in range(3, 8)
            for x in range(258, 300)
        ]
        goalie_row = [
            home.getpixel((x, y))
            for y in range(META_Y, META_Y + 5)
            for x in range(260, 340)
        ]
        self.assertIn(PP_ORANGE, badge)
        self.assertNotIn(PP_ORANGE, goalie_row)

    def test_last_play_is_yellow_for_a_goal_and_shots_stay(self):
        image = render_nhl_focus(
            _live(
                event_id="goal-text",
                last_play_name="Ekblad",
                last_play_label="GOAL",
                last_play_goal=True,
            ),
            {},
        )
        middle = [
            image.getpixel((x, y))
            for y in range(12, 19)
            for x in range(150, 234)
        ]
        shots = [
            image.getpixel((x, y))
            for y in range(META_Y, META_Y + 5)
            for x in range(110, 126)
        ]
        self.assertIn(YELLOW, middle)
        self.assertIn(WHITE, shots)

    def test_empty_net_replaces_the_last_play(self):
        image = render_nhl_focus(
            _live(
                event_id="empty-net",
                empty_net=True,
                last_play_name="Ekblad",
                last_play_label="GOAL",
                last_play_goal=True,
            ),
            {},
        )
        goal = render_nhl_focus(
            _live(
                event_id="goal-text-plain",
                last_play_name="Ekblad",
                last_play_label="GOAL",
                last_play_goal=True,
            ),
            {},
        )
        middle = [
            image.getpixel((x, y))
            for y in range(12, 19)
            for x in range(150, 234)
        ]
        self.assertNotEqual(image.tobytes(), goal.tobytes())
        self.assertIn((255, 255, 255), middle)
        self.assertNotIn(YELLOW, middle)

    def test_on_ice_numbers_sit_beside_the_score(self):
        image = render_nhl_focus(
            _live(away_lineup=("61", "9", "49", "27", "79")),
            {},
        )
        plain = render_nhl_focus(_live(), {})
        self.assertNotEqual(image.tobytes(), plain.tobytes())
        band = [
            image.getpixel((x, y))
            for y in range(16, 22)
            for x in range(40, 110)
        ]
        self.assertIn(team_color("DAL"), band)
        final = render_nhl_focus(
            _live(
                status="Final",
                clock="",
                away_lineup=("61", "9", "49", "27", "79"),
            ),
            {},
        )
        self.assertNotEqual(image.tobytes(), final.tobytes())

    def test_goalie_line_uses_the_bottom_row(self):
        image = render_nhl_focus(_live(), {})
        bottom = [
            image.getpixel((x, y))
            for y in range(META_Y, META_Y + 5)
            for x in range(40, 120)
        ]
        self.assertIn(team_color("DAL"), bottom)

    def test_score_change_rolls(self):
        from common import football_focus

        game = _live(event_id="slide-1", away_score=1, home_score=0)
        for side in ("away", "home"):
            football_focus._score_slides.pop(("nhl:slide-1", side), None)

        render_nhl_focus(game, {})
        render_nhl_focus(game, {})
        game.away_score = 2
        sliding = render_nhl_focus(game, {})
        settled = render_nhl_focus(
            _live(event_id="slide-settled", away_score=2, home_score=0),
            {},
        )
        self.assertNotEqual(sliding.tobytes(), settled.tobytes())

        football_focus._score_slides[("nhl:slide-1", "away")]["start"] -= 1
        finished = render_nhl_focus(game, {})
        self.assertEqual(finished.tobytes(), settled.tobytes())


class NhlGoalCelebrationTests(unittest.TestCase):
    def _center(self, image, y0, y1):
        return [
            image.getpixel((x, y))
            for y in range(y0, y1)
            for x in range(140, 250)
        ]

    def test_a_goal_already_on_the_board_does_not_celebrate(self):
        _goal_celebrations.clear()
        game = _live(
            event_id="goal-seen",
            last_play_name="Ekblad",
            last_play_label="GOAL",
            last_play_goal=True,
        )
        image = render_nhl_focus(game, {}, now=10)
        self.assertIn(CLOCK_AMBER, self._center(image, 1, 8))
        self.assertNotIn(ICE, self._center(image, 28, 32))

    def test_a_new_goal_puts_the_scorer_over_the_ice(self):
        _goal_celebrations.clear()
        game = _live(event_id="goal-new", away_score=1, home_score=0)
        render_nhl_focus(game, {}, now=10)
        game.away_score = 2
        game.last_play_name = "Ekblad"
        game.last_play_label = "GOAL"
        game.last_play_goal = True
        skating = render_nhl_focus(game, {}, now=10.3)
        scored = render_nhl_focus(game, {}, now=11.5)
        done = render_nhl_focus(game, {}, now=14)
        self.assertIn(ICE, self._center(skating, 28, 32))
        self.assertIn(YELLOW, self._center(skating, 0, 7))
        self.assertNotIn(CLOCK_AMBER, self._center(skating, 0, 8))
        self.assertNotIn(SIREN_ON, self._center(skating, 8, 16))
        self.assertIn(SIREN_ON, self._center(scored, 8, 16))
        self.assertIn(CLOCK_AMBER, self._center(done, 1, 8))
        self.assertNotIn(ICE, self._center(done, 28, 32))
