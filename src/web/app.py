from functools import wraps

from flask import Flask, request, redirect, session

from common.settings import get_settings, update_settings

app = Flask(__name__)
app.secret_key = "change-this-later"

WEB_PASSWORD = "ticker123"

latest_games = []


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
    settings_active = "active" if active_page == "settings" else ""

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
            display: flex;
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

        .game-buttons {
            display: flex;
            gap: 10px;
            margin-bottom: 12px;
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
    </style>
    """


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
        game_id = f"{game.away}@{game.home}"
        checked = "" if game_id in hidden else "checked"

        if hasattr(game, "quarter"):
            league = "NFL"

            if game.status == "STATUS_SCHEDULED":
                display_status = f"Week {getattr(game, 'week', 1)}"
            else:
                display_status = game.status
        else:
            if hasattr(game, "minute"):
                league = "Soccer"

                if game.status == "STATUS_SCHEDULED":
                    display_status = game.stage
                else:
                    display_status = game.status
            else:
                league = "MLB"

                if game.status == "STATUS_SCHEDULED":
                    display_status = "Scheduled"
                else:
                    display_status = game.status

        game_rows += f"""
        <div class="game-row-container" draggable="true" data-id="{game_id}">
            <label class="game-row">
                <input type="checkbox" name="game" value="{game_id}" data-league="{league.lower()}" {checked}>
                <div class="game-info">
                    <div class="matchup">{game.away} @ {game.home}</div>
                    <div class="details">
                        {game.away_score} - {game.home_score} · {display_status}
                    </div>
                </div>

                <div class="league-badge">
                    {league}
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
            <div class="card">
                <div class="card-title">Games</div>

                <input
                    class="search-input"
                    type="text"
                    id="game_search"
                    placeholder="Search games..."
                    oninput="filterGames()"
                >

                <div class="game-buttons">
                    <button type="button" class="secondary-button" onclick="selectAllGames()">All</button>
                    <button type="button" class="secondary-button" onclick="selectLeague('mlb')">MLB</button>
                    <button type="button" class="secondary-button" onclick="selectLeague('nfl')">NFL</button>
                    <button type="button" class="secondary-button" onclick="selectLeague('soccer')">Soccer</button>
                    <button type="button" class="secondary-button" onclick="deselectAllGames()">None</button>
                </div>

                {game_rows}
            </div>

            <button class="save-button" type="submit">
                Save Games
            </button>
        </form>
    </div>

    <script>
        function filterGames() {{
            const search = document.getElementById("game_search").value.toLowerCase();

            document.querySelectorAll(".game-row-container").forEach(function(row) {{
                const text = row.innerText.toLowerCase();
                row.style.display = text.includes(search) ? "" : "none";
            }});
        }}

        function selectAllGames() {{
            document.querySelectorAll('input[type="checkbox"][name="game"]').forEach(function(cb) {{
                cb.checked = true;
            }});
        }}

        function deselectAllGames() {{
            document.querySelectorAll('input[type="checkbox"][name="game"]').forEach(function(cb) {{
                cb.checked = false;
            }});
        }}

        function selectLeague(league) {{
            let anyChecked = false;

            document.querySelectorAll('input[type="checkbox"][name="game"]').forEach(function(cb) {{
                if (cb.getAttribute('data-league') === league && cb.checked) {{
                    anyChecked = true;
                }}
            }});

            document.querySelectorAll('input[type="checkbox"][name="game"]').forEach(function(cb) {{
                if (cb.getAttribute('data-league') === league) {{
                    cb.checked = !anyChecked;
                }}
            }});
        }}

        const container = document.querySelector('.card');

        container.addEventListener('dragstart', function(e) {{
            const row = e.target.closest('.game-row-container');

            if (row) {{
                row.classList.add('dragging');

                if (e.dataTransfer) {{
                    e.dataTransfer.setData('text/plain', '');
                }}
            }}
        }});

        container.addEventListener('dragend', function(e) {{
            const row = e.target.closest('.game-row-container');

            if (row) {{
                row.classList.remove('dragging');
            }}
        }});

        container.addEventListener('dragover', function(e) {{
            e.preventDefault();

            const draggingItem = document.querySelector('.dragging');
            if (!draggingItem) return;

            const siblings = [...container.querySelectorAll('.game-row-container:not(.dragging)')];

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
    </script>
</body>
</html>
    """


@app.route("/settings")
@login_required
def settings_page():
    settings = get_settings()

    scroll_speed = settings.get("scroll_speed", 0.4)
    brightness = settings.get("brightness", 50)
    refresh_interval = settings.get("refresh_interval", 120)

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
                            min="0.1" max="2.0" step="0.1"
                            value="{scroll_speed}">
                    </div>

                    <input type="range" id="scroll_speed"
                        min="0.1" max="2.0" step="0.1"
                        value="{scroll_speed}"
                        oninput="scroll_speed_number.value = this.value">
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

        bindNumberToSlider("scroll_speed_number", "scroll_speed");
        bindNumberToSlider("brightness_number", "brightness");
        bindNumberToSlider("refresh_interval_number", "refresh_interval");
    </script>
</body>
</html>
    """


@app.route("/save_games", methods=["POST"])
@login_required
def save_games():
    visible_games = request.form.getlist("game")

    all_game_ids = [
        f"{game.away}@{game.home}"
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
    update_settings({
        "scroll_speed": float(request.form["scroll_speed"]),
        "brightness": int(request.form["brightness"]),
        "refresh_interval": int(request.form["refresh_interval"]),
    })

    return redirect("/settings")