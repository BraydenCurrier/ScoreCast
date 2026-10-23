import unittest
from unittest.mock import patch

import web.app as appmod
from fantasy.api import _safe_error
from setup.network import hotspot_password
from updater.updater import UpdateError, assert_trusted_origin


class LoginLockTests(unittest.TestCase):
    def test_locks_after_repeated_failures(self):
        ip = "203.0.113.10"
        appmod._login_clear(ip)
        for _ in range(appmod._LOGIN_FAILURE_LIMIT - 1):
            appmod._login_record_failure(ip)
        self.assertFalse(appmod._login_is_locked(ip))
        appmod._login_record_failure(ip)
        self.assertTrue(appmod._login_is_locked(ip))
        appmod._login_clear(ip)
        self.assertFalse(appmod._login_is_locked(ip))


class DeveloperAccessTests(unittest.TestCase):
    def _page(self, settings, role):
        user = {"id": "1", "role": role, "username": "owner"}
        with appmod.app.test_request_context("/settings"):
            with patch.object(appmod, "get_settings", return_value=settings), \
                 patch.object(appmod, "current_user", return_value=user), \
                 patch.object(appmod, "has_users", return_value=True), \
                 patch.object(appmod, "list_users", return_value=[user]):
                return appmod.settings_page.__wrapped__()

    def test_developer_card_stays_hidden_until_unlocked(self):
        html = self._page({}, "root")
        self.assertNotIn('id="developer"', html)
        self.assertIn('id="version_unlock"', html)
        self.assertIn('id="update_button"', html)
        self.assertNotIn("Sample games", html)

    def test_root_sees_developer_card_after_unlock(self):
        html = self._page({"developer_unlocked": True}, "root")
        self.assertIn('id="developer"', html)
        self.assertIn("Hide developer options", html)
        self.assertNotIn('id="version_unlock"', html)

    def test_other_profiles_cannot_unlock(self):
        html = self._page({}, "user")
        self.assertNotIn('id="developer"', html)
        self.assertNotIn('id="version_unlock"', html)
        self.assertNotIn('id="update_button"', html)
        self.assertNotIn('id="system_restart_button"', html)


class FeedLogTests(unittest.TestCase):
    def test_sleeper_user_id_is_removed(self):
        exc = RuntimeError(
            "404 Client Error for url: "
            "https://api.sleeper.app/v1/user/922723947337093120/leagues/nfl/2026"
        )
        text = _safe_error(exc)
        self.assertNotIn("922723947337093120", text)
        self.assertIn("/user/…", text)


class HotspotPasswordTests(unittest.TestCase):
    def test_password_is_stable_and_not_the_ssid_suffix(self):
        with patch("setup.network._device_serial", return_value="10000000aabbccdd"):
            first = hotspot_password()
            second = hotspot_password()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 8)
        self.assertTrue(first.isalnum())
        self.assertNotIn("CCDD", first)


class UpdatePinTests(unittest.TestCase):
    def test_other_repositories_are_refused(self):
        with patch(
            "updater.updater.run_git",
            return_value="https://github.com/example/other.git",
        ):
            with self.assertRaises(UpdateError):
                assert_trusted_origin()

    def test_game_line_repository_is_accepted(self):
        with patch(
            "updater.updater.run_git",
            return_value="git@github.com:BraydenCurrier/ScoreCast.git",
        ):
            assert_trusted_origin()


if __name__ == "__main__":
    unittest.main()
