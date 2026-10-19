from __future__ import annotations

import shutil
from pathlib import Path

from common.settings import SETTINGS_DIR, clear_settings_cache
from common.users import clear_users_cache
from setup.state import clear_setup_cache


STATE_FILES = (
    "settings.json",
    "users.json",
    "web-secret",
    "setup.json",
    "bets.sqlite",
    "bets.sqlite-wal",
    "bets.sqlite-shm",
    "nfl_player_directory.json",
    "install-resume.pending",
)

STATE_DIRS = (
    "logos",
)

TEMP_DIRS = (
    Path("/tmp/scorecast-fantasy-avatars"),
)


def _unlink(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
    except OSError:
        pass


def wipe_local_state() -> list[str]:
    """Delete profiles, settings, bets, custom logos, and setup status."""
    removed = []
    for name in STATE_FILES:
        path = SETTINGS_DIR / name
        if path.exists() or path.is_symlink():
            _unlink(path)
            removed.append(name)

    for name in STATE_DIRS:
        path = SETTINGS_DIR / name
        if path.exists():
            _unlink(path)
            removed.append(name + "/")

    for extra in SETTINGS_DIR.glob(".*"):
        if extra.name.endswith(".tmp"):
            _unlink(extra)
            removed.append(extra.name)

    for path in TEMP_DIRS:
        if path.exists():
            _unlink(path)
            removed.append(str(path))

    clear_settings_cache()
    clear_users_cache()
    clear_setup_cache()
    return removed


def forget_wifi_networks() -> None:
    from setup.network import NetworkError, forget_saved_wifi

    try:
        forget_saved_wifi()
    except NetworkError:
        pass


def factory_reset(*, forget_wifi: bool = False) -> list[str]:
    removed = wipe_local_state()
    if forget_wifi:
        forget_wifi_networks()
        removed.append("wifi")
    return removed
