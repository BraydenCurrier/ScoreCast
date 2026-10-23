import unittest
from unittest.mock import patch

import web.app as appmod


class FavoritePageTests(unittest.TestCase):
    def test_page_shows_one_league_and_a_search_box(self):
        settings = {"favorite_teams": {"nfl": ["KC"], "nba": ["BOS"]}}
        user = {"id": "1", "role": "root", "username": "brayden"}

        with appmod.app.test_request_context("/favorites?league=nfl"):
            with patch.object(appmod, "get_settings", return_value=settings), \
                 patch.object(appmod, "current_user", return_value=user), \
                 patch.object(appmod, "has_users", return_value=True):
                html = appmod.favorites_page.__wrapped__()

        self.assertIn('id="favorite_league"', html)
        self.assertIn('id="favorite_team_search"', html)
        self.assertIn('value="nfl" selected', html)
        self.assertIn("Arizona Cardinals", html)
        self.assertIn('name="favorite_nfl"', html)
        self.assertNotIn('name="favorite_cfb"', html)
        self.assertNotIn('name="favorite_nba"', html)
        self.assertIn('value="KC"', html)
        self.assertIn("checked", html)

    def test_save_updates_only_the_open_league(self):
        stored = {}

        def update(values):
            stored.update(values)
            return values

        settings = {"favorite_teams": {"nfl": ["KC"], "nba": ["NYK"]}}
        with appmod.app.test_request_context(
            "/save_favorites",
            method="POST",
            data={"league": "nba", "favorite_nba": ["BOS", "LAL", "NOPE"]},
        ):
            with patch.object(appmod, "get_settings", return_value=settings), \
                 patch.object(appmod, "update_settings", side_effect=update), \
                 patch.object(
                     appmod,
                     "get_favorite_team_options",
                     return_value=["BOS", "LAL", "NYK"],
                 ):
                appmod.save_favorites.__wrapped__()

        self.assertEqual(stored["favorite_teams"]["nfl"], ["KC"])
        self.assertEqual(stored["favorite_teams"]["nba"], ["BOS", "LAL"])


if __name__ == "__main__":
    unittest.main()
