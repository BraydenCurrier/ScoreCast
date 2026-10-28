import unittest
from unittest.mock import patch

from fantasy.espn import (
    EspnError,
    _scoring_period,
    failure_message,
    form_settings,
    matchups_from_payload,
    parse_cookie_paste,
    parse_league_ids,
    parse_league_paste,
)


PAYLOAD = {
    "settings": {"name": "MLB2K23"},
    "status": {"currentMatchupPeriod": 26},
    "teams": [
        {"id": 1, "abbrev": "NYY", "name": "Bombers", "logo": "https://example.test/nyy.png", "record": {"overall": {"wins": 8, "losses": 5, "ties": 0}}},
        {"id": 2, "abbrev": "BOS", "name": "Sox", "logo": "", "record": {"overall": {"wins": 6, "losses": 6, "ties": 1}}},
    ],
    "schedule": [
        {
            "id": 90,
            "matchupPeriodId": 25,
            "home": {"teamId": 1, "totalPoints": 10},
            "away": {"teamId": 2, "totalPoints": 9},
        },
        {
            "id": 91,
            "matchupPeriodId": 26,
            "away": {
                "teamId": 2,
                "totalPoints": 3,
                "totalPointsLive": 8,
                "rosterForCurrentScoringPeriod": {
                    "entries": [
                        {
                            "lineupSlotId": 0,
                            "playerPoolEntry": {"player": {"stats": [
                                {"scoringPeriodId": 26, "statSourceId": 1, "statSplitTypeId": 1, "appliedTotal": 18.5},
                                {"scoringPeriodId": 26, "statSourceId": 0, "statSplitTypeId": 1, "appliedTotal": 8},
                            ]}},
                        },
                        {
                            "lineupSlotId": 2,
                            "playerPoolEntry": {"player": {"stats": [
                                {"scoringPeriodId": 26, "statSourceId": 1, "statSplitTypeId": 1, "appliedTotal": 11.25},
                            ]}},
                        },
                        {
                            "lineupSlotId": 16,
                            "playerPoolEntry": {"player": {"stats": [
                                {"scoringPeriodId": 26, "statSourceId": 1, "statSplitTypeId": 1, "appliedTotal": 40},
                            ]}},
                        },
                    ],
                },
            },
            "home": {
                "teamId": 1,
                "totalPoints": 4,
                "totalPointsLive": 12.5,
                "totalProjectedPointsLive": 110.4,
            },
        },
        {
            "id": 92,
            "matchupPeriodId": 26,
            "home": {"teamId": 1, "totalPoints": 1},
        },
    ],
}


class EspnTests(unittest.TestCase):
    def test_league_ids_reject_words(self):
        self.assertEqual(parse_league_ids(" 101, 202 101 "), ["101", "202"])
        with self.assertRaises(EspnError):
            parse_league_ids("101 abc")

    def test_league_link_sets_the_sport_and_id(self):
        ids, sport, season = parse_league_paste(
            "https://fantasy.espn.com/basketball/league?leagueId=55&seasonId=2026"
        )
        self.assertEqual(ids, ["55"])
        self.assertEqual(sport, "fba")
        self.assertEqual(season, "2026")

    def test_cookie_header_fills_both_secrets(self):
        swid, secret = parse_cookie_paste(
            "SWID=%7Babc%7D; other=1; espn_s2=topsecret"
        )
        self.assertEqual(swid, "{abc}")
        self.assertEqual(secret, "topsecret")
        with self.assertRaises(EspnError):
            parse_cookie_paste("SWID={abc}")

    def test_a_league_link_and_cookie_header_can_be_saved(self):
        with patch("fantasy.espn.fetch_league") as fetch:
            fields = form_settings(
                {
                    "espn_sport": "ffl",
                    "espn_leagues": (
                        "https://fantasy.espn.com/football/team"
                        "?leagueId=77&seasonId=2026"
                    ),
                    "espn_cookies": "SWID={abc}; espn_s2=secret",
                    "check_espn": "1",
                },
                {},
                "2026",
            )
        self.assertEqual(fields["espn_sport"], "ffl")
        self.assertEqual(fields["espn_leagues"], ["77"])
        self.assertEqual(fields["espn_swid"], "{abc}")
        self.assertEqual(fields["espn_s2"], "secret")
        fetch.assert_called_once()
        with patch("fantasy.espn.fetch_league"):
            with self.assertRaises(EspnError):
                form_settings(
                    {
                        "espn_sport": "ffl",
                        "espn_leagues": (
                            "https://fantasy.espn.com/football/team"
                            "?leagueId=77&seasonId=2025"
                        ),
                    },
                    {},
                    "2026",
                )

    def test_private_league_message_asks_for_cookies(self):
        message = failure_message(401, ["You are not authorized to view this League."])
        self.assertIn("espn_s2", message)
        self.assertNotIn("authorized", message.lower())

    def test_current_period_uses_live_points_and_skips_byes(self):
        with patch("fantasy.espn.ensure_avatar", return_value="/tmp/logo.png"):
            games = matchups_from_payload(PAYLOAD, "flb", "101")
        self.assertEqual(len(games), 1)
        game = games[0]
        self.assertEqual(game.away, "BOS")
        self.assertEqual(game.home, "NYY")
        self.assertEqual(game.away_score, 8)
        self.assertEqual(game.home_score, 12.5)
        self.assertEqual(game.away_projected, 29.75)
        self.assertEqual(game.home_projected, 110.4)
        self.assertEqual((game.away_wins, game.away_losses, game.away_ties), (6, 6, 1))
        self.assertEqual((game.home_wins, game.home_losses, game.home_ties), (8, 5, 0))
        self.assertEqual(game.league_id, "espn-flb-101")
        self.assertEqual(game.league_name, "MLB2K23")
        self.assertEqual(game.week, 26)
        self.assertEqual(game.matchup_id, 91)
        self.assertEqual(game.away_logo, "/tmp/logo.png")

    def test_football_uses_the_matchup_week_for_projections(self):
        self.assertEqual(_scoring_period("ffl", {
            "currentMatchupPeriod": 16,
            "latestScoringPeriod": 18,
        }), 16)
        self.assertEqual(_scoring_period("flb", {
            "currentMatchupPeriod": 26,
            "latestScoringPeriod": 196,
        }), 196)

    def test_blank_cookies_stay_saved_until_the_league_changes(self):
        previous = {
            "espn_sport": "ffl",
            "espn_leagues": ["101"],
            "espn_swid": "{saved}",
            "espn_s2": "saved-secret",
        }
        with patch("fantasy.espn.fetch_league") as fetch:
            fields = form_settings(
                {"espn_sport": "ffl", "espn_leagues": "101", "espn_swid": "", "espn_s2": ""},
                previous,
                "2026",
            )
        fetch.assert_not_called()
        self.assertEqual(fields["espn_s2"], "saved-secret")
        self.assertEqual(fields["espn_swid"], "{saved}")

    def test_added_leagues_stay_until_one_is_removed(self):
        previous = {
            "espn_sport": "ffl",
            "espn_leagues": ["101", "202"],
            "espn_swid": "",
            "espn_s2": "",
        }
        with patch("fantasy.espn.fetch_league") as fetch:
            kept = form_settings(
                {"espn_sport": "ffl", "espn_leagues": "", "espn_swid": "", "espn_s2": ""},
                previous,
                "2026",
            )
            remaining = form_settings(
                {
                    "espn_sport": "ffl",
                    "espn_leagues": "303",
                    "espn_swid": "",
                    "espn_s2": "",
                    "remove_league": "espn:101",
                },
                previous,
                "2026",
            )
        self.assertEqual(
            [call.args[2] for call in fetch.call_args_list],
            ["202", "303"],
        )
        self.assertEqual(kept["espn_leagues"], ["101", "202"])
        self.assertEqual(remaining["espn_leagues"], ["202", "303"])

    def test_a_new_league_is_checked_before_it_is_saved(self):
        with patch("fantasy.espn.fetch_league", side_effect=EspnError("missing")) as fetch:
            with self.assertRaises(EspnError):
                form_settings(
                    {"espn_sport": "ffl", "espn_leagues": "55", "espn_swid": "", "espn_s2": ""},
                    {},
                    "2026",
                )
        fetch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
