import json
import subprocess
from pathlib import Path

from functools import wraps
from html import escape

from flask import Flask, request, redirect, session, jsonify, url_for

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
        selected_teams = [
            abbreviation
            for abbreviation in NFL_TEAM_ALERTS
            if request.form.get(
                f"possession_team:{abbreviation}"
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
        }

        update_settings({
            "alerts": updated_alerts,
        })

        return redirect("/alerts?saved=1")

    def checked(name: str, default: bool) -> str:
        return (
            "checked"
            if bool(alerts.get(name, default))
            else ""
        )

    selected_teams = {
        str(team).upper()
        for team in alerts.get(
            "possession_teams",
            [],
        )
    }

    team_rows = ""

    for abbreviation, definition in sorted(
        NFL_TEAM_ALERTS.items(),
        key=lambda item: item[1].name,
    ):
        team_checked = (
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
        <div
            class="alert-team-row"
            data-team-search="
                {safe_name.lower()}
                {safe_abbreviation.lower()}
            "
        >
            <label class="game-row alert-team-label">
                <input
                    type="checkbox"
                    name="
                        possession_team:
                        {safe_abbreviation}
                    "
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

            <div class="team-test-row">
                <button
                    class="secondary-button alert-test-button"
                    type="submit"
                    formaction="{url_for(
                        'test_possession_alert',
                        team=abbreviation,
                        alert_type='POSSESSION',
                    )}"
                    formmethod="POST"
                >
                    Possession
                </button>

                <button
                    class="secondary-button alert-test-button"
                    type="submit"
                    formaction="{url_for(
                        'test_possession_alert',
                        team=abbreviation,
                        alert_type='REDZONE',
                    )}"
                    formmethod="POST"
                >
                    Red Zone
                </button>

                <button
                    class="secondary-button alert-test-button"
                    type="submit"
                    formaction="{url_for(
                        'test_possession_alert',
                        team=abbreviation,
                        alert_type='TOUCHDOWN',
                    )}"
                    formmethod="POST"
                >
                    TD
                </button>

                <button
                    class="secondary-button alert-test-button"
                    type="submit"
                    formaction="{url_for(
                        'test_possession_alert',
                        team=abbreviation,
                        alert_type='FIELD_GOAL',
                    )}"
                    formmethod="POST"
                >
                    FG
                </button>
            </div>


        </div>
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

            .team-test-row {{
                display: grid;
                grid-template-columns:
                    repeat(4, 1fr);
                gap: 7px;
                padding-left: 36px;
            }}

            .alert-test-button {{
                min-width: 0;
                width: 100%;
                padding: 10px 4px;
                font-size: 12px;
                line-height: 1.1;
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

            @media (max-width: 390px) {{
                .team-test-row {{
                    grid-template-columns:
                        1fr 1fr;
                }}

                .alert-test-button {{
                    font-size: 13px;
                    padding: 11px 6px;
                }}
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
                        NFL Alerts
                    </div>

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
                                Allow NFL events to
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

                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="possession_enabled"
                            {checked(
                                "possession_enabled",
                                True,
                            )}
                        >

                        <div class="alert-icon">
                            🏈
                        </div>

                        <div class="alert-row-text">
                            <div class="alert-row-title">
                                Possession
                            </div>

                            <div
                                class="
                                    alert-row-description
                                "
                            >
                                Show an alert when a
                                selected team gains
                                possession.
                            </div>
                        </div>
                    </label>

                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="redzone_enabled"
                            {checked(
                                "redzone_enabled",
                                True,
                            )}
                        >

                        <div class="alert-icon">
                            🔴
                        </div>

                        <div class="alert-row-text">
                            <div class="alert-row-title">
                                Red Zone
                            </div>

                            <div
                                class="
                                    alert-row-description
                                "
                            >
                                Show an alert when a
                                selected team reaches
                                the opponent's 20.
                            </div>
                        </div>
                    </label>

                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="touchdown_enabled"
                            {checked(
                                "touchdown_enabled",
                                True,
                            )}
                        >

                        <div class="alert-icon">
                            🙌
                        </div>

                        <div class="alert-row-text">
                            <div class="alert-row-title">
                                Touchdown
                            </div>

                            <div
                                class="
                                    alert-row-description
                                "
                            >
                                Show an alert when a
                                selected team scores
                                a touchdown.
                            </div>
                        </div>
                    </label>

                    <label class="alert-type-row">
                        <input
                            type="checkbox"
                            name="field_goal_enabled"
                            {checked(
                                "field_goal_enabled",
                                True,
                            )}
                        >

                        <div class="alert-icon">
                            🥅
                        </div>

                        <div class="alert-row-text">
                            <div class="alert-row-title">
                                Field Goal
                            </div>

                            <div
                                class="
                                    alert-row-description
                                "
                            >
                                Show an alert when a
                                selected team makes
                                a field goal.
                            </div>
                        </div>
                    </label>
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
                        placeholder="Search NFL teams..."
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
                    Save NFL Alerts
                </button>
            </form>
        </div>

        <script>
            function setAllAlertTeams(checked) {{
                document.querySelectorAll(
                    'input[name^="possession_team:"]'
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
    <title>Scoreboard Fantasy</title>
    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
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