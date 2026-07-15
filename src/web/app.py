from functools import wraps
from html import escape

from flask import Flask, request, redirect, session

from common.settings import get_settings, update_settings

from fantasy.api import connect_sleeper_user, get_user_leagues

from alerts.manager import possession_alert_manager
from alerts.teams import NFL_TEAM_ALERTS

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

        document.addEventListener("DOMContentLoaded", filterGames);
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
                request.form.get("enabled")
                == "on"
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

        safe_name = escape(
            definition.name
        )

        safe_chant = escape(
            " → ".join(definition.chant)
        )

        team_rows += f"""
        <div
            class="possession-team-row"
            data-team-search="{safe_name.lower()} {safe_abbreviation.lower()}"
        >
            <input
                type="checkbox"
                name="possession_team:{safe_abbreviation}"
                {checked}
            >

            <div class="team-color"
                style="
                    background: rgb{definition.primary};
                    border-color: rgb{definition.accent};
                ">
            </div>

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

            <button
                class="secondary-button test-alert-button"
                type="submit"
                formaction="/alerts/test/{safe_abbreviation}"
                formmethod="POST"
            >
                Test
            </button>
        </div>
        """

    saved_message = ""

    if request.args.get("saved") == "1":
        saved_message = """
        <div class="success-message">
            Possession alert settings saved.
        </div>
        """

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Possession Alerts</title>
    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
    >

    {page_styles()}

    <style>
        .success-message {{
            background: rgba(48, 209, 88, 0.15);
            border: 1px solid rgba(48, 209, 88, 0.5);
            color: #78f09a;
            border-radius: 12px;
            padding: 12px;
            margin-bottom: 16px;
            font-weight: 700;
        }}

        .possession-team-row {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 0;
            border-bottom: 1px solid #2c2c35;
        }}

        .possession-team-row:last-child {{
            border-bottom: 0;
        }}

        .possession-team-row input {{
            width: 22px;
            height: 22px;
            flex: 0 0 auto;
            accent-color: #0a84ff;
        }}

        .team-color {{
            width: 28px;
            height: 28px;
            flex: 0 0 auto;
            border-radius: 8px;
            border: 3px solid;
        }}

        .quick-actions {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 14px;
        }}

        .settings-grid {{
            display: grid;
            grid-template-columns: 1fr 90px;
            gap: 10px;
            align-items: center;
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
                    Possession Alerts
                </div>

                <label class="game-row">
                    <input
                        type="checkbox"
                        name="enabled"
                        {
                            "checked"
                            if alerts.get(
                                "enabled",
                                False,
                            )
                            else ""
                        }
                    >

                    <div class="game-info">
                        <div class="matchup">
                            Enable possession alerts
                        </div>

                        <div class="details">
                            Temporarily take over the matrix
                            when a selected NFL team gains
                            possession.
                        </div>
                    </div>
                </label>
            </div>

            <div class="card">
                <div class="card-title">
                    Select Teams
                </div>

                <input
                    class="search-input"
                    id="possession_team_search"
                    type="text"
                    placeholder="Search NFL teams..."
                    oninput="filterPossessionTeams()"
                >

                <div class="quick-actions">
                    <button
                        class="secondary-button"
                        type="button"
                        onclick="setVisibleTeams(true)"
                    >
                        Select All
                    </button>

                    <button
                        class="secondary-button"
                        type="button"
                        onclick="setVisibleTeams(false)"
                    >
                        Select None
                    </button>
                </div>

                <div id="possession_team_list">
                    {team_rows}
                </div>
            </div>

            <div class="card">
                <div class="card-title">
                    Timing
                </div>

                <div class="control">
                    <div class="control-top">
                        <label>
                            NFL polling interval
                        </label>

                        <input
                            class="number-input"
                            type="number"
                            name="poll_interval_seconds"
                            min="2"
                            max="30"
                            step="0.5"
                            value="{
                                alerts.get(
                                    "poll_interval_seconds",
                                    3.0,
                                )
                            }"
                        >
                    </div>

                    <div class="hint">
                        How often ScoreCast checks for
                        possession changes. Three seconds
                        is recommended.
                    </div>
                </div>

                <div class="control">
                    <div class="control-top">
                        <label>
                            Confirmations required
                        </label>

                        <input
                            class="number-input"
                            type="number"
                            name="confirmations_required"
                            min="1"
                            max="5"
                            step="1"
                            value="{
                                alerts.get(
                                    "confirmations_required",
                                    2,
                                )
                            }"
                        >
                    </div>

                    <div class="hint">
                        Two matching API readings helps
                        prevent false alerts.
                    </div>
                </div>

                <div class="control">
                    <div class="control-top">
                        <label>
                            Chant word duration
                        </label>

                        <input
                            class="number-input"
                            type="number"
                            name="chant_frame_seconds"
                            min="0.2"
                            max="3"
                            step="0.1"
                            value="{
                                alerts.get(
                                    "chant_frame_seconds",
                                    0.9,
                                )
                            }"
                        >
                    </div>

                    <div class="hint">
                        Seconds each chant word remains
                        visible.
                    </div>
                </div>

                <div class="control">
                    <div class="control-top">
                        <label>
                            Details duration
                        </label>

                        <input
                            class="number-input"
                            type="number"
                            name="details_frame_seconds"
                            min="1"
                            max="15"
                            step="0.5"
                            value="{
                                alerts.get(
                                    "details_frame_seconds",
                                    4.0,
                                )
                            }"
                        >
                    </div>

                    <div class="hint">
                        How long the final team and field
                        position screen remains visible.
                    </div>
                </div>

                <div class="control">
                    <div class="control-top">
                        <label>
                            Duplicate cooldown
                        </label>

                        <input
                            class="number-input"
                            type="number"
                            name="cooldown_seconds"
                            min="0"
                            max="300"
                            step="5"
                            value="{
                                alerts.get(
                                    "cooldown_seconds",
                                    20,
                                )
                            }"
                        >
                    </div>

                    <div class="hint">
                        Prevents the same team from alerting
                        repeatedly because of noisy data.
                    </div>
                </div>
            </div>

            <button
                class="save-button"
                type="submit"
            >
                Save Possession Alerts
            </button>
        </form>
    </div>

    <script>
        function filterPossessionTeams() {{
            const search = (
                document
                    .getElementById(
                        "possession_team_search"
                    )
                    .value
                    .toLowerCase()
                    .trim()
            );

            document
                .querySelectorAll(
                    ".possession-team-row"
                )
                .forEach(function(row) {{
                    const searchable = (
                        row.dataset.teamSearch || ""
                    );

                    row.style.display = (
                        searchable.includes(search)
                        ? ""
                        : "none"
                    );
                }});
        }}

        function setVisibleTeams(checked) {{
            document
                .querySelectorAll(
                    ".possession-team-row"
                )
                .forEach(function(row) {{
                    if (row.style.display === "none") {{
                        return;
                    }}

                    const checkbox = row.querySelector(
                        'input[type="checkbox"]'
                    );

                    if (checkbox) {{
                        checkbox.checked = checked;
                    }}
                }});
        }}
    </script>
</body>
</html>
"""

@app.route(
    "/alerts/test/<team>",
    methods=["POST"],
)
@login_required
def test_possession_alert(team):
    team = str(team).upper()

    if team not in NFL_TEAM_ALERTS:
        return "Unknown NFL team.", 404

    settings = get_settings()

    queued = (
        possession_alert_manager
        .enqueue_test_alert(
            team=team,
            settings=settings,
        )
    )

    if not queued:
        return "Could not queue alert.", 400

    return redirect("/alerts")

@app.route("/fantasy", methods=["GET", "POST"])
@login_required
def fantasy_page():
    settings = get_settings()
    fantasy = settings.get("fantasy", {})

    error = ""

    if request.method == "POST":
        action = request.form.get("action")

        if action == "connect":
            username = request.form.get("username", "").strip()

            try:
                user = connect_sleeper_user(username)

                if not user:
                    error = "Sleeper user not found."
                else:
                    return redirect("/fantasy")

            except Exception as e:
                error = str(e)

        elif action == "save_leagues":
            fantasy["enabled"] = request.form.get("enabled") == "on"
            fantasy["season"] = request.form.get("season", "2026").strip()
            fantasy["selected_leagues"] = request.form.getlist("selected_leagues")

            update_settings({"fantasy": fantasy})
            return redirect("/fantasy")

    user_id = fantasy.get("user_id", "")
    username = fantasy.get("username", "")
    season = fantasy.get("season", "2026")

    leagues = []

    if user_id:
        try:
            leagues = get_user_leagues(user_id, season)
        except Exception as e:
            error = str(e)

    selected_leagues = set(fantasy.get("selected_leagues", []))

    league_rows = ""

    for league in leagues:
        league_id = league.get("league_id", "")
        name = league.get("name", "Sleeper League")
        total_rosters = league.get("total_rosters", 0)

        checked = "checked" if league_id in selected_leagues else ""

        league_rows += f"""
        <label class="game-row">
            <input
                type="checkbox"
                name="selected_leagues"
                value="{escape(str(league_id), quote=True)}"
                {checked}
            >

            <div class="game-info">
                <div class="matchup">{escape(str(name))}</div>
                <div class="details">{total_rosters} teams · {escape(str(season))}</div>
            </div>
        </label>
        """

    if user_id and not league_rows:
        league_rows = """
        <div class="empty">
            No Sleeper leagues found for this season.
        </div>
        """

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Fantasy Football</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    {page_styles()}
</head>

<body>
    <div class="page">
        {page_header("fantasy")}

        {"<div class='error'>" + escape(error) + "</div>" if error else ""}

        <form method="POST">
            <input type="hidden" name="action" value="connect">

            <div class="card">
                <div class="card-title">Connect Sleeper</div>

                <div class="control">
                    <label>Sleeper Username</label>
                    <input
                        class="search-input"
                        name="username"
                        placeholder="Enter Sleeper username"
                        value="{escape(str(username), quote=True)}"
                    >
                </div>

                <button class="save-button" type="submit">
                    Connect Sleeper
                </button>

                <div class="hint">
                    Sleeper does not require a password here. ScoreCast uses Sleeper's public read-only API.
                </div>
            </div>
        </form>

        <form method="POST">
            <input type="hidden" name="action" value="save_leagues">

            <div class="card">
                <div class="card-title">Fantasy Settings</div>

                <label class="game-row">
                    <input type="checkbox" name="enabled" {"checked" if fantasy.get("enabled", False) else ""}>
                    <div class="game-info">
                        <div class="matchup">Enable fantasy football</div>
                        <div class="details">Show Sleeper matchups on the Games page</div>
                    </div>
                </label>

                <div class="control">
                    <div class="control-top">
                        <label>Season</label>
                        <input
                            class="number-input"
                            type="number"
                            name="season"
                            value="{escape(str(season), quote=True)}"
                        >
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-title">Leagues</div>

                {league_rows if user_id else '<div class="empty">Connect Sleeper first.</div>'}
            </div>

            <button class="save-button" type="submit">
                Save Fantasy Leagues
            </button>
        </form>
    </div>
</body>
</html>
    """

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

            <button class="save-button" type="submit">
                Save Settings
            </button>
        </form>
    </div>

    <script>
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
