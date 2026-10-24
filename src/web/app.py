import gzip
import json
import subprocess
import threading
import time
from datetime import timedelta
from pathlib import Path

from functools import lru_cache, wraps
from html import escape

from flask import Flask, abort, request, redirect, send_file, session, jsonify, url_for

from common.game_ids import game_id as shared_game_id
from common.game_ids import selected_sports_ids
from common.settings import get_developer_settings, get_settings, update_settings
from common.timezone import (
    normalize_timezone_setting,
    timezone_choice_groups,
    timezone_label,
    timezone_status,
)
from common.system_stats import collect_system_stats
from common.users import (
    UserError,
    UserStoreError,
    authenticate,
    create_user,
    delete_user,
    get_or_create_web_secret,
    get_user_by_id,
    has_users,
    list_users,
)
from common.logo_store import (
    EDITABLE_LOGO_LEAGUES,
    LogoError,
    delete_custom_logo,
    get_custom_variants_by_team,
    get_logo_variant_path,
    get_logo_variants,
    get_selected_logo_variant,
    get_team_logo_catalog,
    get_teams_with_logos,
    normalize_identifier,
    save_custom_logo,
    variant_label,
)

from soccer.api import (
    DEFAULT_SOCCER_LEAGUES,
    SOCCER_LEAGUES,
)
from stocks.api import (
    DEFAULT_STOCK_SYMBOLS,
    MAX_SYMBOLS,
    POPULAR_SYMBOLS,
    parse_symbol_list,
    search_symbols,
)

from alerts.manager import possession_alert_manager
from alerts.teams import (
    MLB_TEAM_NAMES,
    NFL_TEAM_ALERTS,
    get_team_alert,
)
from nfl.player_directory import (
    MAX_WATCHED_PLAYERS,
    get_fantasy_alert_rosters,
    hydrate_watched_players,
    search_players,
    watched_nfl_players,
)
from fantasy.api import (
    connect_sleeper_user,
    get_user_leagues,
)

from updater.releases import peek_release_info
from updater.status import (
    mark_start_requested,
    read_status,
    reconcile_status,
    service_state_is_running,
    write_status,
)

class _GzipMiddleware:
    """Compress text responses so phones pull less over the Pi's Wi-Fi."""

    def __init__(self, wsgi_app, minimum=1024):
        self.wsgi_app = wsgi_app
        self.minimum = minimum

    def __call__(self, environ, start_response):
        accept = environ.get("HTTP_ACCEPT_ENCODING", "")
        if "gzip" not in accept.lower():
            return self.wsgi_app(environ, start_response)

        captured = {}

        def _start(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = list(headers)
            captured["exc_info"] = exc_info

        result = self.wsgi_app(environ, _start)
        chunks = []
        try:
            for chunk in result:
                if chunk:
                    chunks.append(chunk)
        finally:
            close = getattr(result, "close", None)
            if close is not None:
                close()

        status = captured.get("status", "500 Internal Server Error")
        headers = captured.get("headers", [])
        body = b"".join(chunks)
        if (
            not status.startswith("200")
            or len(body) < self.minimum
            or not _should_gzip(headers)
        ):
            start_response(status, headers, captured.get("exc_info"))
            return [body]

        gzipped = gzip.compress(body, compresslevel=5)
        if len(gzipped) >= len(body):
            start_response(status, headers, captured.get("exc_info"))
            return [body]

        rewritten = []
        vary = None
        for key, value in headers:
            lower = key.lower()
            if lower == "content-length":
                continue
            if lower == "vary":
                vary = value if vary is None else f"{vary}, {value}"
                continue
            rewritten.append((key, value))
        if not vary:
            vary = "Accept-Encoding"
        elif "accept-encoding" not in vary.lower():
            vary = f"{vary}, Accept-Encoding"
        rewritten.append(("Content-Encoding", "gzip"))
        rewritten.append(("Content-Length", str(len(gzipped))))
        rewritten.append(("Vary", vary))
        start_response(status, rewritten, captured.get("exc_info"))
        return [gzipped]


def _should_gzip(headers) -> bool:
    content_type = ""
    for key, value in headers:
        lower = key.lower()
        if lower == "content-encoding":
            return False
        if lower == "content-type":
            content_type = value.lower()
    return (
        content_type.startswith("text/")
        or "javascript" in content_type
        or "json" in content_type
        or content_type.startswith("image/svg")
    )


app = Flask(__name__)
app.wsgi_app = _GzipMiddleware(app.wsgi_app)
app.secret_key = get_or_create_web_secret()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 86400
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

latest_games = []

CFB_CONFERENCE_OPTIONS = [
    ("80", "All FBS"),
    ("8", "SEC"),
    ("5", "Big Ten"),
    ("1", "ACC"),
    ("4", "Big 12"),
    ("17", "Mountain West"),
]

SOCCER_LEAGUE_OPTIONS = [
    (league_id, league_name)
    for league_id, league_name in SOCCER_LEAGUES.items()
]

FOCUS_LEAGUES = [
    ("nfl", "NFL"),
    ("cfb", "College Football"),
    ("mlb", "MLB"),
    ("nba", "NBA"),
]

FOCUS_LEAGUE_HINTS = {
    "nfl": "Select one or more games to display in Focus Mode.",
    "cfb": (
        "Ranked teams show AP rank on the scoreboard. "
        "Select one or more games to display in Focus Mode."
    ),
    "mlb": (
        "Live games show the scorecard, count, batter, pitcher, "
        "and a strike zone of every pitch in the current at-bat."
    ),
    "nba": (
        "Live games show the quarter, clock, last play, "
        "quarter scores, timeouts, bonus, and possession."
    ),
}

FAVORITE_LEAGUES = [
    (
        "mlb",
        "MLB"
    ),
    (
        "nfl",
        "NFL"
    ),
    (
        "cfb",
        "College Football"
    ),
    (
        "nba",
        "NBA"
    ),
    (
        "nhl",
        "NHL"
    ),
    (
        "soccer",
        "Soccer"
    ),
]

UPDATE_SERVICE_NAME = "scorecast-update.service"

UPDATE_STATUS_FILE = Path(
    "/opt/scorecast/update-status.json"
)

ACTIVE_UPDATE_STATES = {
    "checking",
    "downloading",
    "installing",
    "validating",
    "restarting",
    "rolling_back",
}

_service_state_lock = threading.Lock()
_service_state_cache = {"value": "", "at": 0.0}


def update_service_state() -> str:
    """Return the systemd ActiveState, or "unknown" if it cannot be read."""
    now = time.monotonic()
    with _service_state_lock:
        cached_value = _service_state_cache["value"]
        cached_at = float(_service_state_cache["at"])

    if cached_value:
        busy = cached_value in {"active", "activating", "deactivating"}
        ttl = 1.5 if busy else 12.0
        if now - cached_at < ttl:
            return cached_value

    state = _read_update_service_state()
    with _service_state_lock:
        _service_state_cache["value"] = state
        _service_state_cache["at"] = time.monotonic()
    return state


def _read_update_service_state() -> str:
    try:
        result = subprocess.run(
            [
                "/usr/bin/systemctl",
                "show",
                "-p",
                "ActiveState",
                "--value",
                UPDATE_SERVICE_NAME,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

    except (
        OSError,
        subprocess.TimeoutExpired,
    ):
        return "unknown"

    if result.returncode != 0:
        return "unknown"

    return result.stdout.strip().lower() or "unknown"


def is_update_service_active() -> bool:
    return service_state_is_running(
        update_service_state()
    )

def get_scorecast_version() -> str:
    """Return the version of the installed GameLine Pro release."""
    current_link = Path("/opt/scorecast/current")

    try:
        release_path = current_link.resolve(strict=True)
        version = release_path.name

        if version:
            return version.removeprefix("v")

    except (OSError, RuntimeError):
        pass

    return "Development"


def set_latest_games(games):
    global latest_games
    latest_games = games

def establish_session(user):
    session.clear()
    session.permanent = True
    session["logged_in"] = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["is_root"] = user["role"] == "root"


@app.after_request
def set_response_cache_headers(response):
    content_type = response.headers.get("Content-Type", "")

    if "text/html" in content_type:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"

    return response


def current_user():
    if not session.get("logged_in"):
        return None

    return get_user_by_id(session.get("user_id"))


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            profiles_exist = has_users()
        except UserStoreError:
            session.clear()
            return redirect("/login")

        if not profiles_exist:
            return redirect("/setup")

        user = current_user()
        if user is None:
            session.clear()
            return redirect("/login")

        return f(*args, **kwargs)

    return wrapper


def root_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            profiles_exist = has_users()
        except UserStoreError:
            session.clear()
            return redirect("/login")

        if not profiles_exist:
            return redirect("/login")

        user = current_user()
        if user is None:
            session.clear()
            return redirect("/login")

        if user["role"] != "root":
            return redirect("/games")

        return f(*args, **kwargs)

    return wrapper


def page_header(active_page="games"):
    more_pages = (
        "stocks",
        "fantasy",
        "players",
        "logos",
        "favorites",
        "settings",
        "profiles",
    )
    bets_pages = ("bets", "live", "history", "analytics", "new")
    games_active = "active" if active_page == "games" else ""
    focus_active = "active" if active_page == "focus" else ""
    alerts_active = "active" if active_page == "alerts" else ""
    bets_active = "active" if active_page in bets_pages else ""
    more_active = "active" if active_page in more_pages else ""
    settings_active = "active" if active_page in ("settings", "profiles") else ""

    page_titles = {
        "games": ("Scores", "Select games for the board"),
        "focus": ("Focus", "Pin one game full-width"),
        "fantasy": ("Fantasy", "Sleeper matchups on the ticker"),
        "alerts": ("Alerts", "Team takeovers and chants"),
        "players": ("Players", "Big-play alerts for NFL stars"),
        "bets": ("Bets", "Track slips you already placed"),
        "live": ("Live", "Open bets in progress"),
        "history": ("History", "Settled slips"),
        "analytics": ("Analytics", "Your tracked results"),
        "new": ("Add Bet", "Log a slip you already placed"),
        "logos": ("Logos", "Pick a look or upload your own"),
        "settings": ("Settings", "Display, updates, and access"),
        "favorites": ("Favorites", "Keep your teams first"),
        "profiles": ("Settings", "Display, updates, and access"),
        "stocks": ("Stocks", "Quotes that scroll on the board"),
    }
    page_title, page_lede = page_titles.get(
        active_page,
        ("GameLine Pro", ""),
    )

    user = current_user()
    username = escape(user["username"]) if user else "Guest"
    is_root = bool(user and user["role"] == "root")
    root_badge = '<span class="account-role">Root</span>' if is_root else ""

    settings = get_settings()

    display_enabled = bool(
        settings.get("display_enabled", True)
    )

    power_class = (
        "display-power-on"
        if display_enabled
        else "display-power-off"
    )

    power_label = (
        "Turn display off"
        if display_enabled
        else "Turn display on"
    )

    return f"""
    {_BOOT_SPLASH_HTML}
    <a
        id="update-banner"
        class="update-banner"
        href="/settings#software-update"
        hidden
    >
        <span class="update-banner-kicker">Update available</span>
        <span id="update-banner-text" class="update-banner-text"></span>
    </a>

    <header class="topbar">
        <div class="topbar-main">
            <div class="brand-lockup brand-lockup-compact">
                <div class="brand-mark" aria-hidden="true">GL</div>
                <h1 class="title">GameLine</h1>
            </div>
            <div class="topbar-actions">
                <a
                    class="icon-button {settings_active}"
                    href="/settings"
                    aria-label="Settings"
                    title="Settings"
                >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                        <circle cx="12" cy="12" r="3"></circle>
                        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0 1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09A1.65 1.65 0 0 0 15 4.6a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09A1.65 1.65 0 0 0 19.4 15z"></path>
                    </svg>
                </a>
                <form
                    class="display-power-form"
                    method="POST"
                    action="/display/power/toggle"
                >
                    <input
                        type="hidden"
                        name="next"
                        value="{escape(request.path, quote=True)}"
                    >
                    <button
                        type="submit"
                        class="display-power-button {power_class}"
                        aria-label="{power_label}"
                        title="{power_label}"
                    >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M12 2 V12 M7.05 4.93 A9 9 0 1 0 16.95 4.93"/>
                        </svg>
                    </button>
                </form>
            </div>
        </div>
    </header>

    <div class="page-intro">
        <h2 class="page-title">{escape(page_title)}</h2>
        <p class="page-lede">{escape(page_lede)}</p>
    </div>

    <nav class="bottom-nav" aria-label="GameLine Pro">
        <a class="bottom-nav-item {games_active}" href="/games">
            <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"></rect><path d="M3 9h18"></path></svg>
            <span>Scores</span>
        </a>
        <a class="bottom-nav-item {focus_active}" href="/focus">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"></circle><circle cx="12" cy="12" r="3"></circle></svg>
            <span>Focus</span>
        </a>
        <a class="bottom-nav-item {alerts_active}" href="/alerts">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 7 3 9H3c0-2 3-2 3-9"></path><path d="M10 21h4"></path></svg>
            <span>Alerts</span>
        </a>
        <a class="bottom-nav-item {bets_active}" href="/bets">
            <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="6" width="18" height="12" rx="2"></rect><path d="M3 10h18"></path></svg>
            <span>Bets</span>
        </a>
        <button class="bottom-nav-item {more_active}" type="button" id="more-tab" aria-expanded="false">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.6"></circle><circle cx="12" cy="12" r="1.6"></circle><circle cx="19" cy="12" r="1.6"></circle></svg>
            <span>More</span>
        </button>
    </nav>
    <div class="more-sheet" id="more-sheet" hidden>
        <button class="more-sheet-backdrop" type="button" aria-label="Close menu"></button>
        <div class="more-sheet-card">
            <div class="more-sheet-account">
                <span class="account-name">{username}</span>
                {root_badge}
            </div>
            <a class="more-link" href="/stocks">Stocks</a>
            <a class="more-link" href="/fantasy">Fantasy</a>
            <a class="more-link" href="/players">Players</a>
            <a class="more-link" href="/favorites">Favorites</a>
            <a class="more-link" href="/logos">Logos</a>
            <a class="more-link" href="/settings">Settings</a>
            <a class="more-link more-link-quiet" href="/logout">Sign out</a>
        </div>
    </div>
    <script>
    (function () {{
      var tab = document.getElementById("more-tab");
      var sheet = document.getElementById("more-sheet");
      if (!tab || !sheet) return;
      function closeMore() {{
        sheet.hidden = true;
        tab.setAttribute("aria-expanded", "false");
      }}
      tab.addEventListener("click", function () {{
        var open = sheet.hidden;
        sheet.hidden = !open;
        tab.setAttribute("aria-expanded", open ? "true" : "false");
      }});
      var backdrop = sheet.querySelector(".more-sheet-backdrop");
      if (backdrop) backdrop.addEventListener("click", closeMore);
    }})();
    </script>
    <script>
    (function () {{
      var busyStates = {{
        checking: true,
        downloading: true,
        installing: true,
        validating: true,
        restarting: true,
        rolling_back: true
      }};

      window.applyUpdateBanner = function (status) {{
        var banner = document.getElementById("update-banner");
        var text = document.getElementById("update-banner-text");
        if (!banner || !text || !status) {{
          return;
        }}

        var release = status.release || {{}};
        var state = status.state || "idle";
        var busy = !!busyStates[state] || status.service_active === true;
        var show = release.update_available === true && !busy;
        banner.hidden = !show;
        if (!show) {{
          return;
        }}

        var version = release.latest_version
          ? ("v" + String(release.latest_version).replace(/^v/, ""))
          : "A new version";
        var title = String(release.title || "").trim();
        text.textContent = title
          ? (version + " — " + title)
          : (version + " is ready to install");
      }};

      function revealSoftwareUpdate() {{
        if (location.hash !== "#software-update") {{
          return;
        }}
        var target = document.getElementById("software-update");
        if (target) {{
          target.scrollIntoView({{ block: "start" }});
        }}
      }}

      var banner = document.getElementById("update-banner");
      if (banner) {{
        banner.addEventListener("click", function (event) {{
          var target = document.getElementById("software-update");
          if (!target) {{
            return;
          }}
          event.preventDefault();
          target.scrollIntoView({{ block: "start" }});
          if (location.hash !== "#software-update") {{
            history.replaceState(null, "", "#software-update");
          }}
        }});
      }}

      if (document.readyState === "loading") {{
        document.addEventListener("DOMContentLoaded", revealSoftwareUpdate);
      }} else {{
        revealSoftwareUpdate();
      }}

      window.setTimeout(function () {{
        fetch("/api/update/status", {{
          method: "GET",
          cache: "no-store"
        }}).then(function (response) {{
          if (!response.ok) {{
            throw new Error("status");
          }}
          return response.json();
        }}).then(function (status) {{
          window.applyUpdateBanner(status);
        }}).catch(function () {{}});
      }}, 1600);
    }})();
    </script>
    """

def page_head(title: str) -> str:
    return f"""
    <head>
        <meta charset="utf-8">

        <meta
            name="viewport"
            content="width=device-width, initial-scale=1, viewport-fit=cover"
        >

        <title>{escape(title)}</title>

        <meta name="theme-color" content="#0B1120">

        <meta
            name="apple-mobile-web-app-capable"
            content="yes"
        >

        <meta
            name="mobile-web-app-capable"
            content="yes"
        >

        <meta
            name="apple-mobile-web-app-title"
            content="GameLine"
        >

        <meta
            name="apple-mobile-web-app-status-bar-style"
            content="black"
        >

        <link
            rel="manifest"
            href="/static/manifest.webmanifest"
        >

        <link
            rel="apple-touch-icon"
            sizes="180x180"
            href="/static/icons/apple-touch-icon.png"
        >

        <link
            rel="icon"
            type="image/png"
            sizes="64x64"
            href="/static/icons/favicon-64.png"
        >

        <link
            rel="icon"
            type="image/png"
            sizes="32x32"
            href="/static/icons/favicon-32.png"
        >

        <link
            rel="icon"
            type="image/png"
            sizes="16x16"
            href="/static/icons/favicon-16.png"
        >

        <link
            rel="shortcut icon"
            href="/static/favicon.ico"
        >

        <link
            rel="mask-icon"
            href="/static/safari-pinned-tab.svg"
            color="#2563EB"
        >

        <meta property="og:type" content="website">
        <meta property="og:title" content="GameLine Pro">

        <meta
            property="og:description"
            content="Live sports on GameLine Pro from GameLine Displays."
        >

        <meta
            property="og:image"
            content="/static/social/gameline-og-1200x630.png"
        >

        {page_styles()}
    </head>
    """

_BOOT_SPLASH_HTML = """
    <div id="boot-splash" class="boot-splash" role="status" aria-live="polite" aria-label="Loading GameLine">
        <div class="boot-splash-mark">
            <span class="boot-splash-rule"></span>
            <span class="boot-splash-word">GAMELINE</span>
            <span class="boot-splash-rule"></span>
        </div>
        <div class="boot-splash-bar" aria-hidden="true"><span></span></div>
    </div>
"""

_APPLE_STARTUP_IMAGES = (
    (
        "iphone-se-640x1136.png",
        "(device-width: 320px) and (device-height: 568px) and (-webkit-device-pixel-ratio: 2)",
    ),
    (
        "iphone-8-750x1334.png",
        "(device-width: 375px) and (device-height: 667px) and (-webkit-device-pixel-ratio: 2)",
    ),
    (
        "iphone-8-plus-1242x2208.png",
        "(device-width: 414px) and (device-height: 736px) and (-webkit-device-pixel-ratio: 3)",
    ),
    (
        "iphone-x-1125x2436.png",
        "(device-width: 375px) and (device-height: 812px) and (-webkit-device-pixel-ratio: 3)",
    ),
    (
        "iphone-11-828x1792.png",
        "(device-width: 414px) and (device-height: 896px) and (-webkit-device-pixel-ratio: 2)",
    ),
    (
        "iphone-11-pro-max-1242x2688.png",
        "(device-width: 414px) and (device-height: 896px) and (-webkit-device-pixel-ratio: 3)",
    ),
    (
        "iphone-12-1170x2532.png",
        "(device-width: 390px) and (device-height: 844px) and (-webkit-device-pixel-ratio: 3)",
    ),
    (
        "iphone-12-pro-max-1284x2778.png",
        "(device-width: 428px) and (device-height: 926px) and (-webkit-device-pixel-ratio: 3)",
    ),
    (
        "iphone-14-pro-1179x2556.png",
        "(device-width: 393px) and (device-height: 852px) and (-webkit-device-pixel-ratio: 3)",
    ),
    (
        "iphone-14-pro-max-1290x2796.png",
        "(device-width: 430px) and (device-height: 932px) and (-webkit-device-pixel-ratio: 3)",
    ),
)


def _apple_startup_links() -> str:
    return "".join(
        f"""
        <link
            rel="apple-touch-startup-image"
            href="/static/splash/{filename}"
            media="{media}"
        >
        """
        for filename, media in _APPLE_STARTUP_IMAGES
    )


def page_styles():
    font_href = (
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
        "&family=Sora:wght@600;700;800&display=swap"
    )
    return f"""
    <style>
        html {{
            background: #0B1120;
        }}
        .boot-splash {{
            position: fixed;
            inset: 0;
            z-index: 80;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 28px;
            background: #0B1120;
            transition: opacity 0.32s ease;
        }}
        html.splash-skip .boot-splash {{
            display: none !important;
        }}
        .boot-splash.is-done {{
            opacity: 0;
            pointer-events: none;
        }}
        .boot-splash-mark {{
            display: flex;
            flex-direction: column;
            width: max-content;
            min-width: 210px;
        }}
        .boot-splash-rule {{
            display: block;
            height: 2px;
            background: #00D4FF;
        }}
        .boot-splash-word {{
            margin: 12px 0;
            text-align: center;
            font-family: "Sora", Inter, system-ui, sans-serif;
            font-size: 22px;
            font-weight: 800;
            letter-spacing: 0.22em;
            color: #2563EB;
            padding-left: 0.22em;
        }}
        .boot-splash-bar {{
            width: 128px;
            height: 2px;
            overflow: hidden;
            background: rgba(0, 212, 255, 0.18);
        }}
        .boot-splash-bar span {{
            display: block;
            width: 40%;
            height: 100%;
            background: #00D4FF;
            animation: boot-splash-slide 1.05s ease-in-out infinite;
        }}
        @keyframes boot-splash-slide {{
            0% {{ transform: translateX(-120%); }}
            100% {{ transform: translateX(320%); }}
        }}
        @media (prefers-reduced-motion: reduce) {{
            .boot-splash {{
                transition: none;
            }}
            .boot-splash-bar span {{
                animation: none;
                width: 100%;
            }}
        }}
    </style>
    <noscript><style>#boot-splash {{ display: none !important; }}</style></noscript>
    <script>
    (function () {{
      var root = document.documentElement;
      try {{
        if (sessionStorage.getItem("gameline-opened") === "1") {{
          root.classList.add("splash-skip");
        }}
      }} catch (error) {{}}

      if (root.classList.contains("splash-skip")) {{
        document.addEventListener("DOMContentLoaded", function () {{
          var splash = document.getElementById("boot-splash");
          if (splash) splash.remove();
        }});
        return;
      }}

      var started = Date.now();
      var closed = false;
      function finish() {{
        if (closed) return;
        closed = true;
        var wait = Math.max(0, 480 - (Date.now() - started));
        window.setTimeout(function () {{
          try {{
            sessionStorage.setItem("gameline-opened", "1");
          }} catch (error) {{}}
          var splash = document.getElementById("boot-splash");
          if (!splash) return;
          splash.classList.add("is-done");
          window.setTimeout(function () {{
            splash.remove();
          }}, 340);
        }}, wait);
      }}
      window.addEventListener("load", finish);
      window.setTimeout(finish, 6000);
    }})();
    </script>
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="mobile-web-app-capable" content="yes">
    {_apple_startup_links()}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="{font_href}" media="print" onload="this.media='all'">
    <noscript><link rel="stylesheet" href="{font_href}"></noscript>
    <link rel="stylesheet" href="/static/app.css?v=33">
    """ + """
    <script>
    (function () {
      if (navigator.serviceWorker) {
        navigator.serviceWorker.getRegistrations().then(function (registrations) {
          registrations.forEach(function (registration) {
            registration.unregister();
          });
        });
      }
      if (window.caches) {
        caches.keys().then(function (keys) {
          keys.forEach(function (key) {
            caches.delete(key);
          });
        });
      }
    })();
    </script>
    <script>
    document.addEventListener("DOMContentLoaded", function () {
      setupStockSearch();
    });

    function isAutosaveForm(form) {
      return !!(form && form.getAttribute("data-autosave") === "1");
    }

    var autosaveTimers = new WeakMap();
    var autosaveQueued = new WeakMap();

    window.autosaveForm = function (form, delay) {
      if (!isAutosaveForm(form)) {
        return;
      }

      delay = delay == null ? 160 : delay;
      var existing = autosaveTimers.get(form);
      if (existing) {
        window.clearTimeout(existing);
      }

      autosaveTimers.set(form, window.setTimeout(function () {
        autosaveTimers.delete(form);
        if (form.dataset.autosaveBusy === "1") {
          autosaveQueued.set(form, true);
          return;
        }

        form.dataset.autosaveBusy = "1";
        fetch(form.getAttribute("action") || window.location.pathname, {
          method: "POST",
          body: new FormData(form),
          credentials: "same-origin",
          headers: {
            "X-GameLine-Autosave": "1",
            "Accept": "application/json"
          }
        }).then(function (response) {
          return response.json().catch(function () {
            return {};
          }).then(function (payload) {
            payload = payload || {};
            var status = form.querySelector("[data-autosave-error]");
            if (!response.ok || payload.ok === false) {
              if (status) {
                status.hidden = false;
                status.textContent = payload.error || "Couldn't save that change.";
              }
              return;
            }
            if (status) {
              status.hidden = true;
              status.textContent = "";
            }
            if (payload.reload) {
              window.location.reload();
            }
          });
        }).catch(function () {
          return null;
        }).finally(function () {
          form.dataset.autosaveBusy = "0";
          if (autosaveQueued.get(form)) {
            autosaveQueued.delete(form);
            window.autosaveForm(form, 0);
          }
        });
      }, delay));
    };

    function shouldSkipAutosave(target) {
      if (!target || target.disabled) {
        return true;
      }
      if (target.closest("[data-no-autosave]")) {
        return true;
      }
      if (target.type === "search") {
        return true;
      }
      if (target.id && /search/i.test(target.id)) {
        return true;
      }
      if (target.id === "alert_league" || target.id === "logo_league" || target.id === "focus_league" || target.id === "favorite_league") {
        return true;
      }
      if (target.id === "live_games_only" || target.id === "league_filter") {
        return true;
      }
      if (!target.name && target.type !== "range") {
        return true;
      }
      return false;
    }

    document.addEventListener("change", function (event) {
      var target = event.target;
      var form = target && target.form;
      if (!isAutosaveForm(form) || shouldSkipAutosave(target)) {
        return;
      }
      var delay = (
        target.type === "text"
        || target.type === "number"
        || target.type === "range"
      ) ? 280 : 60;
      window.autosaveForm(form, delay);
    });

    document.addEventListener("input", function (event) {
      var target = event.target;
      var form = target && target.form;
      if (!isAutosaveForm(form) || shouldSkipAutosave(target)) {
        return;
      }
      if (target.name === "username" || target.name === "season") {
        return;
      }
      if (
        target.type === "range"
        || target.type === "number"
        || target.type === "text"
      ) {
        window.autosaveForm(form, 280);
      }
    });

    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (!isAutosaveForm(form)) {
        return;
      }
      event.preventDefault();
      window.autosaveForm(form, 0);
    });

    function handleCfbConferenceChange(changedCheckbox) {
      var allFbs = document.querySelector(
        'input[name="cfb_conferences"][value="80"]'
      );
      var individualConferences = Array.from(
        document.querySelectorAll(
          'input[name="cfb_conferences"]:not([value="80"])'
        )
      );

      if (changedCheckbox.value === "80" && changedCheckbox.checked) {
        individualConferences.forEach(function(checkbox) {
          checkbox.checked = false;
        });
        return;
      }

      if (
        changedCheckbox.value !== "80"
        && changedCheckbox.checked
        && allFbs
      ) {
        allFbs.checked = false;
      }

      var anySelected = Array.from(
        document.querySelectorAll(
          'input[name="cfb_conferences"]:checked'
        )
      ).length > 0;

      if (!anySelected && allFbs) {
        allFbs.checked = true;
      }
    }

    function setupStockSearch() {
      var search = document.getElementById("stock_search");
      var results = document.getElementById("stock_search_results");
      var list = document.getElementById("stock_watchlist");
      var empty = document.getElementById("stock_watchlist_empty");
      var maxSymbols = Number(
        (list && list.getAttribute("data-max-symbols")) || "25"
      );

      if (!search || !results || !list) {
        return;
      }

      var timer = null;
      var requestId = 0;

      function selectedSymbols() {
        return Array.from(
          list.querySelectorAll('input[name="stock_symbols"]')
        ).map(function(input) {
          return input.value;
        });
      }

      function refreshEmpty() {
        if (!empty) {
          return;
        }
        empty.style.display = selectedSymbols().length ? "none" : "block";
      }

      function hideResults() {
        results.hidden = true;
        results.innerHTML = "";
      }

      function addStock(symbol, name) {
        symbol = String(symbol || "").toUpperCase();
        name = String(name || "").trim();

        if (!symbol) {
          return;
        }

        if (selectedSymbols().indexOf(symbol) !== -1) {
          search.value = "";
          hideResults();
          return;
        }

        if (selectedSymbols().length >= maxSymbols) {
          results.innerHTML = (
            '<div class="stock-search-empty">You can track '
            + maxSymbols
            + " stocks.</div>"
          );
          results.hidden = false;
          return;
        }

        var row = document.createElement("div");
        row.className = "stock-watch-row";

        var label = document.createElement("label");
        label.className = "game-row";

        var checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.name = "stock_shown";
        checkbox.value = symbol;
        checkbox.checked = true;

        var symbolInput = document.createElement("input");
        symbolInput.type = "hidden";
        symbolInput.name = "stock_symbols";
        symbolInput.value = symbol;

        var nameInput = document.createElement("input");
        nameInput.type = "hidden";
        nameInput.name = "stock_names";
        nameInput.value = name;

        var info = document.createElement("div");
        info.className = "game-info";

        var matchup = document.createElement("div");
        matchup.className = "matchup";
        matchup.textContent = symbol;

        var details = document.createElement("div");
        details.className = "details";
        details.textContent = name || "Show this quote on the board";

        info.appendChild(matchup);
        info.appendChild(details);

        label.appendChild(checkbox);
        label.appendChild(symbolInput);
        label.appendChild(nameInput);
        label.appendChild(info);

        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "stock-remove-button";
        remove.textContent = "Remove";
        remove.setAttribute("aria-label", "Remove " + symbol);

        row.appendChild(label);
        row.appendChild(remove);
        list.appendChild(row);

        search.value = "";
        hideResults();
        refreshEmpty();
        if (window.autosaveForm && search.form) {
          window.autosaveForm(search.form, 0);
        }
      }

      function renderResults(items) {
        results.innerHTML = "";

        if (!items.length) {
          results.innerHTML = (
            '<div class="stock-search-empty">No matching stocks.</div>'
          );
          results.hidden = false;
          return;
        }

        items.forEach(function(item) {
          var button = document.createElement("button");
          button.type = "button";
          button.className = "stock-search-result";

          var symbol = document.createElement("div");
          symbol.className = "matchup";
          symbol.textContent = item.symbol;

          var meta = document.createElement("div");
          meta.className = "details";
          meta.textContent = [item.name, item.exchange]
            .filter(Boolean)
            .join(" · ");

          button.appendChild(symbol);
          button.appendChild(meta);
          button.addEventListener("click", function() {
            addStock(item.symbol, item.name);
          });
          results.appendChild(button);
        });

        results.hidden = false;
      }

      async function lookup(query) {
        var currentId = ++requestId;

        try {
          var response = await fetch(
            "/api/stocks/search?q=" + encodeURIComponent(query),
            { method: "GET", cache: "no-store" }
          );

          if (!response.ok) {
            throw new Error("search failed");
          }

          var payload = await response.json();

          if (currentId !== requestId) {
            return;
          }

          renderResults(payload.results || []);
        } catch (error) {
          if (currentId !== requestId) {
            return;
          }

          results.innerHTML = (
            '<div class="stock-search-empty">Unable to search right now.</div>'
          );
          results.hidden = false;
        }
      }

      search.addEventListener("input", function() {
        var query = search.value.trim();
        window.clearTimeout(timer);

        if (query.length < 1) {
          hideResults();
          return;
        }

        timer = window.setTimeout(function() {
          lookup(query);
        }, 250);
      });

      search.addEventListener("keydown", function(event) {
        if (event.key === "Enter") {
          event.preventDefault();
          var first = results.querySelector(".stock-search-result");
          if (first) {
            first.click();
          }
        }
      });

      list.addEventListener("click", function(event) {
        var button = event.target.closest(".stock-remove-button");
        if (!button) {
          return;
        }
        var row = button.closest(".stock-watch-row");
        if (row) {
          row.remove();
          refreshEmpty();
          if (window.autosaveForm && list.closest("form")) {
            window.autosaveForm(list.closest("form"), 0);
          }
        }
      });

      document.addEventListener("click", function(event) {
        if (!event.target.closest(".stock-search")) {
          hideResults();
        }
      });
    }
    </script>
    """


def is_autosave_request():
    return request.headers.get("X-GameLine-Autosave") == "1"


def autosave_response(url, extra=None):
    if is_autosave_request():
        payload = {"ok": True}
        if extra:
            payload.update(extra)
        return jsonify(payload)
    return redirect(url)


def get_game_league(game):
    class_name = game.__class__.__name__

    if class_name == "CollegeFootballGame":
        return "cfb", "CFB"

    if class_name == "FootballGame":
        return "nfl", "NFL"

    if class_name == "SoccerGame":
        return "soccer", "Soccer"

    if class_name == "StockQuote":
        return "stocks", "Stocks"
    
    if class_name == "BasketballGame":
        return "nba", "NBA"
    
    if class_name == "HockeyGame":
        return "nhl", "NHL"

    if class_name == "GolfTournament":
        return "pga", "PGA"

    if class_name == "FantasyMatchup":
        return "fantasy", "FANTASY"
    
    return "mlb", "MLB"

def get_game_id(game):
    return shared_game_id(game)


_WEB_COLOR_LEAGUES = {
    "nfl": "nfl.colors",
    "cfb": "cfb.colors",
    "mlb": "mlb.colors",
    "nhl": "nhl.colors",
}
_LOGO_MARK_LEAGUES = frozenset(
    {"nfl", "nba", "mlb", "nhl", "cfb", "soccer"}
)


def _web_team_rgb(league_key, abbreviation):
    module_name = _WEB_COLOR_LEAGUES.get(str(league_key or "").lower())
    if not module_name:
        return None
    try:
        module = __import__(module_name, fromlist=["team_color"])
        rgb = module.team_color(abbreviation)
    except Exception:
        return None
    if not rgb or len(rgb) < 3:
        return None
    red, green, blue = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    if red + green + blue >= 720:
        return None
    return (red, green, blue)


def _accent_from_logo(logo_path):
    try:
        stamp = Path(logo_path).stat().st_mtime_ns
    except OSError:
        return None
    return _accent_from_logo_cached(str(logo_path), stamp)


@lru_cache(maxsize=256)
def _accent_from_logo_cached(logo_path, _mtime_ns):
    try:
        from PIL import Image

        image = Image.open(logo_path).convert("RGBA")
    except Exception:
        return None

    best = None
    best_sat = 12
    pixels = list(image.getdata())
    step = max(1, len(pixels) // 500)
    for index in range(0, len(pixels), step):
        red, green, blue, alpha = pixels[index]
        if alpha < 48:
            continue
        luminance = red + green + blue
        if luminance < 70 or luminance > 700:
            continue
        sat = max(red, green, blue) - min(red, green, blue)
        if sat > best_sat:
            best_sat = sat
            best = (red, green, blue)
    return best


def web_team_mark(league_key, abbreviation, settings, rank=None, accent=True):
    raw = str(abbreviation or "").strip()
    if not raw:
        return '<span class="score-team-main"><span class="score-abbr"></span></span>'

    label = escape(raw)
    logo_html = ""
    color_style = ""
    rgb = _web_team_rgb(league_key, raw)
    league = str(league_key or "").strip().lower()

    if league in _LOGO_MARK_LEAGUES:
        try:
            ident = normalize_identifier(raw)
            variants = get_logo_variants(league, ident)
        except ValueError:
            ident = ""
            variants = []

        if ident and variants:
            variant = get_selected_logo_variant(
                settings,
                league,
                ident,
                available=variants,
            )
            src = (
                f"/logo-preview/{escape(league, quote=True)}"
                f"/{escape(ident, quote=True)}"
                f"/{escape(str(variant), quote=True)}"
            )
            logo_html = (
                f'<img class="score-logo" src="{src}" alt="" '
                f'width="24" height="24" loading="lazy" '
                f'decoding="async" draggable="false">'
            )
            if accent and rgb is None:
                logo_path = get_logo_variant_path(league, ident, variant)
                if logo_path is not None:
                    rgb = _accent_from_logo(logo_path)

    if rgb is not None:
        color_style = (
            f' style="color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"'
        )

    rank_html = ""
    if rank not in (None, "", 0):
        rank_html = (
            f'<span class="score-rank">{escape(str(rank))}</span>'
        )

    return (
        f'<span class="score-team-main">{rank_html}{logo_html}'
        f'<span class="score-abbr"{color_style}>{label}</span></span>'
    )

def get_favorite_teams(
    settings,
    league_key
):
    favorites = settings.get(
        "favorite_teams",
        {}
    )

    if not isinstance(
        favorites,
        dict
    ):
        return set()

    values = favorites.get(
        league_key,
        []
    )

    if isinstance(values, str):
        values = [values]

    return {
        str(team).strip().upper()
        for team in values
        if str(team).strip()
    }

def is_favorite_game(
    game,
    settings
):
    league_key, _ = (
        get_game_league(game)
    )

    favorites = (
        get_favorite_teams(
            settings,
            league_key
        )
    )

    if not favorites:
        return False

    away = str(
        getattr(
            game,
            "away",
            ""
        )
    ).strip().upper()

    home = str(
        getattr(
            game,
            "home",
            ""
        )
    ).strip().upper()

    return (
        away in favorites
        or home in favorites
    )


def favorite_star_html(is_favorite):
    if not is_favorite:
        return ""
    return """
        <span class="score-star" title="Favorite" aria-label="Favorite">
            <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 3.2l2.5 6.3 6.8.6-5.2 4.5 1.6 6.6L12 17.8 6.3 21.2l1.6-6.6L2.7 10.1l6.8-.6z"></path>
            </svg>
        </span>
    """


def get_favorite_team_options(league_key):
    try:
        return get_teams_with_logos(league_key)
    except (ValueError, OSError):
        return []

def is_game_live(game):
    status = str(
        getattr(game, "status", "")
    ).strip().upper()

    if not status:
        return False

    not_live_statuses = {
        "STATUS_SCHEDULED",
        "SCHEDULED",
        "STATUS_FINAL",
        "FINAL",
        "STATUS_PREVIEW",
        "PREVIEW",
        "QUOTE",
        "CLOSED",
    }

    return status not in not_live_statuses

def _status_clock_line(game):
    clock = str(getattr(game, "clock", "") or "").strip()
    quarter = getattr(game, "quarter", None)
    period = getattr(game, "period", None)
    inning = getattr(game, "inning", None)

    if inning not in (None, "", 0):
        if hasattr(game, "top_inning"):
            half = "T" if game.top_inning else "B"
            return f"{half}{inning}"

        inning_half = str(
            getattr(game, "inning_half", "") or ""
        ).strip().lower()
        if inning_half.startswith("top"):
            return f"T{inning}"
        if inning_half.startswith("bot"):
            return f"B{inning}"
        if inning_half:
            return f"{inning_half[:3].title()} {inning}"
        return str(inning)

    number = quarter if quarter not in (None, "", 0) else period
    if number not in (None, "", 0):
        label = f"Q{number}"
        if clock:
            return f"{clock} {label}"
        return label

    if clock:
        return clock
    return "Live"


def _pretty_game_status(status):
    raw = str(status or "").strip()
    key = raw.upper().replace(" ", "_")
    labels = {
        "STATUS_FINAL": "Final",
        "FINAL": "Final",
        "STATUS_FULL_TIME": "Final",
        "STATUS_HALFTIME": "Halftime",
        "HALFTIME": "Halftime",
        "STATUS_END_PERIOD": "End of period",
        "STATUS_END_HALF": "Halftime",
        "STATUS_DELAYED": "Delayed",
        "STATUS_POSTPONED": "Postponed",
        "STATUS_CANCELED": "Canceled",
        "STATUS_CANCELLED": "Canceled",
        "STATUS_SUSPENDED": "Suspended",
        "STATUS_PREVIEW": "Preview",
        "PREVIEW": "Preview",
        "STATUS_SCHEDULED": "Scheduled",
        "SCHEDULED": "Scheduled",
        "LIVE": "Live",
    }
    return labels.get(key, raw.replace("STATUS_", "").replace("_", " ").title())


def get_display_status(game, league_key):
    status = getattr(game, "status", "")
    status_key = str(status or "").strip().upper().replace(" ", "_")

    if league_key == "soccer":
        league_name = str(
            getattr(game, "league_short", "")
            or getattr(game, "league_name", "")
            or "Soccer"
        )

        if status_key in ("SCHEDULED", "STATUS_SCHEDULED"):
            return league_name

        pretty = _pretty_game_status(status)
        if pretty:
            return f"{pretty} · {league_name}"

        return league_name

    if league_key == "stocks":
        change = float(getattr(game, "change", 0) or 0)
        percent = float(
            getattr(game, "change_percent", 0) or 0
        )
        sign = "+" if change > 0 else ""
        return (
            f"{sign}{change:.2f} ({sign}{percent:.1f}%)"
        )

    if status_key in ("STATUS_SCHEDULED", "SCHEDULED"):
        if league_key in ("nfl", "cfb"):
            return f"Week {getattr(game, 'week', 1)}"

        return "Scheduled"

    if status_key in (
        "STATUS_IN_PROGRESS",
        "IN_PROGRESS",
        "LIVE",
        "STATUS_FIRST_HALF",
        "STATUS_SECOND_HALF",
    ):
        return _status_clock_line(game)

    return _pretty_game_status(status)


def get_game_when_label(game):
    date = str(getattr(game, "date", "") or "").strip()
    start_time = str(getattr(game, "start_time", "") or "").strip()
    when = str(getattr(game, "when", "") or "").strip()

    if not date and when:
        date = when

    if date and start_time:
        if start_time.lower() in date.lower():
            return date
        return f"{date} {start_time}"

    return date or start_time


def render_auth_page(title, body):
    return f"""
<!DOCTYPE html>
<html>
{page_head(title)}
<body class="auth-body">
    {_BOOT_SPLASH_HTML}
    <div class="page">
        {body}
    </div>
</body>
</html>
    """


@app.route("/")
@login_required
def home():
    return redirect("/games")


_LOGIN_WINDOW_SECONDS = 10 * 60
_LOGIN_LOCK_SECONDS = 5 * 60
_LOGIN_FAILURE_LIMIT = 8
_login_failures: dict[str, list[float]] = {}
_login_failures_lock = threading.Lock()


def _login_is_locked(ip: str) -> bool:
    now = time.monotonic()
    with _login_failures_lock:
        recent = [
            stamp
            for stamp in _login_failures.get(ip, [])
            if now - stamp < _LOGIN_WINDOW_SECONDS
        ]
        _login_failures[ip] = recent
        if len(recent) < _LOGIN_FAILURE_LIMIT:
            return False
        return now - recent[-1] < _LOGIN_LOCK_SECONDS


def _login_record_failure(ip: str) -> None:
    now = time.monotonic()
    with _login_failures_lock:
        recent = [
            stamp
            for stamp in _login_failures.get(ip, [])
            if now - stamp < _LOGIN_WINDOW_SECONDS
        ]
        recent.append(now)
        _login_failures[ip] = recent


def _login_clear(ip: str) -> None:
    with _login_failures_lock:
        _login_failures.pop(ip, None)


@app.route("/login", methods=["GET", "POST"])
def login():
    try:
        profiles_exist = has_users()
    except UserStoreError as exc:
        body = f"""
            <div class="auth-intro">
                <div class="brand-lockup">
                    <div class="brand-mark" aria-hidden="true">GL</div>
                    <div>
                        <div class="brand-name">GameLine Pro</div>
                        <div class="brand-tag">Unable to load profiles</div>
                    </div>
                </div>
            </div>
            <div class="card login-card">
                <div class="error">{escape(str(exc))}</div>
            </div>
        """
        return render_auth_page("GameLine Pro Login", body), 500

    if not profiles_exist:
        return redirect("/setup")

    user = current_user()
    if user is not None:
        return redirect("/games")

    error = ""

    if request.method == "POST":
        client_ip = request.remote_addr or ""
        if _login_is_locked(client_ip):
            error = (
                "Too many sign-in attempts. "
                "Wait a few minutes and try again."
            )
        else:
            user = authenticate(
                request.form.get("username", ""),
                request.form.get("password", ""),
            )

            if user is not None:
                _login_clear(client_ip)
                establish_session(user)
                return redirect("/games")

            _login_record_failure(client_ip)
            error = "Invalid username or password"

    error_html = f"<div class='error'>{escape(error)}</div>" if error else ""

    form_fields = """
            <label class="field-label" for="login_username">Username</label>
            <input
                class="auth-input"
                id="login_username"
                type="text"
                name="username"
                placeholder="Username"
                autocomplete="username"
                autofocus
            >
            <label class="field-label" for="login_password">Password</label>
            <input
                class="auth-input"
                id="login_password"
                type="password"
                name="password"
                placeholder="••••••••"
                autocomplete="current-password"
            >
        """
    button_label = "Sign in"

    body = f"""
        <div class="auth-intro">
            <div class="brand-lockup">
                <div class="brand-mark" aria-hidden="true">GL</div>
                <div>
                    <div class="brand-name">GameLine Pro</div>
                    <div class="brand-tag">GameLine Displays</div>
                </div>
            </div>
        </div>
        <div class="card login-card">
            {error_html}
            <form method="POST">
                {form_fields}
                <button class="save-button" type="submit">
                    {button_label}
                </button>
            </form>
        </div>
    """

    return render_auth_page("GameLine Pro Login", body)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/profiles", methods=["GET", "POST"])
@root_required
def profiles_page():
    if request.method != "POST":
        return redirect("/settings#profiles")

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if password != confirm_password:
        return redirect(
            url_for("settings_page", error="Passwords do not match.")
            + "#profiles"
        )

    try:
        create_user(username, password, role="user")
    except UserError as exc:
        return redirect(
            url_for("settings_page", error=str(exc)) + "#profiles"
        )

    return redirect(url_for("settings_page", saved="1") + "#profiles")


@app.route("/profiles/delete", methods=["POST"])
@root_required
def delete_profile():
    actor = current_user()
    if actor is None:
        return redirect("/login")

    try:
        delete_user(
            request.form.get("user_id", ""),
            actor_id=actor["id"],
        )
    except UserError as exc:
        return redirect(
            url_for("settings_page", error=str(exc)) + "#profiles"
        )

    return redirect(url_for("settings_page", deleted="1") + "#profiles")

@app.route(
    "/display/power/toggle",
    methods=["POST"],
)
@login_required
def toggle_display_power():
    settings = get_settings()

    current_state = bool(
        settings.get(
            "display_enabled",
            True,
        )
    )

    new_state = not current_state

    update_settings({
        "display_enabled": new_state,
    })

    next_path = (
        request.form.get(
            "next",
            "/games",
        )
        .strip()
    )

    if (
        not next_path.startswith("/")
        or next_path.startswith("//")
    ):
        next_path = "/games"

    return redirect(next_path)

@app.route("/api/system/stats", methods=["GET"])
@login_required
def api_system_stats():
    user = current_user()
    if not user or user["role"] != "root":
        return jsonify({"error": "Root only."}), 403

    return jsonify(collect_system_stats())


@app.route("/system/reboot", methods=["POST"])
@login_required
def reboot_raspberry_pi():
    import threading
    import time

    user = current_user()
    if not user or user["role"] != "root":
        return jsonify({"ok": False, "message": "Root only."}), 403

    def reboot_board():
        time.sleep(1.0)
        reboot = Path("/sbin/reboot")
        command = (
            [str(reboot)]
            if reboot.is_file()
            else ["/usr/sbin/reboot"]
        )
        subprocess.run(
            command,
            check=False,
            timeout=30,
        )

    threading.Thread(
        target=reboot_board,
        daemon=True,
    ).start()

    return jsonify({"ok": True})


@app.route("/system/restart", methods=["POST"])
@login_required
def restart_scorecast():
    import threading
    import time

    user = current_user()
    if not user or user.get("role") != "root":
        return jsonify({
            "ok": False,
            "message": "Only the root profile can restart GameLine Pro.",
        }), 403

    def restart_service():
        # Give Flask time to return the response before
        # systemd terminates this process.
        time.sleep(1.0)

        subprocess.run(
            [
                "/usr/bin/systemctl",
                "restart",
                "scorecast.service",
            ],
            check=False,
            timeout=30,
        )

    threading.Thread(
        target=restart_service,
        daemon=True,
        name="scorecast-restart",
    ).start()

    return jsonify({
        "ok": True,
        "message": "GameLine Pro is restarting.",
    })


@app.route("/system/factory-reset", methods=["POST"])
@login_required
def factory_reset_scorecast():
    import threading
    import time

    from setup.factory_reset import factory_reset

    user = current_user()
    if not user or user["role"] != "root":
        return jsonify({"ok": False, "message": "Root only."}), 403

    forget_wifi = False
    if request.is_json:
        forget_wifi = bool((request.get_json(silent=True) or {}).get("forget_wifi"))
    else:
        forget_wifi = request.form.get("forget_wifi") == "1"

    factory_reset(forget_wifi=forget_wifi)

    def restart_service():
        time.sleep(1.0)
        subprocess.run(
            [
                "/usr/bin/systemctl",
                "restart",
                "scorecast.service",
            ],
            check=False,
            timeout=30,
        )

    threading.Thread(
        target=restart_service,
        daemon=True,
        name="gameline-factory-reset",
    ).start()

    return jsonify({
        "ok": True,
        "forget_wifi": forget_wifi,
        "message": "Factory reset started. Watch the board for setup.",
    })


def _is_stock_id(game_id):
    return str(game_id).startswith("stocks:")


def _cfb_conference_rows(settings):
    selected = {
        str(group_id)
        for group_id in settings.get("cfb", {}).get(
            "selected_conferences",
            ["80"],
        )
    }

    rows = ""
    for group_id, conference_name in CFB_CONFERENCE_OPTIONS:
        checked = "checked" if group_id in selected else ""
        rows += f"""
        <label class="game-row">
            <input
                type="checkbox"
                name="cfb_conferences"
                value="{group_id}"
                data-cfb-conference="{group_id}"
                onchange="handleCfbConferenceChange(this)"
                {checked}
            >
            <div class="game-info">
                <div class="matchup">{escape(conference_name)}</div>
                <div class="details">
                    {"Show every FBS game" if group_id == "80" else "Show games involving this conference"}
                </div>
            </div>
        </label>
        """
    return rows


def _soccer_league_rows(settings):
    selected = {
        str(league_id)
        for league_id in settings.get("soccer", {}).get(
            "selected_leagues",
            DEFAULT_SOCCER_LEAGUES,
        )
    }

    rows = ""
    for league_id, league_name in SOCCER_LEAGUE_OPTIONS:
        checked = "checked" if league_id in selected else ""
        rows += f"""
        <label class="game-row">
            <input
                type="checkbox"
                name="soccer_leagues"
                value="{escape(league_id, quote=True)}"
                {checked}
            >
            <div class="game-info">
                <div class="matchup">{escape(league_name)}</div>
                <div class="details">
                    Show today's games from this league
                </div>
            </div>
        </label>
        """
    return rows


def _normalized_cfb_conferences(values):
    valid_ids = {group_id for group_id, _ in CFB_CONFERENCE_OPTIONS}
    selected = [
        group_id
        for group_id in values
        if group_id in valid_ids
    ]
    if not selected:
        selected = ["80"]
    if "80" in selected:
        selected = ["80"]
    return selected


def _normalized_soccer_leagues(values):
    valid_ids = set(SOCCER_LEAGUES)
    selected = [
        league_id
        for league_id in values
        if league_id in valid_ids
    ]
    if not selected:
        selected = list(DEFAULT_SOCCER_LEAGUES)
    return selected


def _profiles_cards_html(saved_message="", error=""):
    error_html = f"<div class='error'>{escape(error)}</div>" if error else ""
    actor = current_user()
    actor_id = actor["id"] if actor else ""

    profile_rows = ""
    for user in list_users():
        is_root = user["role"] == "root"
        role_label = "Root" if is_root else "Profile"
        can_delete = user["id"] != actor_id and not is_root

        if can_delete:
            delete_control = f"""
                <form method="POST" action="/profiles/delete">
                    <input type="hidden" name="user_id" value="{escape(user['id'], quote=True)}">
                    <button
                        class="delete-profile-button"
                        type="submit"
                        onclick="return confirm('Delete this profile?');"
                    >
                        Delete
                    </button>
                </form>
            """
        else:
            delete_control = """
                <button class="delete-profile-button" type="button" disabled>
                    Root
                </button>
            """

        profile_rows += f"""
            <div class="profile-row">
                <div class="profile-meta">
                    <div class="profile-name">{escape(user['username'])}</div>
                    <div class="profile-details">{role_label}</div>
                </div>
                {delete_control}
            </div>
        """

    return f"""
        <div class="card" id="profiles">
            <div class="card-title">Profiles</div>
            <div class="hint" style="margin-bottom:12px;">
                People who can sign in to this display.
                Only the root user can add or remove them.
            </div>
            {saved_message}
            {profile_rows}
        </div>

        <form method="POST" action="/profiles">
            <div class="card">
                <div class="card-title">Add profile</div>
                {error_html}
                <input
                    class="auth-input"
                    type="text"
                    name="username"
                    placeholder="Username"
                    autocomplete="off"
                    value="{escape(request.form.get('username', ''), quote=True)}"
                >
                <input
                    class="auth-input"
                    type="password"
                    name="password"
                    placeholder="Password"
                    autocomplete="new-password"
                >
                <input
                    class="auth-input"
                    type="password"
                    name="confirm_password"
                    placeholder="Confirm password"
                    autocomplete="new-password"
                >
                <button class="save-button" type="submit">
                    Create profile
                </button>
            </div>
        </form>
    """


@app.route("/games")
@login_required
def games():
    settings = get_settings()
    hidden = set(settings.get("hidden_games", []))
    selected_ids = selected_sports_ids(settings)
    league_filters = {
        "selected",
        "favorites",
        "all",
        "mlb",
        "nfl",
        "cfb",
        "top25",
        "soccer",
        "nba",
        "nhl",
        "pga",
        "fantasy",
    }
    selected_league_filter = request.args.get("league", "selected")
    if selected_league_filter not in league_filters:
        selected_league_filter = "selected"

    def league_option(value, label):
        selected = "selected" if selected_league_filter == value else ""
        return (
            f'<option value="{value}" {selected}>{label}</option>'
        )

    game_row_parts = []
    display_games = []
    favorite_cache = {}

    def favorite_cached(game):
        key = id(game)
        if key not in favorite_cache:
            favorite_cache[key] = is_favorite_game(game, settings)
        return favorite_cache[key]

    for game in latest_games:
        league_key, league_label = get_game_league(game)
        if league_key == "stocks":
            continue
        display_games.append((
            game,
            league_key,
            league_label,
            favorite_cached(game),
        ))
    display_games.sort(key=lambda item: 0 if item[3] else 1)

    for game, league_key, league_label, favorite_game in display_games:
        game_id = get_game_id(game)

        checked = (
            "checked"
            if game_id in selected_ids
            else ""
        )

        display_status = get_display_status(game, league_key)
        when_label = get_game_when_label(game)
        is_live = is_game_live(game)

        is_top_25 = (
            league_key == "cfb"
            and (
                getattr(game, "away_rank", None) is not None
                or getattr(game, "home_rank", None) is not None
            )
        )

        safe_game_id = escape(game_id, quote=True)
        safe_status = escape(str(display_status))
        safe_when = escape(when_label) if when_label else ""
        star_html = favorite_star_html(favorite_game)

        live_class = "is-live" if is_live else ""
        if league_key == "pga":
            matchup = escape(str(getattr(game, "name", "PGA")))
            leaders = []
            for player in list(getattr(game, "players", ()) or ())[:6]:
                place = escape(getattr(player, "position", "") or "")
                tee = ""
                if getattr(player, "awaiting_tee", False):
                    tee = escape(getattr(player, "marker", "") or "")
                leaders.append(
                    " ".join(
                        part for part in (
                            place,
                            escape(player.name),
                            escape(player.score),
                            tee,
                        )
                        if part
                    )
                )
            summary = ", ".join(leaders) or escape(
                getattr(game, "when", "") or "This week"
            )
            scoreboard = f"""
                <div class="score-meta">
                    <span class="score-league-wrap">
                        <span class="score-league">{league_label}</span>
                        {star_html}
                    </span>
                    <span class="score-status {live_class}">{safe_status}</span>
                </div>
                <div class="score-team">
                    <span class="score-abbr">{matchup}</span>
                </div>
                <div class="score-when">{summary}</div>
            """
        else:
            show_scores = is_live or "final" in str(display_status).lower()
            away_score = (
                escape(str(getattr(game, "away_score", 0)))
                if show_scores
                else ""
            )
            home_score = (
                escape(str(getattr(game, "home_score", 0)))
                if show_scores
                else ""
            )
            when_line = safe_when or ""
            away_mark = web_team_mark(
                league_key,
                getattr(game, "away", ""),
                settings,
                getattr(game, "away_rank", None),
            )
            home_mark = web_team_mark(
                league_key,
                getattr(game, "home", ""),
                settings,
                getattr(game, "home_rank", None),
            )
            scoreboard = f"""
                <div class="score-meta">
                    <span class="score-league-wrap">
                        <span class="score-league">{league_label}</span>
                        {star_html}
                    </span>
                    <span class="score-status {live_class}">{safe_status}</span>
                </div>
                <div class="score-team">
                    {away_mark}
                    <span class="score-pts">{away_score}</span>
                </div>
                <div class="score-team">
                    {home_mark}
                    <span class="score-pts">{home_score}</span>
                </div>
                <div class="score-when">{when_line}</div>
            """

        search_bits = [
            league_key,
            league_label,
            getattr(game, "away", ""),
            getattr(game, "home", ""),
            getattr(game, "name", ""),
            display_status,
            when_label,
            getattr(game, "away_score", ""),
            getattr(game, "home_score", ""),
        ]
        if league_key == "pga":
            for player in list(getattr(game, "players", ()) or ())[:6]:
                search_bits.append(getattr(player, "name", ""))
                search_bits.append(getattr(player, "score", ""))
        safe_search = escape(
            " ".join(
                str(part).strip()
                for part in search_bits
                if str(part).strip()
            ).lower(),
            quote=True,
        )
        if selected_league_filter == "all":
            show_initially = True
        elif selected_league_filter == "selected":
            show_initially = game_id in selected_ids
        elif selected_league_filter == "favorites":
            show_initially = favorite_game
        elif selected_league_filter == "top25":
            show_initially = is_top_25
        else:
            show_initially = league_key == selected_league_filter
        row_style = "" if show_initially else ' style="display:none"'

        game_row_parts.append(f"""
        <div class="game-row-container" draggable="true" data-search="{safe_search}" data-id="{safe_game_id}" data-league="{league_key}" data-top25="{"true" if is_top_25 else "false"}" data-live="{"true" if is_live else "false"}" data-favorite="{"true" if favorite_game else "false"}"{row_style}>
            <label class="game-row">
                <input type="checkbox" name="game" value="{safe_game_id}" {checked}>
                <div class="scoreboard">
                    {scoreboard}
                </div>
            </label>
        </div>
        """)

    game_rows = "".join(game_row_parts)
    if not game_rows:
        game_rows = """
        <div class="empty">
            No games loaded yet.
        </div>
        """

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>GameLine Pro Games</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    {page_styles()}
</head>

<body>
    <div class="page">
        {page_header("games")}

        <form method="POST" action="/save_games" data-autosave="1">
            <div class="card score-card" id="games_card">
                <div class="hint" style="margin-bottom:12px;">
                    Only checked games scroll on the board.
                    New games stay off until you select them.
                    Changes apply as soon as you tap a game.
                </div>
                <input
                    class="search-input"
                    type="text"
                    id="game_search"
                    placeholder="Search games and teams"
                    oninput="filterGames()"
                >
                <div class="sport-pills" id="sport-pills"></div>
                <div class="filter-row">
                    <select id="league_filter" class="select-input league-filter-select" onchange="filterGames()">
                        {league_option("selected", "Selected")}
                        {league_option("favorites", "Favorites")}
                        {league_option("all", "All")}
                        {league_option("mlb", "MLB")}
                        {league_option("nfl", "NFL")}
                        {league_option("cfb", "CFB")}
                        {league_option("top25", "Top 25")}
                        {league_option("soccer", "Soccer")}
                        {league_option("nba", "NBA")}
                        {league_option("nhl", "NHL")}
                        {league_option("pga", "PGA")}
                        {league_option("fantasy", "Fantasy")}
                    </select>

                    <label class="live-filter">
                        <input
                            type="checkbox"
                            id="live_games_only"
                            onchange="filterGames()"
                        >
                        <span>Live Games</span>
                    </label>

                    <button type="button" class="secondary-button" onclick="selectVisibleGames()">All</button>
                    <button type="button" class="secondary-button" onclick="deselectVisibleGames()">None</button>
                </div>

                {game_rows}
                <div class="empty" id="favorites_empty" hidden>
                    No games for your favorite teams yet.
                    Add teams in More → Favorites.
                </div>
            </div>
        </form>

        <form
            method="POST"
            action="/save_cfb_conferences"
            id="cfb_panel"
            class="league-setup-card"
            data-autosave="1"
            hidden
        >
            <div class="card">
                <div class="card-title">College Football Conferences</div>
                <div class="hint" style="margin-bottom: 12px;">
                    Choose All FBS or select one or more conferences.
                    Games from those conferences show up here.
                </div>
                {_cfb_conference_rows(settings)}
            </div>
        </form>

        <form
            method="POST"
            action="/save_soccer_leagues"
            id="soccer_panel"
            class="league-setup-card"
            data-autosave="1"
            hidden
        >
            <div class="card">
                <div class="card-title">Soccer Leagues</div>
                <div class="hint" style="margin-bottom: 12px;">
                    Choose the soccer competitions to load.
                    Premier League, Champions League, and MLS
                    are on by default.
                </div>
                {_soccer_league_rows(settings)}
            </div>
        </form>
    </div>

    <script>
        function getCurrentLeagueFilter() {{
            const filter = document.getElementById("league_filter");
            return filter ? filter.value : "all";
        }}

        (function setupSportPills() {{
            const select = document.getElementById("league_filter");
            const host = document.getElementById("sport-pills");
            if (!select || !host) {{
                return;
            }}
            Array.from(select.options).forEach(function (option) {{
                const pill = document.createElement("button");
                pill.type = "button";
                pill.className = "sport-pill";
                pill.dataset.league = option.value;
                pill.textContent = option.textContent;
                if (option.selected) {{
                    pill.classList.add("active");
                }}
                pill.addEventListener("click", function () {{
                    select.value = option.value;
                    host.querySelectorAll(".sport-pill").forEach(function (item) {{
                        item.classList.toggle(
                            "active",
                            item.dataset.league === option.value
                        );
                    }});
                    filterGames();
                }});
                host.appendChild(pill);
            }});
        }})();

        function filterGames() {{
            const searchInput = document.getElementById("game_search");
            const search = searchInput
                ? searchInput.value.toLowerCase().trim()
                : "";

            const selectedFilter = getCurrentLeagueFilter();

            const liveCheckbox = document.getElementById(
                "live_games_only"
            );

            const liveOnly = liveCheckbox
                ? liveCheckbox.checked
                : false;

            let visibleCount = 0;

            gameRows.forEach(function(row) {{
                const text = row.dataset.search || "";
                const rowLeague = row.dataset.league;
                const rowIsLive = row.dataset.live === "true";

                const checkbox = row.querySelector(
                    'input[type="checkbox"][name="game"]'
                );

                const isSelected = checkbox
                    ? checkbox.checked
                    : false;

                const matchesSearch = text.includes(search);

                let matchesFilter = false;

                if (selectedFilter === "all") {{
                    matchesFilter = true;
                }} else if (selectedFilter === "selected") {{
                    matchesFilter = isSelected;
                }} else if (selectedFilter === "favorites") {{
                    matchesFilter = row.dataset.favorite === "true";
                }} else if (selectedFilter === "top25") {{
                    matchesFilter = (
                        rowLeague === "cfb"
                        && row.dataset.top25 === "true"
                    );
                }} else {{
                    matchesFilter = rowLeague === selectedFilter;
                }}

                const matchesLive = (
                    !liveOnly
                    || rowIsLive
                );

                const showRow = (
                    matchesSearch
                    && matchesFilter
                    && matchesLive
                );
                row.style.display = showRow ? "" : "none";
                if (showRow) {{
                    visibleCount += 1;
                }}
            }});

            const favoritesEmpty = document.getElementById(
                "favorites_empty"
            );
            if (favoritesEmpty) {{
                favoritesEmpty.hidden = !(
                    selectedFilter === "favorites"
                    && visibleCount === 0
                );
            }}

            syncLeaguePanels();
        }}

        function syncLeaguePanels() {{
            const selectedFilter = getCurrentLeagueFilter();
            const cfbPanel = document.getElementById("cfb_panel");
            const soccerPanel = document.getElementById("soccer_panel");

            if (cfbPanel) {{
                cfbPanel.hidden = !(
                    selectedFilter === "cfb"
                    || selectedFilter === "top25"
                );
            }}

            if (soccerPanel) {{
                soccerPanel.hidden = selectedFilter !== "soccer";
            }}
        }}

        function handleGameSelectionChange() {{
            if (getCurrentLeagueFilter() === "selected") {{
                filterGames();
            }}
        }}

        function rowIsVisible(row) {{
            return row.style.display !== "none";
        }}

        function selectVisibleGames() {{
            document.querySelectorAll(
                ".game-row-container"
            ).forEach(function(row) {{
                if (!rowIsVisible(row)) {{
                    return;
                }}

                const checkbox = row.querySelector(
                    'input[type="checkbox"][name="game"]'
                );

                if (checkbox) {{
                    checkbox.checked = true;
                }}
            }});

            filterGames();
            const gamesForm = document.querySelector(
                'form[action="/save_games"]'
            );
            if (window.autosaveForm && gamesForm) {{
                window.autosaveForm(gamesForm, 0);
            }}
        }}

        function deselectVisibleGames() {{
            document.querySelectorAll(
                ".game-row-container"
            ).forEach(function(row) {{
                if (!rowIsVisible(row)) {{
                    return;
                }}

                const checkbox = row.querySelector(
                    'input[type="checkbox"][name="game"]'
                );

                if (checkbox) {{
                    checkbox.checked = false;
                }}
            }});

            filterGames();
            const gamesForm = document.querySelector(
                'form[action="/save_games"]'
            );
            if (window.autosaveForm && gamesForm) {{
                window.autosaveForm(gamesForm, 0);
            }}
        }}

        const container = document.getElementById("games_card");
        const gameRows = container
            ? Array.from(container.querySelectorAll(".game-row-container"))
            : [];
        let dragFrame = 0;
        let dragY = 0;

        container.addEventListener("dragstart", function(e) {{
            const row = e.target.closest(".game-row-container");

            if (row) {{
                container.classList.add("is-reordering");
                row.classList.add("dragging");

                if (e.dataTransfer) {{
                    e.dataTransfer.setData("text/plain", "");
                }}
            }}
        }});

        container.addEventListener("dragend", function(e) {{
            if (dragFrame) {{
                window.cancelAnimationFrame(dragFrame);
                dragFrame = 0;
            }}
            container.classList.remove("is-reordering");
            const row = e.target.closest(".game-row-container");

            if (row) {{
                row.classList.remove("dragging");
            }}
            const gamesForm = document.querySelector(
                'form[action="/save_games"]'
            );
            if (window.autosaveForm && gamesForm) {{
                window.autosaveForm(gamesForm, 0);
            }}
        }});

        function moveDraggedGame() {{
            dragFrame = 0;
            const draggingItem = document.querySelector(".dragging");
            if (!draggingItem) return;

            const siblings = [];
            const nodes = container.querySelectorAll(".game-row-container");
            for (let index = 0; index < nodes.length; index++) {{
                const row = nodes[index];
                if (row !== draggingItem && row.style.display !== "none") {{
                    siblings.push(row);
                }}
            }}
            let low = 0;
            let high = siblings.length;
            while (low < high) {{
                const mid = (low + high) >> 1;
                const box = siblings[mid].getBoundingClientRect();
                if (dragY <= box.top + box.height / 2) {{
                    high = mid;
                }} else {{
                    low = mid + 1;
                }}
            }}
            const nextSibling = siblings[low] || null;
            if (nextSibling) {{
                if (draggingItem.nextElementSibling !== nextSibling) {{
                    container.insertBefore(draggingItem, nextSibling);
                }}
            }} else if (siblings.length) {{
                const last = siblings[siblings.length - 1];
                if (draggingItem.previousElementSibling !== last) {{
                    container.appendChild(draggingItem);
                }}
            }}
        }}

        container.addEventListener("dragover", function(e) {{
            e.preventDefault();
            dragY = e.clientY;
            if (!dragFrame) {{
                dragFrame = window.requestAnimationFrame(moveDraggedGame);
            }}
        }});

        container.addEventListener("change", function (event) {{
            if (event.target && event.target.name === "game") {{
                handleGameSelectionChange();
            }}
        }});

        document.addEventListener("DOMContentLoaded", function () {{
            filterGames();
        }});
    </script>
</body>
</html>
    """

@app.route("/stocks")
@login_required
def stocks_page():
    settings = get_settings()
    hidden = set(settings.get("hidden_games", []))
    stocks_settings = settings.get("stocks", {})
    selected_stock_symbols = parse_symbol_list(
        stocks_settings.get(
            "symbols",
            DEFAULT_STOCK_SYMBOLS,
        )
    )
    stock_names = stocks_settings.get("names", {})
    if not isinstance(stock_names, dict):
        stock_names = {}

    popular_names = dict(POPULAR_SYMBOLS)
    stock_watchlist_rows = ""

    for symbol in selected_stock_symbols:
        name = str(
            stock_names.get(symbol)
            or popular_names.get(symbol)
            or ""
        ).strip()
        safe_symbol = escape(symbol, quote=True)
        safe_name = escape(name, quote=True)
        safe_name_label = escape(name) if name else "Show this quote on the board"
        shown = "" if f"stocks:{symbol}" in hidden else "checked"

        stock_watchlist_rows += f"""
        <div class="stock-watch-row">
            <label class="game-row">
                <input
                    type="checkbox"
                    name="stock_shown"
                    value="{safe_symbol}"
                    {shown}
                >
                <input type="hidden" name="stock_symbols" value="{safe_symbol}">
                <input type="hidden" name="stock_names" value="{safe_name}">
                <div class="game-info">
                    <div class="matchup">{escape(symbol)}</div>
                    <div class="details">{safe_name_label}</div>
                </div>
            </label>
            <button
                type="button"
                class="stock-remove-button"
                aria-label="Remove {safe_symbol}"
            >Remove</button>
        </div>
        """

    stock_empty_display = "none" if selected_stock_symbols else "block"
    saved_message = ""
    if request.args.get("saved") == "1":
        saved_message = '<div class="hint" style="margin-bottom:12px;">Stock list saved.</div>'

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>GameLine Pro Stocks</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    {page_styles()}
</head>
<body>
    <div class="page">
        {page_header("stocks")}
        {saved_message}

        <form method="POST" action="/save_stocks" data-autosave="1">
            <div class="card">
                <div class="card-title">Watchlist</div>
                <div class="hint" style="margin-bottom: 12px;">
                    Search for a company or ticker, then tap it to add it.
                    Checked quotes scroll on the board. You can track
                    up to {MAX_SYMBOLS}.
                </div>

                <div class="stock-search">
                    <input
                        class="search-input"
                        type="search"
                        id="stock_search"
                        placeholder="Search Apple, NVDA, Bitcoin…"
                        autocomplete="off"
                        enterkeyhint="search"
                    >
                    <div
                        id="stock_search_results"
                        class="stock-search-results"
                        hidden
                    ></div>
                </div>

                <div
                    id="stock_watchlist_empty"
                    class="empty"
                    style="display:{stock_empty_display};"
                >
                    No stocks yet. Search to add one.
                </div>

                <div id="stock_watchlist" data-max-symbols="{MAX_SYMBOLS}">
                    {stock_watchlist_rows}
                </div>
            </div>
        </form>
    </div>
</body>
</html>
    """


def _focus_search_blob(game, league_key):
    parts = [
        league_key,
        str(getattr(game, "away", "")),
        str(getattr(game, "home", "")),
        str(get_display_status(game, league_key)),
        str(getattr(game, "broadcast", "") or ""),
        str(getattr(game, "start_time", "") or ""),
        str(getattr(game, "date", "") or ""),
        str(getattr(game, "when", "") or ""),
    ]

    for team in (
        getattr(game, "away", ""),
        getattr(game, "home", ""),
    ):
        definition = get_team_alert(
            team,
            league=league_key,
        )

        if definition is not None:
            parts.append(definition.name)
            parts.append(definition.abbreviation)

        if league_key == "cfb":
            parts.append(str(team).replace(" ", ""))

    if league_key == "cfb":
        for rank in (
            getattr(game, "away_rank", None),
            getattr(game, "home_rank", None),
        ):
            if rank:
                parts.append(str(rank))
                parts.append(f"#{rank}")

    return " ".join(
        str(part).strip()
        for part in parts
        if str(part).strip()
    ).lower()


def _focus_game_rows(
    games,
    league_key,
    selected_ids,
    input_name,
    badge,
    settings,
):
    row_parts = []
    league_games = [
        game
        for game in games
        if get_game_league(game)[0] == league_key
    ]
    league_games.sort(
        key=lambda item: 0 if is_favorite_game(item, settings) else 1
    )

    for game in league_games:
        game_identifier = get_game_id(game)
        checked = (
            "checked"
            if game_identifier in selected_ids
            else ""
        )
        safe_id = escape(game_identifier, quote=True)
        safe_status = escape(
            str(get_display_status(game, league_key))
        )
        away_score = escape(
            str(getattr(game, "away_score", 0))
        )
        home_score = escape(
            str(getattr(game, "home_score", 0))
        )
        safe_search = escape(
            _focus_search_blob(game, league_key),
            quote=True,
        )
        away_mark = web_team_mark(
            league_key,
            getattr(game, "away", ""),
            settings,
            getattr(game, "away_rank", None),
        )
        home_mark = web_team_mark(
            league_key,
            getattr(game, "home", ""),
            settings,
            getattr(game, "home_rank", None),
        )
        star_html = favorite_star_html(
            is_favorite_game(game, settings)
        )

        row_parts.append(f"""
        <label
            class="game-row focus-game-row"
            data-league="{league_key}"
            data-search="{safe_search}"
        >
            <input
                type="checkbox"
                name="{input_name}"
                value="{safe_id}"
                {checked}
            >
            <div class="scoreboard">
                <div class="score-meta">
                    <span class="score-league-wrap">
                        <span class="score-league">{badge}</span>
                        {star_html}
                    </span>
                    <span class="score-status">{safe_status}</span>
                </div>
                <div class="score-team">
                    {away_mark}
                    <span class="score-pts">{away_score}</span>
                </div>
                <div class="score-team">
                    {home_mark}
                    <span class="score-pts">{home_score}</span>
                </div>
            </div>
        </label>
        """)

    return "".join(row_parts)


def _focus_league_key(value) -> str:
    league = str(value or "").strip().lower()
    if league not in {key for key, _label in FOCUS_LEAGUES}:
        return "nfl"
    return league


@app.route("/focus")
@login_required
def focus_page():
    settings = get_settings()

    focus_settings = settings.get(
        "focus_mode",
        {},
    )

    if not isinstance(
        focus_settings,
        dict,
    ):
        focus_settings = {}

    focus_enabled = bool(
        focus_settings.get(
            "enabled",
            False,
        )
    )

    league_key = _focus_league_key(request.values.get("league"))
    league_label = dict(FOCUS_LEAGUES)[league_key]
    selected_ids = {
        str(value)
        for value in focus_settings.get(f"{league_key}_game_ids", [])
    }

    try:
        rotation_seconds = int(
            focus_settings.get(
                "rotation_seconds",
                30,
            )
        )
    except (TypeError, ValueError):
        rotation_seconds = 30

    rotation_seconds = max(
        5,
        min(
            300,
            rotation_seconds,
        ),
    )

    game_badge = {
        "nfl": "NFL",
        "cfb": "CFB",
        "mlb": "MLB",
        "nba": "NBA",
    }[league_key]
    game_rows = _focus_game_rows(
        latest_games,
        league_key,
        selected_ids,
        f"focus_{league_key}_game",
        game_badge,
        settings,
    )

    if not game_rows:
        game_rows = f"""
        <div class="empty">
            No {escape(league_label)} games loaded yet.
        </div>
        """

    league_options = []
    for key, label in FOCUS_LEAGUES:
        picked = " selected" if key == league_key else ""
        league_options.append(
            f'<option value="{escape(key)}"{picked}>{escape(label)}</option>'
        )

    enabled_checked = (
        "checked"
        if focus_enabled
        else ""
    )

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>GameLine Pro Focus Mode</title>
    <meta
        name="viewport"
        content="
            width=device-width,
            initial-scale=1,
            viewport-fit=cover
        "
    >
    {page_styles()}
</head>

<body>
    <div class="page">
        {page_header("focus")}

        <form
            method="POST"
            action="/save_focus"
            data-autosave="1"
        >
            <div class="card">
                <div class="hint"
                     style="margin-bottom: 14px;">
                    Replace the normal ticker with a
                    full-screen NFL, CFB, MLB, or NBA scoreboard.
                </div>

                <label class="game-row">
                    <input
                        type="checkbox"
                        name="focus_enabled"
                        {enabled_checked}
                    >

                    <div class="game-info">
                        <div class="matchup">
                            Enable Focus Mode
                        </div>

                        <div class="details">
                            Alerts will still temporarily
                            override Focus Mode.
                        </div>
                    </div>
                </label>
            </div>

            <div class="card">
                <div class="card-title">
                    Rotation
                </div>

                <div class="control">
                    <div class="control-top">
                        <label
                            for="focus_rotation_seconds"
                        >
                            Switch Games Every
                        </label>

                        <input
                            class="number-input"
                            type="number"
                            id="focus_rotation_seconds"
                            name="focus_rotation_seconds"
                            min="5"
                            max="300"
                            step="5"
                            value="{rotation_seconds}"
                        >
                    </div>

                    <input
                        type="range"
                        id="focus_rotation_slider"
                        min="5"
                        max="300"
                        step="5"
                        value="{rotation_seconds}"
                        oninput="
                            focus_rotation_seconds.value
                            = this.value
                        "
                    >

                    <div class="hint">
                        Only used when more than one
                        game is selected.
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-title">League</div>
                <div class="hint" style="margin-bottom: 14px;">
                    Pick a league, then choose the games
                    to pin on the full-screen board.
                </div>
                <select
                    class="select-input favorite-league-select"
                    id="focus_league"
                    onchange="window.location.href='/focus?league=' + encodeURIComponent(this.value)"
                >
                    {''.join(league_options)}
                </select>
                <input type="hidden" name="league" value="{escape(league_key, quote=True)}">
            </div>

            <div class="card">
                <div class="card-title">{escape(league_label)} Games</div>
                <div class="hint" style="margin-bottom: 14px;">
                    {escape(FOCUS_LEAGUE_HINTS[league_key])}
                </div>
                <input
                    class="search-input favorite-team-search"
                    type="search"
                    id="focus_game_search"
                    placeholder="Search {escape(league_label)} games..."
                    autocomplete="off"
                    enterkeyhint="search"
                    spellcheck="false"
                    oninput="filterFocusGames()"
                >
                <div class="favorite-select-actions">
                    <button
                        class="secondary-button"
                        type="button"
                        onclick="setFocusGames(true)"
                    >
                        Select All
                    </button>
                    <button
                        class="secondary-button"
                        type="button"
                        onclick="setFocusGames(false)"
                    >
                        Clear
                    </button>
                </div>
                <div id="focus_game_list">
                    {game_rows}
                </div>
                <div
                    id="focus_no_results"
                    class="empty"
                    hidden
                >
                    No matching games.
                </div>
            </div>
        </form>
    </div>

    <script>
        const rotationNumber =
            document.getElementById(
                "focus_rotation_seconds"
            );

        const rotationSlider =
            document.getElementById(
                "focus_rotation_slider"
            );

        rotationNumber.addEventListener(
            "input",
            function() {{
                rotationSlider.value =
                    rotationNumber.value;
            }}
        );

        function setFocusGames(checked) {{
            document.querySelectorAll(
                '#focus_game_list input[type="checkbox"]'
            ).forEach(function (input) {{
                input.checked = checked;
            }});
            var form = document.querySelector(
                'form[action="/save_focus"]'
            );
            if (window.autosaveForm && form) {{
                window.autosaveForm(form, 0);
            }}
        }}

        function filterFocusGames() {{
            const searchInput = document.getElementById(
                "focus_game_search"
            );
            const search = searchInput
                ? searchInput.value.toLowerCase().trim()
                : "";
            const empty = document.getElementById(
                "focus_no_results"
            );
            let visibleCount = 0;
            const rows = document.querySelectorAll(
                ".focus-game-row"
            );

            rows.forEach(function(row) {{
                const haystack = row.getAttribute("data-search") || "";
                const match = !search || haystack.indexOf(search) !== -1;
                row.style.display = match ? "" : "none";
                if (match) {{
                    visibleCount += 1;
                }}
            }});

            if (empty) {{
                empty.hidden = !(
                    search
                    && rows.length > 0
                    && visibleCount === 0
                );
            }}
        }}

        const focusSearch = document.getElementById(
            "focus_game_search"
        );

        if (focusSearch) {{
            focusSearch.addEventListener(
                "input",
                filterFocusGames
            );
            focusSearch.addEventListener(
                "keydown",
                function(event) {{
                    if (event.key === "Enter") {{
                        event.preventDefault();
                    }}
                }}
            );
            filterFocusGames();
        }}
    </script>
</body>
</html>
    """

@app.route(
    "/save_focus",
    methods=["POST"],
)
@login_required
def save_focus():
    posted_league = str(request.form.get("league", "")).strip().lower()
    if posted_league not in {key for key, _label in FOCUS_LEAGUES}:
        return autosave_response("/focus")

    league_key = _focus_league_key(posted_league)
    valid_ids = {
        get_game_id(game)
        for game in latest_games
        if get_game_league(game)[0] == league_key
    }
    selected_ids = [
        game_identifier
        for game_identifier in request.form.getlist(f"focus_{league_key}_game")
        if game_identifier in valid_ids
    ]

    try:
        rotation_seconds = int(
            request.form.get(
                "focus_rotation_seconds",
                30,
            )
        )
    except (TypeError, ValueError):
        rotation_seconds = 30

    rotation_seconds = max(
        5,
        min(
            300,
            rotation_seconds,
        ),
    )

    focus_enabled = (
        request.form.get(
            "focus_enabled"
        )
        == "on"
    )

    update_settings({
        "focus_mode": {
            "enabled": focus_enabled,
            "rotation_seconds": rotation_seconds,
            f"{league_key}_game_ids": selected_ids,
        },
    })

    return autosave_response(url_for("focus_page", league=league_key))

@app.route("/alerts", methods=["GET", "POST"])
@login_required
def alerts_page():
    settings = get_settings()
    alerts = settings.get("alerts", {})

    requested_league = (
        request.values.get(
            "league",
            "nfl",
        )
        .strip()
        .lower()
    )

    if requested_league == "players":
        return redirect("/players")

    if requested_league not in {
        "nfl",
        "cfb",
        "mlb",
    }:
        requested_league = "nfl"

    league_label = {
        "nfl": "NFL",
        "cfb": "CFB",
        "mlb": "MLB",
    }[requested_league]

    if requested_league == "nfl":
        available_teams = sorted(
            NFL_TEAM_ALERTS.keys()
        )
    elif requested_league == "mlb":
        available_teams = sorted(
            MLB_TEAM_NAMES.keys()
        )
    else:
        available_teams = (
            get_teams_with_logos(
                "cfb"
            )
        )

    if request.method == "POST":
        def form_float(
            name: str,
            default: float,
            minimum: float,
            maximum: float,
        ) -> float:
            try:
                value = float(
                    request.form.get(name, default)
                )
            except (TypeError, ValueError):
                value = default

            return max(minimum, min(maximum, value))

        def form_int(
            name: str,
            default: int,
            minimum: int,
            maximum: int,
        ) -> int:
            try:
                value = int(
                    request.form.get(name, default)
                )
            except (TypeError, ValueError):
                value = default

            return max(minimum, min(maximum, value))

        updated_alerts = dict(alerts)
        updated_alerts.update({
            "enabled": (
                request.form.get("enabled") == "on"
            ),
            "poll_interval_seconds": form_float(
                "poll_interval_seconds",
                3.0,
                2.0,
                30.0,
            ),
            "confirmations_required": form_int(
                "confirmations_required",
                2,
                1,
                5,
            ),
            "cooldown_seconds": form_float(
                "cooldown_seconds",
                20.0,
                0.0,
                300.0,
            ),
            "details_frame_seconds": form_float(
                "details_frame_seconds",
                5.0,
                1.0,
                15.0,
            ),
            "chant_enabled": (
                request.form.get("chant_enabled") == "on"
            ),
        })

        selected_teams = [
            abbreviation
            for abbreviation
            in available_teams
            if request.form.get(
                f"alert_team:{abbreviation}"
            ) == "on"
        ]

        teams_by_league = alerts.get(
            "teams",
            {},
        )

        if not isinstance(
            teams_by_league,
            dict,
        ):
            teams_by_league = {}

        if "nfl" not in teams_by_league:
            teams_by_league["nfl"] = [
                str(team).upper()
                for team in alerts.get(
                    "possession_teams",
                    [],
                )
            ]

        teams_by_league[
            requested_league
        ] = sorted(
            selected_teams
        )
        updated_alerts["teams"] = (
            teams_by_league
        )

        if requested_league == "mlb":
            updated_alerts["homerun_enabled"] = (
                request.form.get("homerun_enabled") == "on"
            )
            updated_alerts["mlb_win_enabled"] = (
                request.form.get("mlb_win_enabled") == "on"
            )
            updated_alerts["close_game_enabled"] = (
                request.form.get("close_game_enabled") == "on"
            )
        else:
            updated_alerts["possession_enabled"] = (
                request.form.get("possession_enabled") == "on"
            )
            updated_alerts["redzone_enabled"] = (
                request.form.get("redzone_enabled") == "on"
            )
            updated_alerts["touchdown_enabled"] = (
                request.form.get("touchdown_enabled") == "on"
            )
            updated_alerts["field_goal_enabled"] = (
                request.form.get("field_goal_enabled") == "on"
            )

        update_settings({
            "alerts": updated_alerts,
        })

        return autosave_response(
            url_for(
                "alerts_page",
                league=requested_league,
            )
        )

    def checked(name: str, default: bool) -> str:
        return (
            "checked"
            if bool(alerts.get(name, default))
            else ""
        )

    teams_by_league = alerts.get(
        "teams",
        {},
    )

    if not isinstance(
        teams_by_league,
        dict,
    ):
        teams_by_league = {}

    if "nfl" not in teams_by_league:
        teams_by_league["nfl"] = [
            str(team).upper()
            for team in alerts.get(
                "possession_teams",
                [],
            )
        ]

    selected_teams = {
        str(team).upper()
        for team in teams_by_league.get(
            requested_league,
            [],
        )
    }

    team_rows = ""

    for abbreviation in available_teams:
        abbreviation = str(
            abbreviation
        ).upper()

        definition = get_team_alert(
            abbreviation,
            league=requested_league,
        )

        if definition is None:
            continue

        team_checked = (
            "checked"
            if abbreviation in selected_teams
            else ""
        )

        safe_abbreviation = escape(
            abbreviation,
            quote=True,
        )

        safe_name = escape(
            definition.name
        )

        safe_chant = escape(
            " → ".join(
                definition.chant
            )
        )

        team_rows += f"""
        <div
            class="alert-team-row"
            data-team-search="
                {safe_name.lower()}
                {safe_abbreviation.lower()}
            "
        >
            <label
                class="
                    game-row
                    alert-team-label
                "
            >
                <input
                    type="checkbox"
                    name="alert_team:{safe_abbreviation}"
                    {team_checked}
                >

                {web_team_mark(requested_league, abbreviation, settings, accent=False)}

                <div class="game-info">
                    <div class="matchup">
                        {safe_name}
                    </div>

                    <div class="details">
                        {safe_abbreviation}
                        ·
                        {safe_chant}
                    </div>
                </div>
            </label>
        </div>
        """

    if requested_league == "mlb":
        alert_type_rows = f"""
                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="homerun_enabled"
                            {checked("homerun_enabled", True)}
                        >
                        <div class="alert-icon">💣</div>
                        <div class="alert-row-text">
                            <div class="alert-row-title">Home Run</div>
                            <div class="alert-row-description">
                                Take over the board when a
                                selected team hits a home run.
                            </div>
                        </div>
                    </label>
                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="mlb_win_enabled"
                            {checked("mlb_win_enabled", True)}
                        >
                        <div class="alert-icon">🏆</div>
                        <div class="alert-row-text">
                            <div class="alert-row-title">Win</div>
                            <div class="alert-row-description">
                                Take over the board when a
                                selected team wins.
                            </div>
                        </div>
                    </label>
                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="close_game_enabled"
                            {checked("close_game_enabled", True)}
                        >
                        <div class="alert-icon">🔥</div>
                        <div class="alert-row-text">
                            <div class="alert-row-title">Close Game</div>
                            <div class="alert-row-description">
                                Alert once when a selected team's
                                game is tied or within one run
                                from the 7th inning on.
                            </div>
                        </div>
                    </label>
        """
    else:
        alert_type_rows = f"""
                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="possession_enabled"
                            {checked("possession_enabled", True)}
                        >
                        <div class="alert-icon">🏈</div>
                        <div class="alert-row-text">
                            <div class="alert-row-title">Possession</div>
                            <div class="alert-row-description">
                                Show an alert when a selected
                                team gains possession.
                            </div>
                        </div>
                    </label>
                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="redzone_enabled"
                            {checked("redzone_enabled", True)}
                        >
                        <div class="alert-icon">🔴</div>
                        <div class="alert-row-text">
                            <div class="alert-row-title">Red Zone</div>
                            <div class="alert-row-description">
                                Show an alert when a selected
                                team reaches the opponent's 20.
                            </div>
                        </div>
                    </label>
                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="touchdown_enabled"
                            {checked("touchdown_enabled", True)}
                        >
                        <div class="alert-icon">🙌</div>
                        <div class="alert-row-text">
                            <div class="alert-row-title">Touchdown</div>
                            <div class="alert-row-description">
                                Show an alert when a selected
                                team scores a touchdown.
                            </div>
                        </div>
                    </label>
                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="field_goal_enabled"
                            {checked("field_goal_enabled", True)}
                        >
                        <div class="alert-icon">🥅</div>
                        <div class="alert-row-text">
                            <div class="alert-row-title">Field Goal</div>
                            <div class="alert-row-description">
                                Show an alert when a selected
                                team makes a field goal.
                            </div>
                        </div>
                    </label>
        """

    saved_message = ""

    if request.args.get("saved") == "1":
        saved_message = """
        <div class="alert-success">
            Alert settings saved.
        </div>
        """

    poll_interval = escape(str(
        alerts.get(
            "poll_interval_seconds",
            3.0,
        )
    ))

    confirmations = escape(str(
        alerts.get(
            "confirmations_required",
            2,
        )
    ))

    cooldown = escape(str(
        alerts.get(
            "cooldown_seconds",
            20.0,
        )
    ))

    details_seconds = escape(str(
        alerts.get(
            "details_frame_seconds",
            5.0,
        )
    ))

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>GameLine Pro Alerts</title>

        <meta
            name="viewport"
            content="
                width=device-width,
                initial-scale=1,
                viewport-fit=cover
            "
        >

        {page_styles()}

        <style>
            .alert-success {{
                background: rgba(
                    48,
                    209,
                    88,
                    0.14
                );
                border: 1px solid rgba(
                    48,
                    209,
                    88,
                    0.45
                );
                color: #7ee893;
                border-radius: 14px;
                padding: 14px 16px;
                margin-bottom: 16px;
                font-size: 15px;
                font-weight: 700;
            }}

            .alert-master-row,
            .alert-type-row {{
                display: flex;
                align-items: center;
                gap: 14px;
                min-height: 70px;
                padding: 14px 0;
                border-bottom:
                    1px solid #2c2c35;
                cursor: pointer;
                -webkit-tap-highlight-color:
                    transparent;
            }}

            .alert-master-row:last-child,
            .alert-type-row:last-child {{
                border-bottom: 0;
            }}

            .alert-master-row input,
            .alert-type-row input,
            .alert-team-label input {{
                flex: 0 0 auto;
                width: 24px;
                height: 24px;
                accent-color: #0a84ff;
            }}

            .alert-row-text {{
                flex: 1;
                min-width: 0;
            }}

            .alert-row-title {{
                font-size: 17px;
                line-height: 1.2;
                font-weight: 750;
            }}

            .alert-row-description {{
                color: #aaa;
                font-size: 13px;
                line-height: 1.4;
                margin-top: 4px;
            }}

            .alert-icon {{
                display: flex;
                align-items: center;
                justify-content: center;
                flex: 0 0 auto;
                width: 42px;
                height: 42px;
                border-radius: 13px;
                background: #24242c;
                font-size: 21px;
            }}

            .alert-select-actions {{
                display: grid;
                grid-template-columns:
                    1fr 1fr;
                gap: 10px;
                margin-bottom: 12px;
            }}

            .alert-team-search {{
                margin-bottom: 12px;
            }}

            .alert-team-row {{
                border-bottom:
                    1px solid #2c2c35;
                padding-bottom: 12px;
                margin-bottom: 2px;
            }}

            .alert-team-row:last-child {{
                border-bottom: 0;
                padding-bottom: 0;
            }}

            .alert-team-label {{
                border-bottom: 0;
                padding: 14px 0 10px;
            }}

            .team-color {{
                flex: 0 0 auto;
                width: 38px;
                height: 38px;
                border: 3px solid;
                border-radius: 12px;
            }}

            .alert-control {{
                margin-bottom: 22px;
            }}

            .alert-control:last-child {{
                margin-bottom: 0;
            }}

            .alert-control-heading {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 14px;
                margin-bottom: 7px;
            }}

            .alert-control-title {{
                font-size: 16px;
                font-weight: 700;
            }}

            .alert-control-input {{
                width: 96px;
                min-height: 44px;
                padding: 9px;
                border-radius: 11px;
                border: 1px solid #444;
                background: #0f0f14;
                color: white;
                font-size: 16px;
                text-align: center;
            }}

            .alert-control-description {{
                color: #888;
                font-size: 13px;
                line-height: 1.4;
            }}

            .alerts-save {{
                position: sticky;
                bottom: 12px;
                z-index: 10;
                box-shadow:
                    0 10px 28px
                    rgba(0, 0, 0, 0.55);
                margin-bottom:
                    max(
                        8px,
                        env(safe-area-inset-bottom)
                    );
            }}

        </style>
    </head>

    <body>
        <div class="page">
            {page_header("alerts")}
            {saved_message}

            <form method="POST" data-autosave="1">
                <div class="card">
                    <div class="card-title">
                        League
                    </div>

                    <div
                        style="
                            margin-bottom: 16px;
                        "
                    >
                        <select
                            class="select-input"
                            id="alert_league"
                            onchange="
                                window.location.href =
                                    '/alerts?league='
                                    + encodeURIComponent(
                                        this.value
                                    )
                            "
                        >
                            <option
                                value="nfl"
                                {
                                    "selected"
                                    if requested_league == "nfl"
                                    else ""
                                }
                            >
                                NFL
                            </option>

                            <option
                                value="cfb"
                                {
                                    "selected"
                                    if requested_league == "cfb"
                                    else ""
                                }
                            >
                                CFB
                            </option>

                            <option
                                value="mlb"
                                {
                                    "selected"
                                    if requested_league == "mlb"
                                    else ""
                                }
                            >
                                MLB
                            </option>
                        </select>
                    </div>

                    <input
                        type="hidden"
                        name="league"
                        value="{requested_league}"
                    >

                    <label class="alert-master-row">
                        <input
                            type="checkbox"
                            name="enabled"
                            {checked("enabled", False)}
                        >

                        <div class="alert-icon">
                            🔔
                        </div>

                        <div class="alert-row-text">
                            <div class="alert-row-title">
                                Enable alerts
                            </div>

                            <div
                                class="
                                    alert-row-description
                                "
                            >
                                Allow {league_label} events to
                                temporarily take over
                                the scoreboard.
                            </div>
                        </div>
                    </label>
                </div>

                <div class="card">
                    <div class="card-title">
                        Alert Types
                    </div>

                    {alert_type_rows}
                </div>

                <div class="card">
                    <div class="card-title">
                        Display
                    </div>

                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="chant_enabled"
                            {checked("chant_enabled", False)}
                        >
                        <div class="alert-icon">📣</div>
                        <div class="alert-row-text">
                            <div class="alert-row-title">Team chant</div>
                            <div class="alert-row-description">
                                Flash the team chant, then
                                show the play card.
                            </div>
                        </div>
                    </label>

                    <div class="alert-control" style="margin-top: 12px;">
                        <div class="alert-control-heading">
                            <label
                                class="alert-control-title"
                                for="details_frame_seconds"
                            >
                                Display duration
                            </label>

                            <input
                                class="alert-control-input"
                                id="details_frame_seconds"
                                name="details_frame_seconds"
                                type="number"
                                min="1"
                                max="15"
                                step="0.5"
                                value="{details_seconds}"
                            >
                        </div>

                        <div class="alert-control-description">
                            Seconds the play card stays
                            on the scoreboard.
                        </div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        Teams
                    </div>

                    <input
                        class="
                            search-input
                            alert-team-search
                        "
                        id="alert_team_search"
                        type="search"
                        placeholder="Search {league_label} teams..."
                        oninput="filterAlertTeams()"
                    >

                    <div class="alert-select-actions">
                        <button
                            class="secondary-button"
                            type="button"
                            onclick="
                                setAllAlertTeams(true)
                            "
                        >
                            Select All
                        </button>

                        <button
                            class="secondary-button"
                            type="button"
                            onclick="
                                setAllAlertTeams(false)
                            "
                        >
                            Select None
                        </button>
                    </div>

                    <div id="alert_team_list">
                        {team_rows}
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        Timing
                    </div>

                    <div class="alert-control">
                        <div
                            class="
                                alert-control-heading
                            "
                        >
                            <label
                                class="
                                    alert-control-title
                                "
                                for="
                                    poll_interval_seconds
                                "
                            >
                                Polling interval
                            </label>

                            <input
                                class="
                                    alert-control-input
                                "
                                id="
                                    poll_interval_seconds
                                "
                                name="
                                    poll_interval_seconds
                                "
                                type="number"
                                min="2"
                                max="30"
                                step="0.5"
                                value="{poll_interval}"
                            >
                        </div>

                        <div
                            class="
                                alert-control-description
                            "
                        >
                            Seconds between checks for
                            new NFL events.
                        </div>
                    </div>

                    <div class="alert-control">
                        <div
                            class="
                                alert-control-heading
                            "
                        >
                            <label
                                class="
                                    alert-control-title
                                "
                                for="
                                    confirmations_required
                                "
                            >
                                Confirmations
                            </label>

                            <input
                                class="
                                    alert-control-input
                                "
                                id="
                                    confirmations_required
                                "
                                name="
                                    confirmations_required
                                "
                                type="number"
                                min="1"
                                max="5"
                                step="1"
                                value="{confirmations}"
                            >
                        </div>

                        <div
                            class="
                                alert-control-description
                            "
                        >
                            Matching readings required
                            before a possession change
                            is confirmed.
                        </div>
                    </div>

                    <div class="alert-control">
                        <div
                            class="
                                alert-control-heading
                            "
                        >
                            <label
                                class="
                                    alert-control-title
                                "
                                for="
                                    cooldown_seconds
                                "
                            >
                                Duplicate cooldown
                            </label>

                            <input
                                class="
                                    alert-control-input
                                "
                                id="
                                    cooldown_seconds
                                "
                                name="
                                    cooldown_seconds
                                "
                                type="number"
                                min="0"
                                max="300"
                                step="1"
                                value="{cooldown}"
                            >
                        </div>

                        <div
                            class="
                                alert-control-description
                            "
                        >
                            Prevent duplicate API data
                            from repeatedly triggering
                            the same alert.
                        </div>
                    </div>
                </div>
            </form>
        </div>

        <script>
            function setAllAlertTeams(checked) {{
                document.querySelectorAll(
                    'input[name^="alert_team:"]'
                ).forEach(function (input) {{
                    input.checked = checked;
                }});
                const form = document.querySelector(
                    "form[data-autosave]"
                );
                if (window.autosaveForm && form) {{
                    window.autosaveForm(form, 0);
                }}
            }}

            function filterAlertTeams() {{
                const input = document.getElementById(
                    "alert_team_search"
                );

                const search = input
                    ? input.value
                        .toLowerCase()
                        .trim()
                    : "";

                document.querySelectorAll(
                    ".alert-team-row"
                ).forEach(function (row) {{
                    const teamText =
                        row.dataset.teamSearch || "";

                    row.style.display =
                        teamText.includes(search)
                            ? ""
                            : "none";
                }});
            }}
        </script>
    </body>
    </html>
    """

@app.route("/players/preview", methods=["POST"])
def preview_player_alert():
    is_local = request.remote_addr in {
        "127.0.0.1",
        "::1",
    }

    if not is_local and current_user() is None:
        return redirect("/login")

    possession_alert_manager.show_player_preview()

    if is_local and request.args.get("plain") == "1":
        return "ok\n", 200, {
            "Content-Type": "text/plain"
        }

    return redirect("/players?preview=1")


@app.route("/players", methods=["GET", "POST"])
@login_required
def players_page():
    settings = get_settings()
    alerts = settings.get("alerts", {})

    if request.method == "POST":
        players_by_league = alerts.get("players", {})

        if not isinstance(players_by_league, dict):
            players_by_league = {}

        players_by_league = dict(players_by_league)
        players_by_league["nfl"] = hydrate_watched_players(
            request.form.getlist("player_ids"),
            previous=players_by_league.get("nfl"),
        )

        updated_alerts = dict(alerts)
        updated_alerts["enabled"] = (
            request.form.get("enabled") == "on"
        )
        updated_alerts["player_alerts_enabled"] = (
            request.form.get("player_alerts_enabled") == "on"
        )
        updated_alerts["chant_enabled"] = (
            request.form.get("chant_enabled") == "on"
        )
        try:
            display_seconds = float(
                request.form.get("details_frame_seconds", 5.0)
            )
        except (TypeError, ValueError):
            display_seconds = 5.0
        updated_alerts["details_frame_seconds"] = max(
            1.0,
            min(15.0, display_seconds),
        )
        updated_alerts["players"] = players_by_league

        update_settings({
            "alerts": updated_alerts,
        })

        return autosave_response("/players")

    def checked(name: str, default: bool) -> str:
        return (
            "checked"
            if bool(alerts.get(name, default))
            else ""
        )

    saved_message = ""

    if request.args.get("saved") == "1":
        saved_message = """
        <div class="alert-success">
            Player alerts saved.
        </div>
        """
    elif request.args.get("preview") == "1":
        saved_message = """
        <div class="alert-success">
            Preview is on the scoreboard now.
        </div>
        """

    player_watch_rows = ""
    watched_players = watched_nfl_players(alerts)

    for player in watched_players:
        player_id = escape(
            str(player.get("id") or ""),
            quote=True,
        )
        player_name = escape(str(player.get("name") or ""))
        player_team = escape(str(player.get("team") or ""))
        player_position = escape(
            str(player.get("position") or "")
        )
        player_watch_rows += f"""
                    <div
                        class="player-watch-row"
                        data-player-id="{player_id}"
                    >
                        <input
                            type="hidden"
                            name="player_ids"
                            value="{player_id}"
                        >
                        <div class="player-pos">
                            {player_position}
                        </div>
                        <div class="game-info">
                            <div class="matchup">
                                {player_name}
                            </div>
                            <div class="details">
                                {player_team} · {player_position}
                            </div>
                        </div>
                        <button
                            class="stock-remove-button"
                            type="button"
                            data-remove-player="{player_id}"
                        >
                            Remove
                        </button>
                    </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>GameLine Pro Players</title>

        <meta
            name="viewport"
            content="
                width=device-width,
                initial-scale=1,
                viewport-fit=cover
            "
        >

        {page_styles()}

        <style>
            .alert-success {{
                background: rgba(48, 209, 88, 0.14);
                border: 1px solid rgba(48, 209, 88, 0.45);
                color: #7ee893;
                border-radius: 14px;
                padding: 14px 16px;
                margin-bottom: 16px;
                font-size: 15px;
                font-weight: 700;
            }}

            .alert-master-row,
            .alert-type-row {{
                display: flex;
                align-items: center;
                gap: 14px;
                min-height: 70px;
                padding: 14px 0;
                border-bottom: 1px solid #2c2c35;
                cursor: pointer;
                -webkit-tap-highlight-color: transparent;
            }}

            .alert-master-row:last-child,
            .alert-type-row:last-child {{
                border-bottom: 0;
            }}

            .alert-master-row input,
            .alert-type-row input {{
                flex: 0 0 auto;
                width: 24px;
                height: 24px;
                accent-color: #0a84ff;
            }}

            .alert-row-text {{
                flex: 1;
                min-width: 0;
            }}

            .alert-row-title {{
                font-size: 17px;
                line-height: 1.2;
                font-weight: 750;
            }}

            .alert-row-description {{
                color: #aaa;
                font-size: 13px;
                line-height: 1.4;
                margin-top: 4px;
            }}

            .alert-icon {{
                display: flex;
                align-items: center;
                justify-content: center;
                flex: 0 0 auto;
                width: 42px;
                height: 42px;
                border-radius: 13px;
                background: #24242c;
                font-size: 21px;
            }}

            .alert-control {{
                margin-top: 12px;
            }}

            .alert-control-heading {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 14px;
                margin-bottom: 7px;
            }}

            .alert-control-title {{
                font-size: 16px;
                font-weight: 700;
            }}

            .alert-control-input {{
                width: 96px;
                min-height: 44px;
                padding: 9px;
                border-radius: 11px;
                border: 1px solid #444;
                background: #0f0f14;
                color: white;
                font-size: 16px;
                text-align: center;
            }}

            .alert-control-description {{
                color: #888;
                font-size: 13px;
                line-height: 1.4;
            }}

            .alerts-save {{
                position: sticky;
                bottom: 12px;
                z-index: 10;
                box-shadow: 0 10px 28px rgba(0, 0, 0, 0.55);
                margin-bottom: max(8px, env(safe-area-inset-bottom));
            }}

            .player-help {{
                color: #8b909b;
                font-size: 13px;
                line-height: 1.45;
                margin: -4px 0 14px;
            }}

            .player-pos {{
                display: flex;
                align-items: center;
                justify-content: center;
                flex: 0 0 auto;
                width: 42px;
                height: 42px;
                border-radius: 12px;
                background: #24242c;
                color: #f2f4f7;
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 0.04em;
            }}

            .player-watch-row,
            .fantasy-player-row {{
                display: flex;
                align-items: center;
                gap: 12px;
                padding: 12px 0;
                border-bottom: 1px solid #2c2c35;
            }}

            .player-watch-row:last-child,
            .fantasy-player-row:last-child {{
                border-bottom: 0;
            }}

            .player-watch-row .game-info,
            .fantasy-player-row .game-info {{
                flex: 1;
                min-width: 0;
            }}

            .fantasy-league {{
                margin-bottom: 18px;
            }}

            .fantasy-league:last-child {{
                margin-bottom: 0;
            }}

            .fantasy-league-name {{
                font-size: 13px;
                font-weight: 800;
                letter-spacing: 0.04em;
                text-transform: uppercase;
                color: #8b909b;
                margin-bottom: 8px;
            }}

            .fantasy-team-card {{
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 14px;
                background: #101117;
                margin-bottom: 10px;
                overflow: hidden;
            }}

            .fantasy-team-card summary {{
                list-style: none;
                cursor: pointer;
                padding: 14px 16px;
                font-weight: 750;
            }}

            .fantasy-team-card summary::-webkit-details-marker {{
                display: none;
            }}

            .fantasy-team-body {{
                padding: 0 16px 8px;
                border-top: 1px solid rgba(255, 255, 255, 0.06);
            }}
        </style>
    </head>
    <body>
        <div class="page">
            {page_header("players")}
            {saved_message}

            <form method="POST" data-autosave="1">
                <div class="card">
                    <div class="card-title">
                        Watch
                    </div>

                    <label class="alert-master-row">
                        <input
                            type="checkbox"
                            name="enabled"
                            {checked("enabled", False)}
                        >
                        <div class="alert-icon">🔔</div>
                        <div class="alert-row-text">
                            <div class="alert-row-title">
                                Enable alerts
                            </div>
                            <div class="alert-row-description">
                                Allow watched-player big plays
                                to take over the scoreboard.
                            </div>
                        </div>
                    </label>

                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="player_alerts_enabled"
                            {checked("player_alerts_enabled", True)}
                        >
                        <div class="alert-icon">⚡</div>
                        <div class="alert-row-text">
                            <div class="alert-row-title">Big Plays</div>
                            <div class="alert-row-description">
                                Touchdowns, picks, sacks,
                                fumbles, and 20+ yard gains.
                            </div>
                        </div>
                    </label>
                </div>

                <div class="card">
                    <div class="card-title">
                        Display
                    </div>

                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="chant_enabled"
                            {checked("chant_enabled", False)}
                        >
                        <div class="alert-icon">📣</div>
                        <div class="alert-row-text">
                            <div class="alert-row-title">Team chant</div>
                            <div class="alert-row-description">
                                Flash the player's team chant,
                                then show the play card.
                            </div>
                        </div>
                    </label>

                    <div class="alert-control">
                        <div class="alert-control-heading">
                            <label
                                class="alert-control-title"
                                for="details_frame_seconds"
                            >
                                Display duration
                            </label>
                            <input
                                class="alert-control-input"
                                id="details_frame_seconds"
                                name="details_frame_seconds"
                                type="number"
                                min="1"
                                max="15"
                                step="0.5"
                                value="{escape(str(alerts.get('details_frame_seconds', 5.0)))}"
                            >
                        </div>
                        <div class="alert-control-description">
                            Seconds the play card stays
                            on the scoreboard.
                        </div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        Watched Players
                    </div>

                    <p class="player-help">
                        Search the NFL roster and add
                        up to {MAX_WATCHED_PLAYERS}
                        players. Alerts fire only for
                        big plays, not every carry.
                    </p>

                    <div class="stock-search player-search">
                        <input
                            class="search-input"
                            id="player_search"
                            type="search"
                            placeholder="Search NFL players..."
                            autocomplete="off"
                        >
                        <div
                            class="stock-search-results"
                            id="player_search_results"
                            hidden
                        ></div>
                    </div>

                    <div id="player_watch_list">
                        {player_watch_rows}
                    </div>

                    <div
                        class="empty"
                        id="player_watch_empty"
                        {"hidden" if player_watch_rows else ""}
                    >
                        No players selected yet.
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        Fantasy Teams
                    </div>

                    <p class="player-help">
                        Pull players from your Sleeper
                        leagues and tap to watch them.
                    </p>

                    <div id="fantasy_alert_rosters">
                        <div class="empty">
                            Loading fantasy rosters...
                        </div>
                    </div>
                </div>
            </form>

            <form method="POST" action="/players/preview">
                <button
                    class="secondary-button"
                    type="submit"
                    style="
                        width: 100%;
                        min-height: 48px;
                        margin-bottom: max(
                            8px,
                            env(safe-area-inset-bottom)
                        );
                    "
                >
                    Preview on display
                </button>
            </form>
        </div>

        <script>
            const search = document.getElementById("player_search");
            const results = document.getElementById("player_search_results");
            const list = document.getElementById("player_watch_list");
            const empty = document.getElementById("player_watch_empty");
            const fantasyRoot = document.getElementById("fantasy_alert_rosters");
            const maxPlayers = {MAX_WATCHED_PLAYERS};
            let searchTimer = null;

            function selectedIds() {{
                return Array.prototype.map.call(
                    list.querySelectorAll('input[name="player_ids"]'),
                    function (input) {{
                        return input.value;
                    }}
                );
            }}

            function refreshEmpty() {{
                empty.hidden = selectedIds().length > 0;
            }}

            function addPlayer(player) {{
                const playerId = String((player && player.id) || "");

                if (!playerId) {{
                    return false;
                }}

                if (selectedIds().indexOf(playerId) !== -1) {{
                    return true;
                }}

                if (selectedIds().length >= maxPlayers) {{
                    results.innerHTML = (
                        '<div class="stock-search-empty">'
                        + "You can watch "
                        + maxPlayers
                        + " players.</div>"
                    );
                    results.hidden = false;
                    return false;
                }}

                const row = document.createElement("div");
                row.className = "player-watch-row";
                row.dataset.playerId = playerId;

                const hidden = document.createElement("input");
                hidden.type = "hidden";
                hidden.name = "player_ids";
                hidden.value = playerId;

                const pos = document.createElement("div");
                pos.className = "player-pos";
                pos.textContent = player.position || "";

                const info = document.createElement("div");
                info.className = "game-info";

                const name = document.createElement("div");
                name.className = "matchup";
                name.textContent = player.name || "";

                const details = document.createElement("div");
                details.className = "details";
                details.textContent = (
                    (player.team || "")
                    + " · "
                    + (player.position || "")
                ).replace(/^ · /, "");

                info.appendChild(name);
                info.appendChild(details);

                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "stock-remove-button";
                remove.textContent = "Remove";
                remove.setAttribute("data-remove-player", playerId);

                row.appendChild(hidden);
                row.appendChild(pos);
                row.appendChild(info);
                row.appendChild(remove);
                list.appendChild(row);
                refreshEmpty();
                syncFantasyButtons();
                if (window.autosaveForm && list.closest("form")) {{
                    window.autosaveForm(list.closest("form"), 0);
                }}
                return true;
            }}

            function removePlayer(playerId) {{
                const row = list.querySelector(
                    '[data-player-id="' + playerId + '"]'
                );

                if (row) {{
                    row.remove();
                }}

                refreshEmpty();
                syncFantasyButtons();
                if (window.autosaveForm && list.closest("form")) {{
                    window.autosaveForm(list.closest("form"), 0);
                }}
            }}

            function hideResults() {{
                results.hidden = true;
                results.innerHTML = "";
            }}

            function renderResults(players) {{
                if (!players.length) {{
                    results.innerHTML = (
                        '<div class="stock-search-empty">'
                        + "No matching NFL players.</div>"
                    );
                    results.hidden = false;
                    return;
                }}

                results.innerHTML = "";

                players.forEach(function (player) {{
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "stock-search-result";
                    button.innerHTML = (
                        '<div class="matchup">'
                        + player.name
                        + '</div><div class="details">'
                        + (player.team || "")
                        + " · "
                        + (player.position || "")
                        + "</div>"
                    );
                    button.addEventListener("click", function () {{
                        if (addPlayer(player)) {{
                            search.value = "";
                            hideResults();
                        }}
                    }});
                    results.appendChild(button);
                }});

                results.hidden = false;
            }}

            search.addEventListener("input", function () {{
                const query = search.value.trim();
                window.clearTimeout(searchTimer);

                if (query.length < 2) {{
                    hideResults();
                    return;
                }}

                searchTimer = window.setTimeout(function () {{
                    fetch(
                        "/api/alerts/players/search?q="
                        + encodeURIComponent(query)
                    )
                        .then(function (response) {{
                            return response.json();
                        }})
                        .then(function (payload) {{
                            renderResults(
                                (payload && payload.results) || []
                            );
                        }})
                        .catch(function () {{
                            renderResults([]);
                        }});
                }}, 200);
            }});

            list.addEventListener("click", function (event) {{
                const button = event.target.closest("[data-remove-player]");

                if (!button) {{
                    return;
                }}

                removePlayer(button.getAttribute("data-remove-player"));
            }});

            document.addEventListener("click", function (event) {{
                if (!event.target.closest(".player-search")) {{
                    hideResults();
                }}
            }});

            function syncFantasyButtons() {{
                const selected = selectedIds();

                document.querySelectorAll("[data-add-player]").forEach(
                    function (button) {{
                        const playerId = button.getAttribute(
                            "data-add-player"
                        );
                        const watching = selected.indexOf(playerId) !== -1;
                        button.textContent = watching ? "Watching" : "Watch";
                        button.disabled = watching;
                    }}
                );
            }}

            function renderFantasy(payload) {{
                if (!payload || !payload.connected) {{
                    fantasyRoot.innerHTML = (
                        '<div class="empty">'
                        + "Connect Sleeper on the Fantasy "
                        + "tab to pick players from your "
                        + "leagues.</div>"
                    );
                    return;
                }}

                const leagues = payload.leagues || [];

                if (!leagues.length) {{
                    fantasyRoot.innerHTML = (
                        '<div class="empty">'
                        + "Select at least one Sleeper "
                        + "league on the Fantasy tab.</div>"
                    );
                    return;
                }}

                fantasyRoot.innerHTML = "";

                leagues.forEach(function (league) {{
                    const wrap = document.createElement("div");
                    wrap.className = "fantasy-league";

                    const title = document.createElement("div");
                    title.className = "fantasy-league-name";
                    title.textContent = league.name || "League";
                    wrap.appendChild(title);

                    (league.teams || []).forEach(function (team) {{
                        const card = document.createElement("details");
                        card.className = "fantasy-team-card";
                        if (team.mine) {{
                            card.open = true;
                        }}

                        const summary = document.createElement("summary");
                        summary.textContent = (
                            (team.name || "Team")
                            + " · "
                            + ((team.players || []).length)
                            + " players"
                        );
                        card.appendChild(summary);

                        const body = document.createElement("div");
                        body.className = "fantasy-team-body";

                        (team.players || []).forEach(function (player) {{
                            const row = document.createElement("div");
                            row.className = "fantasy-player-row";

                            const pos = document.createElement("div");
                            pos.className = "player-pos";
                            pos.textContent = player.position || "";

                            const info = document.createElement("div");
                            info.className = "game-info";
                            const name = document.createElement("div");
                            name.className = "matchup";
                            name.textContent = player.name || "";
                            const details = document.createElement("div");
                            details.className = "details";
                            details.textContent = (
                                (player.team || "")
                                + " · "
                                + (player.position || "")
                            ).replace(/^ · /, "");
                            info.appendChild(name);
                            info.appendChild(details);

                            const button = document.createElement("button");
                            button.type = "button";
                            button.className = "stock-remove-button";
                            button.setAttribute("data-add-player", player.id);
                            button.addEventListener("click", function () {{
                                addPlayer(player);
                            }});

                            row.appendChild(pos);
                            row.appendChild(info);
                            row.appendChild(button);
                            body.appendChild(row);
                        }});

                        if (!(team.players || []).length) {{
                            const none = document.createElement("div");
                            none.className = "empty";
                            none.textContent = "No skill players on this roster.";
                            body.appendChild(none);
                        }}

                        card.appendChild(body);
                        wrap.appendChild(card);
                    }});

                    fantasyRoot.appendChild(wrap);
                }});

                syncFantasyButtons();
            }}

            fetch("/api/alerts/players/fantasy")
                .then(function (response) {{
                    return response.json();
                }})
                .then(renderFantasy)
                .catch(function () {{
                    fantasyRoot.innerHTML = (
                        '<div class="empty">'
                        + "Could not load fantasy rosters.</div>"
                    );
                }});

            refreshEmpty();
        </script>
    </body>
    </html>
    """


@app.route("/api/alerts/players/search")
@login_required
def api_alert_player_search():
    query = request.args.get("q", "")
    league = (
        request.args.get("league", "nfl")
        .strip()
        .lower()
    )

    if league != "nfl":
        return jsonify({
            "results": [],
        })

    try:
        results = search_players(query)
    except Exception:
        return jsonify({
            "results": [],
            "error": "search_failed",
        }), 502

    return jsonify({
        "results": results,
    })


@app.route("/api/alerts/players/fantasy")
@login_required
def api_alert_player_fantasy():
    try:
        payload = get_fantasy_alert_rosters()
    except Exception:
        return jsonify({
            "connected": False,
            "leagues": [],
            "error": "fantasy_failed",
        }), 502

    return jsonify(payload)

@app.route("/fantasy", methods=["GET", "POST"])
@login_required
def fantasy_page():
    settings = get_settings()
    fantasy = settings.get("fantasy", {})

    message = ""
    error = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        season = request.form.get("season", "2026").strip()
        previous_username = str(fantasy.get("username") or "")
        previous_season = str(fantasy.get("season") or "2026")

        if not season.isdigit() or len(season) != 4:
            error = "Enter a valid four-digit season."
        elif not username:
            error = "Enter your Sleeper username."
        else:
            try:
                user = connect_sleeper_user(username)

                if not user:
                    error = "Sleeper user not found."
                else:
                    leagues = get_user_leagues(
                        user.get("user_id"),
                        season,
                    )
                    if not isinstance(leagues, list):
                        leagues = []

                    valid_league_ids = {
                        str(league.get("league_id"))
                        for league in leagues
                        if league.get("league_id")
                    }
                    leagues_were_listed = (
                        request.form.get("leagues_listed") == "1"
                    )
                    saved_username = (
                        user.get("username")
                        or username
                    )
                    account_changed = (
                        not leagues_were_listed
                        or saved_username.lower() != previous_username.lower()
                        or season != previous_season
                    )
                    load_leagues = request.form.get("load_leagues") == "1"
                    posted_leagues = [
                        league_id
                        for league_id in request.form.getlist(
                            "selected_leagues"
                        )
                        if league_id in valid_league_ids
                    ]
                    # The first lookup has no checkboxes yet, so an empty
                    # post would save "no leagues" and the ticker would
                    # stay blank. Add every league on the account.
                    if account_changed or load_leagues:
                        selected_leagues = sorted(valid_league_ids)
                    else:
                        selected_leagues = posted_leagues

                    enabled = request.form.get("enabled") == "on"
                    if (account_changed or load_leagues) and selected_leagues:
                        enabled = True

                    update_settings({
                        "fantasy": {
                            "enabled": enabled,
                            "provider": "sleeper",
                            "username": saved_username,
                            "user_id": user.get("user_id", ""),
                            "season": season,
                            "refresh_interval": 120,
                            "selected_leagues": selected_leagues,
                        }
                    })

                    return autosave_response(
                        "/fantasy",
                        {
                            "reload": account_changed or load_leagues,
                        },
                    )

            except Exception as exc:
                error = f"Unable to connect to Sleeper: {exc}"

        if is_autosave_request() and error:
            return jsonify({"ok": False, "error": error}), 400

    settings = get_settings()
    fantasy = settings.get("fantasy", {})

    leagues = []

    if fantasy.get("user_id"):
        try:
            leagues = get_user_leagues(
                fantasy["user_id"],
                fantasy.get("season", "2026"),
            )
            if not isinstance(leagues, list):
                leagues = []
        except Exception as exc:
            error = f"Unable to load Sleeper leagues: {exc}"

    selected = {
        str(league_id)
        for league_id in fantasy.get("selected_leagues", [])
    }

    league_rows = ""

    for league in leagues:
        league_id = str(league.get("league_id", ""))
        league_name = escape(
            str(league.get("name", "Unnamed League"))
        )

        checked = "checked" if league_id in selected else ""

        league_rows += f"""
        <label class="game-row">
            <input
                type="checkbox"
                name="selected_leagues"
                value="{escape(league_id, quote=True)}"
                {checked}
            >

            <div class="game-info">
                <div class="matchup">{league_name}</div>
                <div class="details">
                    League ID: {escape(league_id)}
                </div>
            </div>
        </label>
        """

    if not league_rows:
        if fantasy.get("user_id") and not error:
            league_rows = """
            <div class="empty">
                No NFL leagues for this season.
                Check the username and season, then load again.
            </div>
            """
        else:
            league_rows = """
            <div class="empty">
                Enter your Sleeper username and load your leagues.
            </div>
            """

    enabled_checked = (
        "checked"
        if fantasy.get("enabled", False)
        else ""
    )

    saved_message = (
        "Fantasy settings saved."
        if request.args.get("saved") == "1"
        else message
    )

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>GameLine Pro Fantasy</title>
    <meta
        name="viewport"
        content="width=device-width, initial-scale=1, viewport-fit=cover"
    >
    {page_styles()}
</head>

<body>
    <div class="page">
        {page_header("fantasy")}

        {
            f'<div class="card">{escape(saved_message)}</div>'
            if saved_message else ""
        }

        {
            f'<div class="card error">{escape(error)}</div>'
            if error else ""
        }

        <form method="POST" data-autosave="1">
            <div class="card">
                <div class="card-title">Sleeper Account</div>
                <div class="error" data-autosave-error hidden></div>

                <label class="game-row">
                    <input
                        type="checkbox"
                        name="enabled"
                        {enabled_checked}
                    >

                    <div class="game-info">
                        <div class="matchup">
                            Enable Fantasy
                        </div>
                        <div class="details">
                            Show Sleeper matchups on the ticker.
                        </div>
                    </div>
                </label>

                <input
                    class="search-input"
                    type="text"
                    name="username"
                    value="{escape(str(fantasy.get('username', '')), quote=True)}"
                    placeholder="Sleeper username"
                >

                <input
                    class="search-input"
                    type="text"
                    name="season"
                    value="{escape(str(fantasy.get('season', '2026')), quote=True)}"
                    placeholder="Season"
                    inputmode="numeric"
                >

                <button
                    class="save-button"
                    type="submit"
                    name="load_leagues"
                    value="1"
                >
                    Load leagues
                </button>
            </div>

            <div class="card">
                <div class="card-title">Leagues</div>
                {
                    '<input type="hidden" name="leagues_listed" value="1">'
                    if leagues else ""
                }
                {league_rows}
            </div>
        </form>
    </div>
</body>
</html>
"""

def _logo_team_label(league, team):
    team = str(team or "").upper()
    if league == "mlb":
        return MLB_TEAM_NAMES.get(team, team)
    if league == "nfl":
        definition = NFL_TEAM_ALERTS.get(team)
        if definition is not None:
            return definition.name
    return team


def _logo_redirect(league, team="", **query):
    kwargs = {"league": league, **query}
    if team:
        kwargs["_anchor"] = f"logo-team-{str(team).upper()}"
    return redirect(url_for("logos_page", **kwargs))


def _set_logo_selection(league, team, variant):
    settings = get_settings()
    logo_variants = settings.get("logo_variants") or {}
    if not isinstance(logo_variants, dict):
        logo_variants = {}
    league_selections = logo_variants.get(league) or {}
    if not isinstance(league_selections, dict):
        league_selections = {}
    league_selections[str(team).upper()] = str(variant).strip().lower()
    logo_variants[league] = league_selections
    update_settings({"logo_variants": logo_variants})


LOGO_LEAGUE_LABELS = {
    "mlb": "MLB",
    "nfl": "NFL",
    "cfb": "College Football",
    "nba": "NBA",
    "nhl": "NHL",
    "soccer": "Soccer",
}


def _render_logo_team_list(league, settings):
    league_teams = get_team_logo_catalog(league)
    custom_by_team = get_custom_variants_by_team(league)
    rows = []

    for team, variants in league_teams.items():
        team = str(team).upper()
        custom_variants = custom_by_team.get(team, set())
        display_name = _logo_team_label(league, team)
        selected_variant = get_selected_logo_variant(
            settings,
            league,
            team,
            available=variants,
        )
        if selected_variant not in variants:
            selected_variant = (
                "current" if "current" in variants else variants[0]
            )

        variant_options = []
        for variant in variants:
            variant = str(variant)
            selected = "selected" if variant == selected_variant else ""
            option_label = variant_label(variant)
            if variant in custom_variants:
                option_label = f"{option_label} (custom)"
            variant_options.append(
                f'<option value="{escape(variant, quote=True)}" {selected}>'
                f"{escape(option_label)}</option>"
            )

        safe_team = escape(team, quote=True)
        safe_league = escape(league, quote=True)
        safe_name = escape(display_name)
        search_blob = escape(f"{team} {display_name}".lower(), quote=True)
        preview_url = (
            f"/logo-preview/{safe_league}/{safe_team}/"
            f"{escape(selected_variant, quote=True)}"
        )

        delete_button = ""
        if selected_variant in custom_variants:
            delete_button = f"""
                <form class="logo-delete-form" method="POST" action="/logos/delete">
                    <input type="hidden" name="league" value="{safe_league}">
                    <input type="hidden" name="team" value="{safe_team}">
                    <input type="hidden" name="variant" value="{escape(selected_variant, quote=True)}">
                    <button class="ghost-button logo-delete-button" type="submit">
                        Remove custom logo
                    </button>
                </form>
            """

        rows.append(f"""
            <div
                class="logo-team-block"
                id="logo-team-{safe_team}"
                data-search="{search_blob}"
                data-league="{safe_league}"
                data-team="{safe_team}"
                data-name="{escape(display_name, quote=True)}"
            >
                <div class="logo-team-row">
                    <div class="logo-preview-box">
                        <img
                            class="logo-preview"
                            id="logo-preview-{safe_team}"
                            src="{preview_url}"
                            alt="{safe_team} logo preview"
                            width="30"
                            height="30"
                            loading="lazy"
                            decoding="async"
                        >
                    </div>
                    <div class="logo-team-controls">
                        <div class="logo-team-heading">
                            <div class="logo-team-copy">
                                <div class="logo-team-name">{safe_name}</div>
                                <div class="logo-team-abbr">{safe_team}</div>
                            </div>
                            <button
                                type="button"
                                class="icon-button logo-add-button"
                                aria-label="Add logo for {safe_name}"
                            >
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                    <path d="M12 5v14M5 12h14"></path>
                                </svg>
                            </button>
                        </div>
                        <select
                            class="logo-variant-select"
                            name="logo:{safe_team}"
                            form="logo-save-form"
                            data-league="{safe_league}"
                            data-team="{safe_team}"
                            data-preview-id="logo-preview-{safe_team}"
                        >
                            {''.join(variant_options)}
                        </select>
                        {delete_button}
                    </div>
                </div>
            </div>
        """)

    if not rows:
        return (
            '<div class="empty">No team logos were found.</div>',
            0,
        )
    return "".join(rows), len(league_teams)


@app.route(
    "/logo-preview/<league>/<team>/<variant>"
)
@login_required
def logo_preview(
    league: str,
    team: str,
    variant: str,
):
    logo_path = get_logo_variant_path(
        league=league,
        identifier=team,
        variant=variant,
    )

    if logo_path is None:
        abort(404)

    return send_file(
        logo_path,
        mimetype="image/png",
        max_age=86400,
        conditional=True,
    )

@app.route("/logos")
@login_required
def logos_page():
    settings = get_settings()
    requested_league = (
        request.args.get("league", "")
        .strip()
        .lower()
    )
    if requested_league in LOGO_LEAGUE_LABELS:
        selected_league = requested_league
    else:
        selected_league = "mlb"

    league_options = "".join(
        f"""
        <option
            value="{escape(league, quote=True)}"
            {"selected" if league == selected_league else ""}
        >
            {escape(label)}
        </option>
        """
        for league, label in LOGO_LEAGUE_LABELS.items()
        if league in EDITABLE_LOGO_LEAGUES
    )
    team_rows, team_count = _render_logo_team_list(
        selected_league,
        settings,
    )

    saved_message = ""
    saved_state = request.args.get("saved", "")
    error_text = request.args.get("error", "").strip()

    if error_text:
        saved_message = f"""
        <div class="logo-error">
            {escape(error_text)}
        </div>
        """
    elif saved_state == "uploaded":
        saved_message = """
        <div class="logo-success">
            Custom logo saved on this GameLine Pro.
        </div>
        """
    elif saved_state == "deleted":
        saved_message = """
        <div class="logo-success">
            Custom logo removed.
        </div>
        """
    elif saved_state == "1":
        saved_message = """
        <div class="logo-success">
            Logo selections saved.
        </div>
        """

    safe_selected_league = escape(
        selected_league,
        quote=True,
    )

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>GameLine Pro Logos</title>
    <meta
        name="viewport"
        content="width=device-width, initial-scale=1, viewport-fit=cover"
    >
    {page_styles()}
</head>

<body>
    <div class="page">
        {page_header("logos")}
        {saved_message}

        <div class="card">
            <div class="card-title">
                League
            </div>

            {
                f'''
                <select
                    id="logo_league"
                    class="select-input"
                >
                    {league_options}
                </select>

                <div class="hint">
                    Custom logos stay on this GameLine Pro
                    through software updates.
                </div>
                '''
                if league_options
                else '''
                <div class="empty">
                    No team logos were found.
                </div>
                '''
            }
        </div>

        <div class="card">
            <div class="card-title">
                Team Logos
            </div>
            {
                f'''
                <input
                    id="logo-search"
                    class="search-input"
                    type="search"
                    placeholder="Search {team_count} teams"
                    autocomplete="off"
                >
                '''
                if selected_league
                else ""
            }

            <div id="logo-team-list">
                {team_rows}
            </div>
        </div>

        <form
            id="logo-save-form"
            method="POST"
            action="/save_logos"
            data-autosave="1"
        >
            <input
                type="hidden"
                name="league"
                value="{safe_selected_league}"
            >
        </form>
    </div>

    <div
        id="logo-add-sheet"
        class="logo-sheet"
        hidden
    >
        <button
            type="button"
            class="logo-sheet-backdrop"
            data-logo-sheet-close="1"
            aria-label="Close"
        ></button>
        <div
            class="logo-sheet-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="logo-add-title"
        >
            <div class="logo-sheet-header">
                <h3 id="logo-add-title">Add logo</h3>
                <button
                    type="button"
                    class="icon-button"
                    data-logo-sheet-close="1"
                    aria-label="Close"
                >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M6 6l12 12M18 6L6 18"></path>
                    </svg>
                </button>
            </div>
            <form
                class="logo-upload-form"
                method="POST"
                action="/logos/upload"
                enctype="multipart/form-data"
            >
                <input
                    id="logo-add-league"
                    type="hidden"
                    name="league"
                    value=""
                >
                <input
                    id="logo-add-team"
                    type="hidden"
                    name="team"
                    value=""
                >
                <input
                    id="logo-add-name"
                    class="search-input logo-name-input"
                    type="text"
                    name="name"
                    maxlength="40"
                    placeholder="Name this logo"
                    required
                    autocomplete="off"
                >
                <input
                    class="logo-file-input"
                    type="file"
                    name="file"
                    accept="image/png,image/jpeg,image/webp,image/gif"
                    required
                >
                <button
                    class="save-button logo-upload-button"
                    type="submit"
                >
                    Upload logo
                </button>
            </form>
        </div>
    </div>

    <script>
        const leagueSelector =
            document.getElementById(
                "logo_league"
            );

        const logoList =
            document.getElementById("logo-team-list");
        const logoLeagueField =
            document.querySelector(
                "#logo-save-form input[name='league']"
            );

        function applyLogoFilter() {{
            if (!logoSearch) {{
                return;
            }}
            const query =
                logoSearch.value.trim().toLowerCase();
            document.querySelectorAll(
                ".logo-team-block"
            ).forEach(function (row) {{
                const haystack = row.dataset.search || "";
                row.hidden = Boolean(
                    query && haystack.indexOf(query) === -1
                );
            }});
        }}

        if (leagueSelector) {{
            leagueSelector.addEventListener(
                "change",
                function () {{
                    const league = leagueSelector.value;
                    if (logoList) {{
                        logoList.innerHTML =
                            '<div class="empty">Loading teams…</div>';
                    }}
                    fetch(
                        "/logos/teams?league="
                        + encodeURIComponent(league),
                        {{ headers: {{ "Accept": "text/html" }} }}
                    ).then(function (response) {{
                        if (!response.ok) {{
                            throw new Error("load failed");
                        }}
                        return response.text();
                    }}).then(function (html) {{
                        if (logoList) {{
                            logoList.innerHTML = html;
                        }}
                        if (logoLeagueField) {{
                            logoLeagueField.value = league;
                        }}
                        if (logoSearch) {{
                            const count =
                                document.querySelectorAll(
                                    ".logo-team-block"
                                ).length;
                            logoSearch.placeholder =
                                "Search " + count + " teams";
                            logoSearch.value = "";
                        }}
                        window.history.replaceState(
                            {{}},
                            "",
                            "/logos?league="
                            + encodeURIComponent(league)
                        );
                    }}).catch(function () {{
                        window.location.href =
                            "/logos?league="
                            + encodeURIComponent(league);
                    }});
                }}
            );
        }}

        const logoSearch =
            document.getElementById("logo-search");

        if (logoSearch) {{
            logoSearch.addEventListener("input", applyLogoFilter);
        }}

        const logoSheet =
            document.getElementById("logo-add-sheet");
        const logoAddTitle =
            document.getElementById("logo-add-title");
        const logoAddLeague =
            document.getElementById("logo-add-league");
        const logoAddTeam =
            document.getElementById("logo-add-team");
        const logoAddName =
            document.getElementById("logo-add-name");

        function closeLogoSheet() {{
            if (!logoSheet) {{
                return;
            }}
            logoSheet.hidden = true;
            document.body.classList.remove(
                "logo-sheet-open"
            );
        }}

        function openLogoSheet(block) {{
            if (!logoSheet || !block) {{
                return;
            }}
            const teamName =
                block.dataset.name || block.dataset.team;
            logoAddLeague.value = block.dataset.league || "";
            logoAddTeam.value = block.dataset.team || "";
            logoAddName.value = "";
            const fileInput =
                logoSheet.querySelector(
                    "input[type='file']"
                );
            if (fileInput) {{
                fileInput.value = "";
            }}
            logoAddTitle.textContent =
                "Add logo for " + teamName;
            logoSheet.hidden = false;
            document.body.classList.add(
                "logo-sheet-open"
            );
            window.setTimeout(function () {{
                logoAddName.focus();
            }}, 50);
        }}

        if (logoList) {{
            logoList.addEventListener(
                "click",
                function (event) {{
                    const button = event.target.closest(
                        ".logo-add-button"
                    );
                    if (button) {{
                        openLogoSheet(
                            button.closest(".logo-team-block")
                        );
                    }}
                }}
            );
            logoList.addEventListener(
                "change",
                function (event) {{
                    const selector = event.target.closest(
                        ".logo-variant-select"
                    );
                    if (!selector) {{
                        return;
                    }}
                    const league = encodeURIComponent(
                        selector.dataset.league
                    );
                    const team = encodeURIComponent(
                        selector.dataset.team
                    );
                    const variant = encodeURIComponent(
                        selector.value
                    );
                    const preview = document.getElementById(
                        (selector.dataset.previewId || "").trim()
                    );
                    if (!preview) {{
                        return;
                    }}
                    preview.src =
                        "/logo-preview/"
                        + league
                        + "/"
                        + team
                        + "/"
                        + variant
                        + "?cache="
                        + Date.now();
                    preview.alt =
                        selector.dataset.team
                        + " "
                        + selector.value
                        + " logo preview";
                }}
            );
        }}

        if (logoSheet) {{
            logoSheet.addEventListener(
                "click",
                function (event) {{
                    if (
                        event.target.closest(
                            "[data-logo-sheet-close]"
                        )
                    ) {{
                        closeLogoSheet();
                    }}
                }}
            );
        }}

        document.addEventListener(
            "keydown",
            function (event) {{
                if (event.key === "Escape") {{
                    closeLogoSheet();
                }}
            }}
        );

        if ({str(bool(error_text)).lower()}) {{
            const hash = window.location.hash.slice(1);
            const block = hash
                ? document.getElementById(hash)
                : null;
            if (block) {{
                openLogoSheet(block);
            }}
        }}
    </script>
</body>
</html>
    """


@app.route("/logos/teams")
@login_required
def logo_team_list():
    league = request.args.get("league", "").strip().lower()
    if league not in LOGO_LEAGUE_LABELS:
        abort(400)
    html, _count = _render_logo_team_list(league, get_settings())
    return html


@app.route(
    "/save_logos",
    methods=["POST"],
)
@login_required
def save_logos():
    league = (
        request.form.get("league", "")
        .strip()
        .lower()
    )

    try:
        available_teams = get_team_logo_catalog(league)
    except ValueError:
        abort(400)

    if not available_teams:
        abort(400)

    settings = get_settings()

    logo_variants = settings.get(
        "logo_variants",
        {},
    )

    if not isinstance(logo_variants, dict):
        logo_variants = {}

    league_selections = logo_variants.get(
        league,
        {},
    )

    if not isinstance(league_selections, dict):
        league_selections = {}

    for team, variants in available_teams.items():
        team = str(team).upper()

        selected_variant = (
            request.form.get(
                f"logo:{team}",
                "",
            )
            .strip()
            .lower()
        )

        if selected_variant not in variants:
            continue

        league_selections[team] = selected_variant

    logo_variants[league] = league_selections

    update_settings({
        "logo_variants": logo_variants,
    })

    return autosave_response(
        url_for("logos_page", league=league)
    )


@app.route(
    "/logos/upload",
    methods=["POST"],
)
@login_required
def upload_custom_logo():
    league = (
        request.form.get("league", "")
        .strip()
        .lower()
    )
    team = (
        request.form.get("team", "")
        .strip()
        .upper()
    )
    name = request.form.get("name", "")
    upload = request.files.get("file")
    payload = upload.read() if upload else b""

    try:
        variant = save_custom_logo(
            league,
            team,
            name,
            payload,
        )
    except (LogoError, ValueError) as error:
        return _logo_redirect(
            league,
            team,
            error=str(error),
        )

    _set_logo_selection(league, team, variant)
    return _logo_redirect(
        league,
        team,
        saved="uploaded",
    )


@app.route(
    "/logos/delete",
    methods=["POST"],
)
@login_required
def delete_uploaded_logo():
    league = (
        request.form.get("league", "")
        .strip()
        .lower()
    )
    team = (
        request.form.get("team", "")
        .strip()
        .upper()
    )
    variant = (
        request.form.get("variant", "")
        .strip()
        .lower()
    )

    try:
        delete_custom_logo(league, team, variant)
    except (LogoError, ValueError) as error:
        return _logo_redirect(
            league,
            team,
            error=str(error),
        )

    selected = get_selected_logo_variant(
        get_settings(),
        league,
        team,
    )
    if selected == variant:
        _set_logo_selection(league, team, "current")

    return _logo_redirect(
        league,
        team,
        saved="deleted",
    )


@app.route("/settings")
@login_required
def settings_page():
    software_version = get_scorecast_version()
    settings = get_settings()

    scroll_speed = settings.get("scroll_speed", 0.4)
    brightness = settings.get("brightness", 40)
    refresh_interval = settings.get("refresh_interval", 120)
    fps = settings.get("fps", 60)
    timezone_setting = normalize_timezone_setting(
        settings.get("timezone", "auto")
    )
    timezone_detail = timezone_status()["detail"]

    user = current_user()
    is_root = bool(user and user["role"] == "root")
    developer = get_developer_settings(settings)
    test_games_checked = "checked" if developer.get("test_games") else ""
    score_slide_checked = "checked" if developer.get("score_slide") else ""
    developer_unlocked = bool(settings.get("developer_unlocked")) and is_root
    developer_html = ""
    if developer_unlocked:
        developer_html = f"""
            <div class="card" id="developer">
                <div class="card-title">Developer</div>
                <div class="hint" style="margin-bottom:12px;">
                    Visible only to the root profile. Changes apply
                    to the live board.
                </div>

                <div class="dev-stat-grid" id="developer_stats">
                    <div class="dev-stat" id="stat_cpu">
                        <div class="dev-stat-value" id="stat_cpu_value">—</div>
                        <div class="dev-stat-label">CPU</div>
                    </div>
                    <div class="dev-stat" id="stat_temp">
                        <div class="dev-stat-value" id="stat_temp_value">—</div>
                        <div class="dev-stat-label">CPU temp</div>
                    </div>
                    <div class="dev-stat" id="stat_ram">
                        <div class="dev-stat-value" id="stat_ram_value">—</div>
                        <div class="dev-stat-label">RAM</div>
                    </div>
                </div>
                <div class="settings-row">
                    <div class="settings-row-copy">
                        <div class="settings-row-title">Uptime</div>
                        <div class="hint" id="stat_uptime">Loading…</div>
                    </div>
                    <div class="settings-row-value" id="stat_load"></div>
                </div>
                <div
                    id="stat_throttle"
                    class="dev-throttle"
                    style="display:none;"
                ></div>

                <label class="dev-option">
                    <input
                        type="checkbox"
                        name="developer_test_games"
                        value="1"
                        {test_games_checked}
                    >
                    <div>
                        <div class="settings-row-title">Sample games</div>
                        <div class="hint">
                            Scroll canned scorecards instead of live APIs.
                            Use this to layout the board when nothing is on.
                        </div>
                    </div>
                </label>

                <label class="dev-option">
                    <input
                        type="checkbox"
                        name="developer_score_slide"
                        value="1"
                        {score_slide_checked}
                    >
                    <div>
                        <div class="settings-row-title">Score slide</div>
                        <div class="hint">
                            Animate football focus scores when they change.
                            Turn off to snap to the new number.
                        </div>
                    </div>
                </label>

                <div class="settings-row">
                    <div class="settings-row-copy">
                        <div class="settings-row-title">Reboot Pi</div>
                        <div class="hint">
                            Full Raspberry Pi reboot. The board and
                            dashboard will be down for about a minute.
                        </div>
                        <div
                            id="system_reboot_status"
                            class="hint"
                        ></div>
                    </div>
                    <button
                        type="button"
                        id="system_reboot_button"
                        class="quiet-button"
                        onclick="rebootRaspberryPi()"
                    >
                        Reboot
                    </button>
                </div>

                <div class="settings-row factory-reset-row">
                    <div class="settings-row-copy">
                        <div class="settings-row-title">Factory reset</div>
                        <div class="hint">
                            Wipe this display back to first boot: profiles,
                            settings, bets, favorites, and custom logos.
                            Software and updates stay. After restart, scan
                            the QR on the board.
                        </div>
                        <label class="dev-option factory-reset-option">
                            <input
                                type="checkbox"
                                id="factory_reset_forget_wifi"
                            >
                            <div>
                                <div class="settings-row-title">Forget Wi-Fi</div>
                                <div class="hint">
                                    Also drop saved networks and start the
                                    setup hotspot. Leave off if you only want
                                    a fresh account on the current network.
                                </div>
                            </div>
                        </label>
                        <div
                            id="factory_reset_status"
                            class="hint"
                        ></div>
                    </div>
                    <button
                        type="button"
                        id="factory_reset_button"
                        class="quiet-button quiet-button-danger"
                        onclick="factoryResetGameLine()"
                    >
                        Reset
                    </button>
                </div>
                <div class="settings-row">
                    <div class="settings-row-copy">
                        <div class="settings-row-title">Hide developer options</div>
                        <div class="hint">
                            Sample games and these controls stay off
                            until you open them again.
                        </div>
                    </div>
                    <button
                        type="button"
                        class="quiet-button"
                        onclick="setDeveloperAccess(false)"
                    >
                        Hide
                    </button>
                </div>
                <input type="hidden" name="developer_form" value="1">
            </div>
        """
    saved_message = ""
    if request.args.get("saved") == "1":
        saved_message = '<div class="hint" style="margin-bottom:12px;">Profile created.</div>'
    elif request.args.get("deleted") == "1":
        saved_message = '<div class="hint" style="margin-bottom:12px;">Profile deleted.</div>'
    error = request.args.get("error", "")
    profiles_html = (
        _profiles_cards_html(saved_message, error)
        if is_root
        else ""
    )

    if is_root and not developer_unlocked:
        version_html = (
            f'<button type="button" id="version_unlock" '
            f'class="settings-row-value version-unlock">'
            f'v{escape(software_version)}</button>'
        )
    else:
        version_html = (
            f'<div class="settings-row-value">'
            f'v{escape(software_version)}</div>'
        )

    if is_root:
        update_button_html = """
                    <button
                        type="button"
                        id="update_button"
                        class="ghost-button"
                        onclick="startGameLineUpdate()"
                    >
                        Check for update
                    </button>
        """
        restart_button_html = """
                    <button
                        type="button"
                        id="system_restart_button"
                        class="quiet-button"
                        onclick="restartGameLine()"
                    >
                        Restart
                    </button>
        """
        unlock_script = """
        async function setDeveloperAccess(enabled) {
            const response = await fetch("/settings/developer", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify({enabled: enabled})
            });
            if (response.ok) {
                window.location.reload();
            }
        }
        """
    else:
        update_button_html = ""
        restart_button_html = ""
        unlock_script = ""

    if is_root and not developer_unlocked:
        unlock_script += """
        (function () {
            var row = document.getElementById("version_unlock");
            if (!row) {
                return;
            }
            var taps = 0;
            var last = 0;
            row.addEventListener("click", function () {
                var now = Date.now();
                taps = now - last < 2000 ? taps + 1 : 1;
                last = now;
                if (taps < 7) {
                    return;
                }
                taps = 0;
                setDeveloperAccess(true);
            });
        })();
        """

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>GameLine Pro Settings</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    {page_styles()}
</head>

<body>
    <div class="page">
        {page_header("settings")}

        <form method="POST" action="/save_settings" data-autosave="1">
            <div class="card">
                <div class="card-title">Display</div>

                <div class="control">
                    <div class="control-top">
                        <label for="scroll_speed">Scroll Speed</label>
                            <input class="number-input" type="number"
                                id="scroll_speed_number" name="scroll_speed"
                                min="5" max="120" step="1"
                                value="{scroll_speed}">
                    </div>

                    <input type="range" id="scroll_speed"
                        min="5" max="120" step="1"
                        value="{scroll_speed}"
                        oninput="scroll_speed_number.value = this.value">

                    <div class="hint">
                        Pixels per second. Each step is held for the same number of panel refreshes.
                    </div>
                </div>

                <div class="control">
                    <div class="control-top">
                        <label for="fps">Frames Per Second</label>

                        <input
                            class="number-input"
                            type="number"
                            id="fps_number"
                            name="fps"
                            min="10"
                            max="120"
                            step="1"
                            value="{fps}"
                        >
                    </div>

                    <input
                        type="range"
                        id="fps"
                        min="10"
                        max="120"
                        step="1"
                        value="{fps}"
                        oninput="fps_number.value = this.value"
                    >

                    <div class="hint">
                        How fast alerts and focus mode animate. Scrolling stays locked to the panel.
                    </div>
                </div>

                <div class="control">
                    <div class="control-top">
                        <label for="brightness">Brightness</label>
                        <input class="number-input" type="number"
                            id="brightness_number" name="brightness"
                            min="5" max="100" step="5"
                            value="{brightness}">
                    </div>

                    <input type="range" id="brightness"
                        min="5" max="100" step="5"
                        value="{brightness}"
                        oninput="brightness_number.value = this.value">
                </div>

                <div class="control">
                    <div class="control-top">
                        <label for="refresh_interval">API Refresh</label>
                        <input class="number-input" type="number"
                            id="refresh_interval_number" name="refresh_interval"
                            min="15" max="600" step="15"
                            value="{refresh_interval}">
                    </div>

                    <input type="range" id="refresh_interval"
                        min="15" max="600" step="15"
                        value="{refresh_interval}"
                        oninput="refresh_interval_number.value = this.value">

                    <div class="hint">
                        Refresh interval is in seconds.
                    </div>
                </div>

                <div class="control">
                    <div class="control-top">
                        <label for="timezone">Timezone</label>
                    </div>

                    <select
                        id="timezone"
                        name="timezone"
                        class="select-input"
                    >
                        {_timezone_options_html(timezone_setting)}
                    </select>

                    <div class="hint" id="timezone_hint">
                        {escape(timezone_detail)}
                    </div>
                    <div class="hint">
                        Automatic uses this network's location.
                        A saved timezone overrides that.
                        The Pi system timezone is not used.
                    </div>
                    {_timezone_picker_script()}
                </div>
            </div>

            <div class="card">
                <div class="card-title">Software</div>

                <div class="settings-row">
                    <div class="settings-row-copy">
                        <div class="settings-row-title">Version</div>
                    </div>
                    {version_html}
                </div>

                <div
                    id="software-update"
                    class="settings-row settings-row-stack"
                >
                    <div class="settings-row-copy">
                        <div class="settings-row-title">Updates</div>
                        <div class="hint">
                            Latest stable release from GitHub.
                        </div>
                    </div>

                    <div
                        id="update_status_box"
                        class="update-status-box"
                    >
                        <div id="update_status_message">
                            Loading update status...
                        </div>
                        <div
                            id="update_status_details"
                            class="hint"
                        ></div>
                    </div>

                    <div
                        id="update_release_notes"
                        class="update-release-notes"
                        hidden
                    >
                        <div
                            id="update_release_kicker"
                            class="update-release-kicker"
                        ></div>
                        <div
                            id="update_release_title"
                            class="update-release-title"
                        ></div>
                        <p
                            id="update_release_body"
                            class="update-release-body"
                            hidden
                        ></p>
                    </div>

                    <div
                        id="update_progress_container"
                        class="update-progress"
                        style="display:none;"
                    >
                        <div class="update-progress-heading">
                            <span id="update_progress_step">
                                Preparing update
                            </span>
                            <strong id="update_progress_percent">
                                0%
                            </strong>
                        </div>
                        <div
                            id="update_progress_track"
                            class="update-progress-track"
                            role="progressbar"
                            aria-label="Update progress"
                            aria-valuemin="0"
                            aria-valuemax="100"
                            aria-valuenow="0"
                        >
                            <div
                                id="update_progress_bar"
                                class="update-progress-fill"
                            ></div>
                        </div>
                        <div
                            id="update_progress_note"
                            class="update-progress-note"
                        >
                            Progress is based on completed
                            installation steps.
                        </div>
                    </div>

                    {update_button_html}
                </div>

                <div class="settings-row">
                    <div class="settings-row-copy">
                        <div class="settings-row-title">Restart</div>
                        <div class="hint">
                            Restarts the app, not the Pi.
                            The board reconnects in a few seconds.
                        </div>
                        <div
                            id="system_restart_status"
                            class="hint"
                        ></div>
                    </div>
                    {restart_button_html}
                </div>
            </div>

            {developer_html}
        </form>

        {profiles_html}
    </div>

    <script>

        const updateStateLabels = {{
            idle: "Ready",
            checking: "Checking GitHub",
            available: "Update Available",
            downloading: "Preparing Release",
            installing: "Installing Dependencies",
            validating: "Validating Release",
            restarting: "Restarting GameLine Pro",
            rolling_back: "Restoring Previous Release",
            complete: "Update Complete",
            current: "Already Up to Date",
            rolled_back: "Update Rolled Back",
            failed: "Update Failed"
        }};

        const updateStateProgress = {{
            idle: 0,
            checking: 5,
            available: 100,
            downloading: 20,
            installing: 40,
            validating: 80,
            restarting: 95,
            rolling_back: 95,
            complete: 100,
            current: 100
        }};

        const activeUpdateStates = new Set([
            "checking",
            "downloading",
            "installing",
            "validating",
            "restarting",
            "rolling_back"
        ]);

        let updateStatusTimer = null;
        let updatePollBusy = false;
        let updateStarting = false;
        let updateReconnect = false;
        let updateLastStatus = null;
        let updateLastProgress = 0;

        function renderUpdateStatus(status) {{
            const state = status.state || "idle";

            const active = (
                activeUpdateStates.has(state)
                || status.service_active === true
            );

            const terminal = [
                "complete",
                "current",
                "failed",
                "rolled_back",
                "available"
            ].includes(state);

            const raw = (
                status.progress === null
                || status.progress === undefined
            )
                ? NaN
                : Number(status.progress);

            const progress = Number.isFinite(raw)
                ? Math.max(
                    0,
                    Math.min(100, raw)
                )
                : (
                    updateStateProgress[state]
                    ?? 0
                );

            const value = active
                ? Math.max(
                    updateLastProgress,
                    progress
                )
                : progress;

            if (active) {{
                updateLastProgress = value;
            }} else if (
                terminal
                || state === "idle"
            ) {{
                updateLastProgress = 0;
            }}

            updateLastStatus = status;

            const message = document.getElementById(
                "update_status_message"
            );

            const details = document.getElementById(
                "update_status_details"
            );

            const button = document.getElementById(
                "update_button"
            );

            const container = document.getElementById(
                "update_progress_container"
            );

            const bar = document.getElementById(
                "update_progress_bar"
            );

            const percent = document.getElementById(
                "update_progress_percent"
            );

            const step = document.getElementById(
                "update_progress_step"
            );

            const note = document.getElementById(
                "update_progress_note"
            );

            const track = document.getElementById(
                "update_progress_track"
            );

            message.textContent = (
                updateStateLabels[state]
                || "Update Status"
            );

            details.textContent = (
                status.message
                || "Update status unavailable."
            );

            if (button) {{
                button.disabled = (
                    active
                    || updateStarting
                );
            }}

            const release = status.release || {{}};
            const notes = document.getElementById(
                "update_release_notes"
            );
            const showNotes = (
                release.update_available === true
                && !active
            );

            if (notes) {{
                notes.hidden = !showNotes;
            }}

            if (showNotes) {{
                const version = String(
                    release.latest_version || ""
                ).replace(/^v/, "");
                const title = String(
                    release.title || ""
                ).trim();
                const body = String(
                    release.description || ""
                ).trim();
                const kicker = document.getElementById(
                    "update_release_kicker"
                );
                const releaseTitle = document.getElementById(
                    "update_release_title"
                );
                const bodyElement = document.getElementById(
                    "update_release_body"
                );

                if (kicker) {{
                    kicker.textContent = version
                        ? ("Version " + version)
                        : "Update";
                }}

                if (version) {{
                    details.textContent = (
                        "GameLine Pro "
                        + version
                        + " is ready to install."
                    );
                }}

                if (releaseTitle) {{
                    releaseTitle.textContent = title
                        || "A new version is ready to install.";
                }}

                if (bodyElement) {{
                    const duplicate = !body || body === title;
                    bodyElement.hidden = duplicate;
                    bodyElement.textContent = duplicate
                        ? ""
                        : body;
                }}
            }}

            if (typeof window.applyUpdateBanner === "function") {{
                window.applyUpdateBanner(status);
            }}

            if (button) {{
                button.textContent = active
                    ? "Updating…"
                    : (
                        release.update_available
                            ? "Install update"
                            : "Check for update"
                    );
            }}

            container.style.display = (
                active
                || terminal
            )
                ? "block"
                : "none";

            if (showNotes) {{
                message.textContent = "Update Available";
                container.style.display = "none";
            }}

            bar.style.width = (
                value + "%"
            );

            bar.classList.toggle(
                "update-progress-failed",
                (
                    state === "failed"
                    || state === "rolled_back"
                )
            );

            percent.textContent = (
                Math.round(value)
                + "%"
            );

            step.textContent = (
                status.step
                || updateStateLabels[state]
                || "Update"
            );

            if (
                state === "failed"
                || state === "rolled_back"
            ) {{
                note.textContent = (
                    "The update did not complete. "
                    + "Review the message above."
                );

            }} else if (
                state === "complete"
                || state === "current"
            ) {{
                note.textContent = (
                    "All update steps completed."
                );

            }} else if (
                status.progress_kind
                === "transfer"
            ) {{
                note.textContent = (
                    "Git transfer progress. "
                    + "The overall update includes "
                    + "additional steps."
                );

            }} else {{
                note.textContent = (
                    "Overall progress is based "
                    + "on completed steps, "
                    + "not estimated time."
                );
            }}

            track.setAttribute(
                "aria-valuenow",
                String(Math.round(value))
            );

            track.setAttribute(
                "aria-valuetext",
                note.textContent
            );
        }}

        let scoreCastWasRestarting = false;

        async function loadUpdateStatus() {{
            if (updatePollBusy) {{
                return;
            }}

            updatePollBusy = true;

            try {{
                const response = await fetch(
                    "/api/update/status",
                    {{
                        method: "GET",
                        cache: "no-store"
                    }}
                );

                if (!response.ok) {{
                    throw new Error(
                        "Status request failed"
                    );
                }}

                const status =
                    await response.json();

                updateReconnect = false;
                renderUpdateStatus(status);

            }} catch (error) {{
                const wasActive = (
                    updateStarting
                    || updateReconnect
                    || (
                        updateLastStatus
                        && (
                            activeUpdateStates.has(
                                updateLastStatus.state
                            )
                            || updateLastStatus
                                .service_active
                                === true
                        )
                    )
                );

                if (wasActive) {{
                    updateReconnect = true;

                    document.getElementById(
                        "update_status_message"
                    ).textContent = (
                        "Reconnecting to GameLine Pro…"
                    );

                    document.getElementById(
                        "update_status_details"
                    ).textContent = (
                        "The dashboard may be "
                        + "restarting. Your update "
                        + "progress is preserved."
                    );

                    document.getElementById(
                        "update_button"
                    ).disabled = true;

                }} else {{
                    document.getElementById(
                        "update_status_message"
                    ).textContent = (
                        "Unable to reach updater"
                    );

                    document.getElementById(
                        "update_status_details"
                    ).textContent = (
                        "Check your connection "
                        + "and try again."
                    );
                }}

            }} finally {{
                updatePollBusy = false;
            }}
        }}

        async function startGameLineUpdate() {{
            const confirmed = window.confirm(
                "Install the latest stable GameLine Pro release? "
                + "The display and dashboard will restart."
            );

            if (!confirmed) {{
                return;
            }}

            updateStarting = true;
            updateLastProgress = 0;

            const button = document.getElementById(
                "update_button"
            );

            const messageElement = document.getElementById(
                "update_status_message"
            );

            const detailsElement = document.getElementById(
                "update_status_details"
            );

            if (button) {{
                button.disabled = true;
                button.textContent = "Starting update...";
            }}

            if (messageElement) {{
                messageElement.textContent = (
                    "Starting Update"
                );
            }}

            if (detailsElement) {{
                detailsElement.textContent = (
                    "Preparing the updater service."
                );
            }}

            try {{
                const response = await fetch(
                    "/api/update/start",
                    {{
                        method: "POST",
                        headers: {{
                            "Content-Type": "application/json"
                        }}
                    }}
                );

                const result = await response.json();

                if (!response.ok || !result.ok) {{
                    throw new Error(
                        result.message
                        || "Unable to start update."
                    );
                }}

                if (detailsElement) {{
                    detailsElement.textContent = (
                        result.message
                    );
                }}

                updateStarting = false;
                updateReconnect = true;

                await loadUpdateStatus();

            }} catch (error) {{
                updateStarting = false;

                if (messageElement) {{
                    messageElement.textContent = (
                        "Unable to Start Update"
                    );
                }}

                if (detailsElement) {{
                    detailsElement.textContent = (
                        error.message
                    );
                }}

                if (button) {{
                    button.disabled = false;
                    button.textContent = (
                        "Check for update"
                    );
                }}
            }}
        }}


        async function restartGameLine() {{
            const confirmed = window.confirm(
                "Restart GameLine Pro? "
                + "The display and dashboard will briefly disconnect."
            );

            if (!confirmed) {{
                return;
            }}

            const button = document.getElementById(
                "system_restart_button"
            );

            const status = document.getElementById(
                "system_restart_status"
            );

            if (button) {{
                button.disabled = true;
                button.textContent = "Restarting…";
            }}

            if (status) {{
                status.textContent = (
                    "Restart requested. Waiting for GameLine Pro to come back online…"
                );
            }}

            try {{
                const response = await fetch(
                    "/system/restart",
                    {{
                        method: "POST",
                        cache: "no-store"
                    }}
                );

                if (!response.ok) {{
                    throw new Error(
                        "Restart request failed"
                    );
                }}

                await new Promise(
                    resolve => setTimeout(resolve, 2500)
                );

                for (
                    let attempt = 0;
                    attempt < 30;
                    attempt++
                ) {{
                    try {{
                        const health = await fetch(
                            "/api/update/status",
                            {{
                                method: "GET",
                                cache: "no-store"
                            }}
                        );

                        if (health.ok) {{
                            window.location.reload();
                            return;
                        }}
                    }} catch (error) {{
                        // GameLine Pro is still restarting.
                    }}

                    await new Promise(
                        resolve => setTimeout(resolve, 1000)
                    );
                }}

                if (status) {{
                    status.textContent = (
                        "Restart is taking longer than expected. "
                        + "Refresh this page in a moment."
                    );
                }}

            }} catch (error) {{
                if (status) {{
                    status.textContent = (
                        "Unable to request the restart."
                    );
                }}

                if (button) {{
                    button.disabled = false;
                    button.textContent = "Restart";
                }}
            }}
        }}

        function bindNumberToSlider(numberId, sliderId) {{
            const number = document.getElementById(numberId);
            const slider = document.getElementById(sliderId);

            if (!number || !slider) {{
                return;
            }}

            number.addEventListener("input", function() {{
                slider.value = number.value;
            }});
        }}

        bindNumberToSlider("scroll_speed_number", "scroll_speed");
        bindNumberToSlider("brightness_number", "brightness");
        bindNumberToSlider("refresh_interval_number", "refresh_interval");
        bindNumberToSlider("fps_number", "fps");

        const timezoneSelect = document.getElementById("timezone");
        const timezoneHint = document.getElementById("timezone_hint");
        if (timezoneSelect && timezoneHint) {{
            timezoneSelect.addEventListener("change", function () {{
                window.setTimeout(function () {{
                    fetch("/api/timezone", {{
                        credentials: "same-origin",
                    }}).then(function (response) {{
                        if (!response.ok) {{
                            return null;
                        }}
                        return response.json();
                    }}).then(function (status) {{
                        if (status && status.detail) {{
                            timezoneHint.textContent = status.detail;
                        }}
                    }}).catch(function () {{}});
                }}, 700);
            }});
        }}

        function setStatTone(id, value, warnAt, hotAt) {{
            const card = document.getElementById(id);
            if (!card) {{
                return;
            }}
            card.classList.remove("warn", "hot");
            if (value === null || value === undefined) {{
                return;
            }}
            if (value >= hotAt) {{
                card.classList.add("hot");
            }} else if (value >= warnAt) {{
                card.classList.add("warn");
            }}
        }}

        async function loadSystemStats() {{
            const grid = document.getElementById("developer_stats");
            if (!grid) {{
                return;
            }}

            try {{
                const response = await fetch(
                    "/api/system/stats",
                    {{ cache: "no-store" }}
                );
                if (!response.ok) {{
                    return;
                }}
                const stats = await response.json();

                const cpu = document.getElementById("stat_cpu_value");
                const temp = document.getElementById("stat_temp_value");
                const ram = document.getElementById("stat_ram_value");
                const uptime = document.getElementById("stat_uptime");
                const load = document.getElementById("stat_load");
                const throttle = document.getElementById("stat_throttle");

                if (cpu) {{
                    cpu.textContent = (
                        stats.cpu_percent === null
                        ? "—"
                        : stats.cpu_percent.toFixed(0) + "%"
                    );
                }}
                if (temp) {{
                    temp.textContent = (
                        stats.cpu_temp_c === null
                        ? "—"
                        : stats.cpu_temp_c.toFixed(1) + "°"
                    );
                }}
                if (ram) {{
                    ram.textContent = (
                        stats.ram_percent === null
                        ? "—"
                        : stats.ram_percent.toFixed(0) + "%"
                    );
                }}
                if (uptime) {{
                    const ramLabel = (
                        stats.ram_used_label
                        && stats.ram_total_label
                    )
                        ? stats.ram_used_label
                            + " of "
                            + stats.ram_total_label
                        : "";
                    uptime.textContent = (
                        "Running "
                        + (stats.uptime_label || "—")
                        + (ramLabel ? " · " + ramLabel : "")
                    );
                }}
                if (load && stats.load_avg) {{
                    load.textContent = (
                        "load "
                        + stats.load_avg.join("  ")
                    );
                }}
                if (throttle) {{
                    if (stats.throttled && stats.throttled.length) {{
                        throttle.style.display = "block";
                        throttle.textContent = stats.throttled.join(" · ");
                    }} else {{
                        throttle.style.display = "none";
                        throttle.textContent = "";
                    }}
                }}

                setStatTone("stat_cpu", stats.cpu_percent, 80, 95);
                setStatTone("stat_temp", stats.cpu_temp_c, 70, 80);
                setStatTone("stat_ram", stats.ram_percent, 80, 90);
            }} catch (error) {{
                // Keep the last reading on the page.
            }}
        }}

        async function factoryResetGameLine() {{
            const forgetWifi = Boolean(
                document.getElementById("factory_reset_forget_wifi")
                && document.getElementById("factory_reset_forget_wifi").checked
            );
            const confirmed = window.confirm(
                forgetWifi
                    ? "Factory reset GameLine and forget Wi-Fi? Profiles, bets, settings, and custom logos will be deleted. The board will start the setup hotspot."
                    : "Factory reset GameLine? Profiles, bets, settings, and custom logos will be deleted. The board will go back to first-run setup."
            );
            if (!confirmed) {{
                return;
            }}
            const again = window.confirm(
                "This cannot be undone. Reset this display now?"
            );
            if (!again) {{
                return;
            }}

            const button = document.getElementById("factory_reset_button");
            const status = document.getElementById("factory_reset_status");
            if (button) {{
                button.disabled = true;
                button.textContent = "Resetting…";
            }}
            if (status) {{
                status.textContent = "Wiping this display. Watch the board for the setup QR.";
            }}

            try {{
                const response = await fetch("/system/factory-reset", {{
                    method: "POST",
                    cache: "no-store",
                    headers: {{
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    }},
                    body: JSON.stringify({{ forget_wifi: forgetWifi }})
                }});
                if (!response.ok) {{
                    throw new Error("Factory reset failed");
                }}
            }} catch (error) {{
                if (status) {{
                    status.textContent = "Unable to factory reset.";
                }}
                if (button) {{
                    button.disabled = false;
                    button.textContent = "Reset";
                }}
            }}
        }}

        async function rebootRaspberryPi() {{
            const confirmed = window.confirm(
                "Reboot the Raspberry Pi? "
                + "GameLine Pro and the dashboard will go offline "
                + "until the board comes back."
            );

            if (!confirmed) {{
                return;
            }}

            const button = document.getElementById(
                "system_reboot_button"
            );
            const status = document.getElementById(
                "system_reboot_status"
            );

            if (button) {{
                button.disabled = true;
                button.textContent = "Rebooting…";
            }}
            if (status) {{
                status.textContent = (
                    "Reboot requested. This page will drop until the Pi is back."
                );
            }}

            try {{
                const response = await fetch(
                    "/system/reboot",
                    {{
                        method: "POST",
                        cache: "no-store"
                    }}
                );
                if (!response.ok) {{
                    throw new Error("Reboot request failed");
                }}
            }} catch (error) {{
                if (status) {{
                    status.textContent = "Unable to request the reboot.";
                }}
                if (button) {{
                    button.disabled = false;
                    button.textContent = "Reboot";
                }}
            }}
        }}

        if (location.hash === "#profiles") {{
            const profiles = document.getElementById("profiles");
            if (profiles) {{
                profiles.scrollIntoView();
            }}
        }}
        if (location.hash === "#developer") {{
            const developer = document.getElementById("developer");
            if (developer) {{
                developer.scrollIntoView();
            }}
        }}

        function pollSettingsStatus() {{
            if (document.hidden) {{
                return;
            }}
            loadUpdateStatus();
            loadSystemStats();
        }}
        pollSettingsStatus();
        updateStatusTimer = setInterval(pollSettingsStatus, 5000);
        document.addEventListener("visibilitychange", pollSettingsStatus);
        {unlock_script}
    </script>
</body>
</html>
    """

def _favorite_league_key(raw):
    league_keys = {key for key, _label in FAVORITE_LEAGUES}
    league = str(raw or "").strip().lower()
    if league in league_keys:
        return league
    return "nfl"


def _selected_favorite_teams(league_key, submitted_teams):
    valid_options = {
        option.upper()
        for option in get_favorite_team_options(league_key)
    }
    selected_teams = []
    seen = set()
    for team in submitted_teams:
        normalized_team = str(team).strip().upper()
        if (
            normalized_team
            and normalized_team in valid_options
            and normalized_team not in seen
        ):
            selected_teams.append(normalized_team)
            seen.add(normalized_team)
    return selected_teams


@app.route("/favorites")
@login_required
def favorites_page():
    settings = get_settings()
    favorite_settings = settings.get("favorite_teams") or {}
    if not isinstance(favorite_settings, dict):
        favorite_settings = {}

    league_key = _favorite_league_key(request.values.get("league"))
    league_label = dict(FAVORITE_LEAGUES)[league_key]
    selected_values = favorite_settings.get(league_key, [])
    if isinstance(selected_values, str):
        selected_values = [selected_values]
    selected = {
        str(team).strip().upper()
        for team in selected_values
        if str(team).strip()
    }

    league_options = []
    for key, label in FAVORITE_LEAGUES:
        picked = " selected" if key == league_key else ""
        league_options.append(
            f'<option value="{escape(key)}"{picked}>{escape(label)}</option>'
        )

    team_rows = []
    for team in get_favorite_team_options(league_key):
        normalized_team = str(team).strip().upper()
        if not normalized_team:
            continue
        display_name = _logo_team_label(league_key, normalized_team)
        checked = "checked" if normalized_team in selected else ""
        search = escape(
            f"{display_name} {normalized_team}".lower(),
            quote=True,
        )
        detail = ""
        if display_name.upper() != normalized_team:
            detail = (
                f'<div class="details">{escape(normalized_team)}</div>'
            )
        team_rows.append(
            f"""
            <div class="favorite-team-row" data-team-search="{search}">
                <label class="game-row favorite-team-label">
                    <input
                        type="checkbox"
                        name="favorite_{league_key}"
                        value="{escape(normalized_team, quote=True)}"
                        {checked}
                    >
                    {web_team_mark(league_key, normalized_team, settings, accent=False)}
                    <div class="game-info">
                        <div class="matchup">{escape(display_name)}</div>
                        {detail}
                    </div>
                </label>
            </div>
            """
        )

    if team_rows:
        team_list = "".join(team_rows)
    else:
        team_list = """
            <div class="empty">
                No teams are currently available for this league.
            </div>
        """

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>GameLine Pro Favorites</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    {page_styles()}
</head>
<body>
    <div class="page">
        {page_header("favorites")}

        <form method="POST" action="/save_favorites" data-autosave="1">
            <div class="card">
                <div class="card-title">League</div>
                <div class="hint" style="margin-bottom: 14px;">
                    Pick a league, then choose the teams to keep
                    on the ticker whenever they have a game loaded.
                </div>
                <select
                    class="select-input favorite-league-select"
                    id="favorite_league"
                    onchange="window.location.href='/favorites?league=' + encodeURIComponent(this.value)"
                >
                    {''.join(league_options)}
                </select>
                <input type="hidden" name="league" value="{escape(league_key, quote=True)}">
            </div>

            <div class="card">
                <div class="card-title">Teams</div>
                <input
                    class="search-input favorite-team-search"
                    id="favorite_team_search"
                    type="search"
                    placeholder="Search {escape(league_label)} teams..."
                    oninput="filterFavoriteTeams()"
                >
                <div class="favorite-select-actions">
                    <button
                        class="secondary-button"
                        type="button"
                        onclick="setLeagueFavorites(true)"
                    >
                        Select All
                    </button>
                    <button
                        class="secondary-button"
                        type="button"
                        onclick="setLeagueFavorites(false)"
                    >
                        Clear
                    </button>
                </div>
                <div id="favorite_team_list">
                    {team_list}
                </div>
            </div>
        </form>
    </div>
    <script>
        function setLeagueFavorites(checked) {{
            document.querySelectorAll(
                '#favorite_team_list input[type="checkbox"]'
            ).forEach(function (input) {{
                input.checked = checked;
            }});
            var form = document.querySelector(
                'form[action="/save_favorites"]'
            );
            if (window.autosaveForm && form) {{
                window.autosaveForm(form, 0);
            }}
        }}

        function filterFavoriteTeams() {{
            var input = document.getElementById("favorite_team_search");
            var search = input
                ? input.value.toLowerCase().trim()
                : "";
            document.querySelectorAll(".favorite-team-row").forEach(
                function (row) {{
                    var teamText = row.dataset.teamSearch || "";
                    row.style.display = teamText.includes(search)
                        ? ""
                        : "none";
                }}
            );
        }}
    </script>
</body>
</html>
    """


@app.route("/save_favorites", methods=["POST"])
@login_required
def save_favorites():
    league_key = _favorite_league_key(request.form.get("league"))
    if str(request.form.get("league", "")).strip().lower() not in {
        key for key, _label in FAVORITE_LEAGUES
    }:
        return autosave_response("/favorites")

    settings = get_settings()
    current = settings.get("favorite_teams") or {}
    if not isinstance(current, dict):
        current = {}

    favorites = {}
    for key, values in current.items():
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            favorites[key] = list(values)

    favorites[league_key] = _selected_favorite_teams(
        league_key,
        request.form.getlist(f"favorite_{league_key}"),
    )
    update_settings({"favorite_teams": favorites})
    return autosave_response(
        url_for("favorites_page", league=league_key)
    )

@app.route("/save_games", methods=["POST"])
@login_required
def save_games():
    settings = get_settings()
    all_game_ids = [
        get_game_id(game)
        for game in latest_games
    ]
    sport_ids = [
        game_id
        for game_id in all_game_ids
        if not _is_stock_id(game_id)
    ]

    visible_games = list(dict.fromkeys(
        game_id
        for game_id in request.form.getlist("game")
        if game_id in sport_ids
    ))

    hidden_sports = [
        game_id
        for game_id in sport_ids
        if game_id not in visible_games
    ]

    previous_hidden = settings.get("hidden_games", [])
    previous_order = settings.get("game_order", [])
    stock_hidden = [
        game_id
        for game_id in previous_hidden
        if _is_stock_id(game_id)
    ]
    stock_order = [
        game_id
        for game_id in previous_order
        if _is_stock_id(game_id)
    ]
    for game_id in all_game_ids:
        if _is_stock_id(game_id) and game_id not in stock_order:
            stock_order.append(game_id)

    update_settings({
        "selected_games": visible_games,
        "hidden_games": hidden_sports + stock_hidden,
        "game_order": visible_games + hidden_sports + stock_order,
    })

    return autosave_response("/games")


@app.route("/save_cfb_conferences", methods=["POST"])
@login_required
def save_cfb_conferences():
    update_settings({
        "cfb": {
            "selected_conferences": _normalized_cfb_conferences(
                request.form.getlist("cfb_conferences")
            ),
        },
    })
    return autosave_response("/games?league=cfb")


@app.route("/save_soccer_leagues", methods=["POST"])
@login_required
def save_soccer_leagues():
    update_settings({
        "soccer": {
            "selected_leagues": _normalized_soccer_leagues(
                request.form.getlist("soccer_leagues")
            ),
        },
    })
    return autosave_response("/games?league=soccer")


@app.route("/save_stocks", methods=["POST"])
@login_required
def save_stocks():
    selected_stock_symbols = parse_symbol_list(
        request.form.getlist("stock_symbols")
    )
    stock_name_values = request.form.getlist("stock_names")
    stock_names = {}

    for index, symbol in enumerate(selected_stock_symbols):
        if index >= len(stock_name_values):
            break

        name = str(stock_name_values[index] or "").strip()
        if name:
            stock_names[symbol] = name[:80]

    shown = {
        str(symbol).strip().upper()
        for symbol in request.form.getlist("stock_shown")
        if str(symbol).strip()
    }

    settings = get_settings()
    previous_hidden = settings.get("hidden_games", [])
    previous_order = settings.get("game_order", [])
    kept_hidden = [
        game_id
        for game_id in previous_hidden
        if not _is_stock_id(game_id)
    ]
    kept_order = [
        game_id
        for game_id in previous_order
        if not _is_stock_id(game_id)
    ]

    stock_ids = [f"stocks:{symbol}" for symbol in selected_stock_symbols]
    stock_hidden = [
        f"stocks:{symbol}"
        for symbol in selected_stock_symbols
        if symbol not in shown
    ]

    update_settings({
        "stocks": {
            "symbols": selected_stock_symbols,
            "names": stock_names,
        },
        "hidden_games": kept_hidden + stock_hidden,
        "game_order": kept_order + stock_ids,
    })

    return autosave_response("/stocks")


@app.route("/save_settings", methods=["POST"])
@login_required
def save_settings():
    payload = {
        "scroll_speed": float(
            request.form["scroll_speed"]
        ),
        "brightness": int(
            request.form["brightness"]
        ),
        "refresh_interval": int(
            request.form["refresh_interval"]
        ),
        "fps": int(
            request.form["fps"]
        ),
    }

    if "timezone" in request.form:
        payload["timezone"] = normalize_timezone_setting(
            request.form.get("timezone")
        )

    user = current_user()
    if user and user["role"] == "root" and request.form.get("developer_form") == "1":
        payload["developer"] = {
            "test_games": (
                request.form.get("developer_test_games") == "1"
            ),
            "score_slide": (
                request.form.get("developer_score_slide") == "1"
            ),
        }

    update_settings(payload)

    return autosave_response("/settings")


@app.route("/settings/developer", methods=["POST"])
@login_required
def set_developer_access():
    user = current_user()
    if not user or user.get("role") != "root":
        return jsonify({
            "ok": False,
            "message": "Only the root profile can change developer options.",
        }), 403

    body = request.get_json(silent=True) or {}
    enabled = bool(body.get("enabled"))
    payload = {"developer_unlocked": enabled}
    if not enabled:
        current = get_developer_settings()
        payload["developer"] = {
            "test_games": False,
            "score_slide": current.get("score_slide", True),
        }
    update_settings(payload)
    return jsonify({
        "ok": True,
        "developer_unlocked": enabled,
    })


@app.route("/api/timezone")
@login_required
def api_timezone():
    return jsonify(timezone_status())


@lru_cache(maxsize=1)
def _timezone_catalog_json() -> str:
    payload = [
        {
            "label": group,
            "choices": [
                {"v": value, "l": label}
                for value, label in choices
            ],
        }
        for group, choices in timezone_choice_groups()
    ]
    return json.dumps(payload, separators=(",", ":"))


def _timezone_options_html(selected):
    """Common zones only. The full list is added after the page paints."""
    parts = []
    auto_selected = " selected" if selected == "auto" else ""
    parts.append(
        f'<option value="auto"{auto_selected}>Automatic (network)</option>'
    )
    known = {"auto"}
    groups = timezone_choice_groups()
    common = groups[0][1] if groups else []
    parts.append('<optgroup label="Common">')
    for value, label in common:
        known.add(value)
        picked = " selected" if value == selected else ""
        parts.append(
            f'<option value="{escape(value)}"{picked}>'
            f"{escape(label)}</option>"
        )
    parts.append("</optgroup>")
    if selected not in known:
        parts.append(
            f'<option value="{escape(selected)}" selected>'
            f"{escape(timezone_label(selected))}</option>"
        )
    return "\n".join(parts)


def _timezone_picker_script() -> str:
    catalog = _timezone_catalog_json().replace("<", "\\u003c")
    return f"""
    <script type="application/json" id="timezone-catalog">{catalog}</script>
    <script>
    (function () {{
      var select = document.getElementById("timezone");
      var catalog = document.getElementById("timezone-catalog");
      if (!select || !catalog) return;

      function fill() {{
        if (select.dataset.full === "1") return;
        var groups;
        try {{
          groups = JSON.parse(catalog.textContent);
        }} catch (error) {{
          return;
        }}
        select.dataset.full = "1";
        var current = select.value;
        select.replaceChildren();
        var automatic = document.createElement("option");
        automatic.value = "auto";
        automatic.textContent = "Automatic (network)";
        select.appendChild(automatic);
        groups.forEach(function (group) {{
          var box = document.createElement("optgroup");
          box.label = group.label;
          (group.choices || []).forEach(function (choice) {{
            var option = document.createElement("option");
            option.value = choice.v;
            option.textContent = choice.l;
            box.appendChild(option);
          }});
          select.appendChild(box);
        }});
        select.value = current;
        catalog.remove();
      }}

      select.addEventListener("pointerdown", fill);
      select.addEventListener("focus", fill);
    }})();
    </script>
    """


@app.route("/api/stocks/search")
@login_required
def api_stocks_search():
    query = request.args.get("q", "")

    try:
        results = search_symbols(query)
    except Exception:
        return jsonify({
            "results": [],
            "error": "search_failed",
        }), 502

    return jsonify({
        "results": results,
    })


@app.route(
    "/api/update/status",
    methods=["GET"],
)
@login_required
def api_update_status():
    service_state = update_service_state()
    service_active = service_state_is_running(
        service_state
    )

    if service_state == "unknown":
        status = read_status()
    else:
        status = reconcile_status(
            service_running=service_active
        )

    status["service_active"] = service_active
    status["release"] = peek_release_info(
        get_scorecast_version()
    )

    return jsonify(status)

@app.route(
    "/api/update/start",
    methods=["POST"],
)
@login_required
def api_start_update():
    user = current_user()
    if not user or user.get("role") != "root":
        return jsonify({
            "ok": False,
            "message": "Only the root profile can install updates.",
        }), 403

    service_state = update_service_state()

    if service_state == "unknown":
        return jsonify({
            "ok": False,
            "message": (
                "GameLine Pro could not check whether "
                "an update is already running."
            ),
        }), 500

    service_active = service_state_is_running(
        service_state
    )
    status = reconcile_status(
        service_running=service_active
    )

    if (
        str(status.get("state", "")).strip().lower()
        in ACTIVE_UPDATE_STATES
        or service_active
    ):
        return jsonify({
            "ok": False,
            "message": (
                "A GameLine Pro update is already running."
            ),
        }), 409

    requested_version = str(status.get("version") or "")
    mark_start_requested(requested_version)

    try:
        result = subprocess.run(
            [
                "/usr/bin/systemctl",
                "start",
                "--no-block",
                UPDATE_SERVICE_NAME,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

    except subprocess.TimeoutExpired:
        write_status(
            "failed",
            "Starting the updater timed out.",
            requested_version,
        )
        return jsonify({
            "ok": False,
            "message": (
                "Starting the updater timed out."
            ),
        }), 500

    except OSError as error:
        write_status(
            "failed",
            f"Unable to start updater: {error}",
            requested_version,
        )
        return jsonify({
            "ok": False,
            "message": (
                f"Unable to start updater: {error}"
            ),
        }), 500

    if result.returncode != 0:
        error_message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "systemctl returned an error"
        )
        write_status(
            "failed",
            error_message,
            requested_version,
        )

        return jsonify({
            "ok": False,
            "message": error_message,
        }), 500

    return jsonify({
        "ok": True,
        "message": (
            "GameLine Pro update started."
        ),
    })


from bets.web import register_bet_routes
from bets.store import init_store as init_bet_store
from setup.web import register_setup_routes

try:
    init_bet_store()
except Exception as error:
    print("Bet store init deferred:", error)

register_bet_routes(
    app,
    login_required=login_required,
    current_user=current_user,
    page_header=page_header,
    page_styles=page_styles,
)

register_setup_routes(
    app,
    render_auth_page=render_auth_page,
    establish_session=establish_session,
)
