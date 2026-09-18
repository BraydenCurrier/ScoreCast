import subprocess
from datetime import timedelta
from pathlib import Path

from functools import wraps
from html import escape

from flask import Flask, abort, request, redirect, send_file, session, jsonify, url_for

from common.settings import get_settings, update_settings
from common.users import (
    BOOTSTRAP_PASSWORD,
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
from common.logo_store import get_logo_variant_path, get_selected_logo_variant, get_teams_with_logo_variants, get_teams_with_logos

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

from updater.status import read_status

app = Flask(__name__)
app.secret_key = get_or_create_web_secret()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 86400

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

def is_update_service_active() -> bool:
    try:
        result = subprocess.run(
            [
                "/usr/bin/systemctl",
                "is-active",
                "--quiet",
                UPDATE_SERVICE_NAME,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

        return result.returncode == 0

    except (
        OSError,
        subprocess.TimeoutExpired,
    ):
        return False

def get_scorecast_version() -> str:
    """Return the version of the installed ScoreCast release."""
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
            if session.get("setup_pending"):
                return redirect("/setup")
            return redirect("/login")

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
    games_active = "active" if active_page == "games" else ""
    focus_active = "active" if active_page == "focus" else ""
    fantasy_active = "active" if active_page == "fantasy" else ""
    alerts_active = "active" if active_page == "alerts" else ""
    logos_active = "active" if active_page == "logos" else ""
    settings_active = "active" if active_page == "settings" else ""
    favorites_active = "active" if active_page == "favorites" else ""
    profiles_active = "active" if active_page == "profiles" else ""

    user = current_user()
    username = escape(user["username"]) if user else "Guest"
    is_root = bool(user and user["role"] == "root")
    root_badge = '<span class="account-role">Root</span>' if is_root else ""
    profiles_tab = (
        f'<a class="tab {profiles_active}" href="/profiles">Profiles</a>'
        if is_root
        else ""
    )

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
    <header class="topbar">
        <div class="topbar-main">
            <div class="brand-lockup brand-lockup-compact">
                <div class="brand-mark" aria-hidden="true">SC</div>
                <h1 class="title">ScoreCast</h1>
            </div>

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
                    <svg
                        viewBox="0 0 24 24"
                        aria-hidden="true"
                    >
                        <path
                            d="
                                M12 2
                                V12
                                M7.05 4.93
                                A9 9 0 1 0 16.95 4.93
                            "
                        />
                    </svg>
                </button>
            </form>
        </div>

        <div class="topbar-account">
            <div class="account-chip">
                <span class="account-name">{username}</span>
                {root_badge}
            </div>
            <a class="logout-link" href="/logout">Sign out</a>
        </div>
    </header>

    <nav class="tabs" aria-label="ScoreCast">
        <a class="tab {games_active}" href="/games">Games</a>
        <a class="tab {focus_active}" href="/focus">Focus</a>
        <a class="tab {fantasy_active}" href="/fantasy">Fantasy</a>
        <a class="tab {alerts_active}" href="/alerts">Alerts</a>
        <a class="tab {logos_active}" href="/logos">Logos</a>
        <a class="tab {settings_active}" href="/settings">Settings</a>
        <a class="tab {favorites_active}" href="/favorites">Favorites</a>
        {profiles_tab}
    </nav>
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

        <meta name="theme-color" content="#0b0c10">

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
            content="ScoreCast"
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
            color="#55f18b"
        >

        <meta property="og:type" content="website">
        <meta property="og:title" content="ScoreCast">

        <meta
            property="og:description"
            content="Live sports on your LED matrix."
        >

        <meta
            property="og:image"
            content="/static/social/scorecast-og-1200x630.png"
        >

        {page_styles()}
    </head>
    """

def page_styles():
    return """
    <link rel="stylesheet" href="/static/app.css?v=7">
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
    """



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

    if class_name == "FantasyMatchup":
        return "fantasy", "FANTASY"
    
    return "mlb", "MLB"

def get_game_id(game):
    league_key, _ = get_game_league(game)

    if league_key == "soccer":
        event_id = str(
            getattr(game, "event_id", "") or ""
        ).strip()

        if event_id:
            return f"{league_key}:{event_id}"

    if league_key == "stocks":
        symbol = str(
            getattr(game, "symbol", "")
            or getattr(game, "away", "")
        ).strip().upper()

        if symbol:
            return f"{league_key}:{symbol}"

    return f"{league_key}:{game.away}@{game.home}"

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

def get_display_status(game, league_key):
    status = getattr(game, "status", "")

    if league_key == "soccer":
        league_name = str(
            getattr(game, "league_short", "")
            or getattr(game, "league_name", "")
            or "Soccer"
        )

        if status in ("Scheduled", "STATUS_SCHEDULED"):
            return league_name

        if status:
            return f"{status} · {league_name}"

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

    if status == "STATUS_SCHEDULED":
        if league_key in ("nfl", "cfb"):
            return f"Week {getattr(game, 'week', 1)}"

        return "Scheduled"

    return status


def render_auth_page(title, body):
    return f"""
<!DOCTYPE html>
<html>
{page_head(title)}
<body class="auth-body">
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


@app.route("/login", methods=["GET", "POST"])
def login():
    try:
        profiles_exist = has_users()
    except UserStoreError as exc:
        body = f"""
            <div class="auth-intro">
                <div class="brand-lockup">
                    <div class="brand-mark" aria-hidden="true">SC</div>
                    <div>
                        <div class="brand-name">ScoreCast</div>
                        <div class="brand-tag">Unable to load profiles</div>
                    </div>
                </div>
            </div>
            <div class="card login-card">
                <div class="error">{escape(str(exc))}</div>
            </div>
        """
        return render_auth_page("ScoreCast Login", body), 500

    if profiles_exist:
        user = current_user()
        if user is not None:
            return redirect("/games")
    elif session.get("setup_pending"):
        return redirect("/setup")

    error = ""
    needs_setup = not profiles_exist

    if request.method == "POST":
        if needs_setup:
            if request.form.get("password") == BOOTSTRAP_PASSWORD:
                session.clear()
                session.permanent = True
                session["setup_pending"] = True
                return redirect("/setup")

            error = "Invalid password"
        else:
            user = authenticate(
                request.form.get("username", ""),
                request.form.get("password", ""),
            )

            if user is not None:
                establish_session(user)
                return redirect("/games")

            error = "Invalid username or password"

    error_html = f"<div class='error'>{escape(error)}</div>" if error else ""

    if needs_setup:
        form_fields = """
            <p class="auth-hint">
                This display has no profiles yet. Enter the setup password
                <strong>ticker123</strong> to create the root account.
            </p>
            <label class="field-label" for="setup_password">Setup password</label>
            <input
                class="auth-input"
                id="setup_password"
                type="password"
                name="password"
                placeholder="••••••••"
                autofocus
            >
        """
        button_label = "Continue"
        subtitle = "Create the first profile"
    else:
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
        subtitle = "Sign in to this display"

    body = f"""
        <div class="auth-intro">
            <div class="brand-lockup">
                <div class="brand-mark" aria-hidden="true">SC</div>
                <div>
                    <div class="brand-name">ScoreCast</div>
                    <div class="brand-tag">{subtitle}</div>
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

    return render_auth_page("ScoreCast Login", body)


@app.route("/setup", methods=["GET", "POST"])
def setup_root_profile():
    if has_users():
        return redirect("/login")

    if not session.get("setup_pending"):
        return redirect("/login")

    error = ""

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if password != confirm_password:
            error = "Passwords do not match."
        else:
            try:
                user = create_user(username, password, role="root")
            except UserError as exc:
                error = str(exc)
            else:
                establish_session(user)
                return redirect("/games")

    error_html = f"<div class='error'>{escape(error)}</div>" if error else ""

    body = f"""
        <div class="auth-intro">
            <div class="brand-lockup">
                <div class="brand-mark" aria-hidden="true">SC</div>
                <div>
                    <div class="brand-name">ScoreCast</div>
                    <div class="brand-tag">Create the root profile</div>
                </div>
            </div>
        </div>
        <div class="card login-card">
            <p class="auth-hint">
                This first account can add other people later.
                The setup password will no longer work after this.
            </p>
            {error_html}
            <form method="POST">
                <label class="field-label" for="root_username">Username</label>
                <input
                    class="auth-input"
                    id="root_username"
                    type="text"
                    name="username"
                    placeholder="Username"
                    autocomplete="username"
                    autofocus
                    value="{escape(request.form.get('username', ''), quote=True)}"
                >
                <label class="field-label" for="root_password">Password</label>
                <input
                    class="auth-input"
                    id="root_password"
                    type="password"
                    name="password"
                    placeholder="At least 8 characters"
                    autocomplete="new-password"
                >
                <label class="field-label" for="root_password_confirm">Confirm password</label>
                <input
                    class="auth-input"
                    id="root_password_confirm"
                    type="password"
                    name="confirm_password"
                    placeholder="Re-enter password"
                    autocomplete="new-password"
                >
                <button class="save-button" type="submit">
                    Create profile
                </button>
            </form>
        </div>
    """

    return render_auth_page("Create root profile", body)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/profiles", methods=["GET", "POST"])
@root_required
def profiles_page():
    error = ""
    saved_message = ""

    if request.args.get("saved") == "1":
        saved_message = '<div class="hint" style="margin-bottom:12px;">Profile created.</div>'
    elif request.args.get("deleted") == "1":
        saved_message = '<div class="hint" style="margin-bottom:12px;">Profile deleted.</div>'
    if request.args.get("error"):
        error = request.args.get("error", "")

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if password != confirm_password:
            error = "Passwords do not match."
        else:
            try:
                create_user(username, password, role="user")
            except UserError as exc:
                error = str(exc)
            else:
                return redirect("/profiles?saved=1")

    error_html = f"<div class='error'>{escape(error)}</div>" if error else ""
    actor = current_user()
    actor_id = actor["id"] if actor else ""

    profile_rows = ""
    for user in list_users():
        is_root = user["role"] == "root"
        role_label = "Root" if is_root else "Profile"
        can_delete = user["id"] != actor_id and not is_root

        delete_control = ""
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
<!DOCTYPE html>
<html>
{page_head("ScoreCast Profiles")}
<body>
    <div class="page">
        {page_header("profiles")}

        <div class="card">
            <div class="card-title">Profiles</div>
            {saved_message}
            {profile_rows}
        </div>

        <form method="POST">
            <div class="card">
                <div class="card-title">Add profile</div>
                <div class="hint" style="margin-bottom:12px;">
                    New profiles can use the dashboard. Only the root user
                    can create or delete them.
                </div>
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
    </div>
</body>
</html>
    """


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
            url_for("profiles_page", error=str(exc))
        )

    return redirect("/profiles?deleted=1")

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

@app.route("/system/restart", methods=["POST"])
@login_required
def restart_scorecast():
    import threading
    import time

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
        "message": "ScoreCast is restarting.",
    })

@app.route("/games")
@login_required
def games():
    settings = get_settings()
    hidden = set(settings.get("hidden_games", []))

    game_rows = ""

    for game in latest_games:
        game_id = get_game_id(game)

        favorite_game = (
            is_favorite_game(
                game,
                settings
            )
        )

        checked = (
            "checked"
            if (
                favorite_game
                or game_id not in hidden
            )
            else ""
        )

        league_key, league_label = get_game_league(game)
        display_status = get_display_status(game, league_key)
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
        favorite_suffix = (
            " · Favorite" if favorite_game else ""
        )

        if league_key == "stocks":
            symbol = escape(
                str(getattr(game, "symbol", game.away))
            )
            name = str(getattr(game, "name", "") or "")
            price = float(getattr(game, "price", 0) or 0)
            matchup = symbol

            if name and name.upper() != symbol.upper():
                matchup = (
                    f"{symbol} · {escape(name)}"
                )

            details = (
                f"{price:.2f} · {safe_status}"
                f"{favorite_suffix}"
            )
        else:
            matchup = (
                f"{escape(str(game.away))} @ "
                f"{escape(str(game.home))}"
            )
            away_score = escape(
                str(getattr(game, "away_score", 0))
            )
            home_score = escape(
                str(getattr(game, "home_score", 0))
            )
            details = (
                f"{away_score} - {home_score} · "
                f"{safe_status}{favorite_suffix}"
            )

        game_rows += f"""
        <div class="game-row-container" draggable="true" data-id="{safe_game_id}" data-league="{league_key}" data-top25="{"true" if is_top_25 else "false"}" data-live="{"true" if is_live else "false"}">
            <label class="game-row">
                <input type="checkbox" name="game" value="{safe_game_id}" {checked} {"disabled" if favorite_game else ""}> 
                {f'<input type="hidden" name="game" value="{safe_game_id}">' if favorite_game else ''}
                <div class="game-info">
                    <div class="matchup">{matchup}</div>
                    <div class="details">
                        {details}
                    </div>
                </div>

                <div class="league-badge">
                    {league_label}
                </div>
            </label>
        </div>
        """

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
    <title>ScoreCast Games</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    {page_styles()}
</head>

<body>
    <div class="page">
        {page_header("games")}

        <form method="POST" action="/save_games">
            <div class="card" id="games_card">
                <div class="card-title">Games</div>

                <input
                    class="search-input"
                    type="text"
                    id="game_search"
                    placeholder="Search games..."
                    oninput="filterGames()"
                >

                <div class="filter-row">
                    <select id="league_filter" class="select-input" onchange="filterGames()">
                        <option value="selected">Selected Games</option>
                        <option value="all">All Sports</option>
                        <option value="mlb">MLB</option>
                        <option value="nfl">NFL</option>
                        <option value="cfb">CFB</option>
                        <option value="top25">Top 25 CFB</option>
                        <option value="soccer">Soccer</option>
                        <option value="stocks">Stocks</option>
                        <option value="nba">NBA</option>
                        <option value="nhl">NHL</option>
                        <option value="fantasy">Fantasy</option>
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
            </div>

            <button class="save-button" type="submit">
                Save Games
            </button>
        </form>
    </div>

    <script>
        function getCurrentLeagueFilter() {{
            const filter = document.getElementById("league_filter");
            return filter ? filter.value : "all";
        }}

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

            document.querySelectorAll(".game-row-container").forEach(function(row) {{
                const text = row.innerText.toLowerCase();
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

                row.style.display = (
                    matchesSearch
                    && matchesFilter
                    && matchesLive
                ) ? "" : "none";
            }});
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
        }}

        const container = document.getElementById("games_card");

        container.addEventListener("dragstart", function(e) {{
            const row = e.target.closest(".game-row-container");

            if (row) {{
                row.classList.add("dragging");

                if (e.dataTransfer) {{
                    e.dataTransfer.setData("text/plain", "");
                }}
            }}
        }});

        container.addEventListener("dragend", function(e) {{
            const row = e.target.closest(".game-row-container");

            if (row) {{
                row.classList.remove("dragging");
            }}
        }});

        container.addEventListener("dragover", function(e) {{
            e.preventDefault();

            const draggingItem = document.querySelector(".dragging");
            if (!draggingItem) return;

            const siblings = [...container.querySelectorAll(".game-row-container:not(.dragging)")]
                .filter(function(row) {{
                    return row.style.display !== "none";
                }});

            const nextSibling = siblings.find(sibling => {{
                const box = sibling.getBoundingClientRect();
                return e.clientY <= box.top + box.height / 2;
            }});

            if (nextSibling) {{
                container.insertBefore(draggingItem, nextSibling);
            }} else {{
                container.appendChild(draggingItem);
            }}
        }});

        document.querySelectorAll(
            'input[type="checkbox"][name="game"]'
        ).forEach(function(checkbox) {{
            checkbox.addEventListener(
                "change",
                handleGameSelectionChange
            );
        }});

        document.addEventListener("DOMContentLoaded", function () {{
            filterGames();
        }});
    </script>
</body>
</html>
    """

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

    selected_game_ids = set(
        str(value)
        for value in focus_settings.get(
            "nfl_game_ids",
            [],
        )
    )

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

    nfl_rows = ""

    for game in latest_games:
        league_key, _ = get_game_league(
            game
        )

        if league_key != "nfl":
            continue

        game_identifier = get_game_id(
            game
        )

        checked = (
            "checked"
            if game_identifier
            in selected_game_ids
            else ""
        )

        safe_id = escape(
            game_identifier,
            quote=True,
        )

        safe_away = escape(
            str(game.away)
        )

        safe_home = escape(
            str(game.home)
        )

        safe_status = escape(
            str(
                get_display_status(
                    game,
                    "nfl",
                )
            )
        )

        away_score = escape(
            str(
                getattr(
                    game,
                    "away_score",
                    0,
                )
            )
        )

        home_score = escape(
            str(
                getattr(
                    game,
                    "home_score",
                    0,
                )
            )
        )

        nfl_rows += f"""
        <label class="game-row">
            <input
                type="checkbox"
                name="focus_nfl_game"
                value="{safe_id}"
                {checked}
            >

            <div class="game-info">
                <div class="matchup">
                    {safe_away} @ {safe_home}
                </div>

                <div class="details">
                    {away_score} - {home_score}
                    · {safe_status}
                </div>
            </div>

            <div class="league-badge">
                NFL
            </div>
        </label>
        """

    if not nfl_rows:
        nfl_rows = """
        <div class="empty">
            No NFL games loaded yet.
        </div>
        """

    enabled_checked = (
        "checked"
        if focus_enabled
        else ""
    )

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>ScoreCast Focus Mode</title>
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
        >
            <div class="card">
                <div class="card-title">
                    NFL Focus Mode
                </div>

                <div class="hint"
                     style="margin-bottom: 14px;">
                    Replace the normal ticker with a
                    full-screen NFL scoreboard.
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
                        NFL game is selected.
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-title">
                    NFL Games
                </div>

                <div
                    class="hint"
                    style="margin-bottom: 14px;"
                >
                    Select one or more games to display
                    in Focus Mode.
                </div>

                {nfl_rows}
            </div>

            <button
                class="save-button"
                type="submit"
            >
                Save Focus Mode
            </button>
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
    selected_game_ids = (
        request.form.getlist(
            "focus_nfl_game"
        )
    )

    valid_nfl_game_ids = {
        get_game_id(game)
        for game in latest_games
        if get_game_league(game)[0]
        == "nfl"
    }

    selected_game_ids = [
        game_identifier
        for game_identifier
        in selected_game_ids
        if game_identifier
        in valid_nfl_game_ids
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
            "nfl_game_ids": (
                selected_game_ids
            ),
            "rotation_seconds": (
                rotation_seconds
            ),
        },
    })

    return redirect("/focus")

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
        selected_teams = [
            abbreviation
            for abbreviation
            in available_teams
            if request.form.get(
                f"alert_team:{abbreviation}"
            ) == "on"
        ]

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

        teams_by_league = alerts.get(
            "teams",
            {},
        )

        if not isinstance(
            teams_by_league,
            dict,
        ):
            teams_by_league = {}

        # Import existing NFL selections from the
        # old NFL-only settings format.
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

        updated_alerts = dict(alerts)
        updated_alerts.update({
            "enabled": (
                request.form.get("enabled") == "on"
            ),
            "teams": teams_by_league,
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
            "chant_frame_seconds": form_float(
                "chant_frame_seconds",
                0.9,
                0.2,
                3.0,
            ),
            "details_frame_seconds": form_float(
                "details_frame_seconds",
                4.0,
                1.0,
                15.0,
            ),
        })

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

        return redirect(
            url_for(
                "alerts_page",
                league=requested_league,
                saved="1",
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

                <div
                    class="team-color"
                    style="
                        background:
                            rgb{definition.primary};
                        border-color:
                            rgb{definition.accent};
                    "
                ></div>

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

    chant_seconds = escape(str(
        alerts.get(
            "chant_frame_seconds",
            0.9,
        )
    ))

    details_seconds = escape(str(
        alerts.get(
            "details_frame_seconds",
            4.0,
        )
    ))

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>ScoreCast Alerts</title>

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

            <form method="POST">
                <div class="card">
                    <div class="card-title">
                        Alerts
                    </div>

                    <div
                        style="
                            margin-bottom: 16px;
                        "
                    >
                        <label
                            for="alert_league"
                            style="
                                display: block;
                                margin-bottom: 7px;
                                font-weight: 700;
                            "
                        >
                            League
                        </label>

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
                                    chant_frame_seconds
                                "
                            >
                                Word duration
                            </label>

                            <input
                                class="
                                    alert-control-input
                                "
                                id="
                                    chant_frame_seconds
                                "
                                name="
                                    chant_frame_seconds
                                "
                                type="number"
                                min="0.2"
                                max="3"
                                step="0.1"
                                value="{chant_seconds}"
                            >
                        </div>

                        <div
                            class="
                                alert-control-description
                            "
                        >
                            Seconds each animated alert
                            word stays on the display.
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
                                    details_frame_seconds
                                "
                            >
                                Details duration
                            </label>

                            <input
                                class="
                                    alert-control-input
                                "
                                id="
                                    details_frame_seconds
                                "
                                name="
                                    details_frame_seconds
                                "
                                type="number"
                                min="1"
                                max="15"
                                step="0.5"
                                value="{details_seconds}"
                            >
                        </div>

                        <div
                            class="
                                alert-control-description
                            "
                        >
                            Seconds the final alert
                            screen remains visible.
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

                <button
                    class="
                        save-button
                        alerts-save
                    "
                    type="submit"
                >
                    Save {league_label} Alerts
                </button>
            </form>
        </div>

        <script>
            function setAllAlertTeams(checked) {{
                document.querySelectorAll(
                    'input[name^="alert_team:"]'
                ).forEach(function (input) {{
                    input.checked = checked;
                }});
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

                    selected_leagues = request.form.getlist(
                        "selected_leagues"
                    )

                    valid_league_ids = {
                        str(league.get("league_id"))
                        for league in leagues
                    }

                    selected_leagues = [
                        league_id
                        for league_id in selected_leagues
                        if league_id in valid_league_ids
                    ]

                    update_settings({
                        "fantasy": {
                            "enabled": (
                                request.form.get("enabled") == "on"
                            ),
                            "provider": "sleeper",
                            "username": (
                                user.get("username")
                                or username
                            ),
                            "user_id": user.get("user_id", ""),
                            "season": season,
                            "refresh_interval": 120,
                            "selected_leagues": selected_leagues,
                        }
                    })

                    return redirect("/fantasy?saved=1")

            except Exception as exc:
                error = f"Unable to connect to Sleeper: {exc}"

    settings = get_settings()
    fantasy = settings.get("fantasy", {})

    leagues = []

    if fantasy.get("user_id"):
        try:
            leagues = get_user_leagues(
                fantasy["user_id"],
                fantasy.get("season", "2026"),
            )
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

        checked = (
            "checked"
            if not selected or league_id in selected
            else ""
        )

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
        league_rows = """
        <div class="empty">
            Connect your Sleeper account to load leagues.
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
    <title>ScoreCast Fantasy</title>
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

        <form method="POST">
            <div class="card">
                <div class="card-title">Sleeper Account</div>

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
                >
            </div>

            <div class="card">
                <div class="card-title">Leagues</div>
                {league_rows}
            </div>

            <button class="save-button" type="submit">
                Save Fantasy Settings
            </button>
        </form>
    </div>
</body>
</html>
"""

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
        max_age=60,
    )

@app.route("/logos")
@login_required
def logos_page():
    settings = get_settings()

    league_labels = {
        "mlb": "MLB",
        "nfl": "NFL",
        "cfb": "College Football",
        "nba": "NBA",
        "nhl": "NHL",
        "soccer": "Soccer",
    }

    teams_by_league = {}

    for league in league_labels:
        teams = get_teams_with_logo_variants(
            league,
        )

        if teams:
            teams_by_league[league] = teams

    requested_league = (
        request.args.get("league", "")
        .strip()
        .lower()
    )

    if requested_league in teams_by_league:
        selected_league = requested_league
    elif teams_by_league:
        selected_league = next(iter(teams_by_league))
    else:
        selected_league = ""

    league_options = ""

    for league, label in league_labels.items():
        if league not in teams_by_league:
            continue

        selected = (
            "selected"
            if league == selected_league
            else ""
        )

        league_options += f"""
        <option
            value="{escape(league, quote=True)}"
            {selected}
        >
            {escape(label)}
        </option>
        """

    team_rows = ""

    if selected_league:
        league_teams = teams_by_league.get(
            selected_league,
            {},
        )

        for team, variants in sorted(
            league_teams.items()
        ):
            team = str(team).upper()

            selected_variant = (
                get_selected_logo_variant(
                    settings,
                    selected_league,
                    team,
                )
            )

            if selected_variant not in variants:
                selected_variant = "current"

            variant_options = ""

            for variant in variants:
                variant = str(variant)

                selected = (
                    "selected"
                    if variant == selected_variant
                    else ""
                )

                variant_label = (
                    variant
                    .replace("_", " ")
                    .replace("-", " ")
                    .title()
                )

                variant_options += f"""
                <option
                    value="{escape(variant, quote=True)}"
                    {selected}
                >
                    {escape(variant_label)}
                </option>
                """

            safe_team = escape(
                team,
                quote=True,
            )
            safe_league = escape(
                selected_league,
                quote=True,
            )
            safe_variant = escape(
                str(selected_variant),
                quote=True,
            )

            preview_url = url_for(
                "logo_preview",
                league=selected_league,
                team=team,
                variant=selected_variant,
            )

            team_rows += f"""
            <div class="logo-team-row">
                <div class="logo-preview-box">
                    <img
                        class="logo-preview"
                        id="logo-preview-{safe_team}"
                        src="{preview_url}"
                        alt="{safe_team} logo preview"
                    >
                </div>

                <div class="logo-team-controls">
                    <div class="logo-team-name">
                        {safe_team}
                    </div>

                    <select
                        class="logo-variant-select"
                        name="logo:{safe_team}"
                        data-league="{safe_league}"
                        data-team="{safe_team}"
                        data-preview-id="
                            logo-preview-{safe_team}
                        "
                    >
                        {variant_options}
                    </select>
                </div>
            </div>
            """

    if not team_rows:
        team_rows = """
        <div class="empty">
            No teams with alternate logos were found.
        </div>
        """

    saved_message = ""

    if request.args.get("saved") == "1":
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
    <title>ScoreCast Logos</title>
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
                    Only leagues containing teams with
                    alternate logos are listed.
                </div>
                '''
                if league_options
                else '''
                <div class="empty">
                    No alternate logos were found.
                </div>
                '''
            }
        </div>

        <form method="POST" action="/save_logos">
            <input
                type="hidden"
                name="league"
                value="{safe_selected_league}"
            >

            <div class="card">
                <div class="card-title">
                    Team Logos
                </div>

                {team_rows}
            </div>

            {
                '''
                <button
                    class="save-button"
                    type="submit"
                >
                    Save Logos
                </button>
                '''
                if selected_league
                else ""
            }
        </form>
    </div>

    <script>
        const leagueSelector =
            document.getElementById(
                "logo_league"
            );

        if (leagueSelector) {{
            leagueSelector.addEventListener(
                "change",
                function () {{
                    const league =
                        encodeURIComponent(
                            leagueSelector.value
                        );

                    window.location.href =
                        "/logos?league=" + league;
                }}
            );
        }}

        document.querySelectorAll(
            ".logo-variant-select"
        ).forEach(function (selector) {{
            selector.addEventListener(
                "change",
                function () {{
                    const league =
                        encodeURIComponent(
                            selector.dataset.league
                        );

                    const team =
                        encodeURIComponent(
                            selector.dataset.team
                        );

                    const variant =
                        encodeURIComponent(
                            selector.value
                        );

                    const previewId = (
                        selector.dataset.previewId
                        || ""
                    ).trim();

                    const preview =
                        document.getElementById(
                            previewId
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
        }});
    </script>
</body>
</html>
    """

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

    available_teams = (
        get_teams_with_logo_variants(
            league,
        )
    )

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

    return redirect(
        url_for(
            "logos_page",
            league=league,
            saved="1",
        )
    )

@app.route("/settings")
@login_required
def settings_page():
    software_version = get_scorecast_version()
    settings = get_settings()

    cfb_settings = settings.get("cfb", {})
    soccer_settings = settings.get("soccer", {})

    selected_cfb_conferences = {
        str(group_id)
        for group_id in cfb_settings.get(
            "selected_conferences",
            ["80"],
        )
    }

    selected_soccer_leagues = {
        str(league_id)
        for league_id in soccer_settings.get(
            "selected_leagues",
            DEFAULT_SOCCER_LEAGUES,
        )
    }

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
        safe_name_label = escape(name) if name else "Tracked quote"

        stock_watchlist_rows += f"""
        <div class="stock-watch-row">
            <input type="hidden" name="stock_symbols" value="{safe_symbol}">
            <input type="hidden" name="stock_names" value="{safe_name}">
            <div class="game-info">
                <div class="matchup">{escape(symbol)}</div>
                <div class="details">{safe_name_label}</div>
            </div>
            <button
                type="button"
                class="stock-remove-button"
                aria-label="Remove {safe_symbol}"
            >Remove</button>
        </div>
        """

    stock_empty_display = (
        "none" if selected_stock_symbols else "block"
    )

    soccer_league_rows = ""

    for league_id, league_name in SOCCER_LEAGUE_OPTIONS:
        checked = (
            "checked"
            if league_id in selected_soccer_leagues
            else ""
        )

        soccer_league_rows += f"""
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

    cfb_conference_rows = ""

    for group_id, conference_name in CFB_CONFERENCE_OPTIONS:
        checked = (
            "checked"
            if group_id in selected_cfb_conferences
            else ""
        )

        cfb_conference_rows += f"""
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

    scroll_speed = settings.get("scroll_speed", 0.4)
    brightness = settings.get("brightness", 50)
    refresh_interval = settings.get("refresh_interval", 120)
    fps = settings.get("fps", 60)

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>ScoreCast Settings</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    {page_styles()}
</head>

<body>
    <div class="page">
        {page_header("settings")}

        <form method="POST" action="/save_settings">
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
                        Scroll speed is measured in pixels per second.
                    </div>
                </div>

                <div class="setting-group">
                    <div class="setting-header">
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
                        Higher values make scrolling smoother.
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
            </div>

            <div class="card">
                <div class="card-title">College Football Conferences</div>

                <div class="hint" style="margin-bottom: 12px;">
                    Choose All FBS or select one or more individual conferences.
                    Games involving a selected conference will appear on the Games page.
                </div>

                {cfb_conference_rows}
            </div>

            <div class="card">
                <div class="card-title">Soccer Leagues</div>

                <div class="hint" style="margin-bottom: 12px;">
                    Choose the soccer competitions to load.
                    Premier League, Champions League, and MLS
                    are on by default.
                </div>

                {soccer_league_rows}
            </div>

            <div class="card">
                <div class="card-title">Stock Ticker</div>

                <div class="hint" style="margin-bottom: 12px;">
                    Search for a company or ticker, then tap
                    it to add it to the board. You can track
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

                <div id="stock_watchlist">
                    {stock_watchlist_rows}
                </div>
            </div>

            <div class="card">
                <div class="card-title">
                    Software Update
                </div>

                <div class="settings-version">
                    <div class="settings-version-label">
                        Software Version
                    </div>

                    <div class="settings-version-value">
                        ScoreCast v{escape(software_version)}
                    </div>
                </div>

                <div class="hint">
                    Install the latest stable ScoreCast
                    release from GitHub.
                </div>

                <div
                    id="update_status_box"
                    style="
                        margin-top: 14px;
                        padding: 12px;
                        border-radius: 8px;
                        background: rgba(255, 255, 255, 0.05);
                    "
                >
                    <div
                        id="update_status_message"
                        style="font-weight: 600;"
                    >
                        Loading update status...
                    </div>

                    <div
                        id="update_status_details"
                        class="hint"
                        style="margin-top: 5px;"
                    ></div>
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

                <button
                    type="button"
                    id="update_button"
                    class="save-button"
                    style="margin-top: 14px;"
                    onclick="startScoreCastUpdate()"
                >
                    Check and Install Update
                </button>
            </div>


            <div class="card">
                <div class="card-title">
                    System
                </div>

                <div class="hint">
                    Restart the ScoreCast application without rebooting
                    the Raspberry Pi. The display and dashboard will
                    briefly disconnect.
                </div>

                <div
                    id="system_restart_status"
                    class="hint"
                    style="margin-top: 12px;"
                ></div>

                <button
                    type="button"
                    id="system_restart_button"
                    class="save-button"
                    style="margin-top: 14px;"
                    onclick="restartScoreCast()"
                >
                    Restart ScoreCast
                </button>
            </div>

            <button class="save-button" type="submit">
                Save Settings
            </button>
        </form>
    </div>

    <script>

        const updateStateLabels = {{
            idle: "Ready",
            checking: "Checking GitHub",
            available: "Update Available",
            downloading: "Preparing Release",
            installing: "Installing Dependencies",
            validating: "Validating Release",
            restarting: "Restarting ScoreCast",
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

            button.disabled = (
                active
                || updateStarting
            );

            button.textContent = active
                ? "Updating…"
                : "Check and Install Update";

            container.style.display = (
                active
                || terminal
            )
                ? "block"
                : "none";

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
                        "Reconnecting to ScoreCast…"
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

        async function startScoreCastUpdate() {{
            const confirmed = window.confirm(
                "Install the latest stable ScoreCast release? "
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
                        "Check and Install Update"
                    );
                }}
            }}
        }}


        async function restartScoreCast() {{
            const confirmed = window.confirm(
                "Restart ScoreCast? "
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
                    "Restart requested. Waiting for ScoreCast to come back online…"
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
                        // ScoreCast is still restarting.
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
                    button.textContent = "Restart ScoreCast";
                }}
            }}
        }}

        function bindNumberToSlider(numberId, sliderId) {{
            const number = document.getElementById(numberId);
            const slider = document.getElementById(sliderId);

            number.addEventListener("input", function() {{
                slider.value = number.value;
            }});
        }}

        function setupStockSearch() {{
            const search = document.getElementById("stock_search");
            const results = document.getElementById("stock_search_results");
            const list = document.getElementById("stock_watchlist");
            const empty = document.getElementById("stock_watchlist_empty");
            const maxSymbols = {MAX_SYMBOLS};

            if (!search || !results || !list) {{
                return;
            }}

            let timer = null;
            let requestId = 0;

            function selectedSymbols() {{
                return Array.from(
                    list.querySelectorAll('input[name="stock_symbols"]')
                ).map(function(input) {{
                    return input.value;
                }});
            }}

            function refreshEmpty() {{
                if (!empty) {{
                    return;
                }}

                empty.style.display = selectedSymbols().length
                    ? "none"
                    : "block";
            }}

            function hideResults() {{
                results.hidden = true;
                results.innerHTML = "";
            }}

            function addStock(symbol, name) {{
                symbol = String(symbol || "").toUpperCase();
                name = String(name || "").trim();

                if (!symbol) {{
                    return;
                }}

                if (selectedSymbols().indexOf(symbol) !== -1) {{
                    search.value = "";
                    hideResults();
                    return;
                }}

                if (selectedSymbols().length >= maxSymbols) {{
                    results.innerHTML = (
                        '<div class="stock-search-empty">'
                        + "You can track "
                        + maxSymbols
                        + " stocks.</div>"
                    );
                    results.hidden = false;
                    return;
                }}

                const row = document.createElement("div");
                row.className = "stock-watch-row";

                const symbolInput = document.createElement("input");
                symbolInput.type = "hidden";
                symbolInput.name = "stock_symbols";
                symbolInput.value = symbol;

                const nameInput = document.createElement("input");
                nameInput.type = "hidden";
                nameInput.name = "stock_names";
                nameInput.value = name;

                const info = document.createElement("div");
                info.className = "game-info";

                const matchup = document.createElement("div");
                matchup.className = "matchup";
                matchup.textContent = symbol;

                const details = document.createElement("div");
                details.className = "details";
                details.textContent = name || "Tracked quote";

                info.appendChild(matchup);
                info.appendChild(details);

                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "stock-remove-button";
                remove.textContent = "Remove";
                remove.setAttribute(
                    "aria-label",
                    "Remove " + symbol
                );

                row.appendChild(symbolInput);
                row.appendChild(nameInput);
                row.appendChild(info);
                row.appendChild(remove);
                list.appendChild(row);

                search.value = "";
                hideResults();
                refreshEmpty();
            }}

            function renderResults(items) {{
                results.innerHTML = "";

                if (!items.length) {{
                    results.innerHTML = (
                        '<div class="stock-search-empty">'
                        + "No matching stocks.</div>"
                    );
                    results.hidden = false;
                    return;
                }}

                items.forEach(function(item) {{
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "stock-search-result";

                    const symbol = document.createElement("div");
                    symbol.className = "matchup";
                    symbol.textContent = item.symbol;

                    const meta = document.createElement("div");
                    meta.className = "details";
                    meta.textContent = [
                        item.name,
                        item.exchange
                    ].filter(Boolean).join(" · ");

                    button.appendChild(symbol);
                    button.appendChild(meta);
                    button.addEventListener("click", function() {{
                        addStock(item.symbol, item.name);
                    }});
                    results.appendChild(button);
                }});

                results.hidden = false;
            }}

            async function lookup(query) {{
                const currentId = ++requestId;

                try {{
                    const response = await fetch(
                        "/api/stocks/search?q="
                        + encodeURIComponent(query),
                        {{
                            method: "GET",
                            cache: "no-store"
                        }}
                    );

                    if (!response.ok) {{
                        throw new Error("search failed");
                    }}

                    const payload = await response.json();

                    if (currentId !== requestId) {{
                        return;
                    }}

                    renderResults(payload.results || []);
                }} catch (error) {{
                    if (currentId !== requestId) {{
                        return;
                    }}

                    results.innerHTML = (
                        '<div class="stock-search-empty">'
                        + "Unable to search right now.</div>"
                    );
                    results.hidden = false;
                }}
            }}

            search.addEventListener("input", function() {{
                const query = search.value.trim();
                window.clearTimeout(timer);

                if (query.length < 1) {{
                    hideResults();
                    return;
                }}

                timer = window.setTimeout(function() {{
                    lookup(query);
                }}, 250);
            }});

            search.addEventListener("keydown", function(event) {{
                if (event.key === "Enter") {{
                    event.preventDefault();
                    const first = results.querySelector(
                        ".stock-search-result"
                    );
                    if (first) {{
                        first.click();
                    }}
                }}
            }});

            list.addEventListener("click", function(event) {{
                const button = event.target.closest(
                    ".stock-remove-button"
                );

                if (!button) {{
                    return;
                }}

                const row = button.closest(".stock-watch-row");

                if (row) {{
                    row.remove();
                    refreshEmpty();
                }}
            }});

            document.addEventListener("click", function(event) {{
                if (!event.target.closest(".stock-search")) {{
                    hideResults();
                }}
            }});
        }}

        setupStockSearch();

        function handleCfbConferenceChange(changedCheckbox) {{
            const allFbs = document.querySelector(
                'input[name="cfb_conferences"][value="80"]'
            );

            const individualConferences = Array.from(
                document.querySelectorAll(
                    'input[name="cfb_conferences"]:not([value="80"])'
                )
            );

            if (changedCheckbox.value === "80" && changedCheckbox.checked) {{
                individualConferences.forEach(function(checkbox) {{
                    checkbox.checked = false;
                }});

                return;
            }}

            if (
                changedCheckbox.value !== "80"
                && changedCheckbox.checked
                && allFbs
            ) {{
                allFbs.checked = false;
            }}

            const anySelected = Array.from(
                document.querySelectorAll(
                    'input[name="cfb_conferences"]:checked'
                )
            ).length > 0;

            if (!anySelected && allFbs) {{
                allFbs.checked = true;
            }}
        }}

        bindNumberToSlider("scroll_speed_number", "scroll_speed");
        bindNumberToSlider("brightness_number", "brightness");
        bindNumberToSlider("refresh_interval_number", "refresh_interval");
        bindNumberToSlider("fps_number", "fps");

        loadUpdateStatus();
        updateStatusTimer = setInterval(loadUpdateStatus, 2000);
    </script>
</body>
</html>
    """

@app.route("/favorites")
@login_required
def favorites_page():
    settings = get_settings()

    favorite_settings = (
        settings.get(
            "favorite_teams",
            {}
        )
    )

    rows = ""

    for (
        league_key,
        league_label
    ) in FAVORITE_LEAGUES:

        selected_values = (
            favorite_settings.get(
                league_key,
                []
            )
        )

        if isinstance(
            selected_values,
            str
        ):
            selected_values = [
                selected_values
            ]

        selected = {
            str(team)
            .strip()
            .upper()
            for team
            in selected_values
            if str(team).strip()
        }

        team_options = (
            get_favorite_team_options(
                league_key
            )
        )

        option_rows = ""

        for team in team_options:
            normalized_team = (
                str(team)
                .strip()
                .upper()
            )

            safe_team = escape(
                normalized_team,
                quote=True
            )

            checked = (
                "checked"
                if normalized_team
                in selected
                else ""
            )

            option_rows += f"""
            <label
                class="favorite-option"
            >
                <input
                    type="checkbox"
                    name="favorite_{league_key}"
                    value="{safe_team}"
                    {checked}
                >

                <span>
                    {escape(normalized_team)}
                </span>
            </label>
            """

        if not option_rows:
            option_rows = """
            <div class="empty">
                No teams are currently
                available for this league.
            </div>
            """

        rows += f"""
        <div class="control">

            <div class="control-top">
                <label>
                    {escape(league_label)}
                </label>
            </div>

            <div class="favorite-grid">
                {option_rows}
            </div>

            <div
                class="favorite-actions"
            >
                <button
                    class="secondary-button"
                    type="button"
                    onclick="
                        setLeagueFavorites(
                            '{league_key}',
                            true
                        )
                    "
                >
                    Select All
                </button>

                <button
                    class="secondary-button"
                    type="button"
                    onclick="
                        setLeagueFavorites(
                            '{league_key}',
                            false
                        )
                    "
                >
                    Clear
                </button>
            </div>

            <div class="hint">
                Every loaded game involving
                any selected team is always
                selected on the ticker.
            </div>

        </div>
        """

    return f"""
<!DOCTYPE html>

<html>

<head>

    <title>
        ScoreCast Favorites
    </title>

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

        {page_header("favorites")}

        <form
            method="POST"
            action="/save_favorites"
        >

            <div class="card">

                <div class="card-title">
                    Favorite Teams
                </div>

                <div
                    class="hint"
                    style="
                        margin-bottom:
                        16px;
                    "
                >
                    Select as many favorite
                    teams as you want in
                    each league. Whenever
                    one of those teams has
                    a loaded game,
                    ScoreCast keeps that
                    matchup selected
                    automatically.
                </div>

                {rows}

            </div>

            <button
                class="save-button"
                type="submit"
            >
                Save Favorites
            </button>

        </form>

    </div>

    <script>

        function setLeagueFavorites(
            league,
            checked
        ) {{

            document
                .querySelectorAll(
                    'input[name="favorite_'
                    + league
                    + '"]'
                )
                .forEach(
                    function(input) {{

                        input.checked =
                            checked;

                    }}
                );

        }}

    </script>

</body>

</html>
    """

@app.route(
    "/save_favorites",
    methods=["POST"]
)
@login_required
def save_favorites():

    favorites = {}

    for (
        league_key,
        _
    ) in FAVORITE_LEAGUES:

        submitted_teams = (
            request.form.getlist(
                f"favorite_{league_key}"
            )
        )

        valid_options = {
            option.upper()
            for option
            in get_favorite_team_options(
                league_key
            )
        }

        selected_teams = []
        seen = set()

        for team in submitted_teams:

            normalized_team = (
                str(team)
                .strip()
                .upper()
            )

            if (
                normalized_team
                and normalized_team
                in valid_options
                and normalized_team
                not in seen
            ):
                selected_teams.append(
                    normalized_team
                )

                seen.add(
                    normalized_team
                )

        favorites[
            league_key
        ] = selected_teams

    update_settings({
        "favorite_teams":
            favorites,
    })

    return redirect(
        "/favorites"
    )

@app.route("/save_games", methods=["POST"])
@login_required
def save_games():
    visible_games = request.form.getlist("game")

    all_game_ids = [
        get_game_id(game)
        for game in latest_games
    ]

    settings = get_settings()

    favorite_game_ids = {
        get_game_id(game)
        for game in latest_games
        if is_favorite_game(game, settings)
    }

    visible_games = list(dict.fromkeys(
        visible_games
        + [
            game_id
            for game_id in all_game_ids
            if game_id in favorite_game_ids
        ]
    ))

    hidden_games = [
        game_id
        for game_id in all_game_ids
        if game_id not in visible_games
    ]

    update_settings({
        "hidden_games": hidden_games,
        "game_order": visible_games + hidden_games
    })

    return redirect("/games")


@app.route("/save_settings", methods=["POST"])
@login_required
def save_settings():
    selected_cfb_conferences = request.form.getlist(
        "cfb_conferences"
    )

    valid_conference_ids = {
        group_id
        for group_id, _ in CFB_CONFERENCE_OPTIONS
    }

    selected_cfb_conferences = [
        group_id
        for group_id in selected_cfb_conferences
        if group_id in valid_conference_ids
    ]

    if not selected_cfb_conferences:
        selected_cfb_conferences = ["80"]

    if "80" in selected_cfb_conferences:
        selected_cfb_conferences = ["80"]

    selected_soccer_leagues = request.form.getlist(
        "soccer_leagues"
    )

    valid_soccer_ids = set(SOCCER_LEAGUES)

    selected_soccer_leagues = [
        league_id
        for league_id in selected_soccer_leagues
        if league_id in valid_soccer_ids
    ]

    if not selected_soccer_leagues:
        selected_soccer_leagues = list(
            DEFAULT_SOCCER_LEAGUES
        )

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

    update_settings({
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
        "cfb": {
            "selected_conferences": (
                selected_cfb_conferences
            ),
        },
        "soccer": {
            "selected_leagues": (
                selected_soccer_leagues
            ),
        },
        "stocks": {
            "symbols": selected_stock_symbols,
            "names": stock_names,
        },
    })

    return redirect("/settings")


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
    status = read_status()

    status["service_active"] = (
        is_update_service_active()
    )

    return jsonify(status)

@app.route(
    "/api/update/start",
    methods=["POST"],
)
@login_required
def api_start_update():
    status = read_status()

    if (
        status.get("state")
        in ACTIVE_UPDATE_STATES
        or is_update_service_active()
    ):
        return jsonify({
            "ok": False,
            "message": (
                "A ScoreCast update is already running."
            ),
        }), 409

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
        return jsonify({
            "ok": False,
            "message": (
                "Starting the updater timed out."
            ),
        }), 500

    except OSError as error:
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

        return jsonify({
            "ok": False,
            "message": error_message,
        }), 500

    return jsonify({
        "ok": True,
        "message": (
            "ScoreCast update started."
        ),
    })
