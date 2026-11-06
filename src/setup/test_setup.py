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


class SecurityProfileTests(unittest.TestCase):
    def test_security_modes_set_key_mgmt(self):
        from setup.network import NetworkError, build_home_add_args, classify_security

        wpa2 = build_home_add_args(
            "Home", "correct horse", "WPA2", interface="wlan0"
        )
        self.assertEqual(wpa2[wpa2.index("wifi-sec.key-mgmt") + 1], "wpa-psk")
        self.assertEqual(wpa2[wpa2.index("wifi-sec.psk") + 1], "correct horse")
        self.assertEqual(wpa2[wpa2.index("wifi-sec.pmf") + 1], "2")
        self.assertNotIn("sh", wpa2)
        self.assertNotIn("bash", wpa2)

        mixed = classify_security("WPA2 WPA3")
        self.assertEqual(mixed["method"], "wpa-psk")
        self.assertEqual(mixed["label"], "WPA2/WPA3")
        self.assertTrue(mixed["needs_password"])

        wpa3 = build_home_add_args("Only3", "secret", "WPA3", interface="wlan0")
        self.assertEqual(wpa3[wpa3.index("wifi-sec.key-mgmt") + 1], "sae")
        self.assertEqual(wpa3[wpa3.index("wifi-sec.pmf") + 1], "3")

        opened = build_home_add_args("Cafe", "", "", interface="wlan0")
        self.assertNotIn("wifi-sec.key-mgmt", opened)
        self.assertNotIn("wifi-sec.psk", opened)

        hidden = build_home_add_args(
            "Hidden", "secret", "wpa-psk", interface="wlan0", hidden=True
        )
        self.assertEqual(hidden[hidden.index("wifi.hidden") + 1], "yes")

        wep = build_home_add_args("Old", "secret", "WEP", interface="wlan0")
        self.assertEqual(wep[wep.index("wifi-sec.key-mgmt") + 1], "none")
        self.assertIn("wifi-sec.wep-key0", wep)

        with self.assertRaises(NetworkError) as caught:
            build_home_add_args("Corp", "secret", "WPA2 802.1X", interface="wlan0")
        self.assertIn("company login", str(caught.exception).lower())

    def test_password_is_removed_from_errors(self):
        from setup.network import friendly_wifi_error, public_error

        secret = "super-secret-value"
        text = public_error(f"psk: {secret} failed", secret)
        self.assertNotIn(secret, text)
        message = friendly_wifi_error(
            "802-11-wireless-security.key-mgmt: property is missing",
            secret,
        )
        self.assertNotIn(secret, message)
        self.assertIn("security", message.lower())
        bad_password = friendly_wifi_error(
            "Secrets were required, but not provided.",
            secret,
        )
        self.assertIn("password", bad_password.lower())
        self.assertNotIn(secret, bad_password)


class ScanAndConnectTests(unittest.TestCase):
    def _completed(self, code=0, stdout="", stderr=""):
        import subprocess
        return subprocess.CompletedProcess(
            args=["nmcli"],
            returncode=code,
            stdout=stdout,
            stderr=stderr,
        )

    def test_parse_sorts_dedupes_and_keeps_weak_networks(self):
        from setup.network import parse_wifi_list

        networks = parse_wifi_list(
            "Cafe\\:Front:80:WPA2\n"
            "GameLine-Test:10:\n"
            "Home:20:WPA2\n"
            "Home:90:WPA2 WPA3\n"
            "Far:5:WPA3\n"
        )
        self.assertEqual(networks[0]["ssid"], "Home")
        self.assertEqual(networks[0]["signal"], "90")
        self.assertEqual(networks[0]["security_label"], "WPA2/WPA3")
        self.assertEqual(networks[1]["ssid"], "Cafe:Front")
        self.assertFalse(networks[1]["open"])
        self.assertEqual(networks[-1]["ssid"], "Far")
        self.assertEqual(networks[-1]["key_mgmt"], "sae")
        self.assertTrue(networks[2]["open"])
        self.assertEqual(
            [item["ssid"] for item in networks],
            ["Home", "Cafe:Front", "GameLine-Test", "Far"],
        )

    def test_failed_scan_is_not_reported_as_success(self):
        from setup import network

        def fake(*args, timeout=20):
            if args[:3] == ("-t", "-f", "DEVICE,TYPE,STATE"):
                return self._completed(0, "wlan0:wifi:disconnected:\n")
            if args[:2] == ("-g", "GENERAL.CONNECTION"):
                return self._completed(0, "\n")
            if "list" in args and "wifi" in args:
                return self._completed(1, "", "Error: Scanning not allowed while in AP mode")
            return self._completed(0, "")

        with patch.object(network, "_nmcli", side_effect=fake), \
             patch.object(network, "_ensure_hotspot_locked") as restore, \
             patch.object(network.time, "sleep"):
            report = network.perform_wifi_scan(allow_hotspot_pause=True)

        self.assertFalse(report["ok"])
        self.assertEqual(report["networks"], [])
        self.assertIn("scan", report["error"].lower())
        restore.assert_not_called()

    def test_empty_scan_can_succeed(self):
        from setup import network

        def fake(*args, timeout=20):
            if args[:3] == ("-t", "-f", "DEVICE,TYPE,STATE"):
                return self._completed(0, "wlan0:wifi:disconnected:\n")
            if args[:2] == ("-g", "GENERAL.CONNECTION"):
                return self._completed(0, "\n")
            if "list" in args and "wifi" in args:
                return self._completed(0, "")
            return self._completed(0, "")

        with patch.object(network, "_nmcli", side_effect=fake), \
             patch.object(network.time, "sleep"):
            report = network.perform_wifi_scan()

        self.assertTrue(report["ok"])
        self.assertEqual(report["networks"], [])
        self.assertEqual(report["error"], "")

    def test_scan_retries_and_filters_hotspot(self):
        from setup import network

        calls = {"list": 0}
        active = {"name": network.AP_CONNECTION}

        def fake(*args, timeout=20):
            if args[:3] == ("-t", "-f", "DEVICE,TYPE,STATE"):
                return self._completed(0, "wlan0:wifi:disconnected:\n")
            if args[:2] == ("-g", "GENERAL.CONNECTION"):
                return self._completed(0, f"{active['name']}\n")
            if args[:3] == ("connection", "down", network.AP_CONNECTION):
                active["name"] = ""
                return self._completed(0, "")
            if "list" in args and "wifi" in args:
                calls["list"] += 1
                if calls["list"] == 1:
                    return self._completed(
                        1, "", "Scanning not allowed immediately following previous scan"
                    )
                own = network.hotspot_ssid()
                return self._completed(0, f"House:70:WPA2\n{own}:99:WPA2\nWeak:4:WPA2\n")
            return self._completed(0, "")

        with patch.object(network, "_nmcli", side_effect=fake), \
             patch.object(network, "_ensure_hotspot_locked", return_value="GameLine-TEST") as restore, \
             patch.object(network.time, "sleep"):
            report = network.perform_wifi_scan()

        self.assertTrue(report["ok"])
        self.assertEqual([item["ssid"] for item in report["networks"]], ["House", "Weak"])
        self.assertGreaterEqual(calls["list"], 2)
        restore.assert_called()

    def _connect_fake(self, *, up_results, key_mgmt="wpa-psk", active="", ssid="HomeWiFi"):
        deleted = []
        added = []
        profiles = {
            "BrokenNet": (
                f"802-11-wireless.ssid:{ssid}\n"
                "802-11-wireless.mode:infrastructure\n"
                "802-11-wireless-security.psk:old\n"
            ),
            "OtherHouse": (
                "802-11-wireless.ssid:OtherHouse\n"
                "802-11-wireless.mode:infrastructure\n"
                "802-11-wireless-security.key-mgmt:wpa-psk\n"
            ),
            "GameLine-Home": (
                f"802-11-wireless.ssid:{ssid}\n"
                "802-11-wireless.mode:infrastructure\n"
                "802-11-wireless-security.key-mgmt:wpa-psk\n"
            ),
        }
        ups = {"n": 0}

        def fake(*args, timeout=20):
            if args[:3] == ("-t", "-f", "DEVICE,TYPE,STATE"):
                return self._completed(0, "wlan0:wifi:disconnected:\n")
            if args[:2] == ("-g", "GENERAL.CONNECTION"):
                return self._completed(0, f"{active or 'GameLine-Home'}\n")
            if args[:3] == ("-t", "-f", "NAME,UUID,TYPE"):
                return self._completed(
                    0,
                    "GameLine-Home:uuid-home:802-11-wireless\n"
                    "BrokenNet:uuid-broken:802-11-wireless\n"
                    "OtherHouse:uuid-other:802-11-wireless\n"
                    "GameLine-Setup:uuid-ap:802-11-wireless\n",
                )
            if args[:3] == ("-t", "connection", "show"):
                return self._completed(0, profiles.get(args[3], ""))
            if args[:2] == ("connection", "delete"):
                deleted.append(args[2])
                return self._completed(0, "")
            if args[:2] == ("connection", "down"):
                return self._completed(0, "")
            if args[:2] == ("connection", "add"):
                added.append(args)
                return self._completed(0, "")
            if args[:2] == ("-g", "802-11-wireless-security.key-mgmt"):
                return self._completed(0, f"{key_mgmt}\n")
            if args[:3] == ("connection", "up", "GameLine-Home"):
                result = up_results[min(ups["n"], len(up_results) - 1)]
                ups["n"] += 1
                return result
            return self._completed(0, "")

        return fake, deleted, added

    def test_connect_replaces_broken_profile_and_sets_key_mgmt(self):
        from setup import network

        fake, deleted, added = self._connect_fake(
            up_results=[self._completed(0, "Connection successfully activated\n")]
        )
        with patch.object(network, "_nmcli", side_effect=fake), \
             patch.object(network, "_ensure_hotspot_locked") as restore, \
             patch.object(network, "_interface_ipv4", return_value="192.168.1.50"), \
             patch.object(network.time, "sleep"):
            ip_address = network.connect_wifi("HomeWiFi", "p@ss; rm -rf /", security="WPA2")

        self.assertEqual(ip_address, "192.168.1.50")
        self.assertIn("uuid-home", deleted)
        self.assertIn("uuid-broken", deleted)
        self.assertNotIn("uuid-other", deleted)
        self.assertNotIn("uuid-ap", deleted)
        security_args = added[0]
        self.assertEqual(
            security_args[security_args.index("wifi-sec.key-mgmt") + 1],
            "wpa-psk",
        )
        self.assertEqual(
            security_args[security_args.index("wifi-sec.psk") + 1],
            "p@ss; rm -rf /",
        )
        restore.assert_not_called()

    def test_wrong_password_restores_hotspot_without_leaking_secret(self):
        from setup import network
        from setup.network import NetworkError

        fake, _deleted, _added = self._connect_fake(
            up_results=[self._completed(1, "", "Secrets were required, but not provided.")]
        )
        with patch.object(network, "_nmcli", side_effect=fake), \
             patch.object(network, "_ensure_hotspot_locked") as restore, \
             patch.object(network.time, "sleep"):
            with self.assertRaises(NetworkError) as caught:
                network.connect_wifi("HomeWiFi", "super-secret-value", security="WPA2")

        self.assertNotIn("super-secret-value", str(caught.exception))
        self.assertIn("password", str(caught.exception).lower())
        restore.assert_called()

    def test_missing_key_mgmt_is_rejected_before_activation(self):
        from setup import network
        from setup.network import NetworkError

        fake, _deleted, added = self._connect_fake(
            up_results=[self._completed(0, "")],
            key_mgmt="",
        )
        with patch.object(network, "_nmcli", side_effect=fake), \
             patch.object(network, "_ensure_hotspot_locked") as restore, \
             patch.object(network.time, "sleep"):
            with self.assertRaises(NetworkError) as caught:
                network.connect_wifi("HomeWiFi", "super-secret-value", security="WPA2")

        self.assertNotIn("super-secret-value", str(caught.exception))
        self.assertIn("security", str(caught.exception).lower())
        self.assertTrue(added)
        self.assertEqual(
            added[0][added[0].index("wifi-sec.key-mgmt") + 1],
            "wpa-psk",
        )
        restore.assert_called()

    def test_dhcp_timeout_restores_hotspot(self):
        from setup import network
        from setup.network import NetworkError

        fake, _deleted, _added = self._connect_fake(
            up_results=[self._completed(0, "activated\n")]
        )
        clock = {"now": 0}

        def monotonic():
            clock["now"] += 100
            return clock["now"]

        with patch.object(network, "_nmcli", side_effect=fake), \
             patch.object(network, "_ensure_hotspot_locked") as restore, \
             patch.object(network, "_interface_ipv4", return_value=""), \
             patch.object(network.time, "sleep"), \
             patch.object(network.time, "monotonic", side_effect=monotonic):
            with self.assertRaises(NetworkError) as caught:
                network.connect_wifi("HomeWiFi", "super-secret-value", security="WPA2")

        self.assertIn("IP address", str(caught.exception))
        self.assertNotIn("super-secret-value", str(caught.exception))
        restore.assert_called()

    def test_hidden_wpa3_retries_with_sae(self):
        from setup import network

        fake, _deleted, added = self._connect_fake(
            up_results=[
                self._completed(1, "", "Connection activation failed: SAE authentication required"),
                self._completed(0, "activated\n"),
            ],
            ssid="Hidden",
        )
        with patch.object(network, "_nmcli", side_effect=fake), \
             patch.object(network, "_ensure_hotspot_locked") as restore, \
             patch.object(network, "_interface_ipv4", return_value="192.168.1.40"), \
             patch.object(network.time, "sleep"):
            ip_address = network.connect_wifi(
                "Hidden",
                "secret",
                security="wpa-psk",
                hidden=True,
            )

        self.assertEqual(ip_address, "192.168.1.40")
        self.assertEqual(added[0][added[0].index("wifi-sec.key-mgmt") + 1], "wpa-psk")
        self.assertEqual(added[1][added[1].index("wifi-sec.key-mgmt") + 1], "sae")
        self.assertEqual(added[1][added[1].index("wifi.hidden") + 1], "yes")
        restore.assert_not_called()


class BootFlowTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        os.environ["SCORECAST_CONFIG_DIR"] = self._temp.name
        import importlib

        import common.settings as settings_mod
        import common.users as users_mod
        import setup.network as network
        import setup.runtime as runtime
        import setup.state as setup_state

        importlib.reload(settings_mod)
        importlib.reload(users_mod)
        importlib.reload(setup_state)
        importlib.reload(network)
        importlib.reload(runtime)
        self.state = setup_state
        self.runtime = runtime

    def test_ethernet_skips_wifi_provisioning(self):
        with patch.object(self.runtime, "wait_for_upstream", return_value="192.168.1.25"), \
             patch.object(self.runtime, "ethernet_has_link", return_value=True), \
             patch.object(self.runtime, "has_users", return_value=False), \
             patch.object(self.runtime, "ensure_hotspot") as hotspot, \
             patch.object(self.runtime, "perform_wifi_scan") as scan, \
             patch.object(self.runtime, "publish_mdns"), \
             patch.object(self.runtime, "stop_hotspot"), \
             patch.object(self.runtime, "_start_ethernet_watcher"):
            self.runtime._run_boot_sequence()

        hotspot.assert_not_called()
        scan.assert_not_called()
        state = self.state.load_setup_state()
        self.assertEqual(state["phase"], "account")
        self.assertEqual(state["lan_ip"], "192.168.1.25")

    def test_ethernet_link_waits_before_starting_hotspot(self):
        action = self.state.resolve_boot_action(
            {"phase": "starting"},
            upstream_ip="",
            ethernet_link=True,
            user_account=False,
        )
        self.assertTrue(action["wait"])
        self.assertFalse(action["start_hotspot"])
        self.assertNotEqual(action["phase"], "hotspot")

    def test_completed_setup_survives_reboot(self):
        self.state.mark_setup_complete()
        self.state.clear_setup_cache()
        self.assertTrue(self.state.setup_is_complete())
        self.assertFalse(self.state.should_run_first_setup())
        with patch.object(self.runtime, "ensure_hotspot") as hotspot, \
             patch.object(self.runtime, "wait_for_upstream", return_value=""):
            self.runtime._run_boot_sequence()
        hotspot.assert_not_called()
        self.state.clear_setup_cache()
        self.assertEqual(self.state.load_setup_state()["phase"], "complete")

    def test_homescreen_is_not_reset_when_network_is_down(self):
        self.state.save_setup_state({
            "phase": "homescreen",
            "lan_ip": "10.1.1.5",
            "networks": [{"ssid": "House"}],
        })
        with patch.object(self.runtime, "wait_for_upstream", return_value=""), \
             patch.object(self.runtime, "ethernet_has_link", return_value=False), \
             patch.object(self.runtime, "has_users", return_value=True), \
             patch.object(self.runtime, "ensure_hotspot", return_value="GameLine-TEST") as hotspot, \
             patch.object(self.runtime, "perform_wifi_scan") as scan, \
             patch.object(self.runtime, "_start_ethernet_watcher"):
            self.runtime._run_boot_sequence()

        state = self.state.load_setup_state()
        self.assertEqual(state["phase"], "homescreen")
        self.assertEqual(state["networks"][0]["ssid"], "House")
        hotspot.assert_called()
        scan.assert_not_called()

    def test_interrupted_join_resumes_wifi_setup(self):
        self.state.save_setup_state({
            "phase": "connecting",
            "networks": [{"ssid": "House", "signal": "80", "security": "WPA2"}],
        })
        with patch.object(self.runtime, "wait_for_upstream", return_value=""), \
             patch.object(self.runtime, "ethernet_has_link", return_value=False), \
             patch.object(self.runtime, "has_users", return_value=False), \
             patch.object(self.runtime, "ensure_hotspot", return_value="GameLine-TEST"), \
             patch.object(self.runtime, "perform_wifi_scan", return_value={
                 "ok": False,
                 "networks": [],
                 "error": "Could not scan for Wi-Fi networks. Tap Refresh Networks.",
             }), \
             patch.object(self.runtime, "_start_ethernet_watcher"):
            self.runtime._run_boot_sequence()

        state = self.state.load_setup_state()
        self.assertEqual(state["phase"], "hotspot")
        self.assertIn("interrupted", state["error"].lower())
        self.assertEqual(state["scan_status"], "failed")
        self.assertEqual(state["networks"][0]["ssid"], "House")
        self.assertNotIn("password", state["error"].lower())

    def test_existing_account_is_not_repeated_when_ethernet_appears(self):
        self.state.save_setup_state({"phase": "hotspot", "ssid": "GameLine-TEST"})
        action = self.state.resolve_boot_action(
            self.state.load_setup_state(),
            upstream_ip="192.168.0.20",
            ethernet_link=True,
            user_account=True,
        )
        self.assertEqual(action["phase"], "homescreen")
        self.assertFalse(action["start_hotspot"])


class WifiPageTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        os.environ["SCORECAST_CONFIG_DIR"] = self._temp.name
        import importlib

        import common.settings as settings_mod
        import common.users as users_mod
        import setup.runtime as runtime
        import setup.state as setup_state
        import setup.web as web

        importlib.reload(settings_mod)
        importlib.reload(users_mod)
        importlib.reload(setup_state)
        importlib.reload(runtime)
        importlib.reload(web)
        self.state = setup_state
        self.runtime = runtime
        self.web = web

    def _client(self):
        from flask import Flask

        app = Flask(__name__)
        app.secret_key = "test"
        self.web.register_setup_routes(
            app,
            render_auth_page=lambda title, body: f"<html><body>{body}</body></html>",
            establish_session=lambda user: None,
        )
        return app.test_client()

    def test_lists_networks_signal_security_and_refresh(self):
        self.state.save_setup_state({
            "phase": "hotspot",
            "ssid": "GameLine-TEST",
            "scan_status": "ready",
            "networks": [
                {"ssid": "Cafe", "signal": "12", "security": ""},
                {"ssid": "House", "signal": "88", "security": "WPA2"},
            ],
        })
        response = self._client().get("/setup/wifi")
        page = response.get_data(as_text=True)
        self.assertLess(page.index("House"), page.index("Cafe"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("House", page)
        self.assertIn("Cafe", page)
        self.assertIn("WPA2", page)
        self.assertIn("Open", page)
        self.assertIn("Strong", page)
        self.assertIn("Weak", page)
        self.assertIn("Refresh Networks", page)
        self.assertIn("Show", page)
        self.assertIn("Other network", page)
        self.assertNotIn("No networks were cached", page)

    def test_scan_failure_offers_refresh_without_cached_message(self):
        self.state.save_setup_state({
            "phase": "hotspot",
            "ssid": "GameLine-TEST",
            "scan_status": "failed",
            "scan_error": "Could not scan for Wi-Fi networks. Tap Refresh Networks.",
            "networks": [],
        })
        page = self._client().get("/setup/wifi").get_data(as_text=True)
        self.assertIn("Could not scan", page)
        self.assertIn("Refresh Networks", page)
        self.assertNotIn("No networks were cached", page)

    def test_connect_posts_security_and_does_not_store_password(self):
        self.state.save_setup_state({
            "phase": "hotspot",
            "ssid": "GameLine-TEST",
            "networks": [{"ssid": "House", "signal": "80", "security": "WPA2"}],
        })
        with patch.object(self.web, "join_home_wifi") as join:
            response = self._client().post(
                "/setup/wifi",
                data={"ssid": "House", "password": "super-secret-value", "security": "WPA2"},
            )
        self.assertEqual(response.status_code, 302)
        join.assert_called_once_with(
            "House",
            "super-secret-value",
            security="WPA2",
            hidden=False,
        )
        self.state.clear_setup_cache()
        saved = (self.state.SETUP_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("super-secret-value", saved)

    def test_open_network_does_not_require_password(self):
        self.state.save_setup_state({
            "phase": "hotspot",
            "ssid": "GameLine-TEST",
            "networks": [{"ssid": "Cafe", "signal": "30", "security": ""}],
        })
        with patch.object(self.web, "join_home_wifi") as join:
            response = self._client().post(
                "/setup/wifi",
                data={"ssid": "Cafe", "password": "", "security": ""},
            )
        self.assertEqual(response.status_code, 302)
        join.assert_called_once()
        self.assertEqual(join.call_args.args[1], "")

    def test_refresh_starts_a_scan(self):
        self.state.save_setup_state({"phase": "hotspot", "ssid": "GameLine-TEST"})
        with patch.object(self.web, "request_wifi_rescan", return_value="scanning") as scan:
            response = self._client().post("/setup/wifi/scan")
        self.assertEqual(response.status_code, 302)
        scan.assert_called_once()


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
