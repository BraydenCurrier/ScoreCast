import json
import subprocess
from pathlib import Path

from functools import wraps
from html import escape

from flask import Flask, request, redirect, session, jsonify

from common.settings import get_settings, update_settings

from fantasy.api import connect_sleeper_user, get_user_leagues

from alerts.manager import possession_alert_manager
from alerts.teams import NFL_TEAM_ALERTS

from updater.status import read_status

app = Flask(__name__)
app.secret_key = "change-this-later"

WEB_PASSWORD = "ticker123"

latest_games = []

CFB_CONFERENCE_OPTIONS = [
    ("80", "All FBS"),
    ("8", "SEC"),
    ("5", "Big Ten"),
    ("1", "ACC"),
    ("4", "Big 12"),
    ("17", "Mountain West"),
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

def set_latest_games(games):
    global latest_games
    latest_games = games


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect("/login")
        return f(*args, **kwargs)

    return wrapper


def page_header(active_page="games"):
    games_active = "active" if active_page == "games" else ""
    alerts_active = "active" if active_page == "alerts" else ""
    settings_active = "active" if active_page == "settings" else ""
    fantasy_active = "active" if active_page == "fantasy" else ""

    return f"""
    <div class="header">
        <div>
            <h1 class="title">Scoreboard</h1>
            <div class="subtitle">Local display controls</div>
        </div>

        <a class="logout" href="/logout">Logout</a>
    </div>

    <div class="tabs">
        <a class="tab {games_active}" href="/games">Games</a>
        <a class="tab {fantasy_active}" href="/fantasy">Fantasy</a>
        <a class="tab {alerts_active}" href="/alerts">Alerts</a>
        <a class="tab {settings_active}" href="/settings">Settings</a>
    </div>
    """


def page_styles():
    return """
    <style>
        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
            background: #0b0b0f;
            color: white;
        }

        .page {
            max-width: 520px;
            margin: 0 auto;
            padding: 18px;
        }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 18px;
        }

        .title {
            font-size: 28px;
            font-weight: 800;
            margin: 0;
        }

        .subtitle {
            color: #aaa;
            font-size: 14px;
            margin-top: 4px;
        }

        .logout {
            color: #aaa;
            text-decoration: none;
            font-size: 14px;
            padding-top: 8px;
        }

        .tabs {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            margin-bottom: 16px;
        }

        .tab {
            flex: 1;
            text-align: center;
            text-decoration: none;
            color: white;
            background: #17171d;
            border: 1px solid #2a2a33;
            padding: 12px;
            border-radius: 14px;
            font-size: 15px;
            font-weight: 700;
        }

        .tab.active {
            background: #0a84ff;
            border-color: #0a84ff;
        }

        .card {
            background: #17171d;
            border: 1px solid #2a2a33;
            border-radius: 18px;
            padding: 16px;
            margin-bottom: 16px;
            box-shadow: 0 8px 20px rgba(0,0,0,0.25);
        }

        .card-title {
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 14px;
        }

        .search-input {
            width: 100%;
            padding: 13px;
            border-radius: 12px;
            border: 1px solid #444;
            background: #0f0f14;
            color: white;
            font-size: 16px;
            margin-bottom: 12px;
        }

        .search-input::placeholder {
            color: #777;
        }

        .filter-row {
            display: flex;
            gap: 10px;
            margin-bottom: 14px;
            align-items: center;
        }

        .select-input {
            flex: 1;
            padding: 12px;
            border-radius: 12px;
            border: 1px solid #444;
            background: #0f0f14;
            color: white;
            font-size: 15px;
        }

        .control {
            margin-bottom: 20px;
        }

        .control:last-child {
            margin-bottom: 0;
        }

        .control-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            margin-bottom: 8px;
        }

        .number-input {
            width: 88px;
            padding: 8px;
            border-radius: 10px;
            border: 1px solid #444;
            background: #0f0f14;
            color: white;
            font-size: 16px;
            text-align: center;
        }

        input[type=range] {
            width: 100%;
            accent-color: #0a84ff;
        }

        .secondary-button {
            flex: 1;
            border: 1px solid #3a3a45;
            background: #24242c;
            color: white;
            padding: 12px;
            border-radius: 12px;
            font-size: 15px;
            font-weight: 600;
        }

        .game-row-container {
            cursor: grab;
            transition: transform 0.1s ease;
            -webkit-user-select: none;
            -ms-user-select: none;
            user-select: none;
        }

        .test-alert-button {
            flex: 0 0 auto;
            width: auto;
            padding: 8px 12px;
        }

        .game-row-container:active {
            cursor: grabbing;
        }

        .game-row-container.dragging {
            opacity: 0.4;
            background: #24242c;
            border-radius: 8px;
        }

        .game-row {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 0;
            border-bottom: 1px solid #2c2c35;
        }

        .game-row:last-child {
            border-bottom: 0;
        }

        .game-row input {
            width: 22px;
            height: 22px;
            accent-color: #0a84ff;
        }

        .game-info {
            flex: 1;
        }

        .matchup {
            font-size: 17px;
            font-weight: 700;
        }

        .details {
            color: #aaa;
            font-size: 13px;
            margin-top: 2px;
        }

        .empty {
            color: #aaa;
            padding: 10px 0;
        }

        .save-button {
            width: 100%;
            border: 0;
            border-radius: 16px;
            background: #0a84ff;
            color: white;
            padding: 16px;
            font-size: 18px;
            font-weight: 800;
            margin-top: 4px;
        }

        button:active {
            transform: scale(0.98);
        }

        .hint {
            color: #888;
            font-size: 12px;
            margin-top: 8px;
            line-height: 1.4;
        }

        input[type=password] {
            width: 100%;
            padding: 14px;
            border-radius: 12px;
            border: 1px solid #444;
            background: #0f0f14;
            color: white;
            font-size: 18px;
        }

        .login-card {
            margin-top: 40px;
        }

        .league-badge {
            margin-left: auto;
            min-width: 56px;
            text-align: center;
            padding: 6px 10px;
            border-radius: 999px;
            background: #2a2a33;
            color: #bcbcbc;
            font-size: 12px;
            font-weight: 700;
            letter-spacing: .5px;
            text-transform: uppercase;
        }

        .error {
            color: #ff453a;
            margin-bottom: 12px;
            font-size: 14px;
        }

        .team-alert-row {
            padding: 14px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.12);
        }

        .team-alert-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }

        .alert-options {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }

        .alert-option {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            padding: 8px;
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.06);
        }

        .alert-option input {
            transform: scale(1.1);
        }

        @media (max-width: 600px) {
            .filter-row {
                flex-direction: column;
                align-items: stretch;
            }

            .alert-options {
                grid-template-columns: 1fr;
            }
        }
    </style>
    """


def get_game_league(game):
    class_name = game.__class__.__name__

    if class_name == "CollegeFootballGame":
        return "cfb", "CFB"

    if class_name == "FootballGame":
        return "nfl", "NFL"

    if class_name == "SoccerGame":
        return "soccer", "Soccer"
    
    if class_name == "BasketballGame":
        return "nba", "NBA"
    
    if class_name == "HockeyGame":
        return "nhl", "NHL"

    if class_name == "NotificationCard":
        return "notification", "Notification"
    
    return "mlb", "MLB"

def get_game_id(game):
    if get_game_league(game) == ("notification", "Notification"):
        return f"notification:{getattr(game, 'provider', 'unknown')}:{getattr(game, 'source', 'unknown')}:{getattr(game, 'title', 'unknown')}"
    else:
        league_key, _ = get_game_league(game)
        return f"{league_key}:{game.away}@{game.home}"

def get_display_status(game, league_key):
    status = getattr(game, "status", "")

    if status == "STATUS_SCHEDULED":
        if league_key in ("nfl", "cfb"):
            return f"Week {getattr(game, 'week', 1)}"

        if league_key == "soccer":
            return getattr(game, "stage", "Scheduled")

        return "Scheduled"

    return status


@app.route("/")
@login_required
def home():
    return redirect("/games")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        if request.form.get("password") == WEB_PASSWORD:
            session["logged_in"] = True
            return redirect("/games")

        error = "Invalid password"

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Scoreboard Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    {page_styles()}
</head>
<body>
    <div class="page">
        <div class="card login-card">
            <h1 class="title">Scoreboard Login</h1>

            {"<div class='error'>" + error + "</div>" if error else ""}

            <form method="POST">
                <input
                    type="password"
                    name="password"
                    placeholder="Password"
                    autofocus
                >

                <button class="save-button" type="submit">
                    Login
                </button>
            </form>
        </div>
    </div>
</body>
</html>
    """


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/games")
@login_required
def games():
    settings = get_settings()
    hidden = set(settings.get("hidden_games", []))

    game_rows = ""

    for game in latest_games:
        if get_game_league(game) == ("notification", "Notification"):
            continue

        game_id = get_game_id(game)
        checked = "" if game_id in hidden else "checked"
        league_key, league_label = get_game_league(game)
        display_status = get_display_status(game, league_key)

        safe_game_id = escape(game_id, quote=True)
        safe_away = escape(str(game.away))
        safe_home = escape(str(game.home))
        safe_status = escape(str(display_status))
        away_score = escape(str(getattr(game, "away_score", 0)))
        home_score = escape(str(getattr(game, "home_score", 0)))

        game_rows += f"""
        <div class="game-row-container" draggable="true" data-id="{safe_game_id}" data-league="{league_key}">
            <label class="game-row">
                <input type="checkbox" name="game" value="{safe_game_id}" {checked}>
                <div class="game-info">
                    <div class="matchup">{safe_away} @ {safe_home}</div>
                    <div class="details">
                        {away_score} - {home_score} · {safe_status}
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
    <title>Scoreboard Games</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
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
                        <option value="soccer">Soccer</option>
                        <option value="nba">NBA</option>
                        <option value="nhl">NHL</option>
                    </select>

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

            document.querySelectorAll(".game-row-container").forEach(function(row) {{
                const text = row.innerText.toLowerCase();
                const rowLeague = row.dataset.league;

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
                }} else {{
                    matchesFilter = rowLeague === selectedFilter;
                }}

                row.style.display = (
                    matchesSearch && matchesFilter
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
            loadUpdateStatus();
            updateStatusTimer = setInterval(loadUpdateStatus, 2000);
        }});
    </script>
</body>
</html>
    """

@app.route("/alerts", methods=["GET", "POST"])
@login_required
def alerts_page():
    settings = get_settings()
    alerts = settings.get("alerts", {})

    if request.method == "POST":
        selected_teams = []

        for team_abbreviation in NFL_TEAM_ALERTS:
            field_name = (
                f"possession_team:{team_abbreviation}"
            )

            if request.form.get(field_name) == "on":
                selected_teams.append(
                    team_abbreviation
                )

        try:
            poll_interval = float(
                request.form.get(
                    "poll_interval_seconds",
                    3.0,
                )
            )
        except (TypeError, ValueError):
            poll_interval = 3.0

        try:
            confirmations = int(
                request.form.get(
                    "confirmations_required",
                    2,
                )
            )
        except (TypeError, ValueError):
            confirmations = 2

        try:
            cooldown = float(
                request.form.get(
                    "cooldown_seconds",
                    20,
                )
            )
        except (TypeError, ValueError):
            cooldown = 20.0

        try:
            chant_seconds = float(
                request.form.get(
                    "chant_frame_seconds",
                    0.9,
                )
            )
        except (TypeError, ValueError):
            chant_seconds = 0.9

        try:
            details_seconds = float(
                request.form.get(
                    "details_frame_seconds",
                    4.0,
                )
            )
        except (TypeError, ValueError):
            details_seconds = 4.0

        updated_alerts = {
            "enabled": (
                request.form.get("enabled") == "on"
            ),
            "possession_enabled": (
                request.form.get(
                    "possession_enabled"
                ) == "on"
            ),
            "redzone_enabled": (
                request.form.get(
                    "redzone_enabled"
                ) == "on"
            ),
            "touchdown_enabled": (
                request.form.get(
                    "touchdown_enabled"
                ) == "on"
            ),
            "field_goal_enabled": (
                request.form.get(
                    "field_goal_enabled"
                ) == "on"
            ),
            "possession_teams": sorted(
                selected_teams
            ),
            "poll_interval_seconds": max(
                2.0,
                min(30.0, poll_interval),
            ),
            "confirmations_required": max(
                1,
                min(5, confirmations),
            ),
            "cooldown_seconds": max(
                0.0,
                min(300.0, cooldown),
            ),
            "chant_frame_seconds": max(
                0.2,
                min(3.0, chant_seconds),
            ),
            "details_frame_seconds": max(
                1.0,
                min(15.0, details_seconds),
            ),
        }

        update_settings({
            "alerts": updated_alerts,
        })

        return redirect("/alerts?saved=1")

    selected_teams = {
        str(team).upper()
        for team in alerts.get(
            "possession_teams",
            [],
        )
    }

    enabled_checked = (
        "checked"
        if alerts.get("enabled", False)
        else ""
    )

    possession_checked = (
        "checked"
        if alerts.get(
            "possession_enabled",
            True,
        )
        else ""
    )

    redzone_checked = (
        "checked"
        if alerts.get(
            "redzone_enabled",
            True,
        )
        else ""
    )

    touchdown_checked = (
        "checked"
        if alerts.get(
            "touchdown_enabled",
            True,
        )
        else ""
    )

    field_goal_checked = (
        "checked"
        if alerts.get(
            "field_goal_enabled",
            True,
        )
        else ""
    )

    team_rows = ""

    for abbreviation, definition in sorted(
        NFL_TEAM_ALERTS.items(),
        key=lambda item: item[1].name,
    ):
        checked = (
            "checked"
            if abbreviation in selected_teams
            else ""
        )

        safe_abbreviation = escape(
            abbreviation,
            quote=True,
        )
        safe_name = escape(definition.name)
        safe_chant = escape(
            " → ".join(definition.chant)
        )

        team_rows += f"""
        <div class="team-row">
            <label>
                <input
                    type="checkbox"
                    name="possession_team:{safe_abbreviation}"
                    {checked}
                >
                <strong>{safe_name}</strong>
                <span>
                    {safe_abbreviation} · {safe_chant}
                </span>
            </label>

            <div class="alert-test-buttons">
                <form
                    method="post"
                    action="/alerts/test/{safe_abbreviation}/POSSESSION"
                >
                    <button type="submit">
                        Possession
                    </button>
                </form>

                <form
                    method="post"
                    action="/alerts/test/{safe_abbreviation}/REDZONE"
                >
                    <button type="submit">
                        Red Zone
                    </button>
                </form>

                <form
                    method="post"
                    action="/alerts/test/{safe_abbreviation}/TOUCHDOWN"
                >
                    <button type="submit">
                        TD
                    </button>
                </form>

                <form
                    method="post"
                    action="/alerts/test/{safe_abbreviation}/FIELD_GOAL"
                >
                    <button type="submit">
                        FG
                    </button>
                </form>
            </div>
        </div>
        """

    saved_message = ""

    if request.args.get("saved") == "1":
        saved_message = """
        <div class="success-message">
            Alert settings saved.
        </div>
        """

    poll_interval = alerts.get(
        "poll_interval_seconds",
        3.0,
    )
    confirmations = alerts.get(
        "confirmations_required",
        2,
    )
    cooldown = alerts.get(
        "cooldown_seconds",
        20,
    )
    chant_seconds = alerts.get(
        "chant_frame_seconds",
        0.9,
    )
    details_seconds = alerts.get(
        "details_frame_seconds",
        4.0,
    )

    return f"""
    <!doctype html>
    <html>
    <head>
        <title>ScoreCast Alerts</title>
        {page_styles()}

        <style>
            .alert-options {{
                display: grid;
                gap: 12px;
                margin-bottom: 24px;
            }}

            .alert-option {{
                display: flex;
                align-items: flex-start;
                gap: 10px;
                padding: 12px;
                border: 1px solid #333;
                border-radius: 8px;
            }}

            .alert-option input {{
                margin-top: 4px;
            }}

            .alert-option strong {{
                display: block;
                margin-bottom: 4px;
            }}

            .alert-option span {{
                display: block;
                opacity: 0.75;
                font-size: 0.9rem;
            }}

            .team-row {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 12px;
                padding: 10px 0;
                border-bottom: 1px solid #333;
            }}

            .team-row label {{
                display: flex;
                align-items: center;
                gap: 8px;
            }}

            .team-row label span {{
                opacity: 0.7;
                margin-left: 6px;
            }}

            .alert-test-buttons {{
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
            }}

            .alert-test-buttons form {{
                margin: 0;
            }}

            .alert-test-buttons button {{
                padding: 5px 8px;
                font-size: 0.8rem;
            }}

            .timing-grid {{
                display: grid;
                grid-template-columns:
                    repeat(auto-fit, minmax(220px, 1fr));
                gap: 14px;
            }}

            .timing-field label {{
                display: block;
                font-weight: bold;
                margin-bottom: 5px;
            }}

            .timing-field input {{
                width: 100%;
            }}

            .timing-field small {{
                display: block;
                margin-top: 4px;
                opacity: 0.7;
            }}
        </style>
    </head>

    <body>
        {page_header("alerts")}
        {saved_message}

        <main>
            <h1>NFL Alerts</h1>

            <form method="post">
                <section>
                    <h2>Alert System</h2>

                    <div class="alert-options">
                        <label class="alert-option">
                            <input
                                type="checkbox"
                                name="enabled"
                                {enabled_checked}
                            >

                            <span>
                                <strong>
                                    Enable NFL alerts
                                </strong>

                                Allow alerts to temporarily
                                take over the matrix.
                            </span>
                        </label>

                        <label class="alert-option">
                            <input
                                type="checkbox"
                                name="possession_enabled"
                                {possession_checked}
                            >

                            <span>
                                <strong>
                                    Possession alerts
                                </strong>

                                Alert when a selected team
                                gains possession.
                            </span>
                        </label>

                        <label class="alert-option">
                            <input
                                type="checkbox"
                                name="redzone_enabled"
                                {redzone_checked}
                            >

                            <span>
                                <strong>
                                    Red-zone alerts
                                </strong>

                                Alert when a selected team
                                enters the opponent's
                                20-yard line.
                            </span>
                        </label>

                        <label class="alert-option">
                            <input
                                type="checkbox"
                                name="touchdown_enabled"
                                {touchdown_checked}
                            >

                            <span>
                                <strong>
                                    Touchdown alerts
                                </strong>

                                Alert when a selected team
                                scores a touchdown.
                            </span>
                        </label>

                        <label class="alert-option">
                            <input
                                type="checkbox"
                                name="field_goal_enabled"
                                {field_goal_checked}
                            >

                            <span>
                                <strong>
                                    Field-goal alerts
                                </strong>

                                Alert when a selected team
                                makes a field goal.
                            </span>
                        </label>
                    </div>
                </section>

                <section>
                    <h2>Select Teams</h2>

                    <p>
                        Alert types above apply to every
                        selected NFL team.
                    </p>

                    <div>
                        <button
                            type="button"
                            onclick="setAllTeams(true)"
                        >
                            Select All
                        </button>

                        <button
                            type="button"
                            onclick="setAllTeams(false)"
                        >
                            Select None
                        </button>
                    </div>

                    <div class="team-list">
                        {team_rows}
                    </div>
                </section>

                <section>
                    <h2>Timing</h2>

                    <div class="timing-grid">
                        <div class="timing-field">
                            <label
                                for="poll_interval_seconds"
                            >
                                NFL polling interval
                            </label>

                            <input
                                id="poll_interval_seconds"
                                name="poll_interval_seconds"
                                type="number"
                                min="2"
                                max="30"
                                step="0.5"
                                value="{poll_interval}"
                            >

                            <small>
                                How often ScoreCast checks
                                for new NFL events.
                            </small>
                        </div>

                        <div class="timing-field">
                            <label
                                for="confirmations_required"
                            >
                                Possession confirmations
                            </label>

                            <input
                                id="confirmations_required"
                                name="confirmations_required"
                                type="number"
                                min="1"
                                max="5"
                                step="1"
                                value="{confirmations}"
                            >

                            <small>
                                Matching readings required
                                before a possession alert.
                            </small>
                        </div>

                        <div class="timing-field">
                            <label
                                for="chant_frame_seconds"
                            >
                                Chant word duration
                            </label>

                            <input
                                id="chant_frame_seconds"
                                name="chant_frame_seconds"
                                type="number"
                                min="0.2"
                                max="3"
                                step="0.1"
                                value="{chant_seconds}"
                            >

                            <small>
                                Seconds each alert word
                                remains visible.
                            </small>
                        </div>

                        <div class="timing-field">
                            <label
                                for="details_frame_seconds"
                            >
                                Details duration
                            </label>

                            <input
                                id="details_frame_seconds"
                                name="details_frame_seconds"
                                type="number"
                                min="1"
                                max="15"
                                step="0.5"
                                value="{details_seconds}"
                            >

                            <small>
                                Seconds the final alert
                                screen remains visible.
                            </small>
                        </div>

                        <div class="timing-field">
                            <label
                                for="cooldown_seconds"
                            >
                                Duplicate cooldown
                            </label>

                            <input
                                id="cooldown_seconds"
                                name="cooldown_seconds"
                                type="number"
                                min="0"
                                max="300"
                                step="1"
                                value="{cooldown}"
                            >

                            <small>
                                Prevent repeated alerts
                                caused by duplicate data.
                            </small>
                        </div>
                    </div>
                </section>

                <p>
                    <button type="submit">
                        Save NFL Alerts
                    </button>
                </p>
            </form>
        </main>

        <script>
            function setAllTeams(checked) {{
                document
                    .querySelectorAll(
                        'input[name^="possession_team:"]'
                    )
                    .forEach((input) => {{
                        input.checked = checked;
                    }});
            }}
        </script>
    </body>
    </html>
    """

@app.route(
    "/alerts/test/<team>/<alert_type>",
    methods=["POST"],
)
@login_required
def test_possession_alert(
    team: str,
    alert_type: str,
):
    team = str(team).upper()
    alert_type = str(alert_type).upper()

    valid_alert_types = {
        "POSSESSION",
        "REDZONE",
        "TOUCHDOWN",
        "FIELD_GOAL",
    }

    if team not in NFL_TEAM_ALERTS:
        return "Unknown NFL team.", 404

    if alert_type not in valid_alert_types:
        return "Unknown alert type.", 404

    settings = get_settings()

    queued = (
        possession_alert_manager
        .enqueue_test_alert(
            team=team,
            settings=settings,
            alert_type=alert_type,
        )
    )

    if not queued:
        return "Could not queue alert.", 400

    return redirect("/alerts")

@app.route("/settings")
@login_required
def settings_page():
    settings = get_settings()

    cfb_settings = settings.get("cfb", {})

    selected_cfb_conferences = {
        str(group_id)
        for group_id in cfb_settings.get(
            "selected_conferences",
            ["80"],
        )
    }

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
    <title>Scoreboard Settings</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
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
                <div class="card-title">
                    Software Update
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
                    style="
                        display: none;
                        margin-top: 12px;
                    "
                >
                    <div
                        style="
                            width: 100%;
                            height: 8px;
                            border-radius: 999px;
                            overflow: hidden;
                            background: rgba(255, 255, 255, 0.1);
                        "
                    >
                        <div
                            id="update_progress_bar"
                            style="
                                width: 10%;
                                height: 100%;
                                border-radius: 999px;
                                background: currentColor;
                                transition: width 0.3s ease;
                            "
                        ></div>
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
            downloading: "Downloading Update",
            installing: "Installing Dependencies",
            validating: "Validating Release",
            restarting: "Restarting ScoreCast",
            complete: "Update Complete",
            current: "Already Up to Date",
            rolled_back: "Update Rolled Back",
            failed: "Update Failed"
        }};

        const updateStateProgress = {{
            idle: 0,
            checking: 10,
            available: 10,
            downloading: 30,
            installing: 55,
            validating: 75,
            restarting: 90,
            complete: 100,
            current: 100,
            rolled_back: 100,
            failed: 100
        }};

        const activeUpdateStates = new Set([
            "checking",
            "downloading",
            "installing",
            "validating",
            "restarting"
        ]);

        function renderUpdateStatus(status) {{
            const messageElement = document.getElementById(
                "update_status_message"
            );

            const detailsElement = document.getElementById(
                "update_status_details"
            );

            const button = document.getElementById(
                "update_button"
            );

            const progressContainer = document.getElementById(
                "update_progress_container"
            );

            const progressBar = document.getElementById(
                "update_progress_bar"
            );

            if (
                !messageElement
                || !detailsElement
                || !button
            ) {{
                return;
            }}

            const state = status.state || "idle";

            const label = (
                updateStateLabels[state]
                || "Update Status"
            );

            messageElement.textContent = label;

            detailsElement.textContent = (
                status.message
                || "Update status unavailable."
            );

            const isActive = (
                activeUpdateStates.has(state)
                || status.service_active === true
            );

            button.disabled = isActive;

            button.textContent = isActive
                ? "Updating..."
                : "Check and Install Update";

            const showProgress = (
                isActive
                || state === "complete"
                || state === "failed"
                || state === "rolled_back"
            );

            if (progressContainer) {{
                progressContainer.style.display = (
                    showProgress
                    ? "block"
                    : "none"
                );
            }}

            if (progressBar) {{
                const progress = (
                    updateStateProgress[state]
                    ?? 0
                );

                progressBar.style.width = (
                    progress + "%"
                );
            }}
        }}

        let updateStatusTimer = null;
        let scoreCastWasRestarting = false;

        async function loadUpdateStatus() {{
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
                        "Unable to read update status."
                    );
                }}

                const status = await response.json();

                renderUpdateStatus(status);

                if (
                    status.state === "restarting"
                    || status.state === "complete"
                ) {{
                    scoreCastWasRestarting = true;
                }}

                if (
                    scoreCastWasRestarting
                    && (
                        status.state === "complete"
                        || status.state === "current"
                        || status.state === "failed"
                        || status.state === "rolled_back"
                    )
                ) {{
                    scoreCastWasRestarting = false;
                }}

            }} catch (error) {{
                const messageElement = (
                    document.getElementById(
                        "update_status_message"
                    )
                );

                const detailsElement = (
                    document.getElementById(
                        "update_status_details"
                    )
                );

                if (messageElement) {{
                    messageElement.textContent = (
                        "ScoreCast is restarting..."
                    );
                }}

                if (detailsElement) {{
                    detailsElement.textContent = (
                        "The dashboard will reconnect automatically."
                    );
                }}

                scoreCastWasRestarting = true;
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

                await loadUpdateStatus();

            }} catch (error) {{
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

        function bindNumberToSlider(numberId, sliderId) {{
            const number = document.getElementById(numberId);
            const slider = document.getElementById(sliderId);

            number.addEventListener("input", function() {{
                slider.value = number.value;
            }});
        }}

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
    </script>
</body>
</html>
    """


@app.route("/save_games", methods=["POST"])
@login_required
def save_games():
    visible_games = request.form.getlist("game")

    all_game_ids = [
        get_game_id(game)
        for game in latest_games
    ]

    hidden_games = [
        game_id for game_id in all_game_ids
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
    })

    return redirect("/settings")


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