from datetime import datetime
import json
import subprocess
from zoneinfo import ZoneInfo
from common.timezone import get_local_timezone

from nba.models import BasketballGame


NBA_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "basketball/nba/scoreboard"
)


HTTP_TIMEOUT = (3.05, 10)


def fetch_nba_scoreboard():
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--fail-with-body",
        "--location",
        "--compressed",
        "--max-time",
        str(HTTP_TIMEOUT[1]),
        "--header",
        "Accept: application/json",
        NBA_SCOREBOARD_URL,
    ]

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "curl is required but is not installed"
        ) from exc
    except subprocess.CalledProcessError as exc:
        response_text = (
            exc.stdout
            or exc.stderr
            or "No response body"
        ).strip()

        raise RuntimeError(
            "NBA ESPN request failed: "
            f"{response_text[:300]}"
        ) from exc

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "NBA ESPN endpoint returned invalid JSON: "
            f"{result.stdout[:300]}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            "Unexpected NBA ESPN response type: "
            f"{type(data).__name__}"
        )

    return data


def format_local_time(date_string):
    utc_dt = datetime.fromisoformat(
        date_string.replace("Z", "+00:00")
    )

    local_dt = utc_dt.astimezone(
        get_local_timezone()
    )

    return local_dt.strftime("%-I:%M")


def format_local_date(date_string):
    utc_dt = datetime.fromisoformat(
        date_string.replace("Z", "+00:00")
    )

    local_dt = utc_dt.astimezone(
        get_local_timezone()
    )

    return local_dt.strftime("%b %-d")


def get_record(team):
    records = team.get("records", [])

    if not records:
        return 0, 0

    summary = records[0].get(
        "summary",
        "0-0",
    )

    try:
        wins, losses = summary.split("-")
        return int(wins), int(losses)
    except (TypeError, ValueError):
        return 0, 0

def _get_broadcast(event, competition):
    """
    Return a readable broadcast string such as:
    "ESPN", "ABC", or "ESPN, ABC".
    """
    broadcast_names = []
    seen_names = set()

    broadcast_sources = [
        competition.get("broadcasts", []),
        event.get("broadcasts", []),
    ]

    for broadcasts in broadcast_sources:
        if not isinstance(broadcasts, list):
            continue

        for broadcast in broadcasts:
            if not isinstance(broadcast, dict):
                continue

            names = broadcast.get("names", [])

            if isinstance(names, str):
                names = [names]

            if not isinstance(names, list):
                continue

            for name in names:
                cleaned_name = str(name or "").strip()

                if not cleaned_name:
                    continue

                normalized_name = cleaned_name.upper()

                if normalized_name in seen_names:
                    continue

                seen_names.add(normalized_name)
                broadcast_names.append(cleaned_name)

    return ", ".join(broadcast_names)

def get_today_games():
    data = fetch_nba_scoreboard()

    games = []

    for event in data.get("events", []):
        competition = event["competitions"][0]

        competitors = competition["competitors"]

        away = next(
            competitor
            for competitor in competitors
            if competitor["homeAway"] == "away"
        )

        home = next(
            competitor
            for competitor in competitors
            if competitor["homeAway"] == "home"
        )

        away_team = away["team"]["abbreviation"]
        home_team = home["team"]["abbreviation"]

        away_wins, away_losses = get_record(away)
        home_wins, home_losses = get_record(home)

        status = competition["status"]
        state = status["type"]["state"]

        if state == "pre":
            game_status = "Scheduled"
            quarter = 0
            clock = ""

        elif state == "in":
            game_status = "Live"
            quarter = status.get("period", 0)
            clock = status.get(
                "displayClock",
                "",
            )

        else:
            game_status = "Final"
            quarter = status.get("period", 4)
            clock = ""

        games.append(
            BasketballGame(
                away=away_team,
                home=home_team,

                status=game_status,

                start_time=format_local_time(
                    event["date"]
                ),
                date=format_local_date(
                    event["date"]
                ),

                broadcast=_get_broadcast(
                    event,
                    competition,
                ),

                away_score=int(
                    away.get("score", 0)
                ),
                home_score=int(
                    home.get("score", 0)
                ),

                away_wins=away_wins,
                away_losses=away_losses,

                home_wins=home_wins,
                home_losses=home_losses,

                quarter=quarter,
                clock=clock,
            )
        )

    return games