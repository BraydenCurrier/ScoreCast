from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from typing import Any

from common.settings import SETTINGS_DIR, ensure_settings_directory
from common.users import has_users


SETUP_FILE = SETTINGS_DIR / "setup.json"

PHASE_COMPLETE = "complete"
PHASE_STARTING = "starting"
PHASE_HOTSPOT = "hotspot"
PHASE_CONNECTING = "connecting"
PHASE_ACCOUNT = "account"
PHASE_HOMESCREEN = "homescreen"

AP_ADDRESS = "192.168.4.1"
AP_CIDR = "192.168.4.1/24"
AP_CONNECTION = "GameLine-Setup"
HOME_CONNECTION = "GameLine-Home"
MDNS_NAME = "gameline"

_lock = threading.RLock()
_cached: dict[str, Any] | None = None


def default_state() -> dict[str, Any]:
    return {
        "phase": PHASE_STARTING,
        "ssid": "",
        "error": "",
        "dashboard_url": "",
        "lan_ip": "",
        "networks": [],
        "scan_status": "idle",
        "scan_error": "",
        "recovery_hotspot": False,
    }


def load_setup_state() -> dict[str, Any]:
    global _cached

    with _lock:
        if _cached is not None:
            return deepcopy(_cached)

        state = default_state()
        try:
            raw = json.loads(SETUP_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            raw = None

        if isinstance(raw, dict):
            state.update(raw)
            if not isinstance(state.get("networks"), list):
                state["networks"] = []
            if state.get("scan_status") not in {"idle", "scanning", "ready", "failed"}:
                state["scan_status"] = "idle"
            if not isinstance(state.get("scan_error"), str):
                state["scan_error"] = ""
            state["recovery_hotspot"] = bool(state.get("recovery_hotspot"))

        _cached = deepcopy(state)
        return deepcopy(state)


def save_setup_state(updates: dict[str, Any] | None = None) -> dict[str, Any]:
    global _cached

    with _lock:
        state = load_setup_state()
        if updates:
            for key, value in updates.items():
                state[key] = deepcopy(value)

        ensure_settings_directory()
        temporary = SETUP_FILE.with_name(".setup.json.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, SETUP_FILE)
            os.chmod(SETUP_FILE, 0o600)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

        _cached = deepcopy(state)
        return deepcopy(state)


def clear_setup_cache() -> None:
    global _cached
    with _lock:
        _cached = None


def setup_is_complete() -> bool:
    return load_setup_state().get("phase") == PHASE_COMPLETE


def setup_holds_display() -> bool:
    return not setup_is_complete()


def mark_setup_complete() -> dict[str, Any]:
    return save_setup_state({
        "phase": PHASE_COMPLETE,
        "error": "",
        "networks": [],
        "scan_status": "idle",
        "scan_error": "",
        "recovery_hotspot": False,
    })


def resolve_boot_action(
    state: dict[str, Any] | None = None,
    *,
    upstream_ip: str = "",
    ethernet_link: bool = False,
    user_account: bool = False,
    ethernet_grace_exhausted: bool = False,
) -> dict[str, Any]:
    """Choose the setup stage after boot or a network change.

    This does not write state and does not touch NetworkManager. Callers
    wait for DHCP before asking, so a cable that is still requesting an
    address does not start the Wi-Fi hotspot.
    """
    current = dict(state or load_setup_state())
    phase = str(current.get("phase") or PHASE_STARTING)
    upstream = str(upstream_ip or "").strip()
    action = {
        "phase": phase,
        "start_hotspot": False,
        "scan": False,
        "recovery": False,
        "wait": False,
        "error": "",
        "lan_ip": upstream,
        "watch_ethernet": phase != PHASE_COMPLETE,
    }

    if phase == PHASE_COMPLETE or (user_account and phase == PHASE_STARTING):
        action["phase"] = PHASE_COMPLETE
        action["watch_ethernet"] = False
        action["error"] = ""
        return action

    if upstream:
        if phase == PHASE_HOMESCREEN or user_account:
            action["phase"] = PHASE_HOMESCREEN
        elif phase == PHASE_ACCOUNT:
            action["phase"] = PHASE_ACCOUNT
        else:
            action["phase"] = PHASE_ACCOUNT
        action["lan_ip"] = upstream
        action["error"] = ""
        return action

    if ethernet_link and not ethernet_grace_exhausted:
        if phase in {PHASE_ACCOUNT, PHASE_HOMESCREEN, PHASE_CONNECTING}:
            action["phase"] = phase
        else:
            action["phase"] = PHASE_STARTING
        action["wait"] = True
        action["error"] = ""
        return action

    if phase == PHASE_CONNECTING:
        action["phase"] = PHASE_HOTSPOT
        action["start_hotspot"] = True
        action["scan"] = True
        action["error"] = (
            "Setup was interrupted before Wi-Fi connected. "
            "Choose the network and try again."
        )
        return action

    if phase in {PHASE_ACCOUNT, PHASE_HOMESCREEN}:
        # Keep the finished steps. A hotspot here is only a way back in
        # when the home network is down; it must not restart account setup.
        action["phase"] = phase
        action["start_hotspot"] = True
        action["recovery"] = True
        action["error"] = ""
        return action

    action["phase"] = PHASE_HOTSPOT
    action["start_hotspot"] = True
    action["scan"] = True
    action["error"] = ""
    return action


def should_run_first_setup() -> bool:
    """Existing installs already have a profile. Do not start a hotspot."""
    state = load_setup_state()
    if state.get("phase") == PHASE_COMPLETE:
        return False

    if SETUP_FILE.exists() and state.get("phase") in {
        PHASE_HOTSPOT,
        PHASE_CONNECTING,
        PHASE_ACCOUNT,
        PHASE_HOMESCREEN,
        PHASE_STARTING,
    }:
        if state.get("phase") == PHASE_STARTING and has_users():
            mark_setup_complete()
            return False
        return True

    if has_users():
        mark_setup_complete()
        return False

    return True


def current_setup_path(state: dict[str, Any] | None = None) -> str:
    phase = (state or load_setup_state()).get("phase")
    if phase == PHASE_HOMESCREEN:
        return "/setup/homescreen"
    if phase == PHASE_ACCOUNT:
        return "/setup/account"
    if phase in {PHASE_CONNECTING, PHASE_STARTING}:
        return "/setup/connecting"
    if phase == PHASE_COMPLETE:
        return "/games"
    return "/setup/wifi"
