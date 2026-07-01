import json
import os
import threading

SETTINGS_FILE = "/tmp/ticker_settings.json"

DEFAULT_SETTINGS = {
    "scroll_speed": 1,
    "brightness": 70,
    "refresh_interval": 30,
    "hidden_games": [],
    "game_order": []
}

_settings_lock = threading.RLock()

_cached_settings = None
_cached_mtime = None


def _ensure_settings_file():
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w") as f:
            json.dump(DEFAULT_SETTINGS, f, indent=2)


def load_settings():
    global _cached_settings, _cached_mtime

    with _settings_lock:
        _ensure_settings_file()

        try:
            mtime = os.path.getmtime(SETTINGS_FILE)
        except OSError:
            mtime = None

        if _cached_settings is not None and _cached_mtime == mtime:
            return _cached_settings.copy()

        try:
            with open(SETTINGS_FILE, "r") as f:
                saved_settings = json.load(f)
        except Exception:
            saved_settings = {}

        settings = DEFAULT_SETTINGS.copy()
        settings.update(saved_settings)

        _cached_settings = settings.copy()
        _cached_mtime = mtime

        return settings.copy()


def save_settings(settings):
    global _cached_settings, _cached_mtime

    with _settings_lock:
        _ensure_settings_file()

        clean_settings = DEFAULT_SETTINGS.copy()
        clean_settings.update(settings)

        with open(SETTINGS_FILE, "w") as f:
            json.dump(clean_settings, f, indent=2)

        try:
            _cached_mtime = os.path.getmtime(SETTINGS_FILE)
        except OSError:
            _cached_mtime = None

        _cached_settings = clean_settings.copy()

        return clean_settings.copy()


def get_settings():
    return load_settings()


def update_settings(new_values):
    with _settings_lock:
        settings = load_settings()
        settings.update(new_values)
        return save_settings(settings)