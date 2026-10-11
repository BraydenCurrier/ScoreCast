import unittest
from unittest import mock

from updater.releases import (
    clear_release_cache,
    latest_release_info,
    notes_from_payloads,
    parse_github_remote,
    select_latest_tag,
    split_message,
)


class ReleaseLookupTests(unittest.TestCase):
    def tearDown(self):
        clear_release_cache()

    def test_github_remote_accepts_https_and_ssh(self):
        self.assertEqual(
            parse_github_remote(
                "https://github.com/BraydenCurrier/ScoreCast.git"
            ),
            ("BraydenCurrier", "ScoreCast"),
        )
        self.assertEqual(
            parse_github_remote(
                "git@github.com:BraydenCurrier/ScoreCast.git"
            ),
            ("BraydenCurrier", "ScoreCast"),
        )
        self.assertIsNone(
            parse_github_remote("https://gitlab.com/example/ScoreCast.git")
        )

    def test_latest_tag_is_the_highest_version(self):
        self.assertEqual(
            select_latest_tag(
                ["v1.0.0", "v1.7.9", "v1.10.0", "nightly"]
            ),
            "v1.10.0",
        )

    def test_message_split_keeps_the_body(self):
        title, body = split_message(
            "Smoother scroll\n\nColumns stay on the refresh clock.\n"
        )
        self.assertEqual(title, "Smoother scroll")
        self.assertEqual(body, "Columns stay on the refresh clock.")

    def test_release_body_wins_over_the_commit(self):
        title, description = notes_from_payloads(
            "v1.8.0",
            {
                "name": "v1.8.0",
                "body": "Smoother scroll\n\nLocked to the panel refresh.",
            },
            {"commit": {"message": "ignored"}},
        )
        self.assertEqual(title, "Smoother scroll")
        self.assertEqual(description, "Locked to the panel refresh.")

    def test_named_release_keeps_its_title(self):
        title, description = notes_from_payloads(
            "v1.8.0",
            {
                "name": "April scoreboard",
                "body": "NHL cards redraw without a flash.",
            },
            None,
        )
        self.assertEqual(title, "April scoreboard")
        self.assertEqual(
            description,
            "NHL cards redraw without a flash.",
        )

    def test_available_update_uses_the_commit_when_no_release_exists(self):
        clear_release_cache()

        def fake_json(url):
            if url.endswith("/tags?per_page=100"):
                return [
                    {"name": "v1.7.8"},
                    {"name": "v1.7.9"},
                ], None
            if "/releases/tags/" in url:
                return None, None
            if url.endswith("/commits/v1.7.9"):
                return {
                    "commit": {
                        "message": (
                            "Updated NHL scorecard, "
                            "and fixed performance issues.\n"
                        )
                    }
                }, None
            raise AssertionError(url)

        with mock.patch(
            "updater.releases.github_repository",
            return_value=("BraydenCurrier", "ScoreCast"),
        ), mock.patch(
            "updater.releases._get_json_page",
            side_effect=fake_json,
        ):
            info = latest_release_info("1.7.8")

        self.assertTrue(info["update_available"])
        self.assertEqual(info["latest_version"], "1.7.9")
        self.assertEqual(
            info["title"],
            "Updated NHL scorecard, and fixed performance issues.",
        )
        self.assertEqual(info["description"], "")

    def test_current_release_hides_the_banner(self):
        clear_release_cache()

        with mock.patch(
            "updater.releases.github_repository",
            return_value=("BraydenCurrier", "ScoreCast"),
        ), mock.patch(
            "updater.releases._get_json_page",
            return_value=([{"name": "v1.7.9"}], None),
        ):
            info = latest_release_info("1.7.9")

        self.assertFalse(info["update_available"])
        self.assertEqual(info["latest_version"], "1.7.9")

    def test_failed_refresh_keeps_the_last_good_description(self):
        clear_release_cache()
        good = {
            "update_available": True,
            "latest_version": "1.8.0",
            "current_version": "1.7.9",
            "title": "Smoother scroll",
            "description": "Held to the panel refresh.",
        }

        with mock.patch(
            "updater.releases._fetch_release",
            return_value=good,
        ):
            self.assertEqual(latest_release_info("1.7.9"), good)

        from updater import releases

        with mock.patch(
            "updater.releases.time.monotonic",
            return_value=10_000,
        ), mock.patch(
            "updater.releases._fetch_release",
            side_effect=OSError("offline"),
        ):
            releases._cache["fetched_at"] = 0
            again = latest_release_info("1.7.9")

        self.assertEqual(again["title"], "Smoother scroll")
        self.assertEqual(
            again["description"],
            "Held to the panel refresh.",
        )


if __name__ == "__main__":
    unittest.main()
