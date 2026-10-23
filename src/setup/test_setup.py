import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class WifiListTests(unittest.TestCase):
    def test_parses_escaped_colons(self):
        from setup.network import parse_wifi_list

        networks = parse_wifi_list("Cafe\\:Front:80:WPA2\nGameLine-Test:10:\n\n")
        self.assertEqual(networks[0]["ssid"], "Cafe:Front")
        self.assertEqual(networks[1]["ssid"], "GameLine-Test")
        self.assertTrue(networks[1]["open"])


class QrTests(unittest.TestCase):
    def test_wifi_payload_and_size(self):
        from setup.qr import qr_matrix, wifi_payload

        payload = wifi_payload("GameLine-A1B2", "A1B2C3D4")
        self.assertTrue(payload.startswith("WIFI:T:WPA;S:GameLine-A1B2"))
        self.assertIn("P:A1B2C3D4", payload)
        matrix = qr_matrix(payload)
        self.assertLessEqual(len(matrix), 29)
        self.assertEqual(len(matrix), len(matrix[0]))

    def test_dashboard_url_fits(self):
        from setup.qr import qr_matrix

        matrix = qr_matrix("http://192.168.1.120/")
        self.assertLessEqual(len(matrix), 29)


class SetupStateTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        os.environ["SCORECAST_CONFIG_DIR"] = self._temp.name
        import importlib

        import common.settings as settings_mod
        import common.users as users_mod
        import setup.state as setup_state

        importlib.reload(settings_mod)
        importlib.reload(users_mod)
        importlib.reload(setup_state)
        self.setup_state = setup_state
        self.users_mod = users_mod

    def test_existing_users_skip_hotspot(self):
        users_file = Path(self._temp.name) / "users.json"
        users_file.write_text(
            '{"users":[{"id":"1","username":"root","role":"root"}]}',
            encoding="utf-8",
        )
        self.assertFalse(self.setup_state.should_run_first_setup())
        self.assertTrue(self.setup_state.setup_is_complete())

    def test_new_device_runs_setup(self):
        self.assertTrue(self.setup_state.should_run_first_setup())
        self.assertFalse(self.setup_state.setup_is_complete())


class FactoryResetTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        os.environ["SCORECAST_CONFIG_DIR"] = self._temp.name
        import importlib

        import common.settings as settings_mod
        import common.users as users_mod
        import setup.state as setup_state
        import setup.factory_reset as factory_reset

        importlib.reload(settings_mod)
        importlib.reload(users_mod)
        importlib.reload(setup_state)
        importlib.reload(factory_reset)
        self.factory_reset = factory_reset
        self.settings_mod = settings_mod

    def test_wipes_profiles_settings_and_bets(self):
        root = Path(self._temp.name)
        (root / "settings.json").write_text("{}", encoding="utf-8")
        (root / "users.json").write_text('{"users":[1]}', encoding="utf-8")
        (root / "setup.json").write_text('{"phase":"complete"}', encoding="utf-8")
        (root / "bets.sqlite").write_text("db", encoding="utf-8")
        (root / "web-secret").write_text("secret", encoding="utf-8")
        logos = root / "logos" / "nfl"
        logos.mkdir(parents=True)
        (logos / "custom.png").write_bytes(b"x")

        removed = self.factory_reset.wipe_local_state()
        self.assertIn("users.json", removed)
        self.assertFalse((root / "users.json").exists())
        self.assertFalse((root / "settings.json").exists())
        self.assertFalse((root / "setup.json").exists())
        self.assertFalse((root / "bets.sqlite").exists())
        self.assertFalse((root / "logos").exists())
        self.assertFalse(self.settings_mod.SETTINGS_FILE.exists())


class CaptiveTests(unittest.TestCase):
    def test_probe_paths(self):
        from flask import Flask

        from setup.captive import is_captive_probe

        app = Flask(__name__)
        with app.test_request_context("/generate_204", headers={"Host": "connectivitycheck.gstatic.com"}):
            self.assertTrue(is_captive_probe())
        with app.test_request_context("/setup/wifi", headers={"Host": "192.168.4.1"}):
            self.assertFalse(is_captive_probe())


if __name__ == "__main__":
    unittest.main()
