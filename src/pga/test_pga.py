import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from datetime import date

from pga.api import (
    logo_from_schedule,
    next_event_id,
    player_from_competitor,
    tournament_from_event,
)
from pga.models import GolfPlayer, GolfTournament
from pga.pga_renderer import (
    PAGE_HOLD_SECONDS,
    card_width,
    display_page,
    page_players,
    render_game_strip_onto,
)


def _competitor(name, score, value, status, linescores):
    return {
        "sortOrder": 1,
        "athlete": {"lastName": name, "displayName": name},
        "score": {"displayValue": score},
        "statistics": [
            {"name": "scoreToPar", "displayValue": score, "value": value},
        ],
        "status": status,
        "linescores": linescores,
    }


class PgaLeaderboardTests(unittest.TestCase):
    def test_finished_round_shows_the_round_score(self):
        player = player_from_competitor(_competitor(
            "Brennan",
            "-16",
            -16,
            {
                "hole": 18,
                "thru": 18,
                "displayThru": "F",
                "type": {
                    "name": "STATUS_FINISH",
                    "state": "post",
                    "completed": True,
                },
            },
            [{"value": 68.0, "displayValue": "-3", "period": 4}],
        ))
        self.assertEqual(player.name, "BRENNAN")
        self.assertEqual(player.score, "-16")
        self.assertTrue(player.finished_round)
        self.assertEqual(player.marker, "68")
        self.assertEqual(player.position, "")

    def test_player_on_the_course_shows_the_hole(self):
        player = player_from_competitor(_competitor(
            "Mitchell",
            "-8",
            -8,
            {
                "hole": 14,
                "thru": 13,
                "displayThru": "13",
                "position": {"displayName": "T2"},
                "type": {
                    "name": "STATUS_IN_PROGRESS",
                    "state": "in",
                    "completed": False,
                },
            },
            [{"value": 32.0, "displayValue": "-4", "period": 1}],
        ))
        self.assertFalse(player.finished_round)
        self.assertEqual(player.marker, "14")
        self.assertEqual(player.position, "T2")

    def test_first_round_shows_the_tee_time(self):
        player = player_from_competitor(
            _competitor(
                "Brennan",
                "",
                None,
                {
                    "teeTime": "2026-10-22T13:10:00Z",
                    "period": 1,
                    "type": {
                        "name": "STATUS_SCHEDULED",
                        "state": "pre",
                        "completed": False,
                    },
                },
                [],
            ),
            today=date(2026, 10, 22),
        )
        self.assertTrue(player.awaiting_tee)
        self.assertEqual(player.marker, "8:10A")
        self.assertEqual(player.score, "")
        self.assertFalse(player.finished_round)

    def test_new_day_shows_todays_tee_time_instead_of_yesterdays_score(self):
        player = player_from_competitor(
            _competitor(
                "Brennan",
                "-3",
                -3,
                {
                    "teeTime": "2026-10-23T14:05:00Z",
                    "period": 2,
                    "displayThru": "F",
                    "thru": 18,
                    "hole": 18,
                    "type": {
                        "name": "STATUS_FINISH",
                        "state": "post",
                        "completed": True,
                    },
                },
                [{
                    "value": 68.0,
                    "displayValue": "-3",
                    "period": 1,
                    "teeTime": "2026-10-22T13:10:00Z",
                }],
            ),
            today=date(2026, 10, 23),
        )
        self.assertTrue(player.awaiting_tee)
        self.assertEqual(player.marker, "9:05A")
        self.assertEqual(player.score, "-3")
        self.assertNotEqual(player.marker, "68")

    def test_cut_players_are_left_off_the_card(self):
        player = player_from_competitor(_competitor(
            "Smith",
            "+4",
            4,
            {
                "type": {"name": "STATUS_CUT", "state": "post"},
                "position": {"displayName": "CUT"},
            },
            [],
        ))
        self.assertIsNone(player)

    def test_leaderboard_keeps_six_players_in_order(self):
        competitors = []
        for index, name in enumerate(
            ["A", "B", "C", "D", "E", "F", "Cut"]
        ):
            status_name = "STATUS_CUT" if name == "Cut" else "STATUS_FINISH"
            competitors.append({
                "sortOrder": index + 1,
                "athlete": {"lastName": name},
                "statistics": [{
                    "name": "scoreToPar",
                    "displayValue": f"-{10 - index}",
                    "value": -(10 - index),
                }],
                "status": {
                    "type": {"name": status_name, "state": "post", "completed": True},
                    "displayThru": "F",
                    "hole": 18,
                    "position": {"displayName": "CUT" if name == "Cut" else str(index + 1)},
                },
                "linescores": [{"value": 70, "displayValue": "E"}],
            })
        tournament = tournament_from_event({
            "id": "99",
            "shortName": "Baycurrent Classic",
            "status": {"type": {"state": "in", "name": "STATUS_IN_PROGRESS"}},
            "competitions": [{"competitors": competitors}],
        })
        self.assertEqual(tournament.status, "Live")
        self.assertEqual(
            [player.name for player in tournament.players],
            ["A", "B", "C", "D", "E", "F"],
        )
        self.assertEqual(
            [player.position for player in tournament.players],
            ["1", "2", "3", "4", "5", "6"],
        )

    def test_leaderboard_keeps_a_second_page(self):
        competitors = []
        for index in range(8):
            competitors.append({
                "sortOrder": index + 1,
                "athlete": {"lastName": chr(ord("A") + index)},
                "statistics": [{
                    "name": "scoreToPar",
                    "displayValue": f"-{8 - index}",
                    "value": -(8 - index),
                }],
                "status": {
                    "type": {"name": "STATUS_FINISH", "state": "post", "completed": True},
                    "displayThru": "F",
                    "hole": 18,
                    "position": {"displayName": str(index + 1)},
                },
                "linescores": [{"value": 70, "displayValue": "E"}],
            })
        tournament = tournament_from_event({
            "id": "99",
            "shortName": "Baycurrent Classic",
            "status": {"type": {"state": "post", "name": "STATUS_FINAL"}},
            "competitions": [{"competitors": competitors}],
        })
        self.assertEqual(len(tournament.players), 8)
        self.assertEqual(
            [player.name for player in page_players(tournament.players, 0)],
            ["A", "B", "C", "D", "E", "F"],
        )
        self.assertEqual(
            [player.name for player in page_players(tournament.players, 1)],
            ["G", "H"],
        )
        self.assertEqual(display_page(tournament.players, now=0), 0)
        self.assertEqual(
            display_page(tournament.players, now=PAGE_HOLD_SECONDS),
            1,
        )
        width = card_width(tournament)
        first = Image.new("RGB", (width, 32), (0, 0, 0))
        second = Image.new("RGB", (width, 32), (0, 0, 0))
        with patch("pga.pga_renderer.time.time", return_value=0):
            render_game_strip_onto(first, ImageDraw.Draw(first), tournament, 0, {})
        with patch(
            "pga.pga_renderer.time.time",
            return_value=PAGE_HOLD_SECONDS,
        ):
            render_game_strip_onto(second, ImageDraw.Draw(second), tournament, 0, {})
        self.assertNotEqual(first.tobytes(), second.tobytes())

    def test_monday_moves_to_the_next_tournament(self):
        calendar = [
            {
                "id": "1",
                "start": date(2026, 10, 8),
                "end": date(2026, 10, 11),
            },
            {
                "id": "2",
                "start": date(2026, 10, 22),
                "end": date(2026, 10, 25),
            },
        ]
        self.assertIsNone(next_event_id(
            calendar, "1", date(2026, 10, 11), date(2026, 10, 11), "post",
        ))
        self.assertEqual(next_event_id(
            calendar, "1", date(2026, 10, 11), date(2026, 10, 12), "post",
        ), "2")
        self.assertIsNone(next_event_id(
            calendar, "1", date(2026, 10, 11), date(2026, 10, 12), "in",
        ))

    def test_first_tee_times_are_the_first_six(self):
        competitors = []
        for index, hour in enumerate((16, 12, 15, 13, 18, 14, 19, 17)):
            competitors.append({
                "sortOrder": index + 1,
                "athlete": {"lastName": chr(ord("A") + index)},
                "status": {
                    "teeTime": f"2026-10-22T{hour:02d}:00:00Z",
                    "period": 1,
                    "type": {
                        "name": "STATUS_SCHEDULED",
                        "state": "pre",
                        "completed": False,
                    },
                },
                "linescores": [],
            })
        tournament = tournament_from_event({
            "id": "99",
            "shortName": "Bermuda",
            "date": "2026-10-22T04:00Z",
            "endDate": "2026-10-25T04:00Z",
            "status": {
                "type": {
                    "state": "pre",
                    "name": "STATUS_SCHEDULED",
                    "completed": False,
                }
            },
            "competitions": [{"competitors": competitors}],
        })
        self.assertEqual(
            [player.name for player in page_players(tournament.players, 0)],
            ["B", "D", "F", "C", "A", "H"],
        )
        self.assertTrue(all(player.awaiting_tee for player in tournament.players))

    def test_schedule_page_logo_matches_the_tournament(self):
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            '{"page":{"tournamentName":"Baycurrent Classic",'
            '"tournamentLogo":["https://example.com/baycurrent.png"]}}'
            "</script>"
        )
        self.assertEqual(
            logo_from_schedule(html, "Baycurrent Classic"),
            "https://example.com/baycurrent.png",
        )
        self.assertEqual(logo_from_schedule(html, "Masters"), "")

    def test_card_draws_the_leader_row(self):
        tournament = GolfTournament(
            event_id="sample",
            name="Baycurrent Classic",
            status="Live",
            logo_url="",
            players=(
                GolfPlayer("BRENNAN", "1", "-16", -16, "68", True),
                GolfPlayer("MITCHELL", "T2", "-8", -8, "14", False),
                GolfPlayer("BRIDGEMAN", "T2", "-7", -7, "11", False),
                GolfPlayer("SCHAUFFELE", "4", "-6", -6, "67", True),
                GolfPlayer("HARMAN", "5", "-5", -5, "8", False),
                GolfPlayer("GERARD", "6", "-4", -4, "70", True),
            ),
        )
        width = card_width(tournament)
        image = Image.new("RGB", (width, 32), (0, 0, 0))
        render_game_strip_onto(
            image,
            ImageDraw.Draw(image),
            tournament,
            0,
            {},
        )
        self.assertGreater(max(image.convert("L").tobytes()), 0)
        for top, bottom in ((8, 15), (16, 23), (24, 31)):
            band = max(image.crop((0, top, width, bottom)).convert("L").tobytes())
            self.assertGreater(band, 0)


if __name__ == "__main__":
    unittest.main()
