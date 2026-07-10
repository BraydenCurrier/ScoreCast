import json
import os
import threading

SETTINGS_FILE = "/tmp/ticker_settings.json"

DEFAULT_SETTINGS = {
    "scroll_speed": 0.5,
    "brightness": 70,
    "refresh_interval": 30,
    "hidden_games": [],
    "game_order": [],

    "music": {
        "enabled": False,
        "provider": "spotify",
        "poll_interval": 5,
        "display_mode": "auto"
    },

    "odds": {
        "enabled": True,
        "provider": "theoddsapi",
        "api_key": "",
        "refresh_interval": 900
    },

    "fantasy": {
        "enabled": False,
        "provider": "sleeper",
        "username": "",
        "user_id": "",
        "season": "2026",
        "refresh_interval": 120,
        "selected_leagues": []
    },

    "notifications": {
        "enabled": True,
        "refresh_interval": 60,
        "max_cards": 3,
        "sources": [
            {
                "provider": "rss",
                "source": "ESPN Headlines",
                "url": "https://www.espn.com/espn/rss/news"
            },
            {
                "provider": "rss",
                "source": "CBS Sports Headlines",
                "url": "https://www.cbssports.com/rss/headlines/"
            },

            {
                "provider": "rss",
                "source": "ESPN NFL",
                "url": "https://www.espn.com/espn/rss/nfl/news"
            },
            {
                "provider": "rss",
                "source": "CBS NFL",
                "url": "https://www.cbssports.com/rss/headlines/nfl/"
            },

            {
                "provider": "rss",
                "source": "ESPN MLB",
                "url": "https://www.espn.com/espn/rss/mlb/news"
            },
            {
                "provider": "rss",
                "source": "CBS MLB",
                "url": "https://www.cbssports.com/rss/headlines/mlb/"
            },
            {
                "provider": "rss",
                "source": "MLB.com",
                "url": "https://www.mlb.com/feeds/news/rss.xml"
            },

            {
                "provider": "rss",
                "source": "ESPN NBA",
                "url": "https://www.espn.com/espn/rss/nba/news"
            },
            {
                "provider": "rss",
                "source": "CBS NBA",
                "url": "https://www.cbssports.com/rss/headlines/nba/"
            },
            {
                "provider": "rss",
                "source": "NBA.com",
                "url": "https://www.nba.com/rss/nba_rss.xml"
            },

            {
                "provider": "rss",
                "source": "ESPN NHL",
                "url": "https://www.espn.com/espn/rss/nhl/news"
            },
            {
                "provider": "rss",
                "source": "CBS NHL",
                "url": "https://www.cbssports.com/rss/headlines/nhl/"
            },
            {
                "provider": "rss",
                "source": "NHL.com",
                "url": "https://www.nhl.com/feeds/news/rss.xml"
            },

            {
                "provider": "rss",
                "source": "ESPN College Football",
                "url": "https://www.espn.com/espn/rss/ncf/news"
            },
            {
                "provider": "rss",
                "source": "CBS College Football",
                "url": "https://www.cbssports.com/rss/headlines/college-football/"
            },

            {
                "provider": "rss",
                "source": "ESPN College Basketball",
                "url": "https://www.espn.com/espn/rss/ncb/news"
            },
            {
                "provider": "rss",
                "source": "CBS College Basketball",
                "url": "https://www.cbssports.com/rss/headlines/college-basketball/"
            },
            {
                "provider": "rss",
                "source": "NCAA Basketball",
                "url": "https://www.ncaa.com/news/basketball-men/d1/rss.xml"
            },

            {
                "provider": "rss",
                "source": "ESPN Golf",
                "url": "https://www.espn.com/espn/rss/golf/news"
            },
            {
                "provider": "rss",
                "source": "CBS Golf",
                "url": "https://www.cbssports.com/rss/headlines/golf/"
            },

            {
                "provider": "rss",
                "source": "ESPN MMA",
                "url": "https://www.espn.com/espn/rss/mma/news"
            },
            {
                "provider": "rss",
                "source": "CBS MMA",
                "url": "https://www.cbssports.com/rss/headlines/mma/"
            }
        ]
    }
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