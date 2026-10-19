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
    })


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
