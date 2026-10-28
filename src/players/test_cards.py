import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from common.game_ids import game_id
from players.cards import (
    PlayerCard,
    field_status,
    game_context,
    game_stat_groups,
    refresh_player_cards,
    ticker_player_cards,
)
from players.renderer import (
    DETAIL_Y,
    GREY,
    HERO_Y,
    LIVE,
    META_Y,
    NAME_Y,
    ON_FIELD,
    TEXT_X,
    WHITE,
    YELLOW,
    _meta_parts,
    card_width,
    render_game_strip_onto,
)
import players.cards as cards_module
import players.renderer as renderer_module


KC = (255, 0, 10)


def _game(names, this_game, season=None, short_name="KC @ SEA"):
    splits = [{
        "displayName": "This Game",
        "stats": this_game,
    }]

    if season is not None:
        splits.append({
            "displayName": "Regular Season",
            "stats": season,
        })

    return {
        "statistics": {
            "names": names,
            "splits": [{
                "displayName": "Regular Season",
                "stats": season or this_game,
            }],
        },
        "nextGame": {
            "displayName": "Previous Game",
            "statistics": {
                "names": names,
                "splits": splits,
            },
            "league": {
                "events": [{
                    "shortName": short_name,
                }],
            },
        },
    }


def _render(card):
    image = Image.new("RGB", (card_width(card), 32), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    render_game_strip_onto(image, draw, card, 0, {})
    return image


def _colors(image, y_start, y_end, x_start=0):
    found = set()

    for y in range(y_start, y_end):
        for x in range(x_start, image.width):
            pixel = image.getpixel((x, y))
            if pixel != (0, 0, 0):
                found.add(pixel)

    return found


class PlayerStatTests(unittest.TestCase):
    def test_quarterback_uses_this_game_not_the_season(self):
        groups, opponent = game_stat_groups(
            _game(
                ["passingYards", "passingTouchdowns", "interceptions"],
                ["165", "0", "1"],
                ["1,474", "9", "4"],
            ),
            "QB",
            "KC",
        )

        self.assertEqual(
            groups,
            (("165", "PASS YD"), ("0", "TD"), ("1", "INT")),
        )
        self.assertEqual(opponent, "@ SEA")

    def test_home_game_is_marked_vs_the_opponent(self):
        groups, opponent = game_stat_groups(
            _game(
                [
                    "receptions",
                    "receivingYards",
                    "receivingTouchdowns",
                ],
                ["4", "44", "0"],
                ["23", "302", "3"],
                short_name="IND @ MIN",
            ),
            "WR",
            "MIN",
        )

        self.assertEqual(
            groups,
            (("44", "REC YD"), ("4", "REC"), ("0", "TD")),
        )
        self.assertEqual(opponent, "VS IND")

    def test_rusher_keeps_a_negative_game_total(self):
        groups, opponent = game_stat_groups(
            _game(
                ["rushingYards", "rushingTouchdowns", "receptions"],
                ["-11", "0", "2"],
            ),
            "rb",
            "KC",
        )

        self.assertEqual(groups[0], ("-11", "RUSH YD"))
        self.assertEqual(groups[1], ("0", "TD"))
        self.assertEqual(opponent, "@ SEA")

    def test_kicker_line_is_the_game(self):
        groups, opponent = game_stat_groups(
            _game(
                [
                    "fieldGoalsMade-fieldGoalAttempts",
                    "extraPointsMade",
                    "totalKickingPoints",
                ],
                ["1-3", "0", "3"],
                ["11-16", "14", "47"],
            ),
            "K",
            "KC",
        )

        self.assertEqual(
            groups,
            (("1-3", "FG"), ("3", "PTS")),
        )
        self.assertEqual(opponent, "@ SEA")

    def test_skill_players_follow_who_has_the_ball(self):
        ball = {"PHI": True, "DAL": False}
        self.assertEqual(field_status("RB", "PHI", ball), "on")
        self.assertEqual(field_status("WR", "DAL", ball), "off")
        self.assertEqual(field_status("QB", "PHI", ball), "on")
        self.assertEqual(field_status("K", "PHI", ball), "")
        self.assertEqual(field_status("K", "DAL", ball), "off")
        self.assertEqual(field_status("RB", "PHI", None), "")

    def test_a_finished_game_does_not_guess_the_field(self):
        payload = {
            "nextGame": {
                "league": {
                    "events": [{
                        "id": "9",
                        "status": "post",
                        "fullStatus": {
                            "type": {
                                "state": "post",
                                "completed": True,
                            },
                        },
                    }],
                },
            },
        }

        with patch("players.cards._possession", side_effect=AssertionError):
            state, field = game_context(payload, "PHI", "RB")

        self.assertEqual((state, field), ("final", ""))

    def test_each_position_names_the_yards_and_the_extra_stat(self):
        quarterback, _ = game_stat_groups(
            _game(
                [
                    "completions",
                    "passingAttempts",
                    "passingYards",
                    "passingTouchdowns",
                    "interceptions",
                    "rushingYards",
                ],
                ["19", "33", "165", "0", "1", "14"],
            ),
            "QB",
            "KC",
        )
        runner, _ = game_stat_groups(
            _game(
                [
                    "rushingAttempts",
                    "rushingYards",
                    "rushingTouchdowns",
                    "receptions",
                    "receivingYards",
                ],
                ["18", "82", "1", "4", "22"],
            ),
            "RB",
            "PHI",
        )
        receiver, _ = game_stat_groups(
            _game(
                [
                    "receptions",
                    "receivingYards",
                    "receivingTouchdowns",
                    "receivingTargets",
                ],
                ["4", "44", "0", "7"],
            ),
            "WR",
            "MIN",
        )
        kicker, _ = game_stat_groups(
            _game(
                [
                    "fieldGoalsMade",
                    "fieldGoalAttempts",
                    "extraPointsMade",
                    "extraPointAttempts",
                    "longFieldGoalMade",
                    "totalKickingPoints",
                ],
                ["1", "3", "0", "0", "50", "3"],
            ),
            "K",
            "KC",
        )

        self.assertEqual(
            quarterback,
            (
                ("165", "PASS YD"),
                ("19-33", "CMP"),
                ("0", "TD"),
                ("1", "INT"),
                ("14", "RUSH YD"),
            ),
        )
        self.assertEqual(
            runner,
            (
                ("82", "RUSH YD"),
                ("18", "CAR"),
                ("1", "TD"),
                ("4", "REC"),
                ("22", "REC YD"),
            ),
        )
        self.assertEqual(
            receiver,
            (
                ("44", "REC YD"),
                ("4", "REC"),
                ("0", "TD"),
                ("7", "TGT"),
            ),
        )
        self.assertEqual(
            kicker,
            (
                ("1-3", "FG"),
                ("50", "LNG"),
                ("3", "PTS"),
            ),
        )

    def test_vs_short_name_does_not_keep_the_player_team(self):
        groups, opponent = game_stat_groups(
            _game(
                ["passingYards", "passingTouchdowns", "interceptions"],
                ["165", "1", "0"],
                short_name="PIT VS NO",
            ),
            "QB",
            "PIT",
        )

        self.assertEqual(groups[0], ("165", "PASS YD"))
        self.assertEqual(opponent, "VS NO")

    def test_away_team_uses_the_at_sign_when_the_site_is_known(self):
        payload = _game(
            ["passingYards", "passingTouchdowns", "interceptions"],
            ["165", "1", "0"],
            short_name="PIT VS NO",
        )
        payload["nextGame"]["league"]["events"][0]["competitors"] = [
            {"abbreviation": "NO", "homeAway": "home"},
            {"abbreviation": "PIT", "homeAway": "away"},
        ]
        groups, opponent = game_stat_groups(payload, "QB", "PIT")

        self.assertEqual(opponent, "@ NO")

    def test_latest_logged_game_is_used_when_this_game_is_missing(self):
        groups, opponent = game_stat_groups(
            {
                "gameLog": {
                    "events": {
                        "old": {
                            "id": "old",
                            "gameDate": "2026-09-01T00:00:00.000+00:00",
                            "atVs": "vs",
                            "opponent": {"abbreviation": "IND"},
                        },
                        "new": {
                            "id": "new",
                            "gameDate": "2026-10-26T00:20:00.000+00:00",
                            "atVs": "@",
                            "opponent": {"abbreviation": "SEA"},
                        },
                    },
                    "statistics": [{
                        "names": [
                            "passingYards",
                            "passingTouchdowns",
                            "interceptions",
                        ],
                        "events": [
                            {"eventId": "old", "stats": ["300", "3", "0"]},
                            {"eventId": "new", "stats": ["165", "0", "1"]},
                        ],
                    }],
                }
            },
            "QB",
            "KC",
        )

        self.assertEqual(
            groups,
            (("165", "PASS YD"), ("0", "TD"), ("1", "INT")),
        )
        self.assertEqual(opponent, "@ SEA")


class PlayerCardRenderTests(unittest.TestCase):
    def test_card_shows_headshot_name_and_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "head.png"
            Image.new("RGB", (40, 40), (255, 0, 0)).save(path)
            renderer_module._load_head.cache_clear()

            image = _render(PlayerCard(
                player_id="4046",
                name="Patrick Mahomes",
                first="Patrick",
                last="Mahomes",
                team="KC",
                position="QB",
                stats=(("165", "YDS"), ("0", "TD"), ("1", "INT")),
                opponent="@ SEA",
                headshot=str(path),
                espn_id="3139477",
            ))

        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(image.getpixel((1, 1)), (255, 0, 0))
        self.assertEqual(image.getpixel((16, 16)), (255, 0, 0))
        self.assertIn(WHITE, _colors(image, NAME_Y, NAME_Y + 7, TEXT_X))
        self.assertNotIn(YELLOW, _colors(image, NAME_Y, NAME_Y + 7, TEXT_X))
        self.assertIn(KC, _colors(image, META_Y, META_Y + 5, TEXT_X))
        self.assertIn(GREY, _colors(image, META_Y, META_Y + 5, TEXT_X))
        self.assertIn(YELLOW, _colors(image, HERO_Y, HERO_Y + 5, TEXT_X))
        self.assertIn(GREY, _colors(image, HERO_Y, HERO_Y + 5, TEXT_X))
        self.assertIn(YELLOW, _colors(image, DETAIL_Y, DETAIL_Y + 5, TEXT_X))
        self.assertIn(GREY, _colors(image, DETAIL_Y, DETAIL_Y + 5, TEXT_X))
        self.assertLess(image.width, 120)
        self.assertEqual(
            image.getpixel((image.width - 1, DETAIL_Y)),
            (0, 0, 0),
        )

    def test_missing_photo_uses_initials_on_the_team_color(self):
        image = _render(PlayerCard(
            player_id="1",
            name="Patrick Mahomes",
            first="Patrick",
            last="Mahomes",
            team="KC",
            position="QB",
        ))

        self.assertIn(KC, _colors(image, 8, 22, 4))
        self.assertIn(WHITE, _colors(image, 8, 22, 4))
        self.assertEqual(game_id(PlayerCard(
            player_id="4046",
            name="Patrick Mahomes",
        )), "player:4046")

    def test_a_stored_matchup_does_not_repeat_the_team(self):
        team, detail = _meta_parts(PlayerCard(
            player_id="1",
            name="Aaron Rodgers",
            team="PIT",
            position="QB",
            opponent="PIT VS NO",
        ))

        self.assertEqual(team, "PIT")
        self.assertEqual(detail, "VS NO")

    def test_live_mark_replaces_the_corner_number(self):
        image = _render(PlayerCard(
            player_id="1",
            name="Saquon Barkley",
            first="Saquon",
            last="Barkley",
            team="PHI",
            position="RB",
            opponent="VS DAL",
            game_state="live",
            on_field="off",
            stats=(("62", "RUSH YD"), ("7", "CAR"), ("1", "TD")),
        ))

        self.assertIn(LIVE, _colors(image, NAME_Y, NAME_Y + 7, TEXT_X))
        self.assertNotIn(ON_FIELD, _colors(image, 0, 32, TEXT_X))
        self.assertNotIn(YELLOW, _colors(image, NAME_Y, NAME_Y + 7, TEXT_X))
        self.assertIn(GREY, _colors(image, META_Y, META_Y + 5, image.width - 20))
        self.assertIn(YELLOW, _colors(image, HERO_Y, HERO_Y + 7, TEXT_X))


class PlayerCardRefreshTests(unittest.TestCase):
    def setUp(self):
        cards_module._cache.clear()
        cards_module._revision = 0
        cards_module._refresh_pending = False
        cards_module._espn_ids.clear()

    def test_stats_are_cached_between_refreshes(self):
        settings = {
            "player_cards": {
                "enabled": True,
                "players": [{
                    "id": "4046",
                    "name": "Patrick Mahomes",
                    "first": "Patrick",
                    "last": "Mahomes",
                    "team": "KC",
                    "position": "QB",
                    "espn_id": "3139477",
                }],
            }
        }
        payload = _game(
            ["passingYards", "passingTouchdowns", "interceptions"],
            ["165", "0", "1"],
            ["1,474", "9", "4"],
        )

        with patch("players.cards.get_settings", return_value=settings), \
                patch("players.cards._fetch_overview", return_value=payload) as overview, \
                patch("players.cards.ensure_headshot", return_value="/tmp/head.png"):
            refresh_player_cards()
            refresh_player_cards()
            cards = ticker_player_cards()

        self.assertEqual(overview.call_count, 1)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].stats[0], ("165", "PASS YD"))
        self.assertEqual(cards[0].opponent, "@ SEA")
        self.assertEqual(cards[0].headshot, "/tmp/head.png")
        self.assertEqual(game_id(cards[0]), "player:4046")

    def test_a_failed_refresh_keeps_the_previous_line(self):
        settings = {
            "player_cards": {
                "enabled": True,
                "players": [{
                    "id": "4046",
                    "name": "Patrick Mahomes",
                    "team": "KC",
                    "position": "QB",
                    "espn_id": "3139477",
                }],
            }
        }
        payload = _game(
            ["passingYards", "passingTouchdowns", "interceptions"],
            ["10", "1", "0"],
        )

        with patch("players.cards.get_settings", return_value=settings), \
                patch("players.cards.ensure_headshot", return_value=""), \
                patch("players.cards._fetch_overview", return_value=payload):
            refresh_player_cards()

        cards_module._cache["4046"]["fetched_at"] = 0

        with patch("players.cards.get_settings", return_value=settings), \
                patch("players.cards.ensure_headshot", return_value=""), \
                patch(
                    "players.cards._fetch_overview",
                    side_effect=OSError("down"),
                ):
            refresh_player_cards()

        self.assertEqual(
            cards_module._cache["4046"]["stats"][0],
            ("10", "PASS YD"),
        )
        self.assertEqual(
            cards_module._cache["4046"]["opponent"],
            "@ SEA",
        )

    def test_a_missing_espn_id_is_looked_up_by_name_and_team(self):
        settings = {
            "player_cards": {
                "enabled": True,
                "players": [{
                    "id": "13294",
                    "name": "Makai Lemon",
                    "first": "Makai",
                    "last": "Lemon",
                    "team": "PHI",
                    "position": "WR",
                    "espn_id": "",
                }],
            }
        }
        payload = _game(
            [
                "receptions",
                "receivingTargets",
                "receivingYards",
                "receivingTouchdowns",
            ],
            ["7", "8", "67", "1"],
        )
        search = {
            "items": [
                {
                    "id": "999",
                    "displayName": "Makai Lemon",
                    "sport": "football",
                    "league": "nfl",
                    "teamRelationships": [
                        {"core": {"abbreviation": "DAL"}},
                    ],
                },
                {
                    "id": "4870795",
                    "displayName": "Makai Lemon",
                    "sport": "football",
                    "league": "nfl",
                    "teamRelationships": [
                        {"core": {"abbreviation": "PHI"}},
                    ],
                },
            ],
        }

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return search

        with patch("players.cards.get_settings", return_value=settings), \
                patch("players.cards.requests.get", return_value=Response()) as fetched, \
                patch("players.cards._fetch_overview", return_value=payload) as overview, \
                patch("players.cards.ensure_headshot", return_value="/tmp/lemon.png"):
            refresh_player_cards()
            cards = ticker_player_cards()

        self.assertEqual(fetched.call_count, 1)
        overview.assert_called_once_with("4870795")
        self.assertEqual(cards[0].espn_id, "4870795")
        self.assertEqual(cards[0].stats[0], ("67", "REC YD"))
        self.assertEqual(cards[0].headshot, "/tmp/lemon.png")

    def test_headshot_is_stored_as_a_small_png(self):
        blob = io.BytesIO()
        Image.new("RGB", (200, 200), (20, 40, 200)).save(blob, "PNG")

        class Response:
            content = blob.getvalue()

            def raise_for_status(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cards_module, "HEAD_DIR", Path(directory)), \
                    patch("players.cards.requests.get", return_value=Response()) as fetched:
                first = cards_module.ensure_headshot("3139477")
                second = cards_module.ensure_headshot("3139477")

            self.assertEqual(fetched.call_count, 1)
            self.assertTrue(first.endswith("3139477.png"))
            self.assertEqual(first, second)

            with Image.open(first) as saved:
                self.assertEqual(saved.width, saved.height)
                self.assertLessEqual(max(saved.size), 96)
