import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any


SETTINGS_DIR = Path(
    os.getenv(
        "SCORECAST_CONFIG_DIR",
        "/var/lib/scorecast",
    )
)

SETTINGS_FILE = SETTINGS_DIR / "settings.json"


DEFAULT_SETTINGS = {
    "scroll_speed": 30.0,
    "brightness": 70,
    "refresh_interval": 30,
    "fps": 90,
    "hidden_games": [],
    "game_order": [],

    "alerts": {
        "enabled": False,
        "possession_teams": [],
        "cooldown_seconds": 20,
        "poll_interval_seconds": 3.0,
        "confirmations_required": 2,
        "chant_frame_seconds": 0.65,
        "details_frame_seconds": 4.0,
    },

    "logo_variants": {
        "nfl": {
            "ARI": "current",
            "DEN": "1993",
            "LAR": "classic",
            "MIA": "2002",
            "NE": "classic",
            "PHI": "classic",
            "PIT": "classic",
            "TEN": "classic",
            "WSH": "1983",
        }
    },

    "music": {
        "enabled": False,
        "provider": "spotify",
        "poll_interval": 5,
        "display_mode": "auto",
    },

    "cfb": {
        "selected_conferences": ["80"],
    },

    "odds": {
        "enabled": True,
        "provider": "theoddsapi",
        "api_key": "",
        "refresh_interval": 900,
    },

    "fantasy": {
        "enabled": False,
        "provider": "sleeper",
        "username": "",
        "user_id": "",
        "season": "2026",
        "refresh_interval": 120,
        "selected_leagues": [],
    },

    "notifications": {
        "enabled": False,
        "refresh_interval": 60,
        "max_cards": 3,
        "sources": [
            {
                "provider": "rss",
                "source": "ESPN Headlines",
                "url": "https://www.espn.com/espn/rss/news",
            },
            {
                "provider": "rss",
                "source": "CBS Sports Headlines",
                "url": "https://www.cbssports.com/rss/headlines/",
            },
            {
                "provider": "rss",
                "source": "ESPN NFL",
                "url": "https://www.espn.com/espn/rss/nfl/news",
            },
            {
                "provider": "rss",
                "source": "CBS NFL",
                "url": "https://www.cbssports.com/rss/headlines/nfl/",
            },
            {
                "provider": "rss",
                "source": "ESPN MLB",
                "url": "https://www.espn.com/espn/rss/mlb/news",
            },
            {
                "provider": "rss",
                "source": "CBS MLB",
                "url": "https://www.cbssports.com/rss/headlines/mlb/",
            },
            {
                "provider": "rss",
                "source": "MLB.com",
                "url": "https://www.mlb.com/feeds/news/rss.xml",
            },
            {
                "provider": "rss",
                "source": "ESPN NBA",
                "url": "https://www.espn.com/espn/rss/nba/news",
            },
            {
                "provider": "rss",
                "source": "CBS NBA",
                "url": "https://www.cbssports.com/rss/headlines/nba/",
            },
            {
                "provider": "rss",
                "source": "NBA.com",
                "url": "https://www.nba.com/rss/nba_rss.xml",
            },
            {
                "provider": "rss",
                "source": "ESPN NHL",
                "url": "https://www.espn.com/espn/rss/nhl/news",
            },
            {
                "provider": "rss",
                "source": "CBS NHL",
                "url": "https://www.cbssports.com/rss/headlines/nhl/",
            },
            {
                "provider": "rss",
                "source": "NHL.com",
                "url": "https://www.nhl.com/feeds/news/rss.xml",
            },
            {
                "provider": "rss",
                "source": "ESPN College Football",
                "url": "https://www.espn.com/espn/rss/ncf/news",
            },
            {
                "provider": "rss",
                "source": "CBS College Football",
                "url": "https://www.cbssports.com/rss/headlines/college-football/",
            },
            {
                "provider": "rss",
                "source": "ESPN College Basketball",
                "url": "https://www.espn.com/espn/rss/ncb/news",
            },
            {
                "provider": "rss",
                "source": "CBS College Basketball",
                "url": "https://www.cbssports.com/rss/headlines/college-basketball/",
            },
            {
                "provider": "rss",
                "source": "NCAA Basketball",
                "url": "https://www.ncaa.com/news/basketball-men/d1/rss.xml",
            },
            {
                "provider": "rss",
                "source": "ESPN Golf",
                "url": "https://www.espn.com/espn/rss/golf/news",
            },
            {
                "provider": "rss",
                "source": "CBS Golf",
                "url": "https://www.cbssports.com/rss/headlines/golf/",
            },
            {
                "provider": "rss",
                "source": "ESPN MMA",
                "url": "https://www.espn.com/espn/rss/mma/news",
            },
            {
                "provider": "rss",
                "source": "CBS MMA",
                "url": "https://www.cbssports.com/rss/headlines/mma/",
            },
        ],
    },
}


_settings_lock = threading.RLock()

_cached_settings: dict[str, Any] | None = None
_cached_mtime_ns: int | None = None


def ensure_settings_directory() -> None:
    SETTINGS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


def deep_merge(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
   
    result = deepcopy(base)

    for key, value in override.items():
        existing_value = result.get(key)

        if isinstance(existing_value, dict) and isinstance(value, dict):
            result[key] = deep_merge(
                existing_value,
                value,
            )
        else:
            result[key] = deepcopy(value)

    return result


def _get_settings_mtime_ns() -> int | None:
    try:
        return SETTINGS_FILE.stat().st_mtime_ns
    except OSError:
        return None


def _sync_directory(directory: Path) -> None:
    directory_fd: int | None = None

    try:
        directory_fd = os.open(
            directory,
            os.O_RDONLY,
        )
        os.fsync(directory_fd)
    except OSError:
        # Some filesystems may not support syncing a directory.
        pass
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _write_json_atomic(
    path: Path,
    data: dict[str, Any],
) -> None:
    
    ensure_settings_directory()

    temporary_path = path.with_name(
        f".{path.name}.tmp"
    )

    try:
        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False,
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        os.replace(
            temporary_path,
            path,
        )

        _sync_directory(path.parent)

    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _ensure_settings_file() -> None:
    ensure_settings_directory()

    if SETTINGS_FILE.exists():
        return

    _write_json_atomic(
        SETTINGS_FILE,
        deepcopy(DEFAULT_SETTINGS),
    )


def _load_saved_settings() -> dict[str, Any]:
    try:
        with SETTINGS_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            loaded = json.load(file)

        if not isinstance(loaded, dict):
            raise ValueError(
                "The settings file must contain a JSON object."
            )

        return loaded

    except FileNotFoundError:
        return {}

    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(
            f"Unable to load settings from {SETTINGS_FILE}: {error}"
        )

        corrupt_path = SETTINGS_FILE.with_suffix(
            SETTINGS_FILE.suffix + ".corrupt"
        )

        try:
            os.replace(
                SETTINGS_FILE,
                corrupt_path,
            )
            print(
                f"Corrupt settings were moved to {corrupt_path}"
            )
        except OSError:
            pass

        return {}


def load_settings() -> dict[str, Any]:
    global _cached_settings
    global _cached_mtime_ns

    with _settings_lock:
        _ensure_settings_file()

        current_mtime_ns = _get_settings_mtime_ns()

        if (
            _cached_settings is not None
            and _cached_mtime_ns == current_mtime_ns
        ):
            return deepcopy(_cached_settings)

        saved_settings = _load_saved_settings()

        settings = deep_merge(
            DEFAULT_SETTINGS,
            saved_settings,
        )

        if settings != saved_settings:
            _write_json_atomic(
                SETTINGS_FILE,
                settings,
            )
            current_mtime_ns = _get_settings_mtime_ns()

        _cached_settings = deepcopy(settings)
        _cached_mtime_ns = current_mtime_ns

        return deepcopy(settings)


def save_settings(
    settings: dict[str, Any],
) -> dict[str, Any]:
    
    global _cached_settings
    global _cached_mtime_ns

    if not isinstance(settings, dict):
        raise TypeError("settings must be a dictionary")

    with _settings_lock:
        clean_settings = deep_merge(
            DEFAULT_SETTINGS,
            settings,
        )

        _write_json_atomic(
            SETTINGS_FILE,
            clean_settings,
        )

        _cached_settings = deepcopy(clean_settings)
        _cached_mtime_ns = _get_settings_mtime_ns()

        return deepcopy(clean_settings)


def get_settings() -> dict[str, Any]:
    return load_settings()


def update_settings(
    new_values: dict[str, Any],
) -> dict[str, Any]:

    if not isinstance(new_values, dict):
        raise TypeError("new_values must be a dictionary")

    with _settings_lock:
        current_settings = load_settings()

        updated_settings = deep_merge(
            current_settings,
            new_values,
        )

        return save_settings(updated_settings)