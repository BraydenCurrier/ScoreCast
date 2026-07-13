from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from nba.models import BasketballGame

NBA_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "basketball/nba/scoreboard"
)

LOCAL_TIMEZONE = "America/Chicago"
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

HTTP_TIMEOUT = (3.05, 10)

_session = requests.Session()
_session.headers.update({
    "User-Agent": "P4SportsTicker/1.0",
    "Accept": "application/json",
})

def format_local_time(date_string):
    utc_dt = datetime.fromisoformat(
        date_string.replace("Z", "+00:00")
    )

    local_dt = utc_dt.astimezone(
        ZoneInfo(LOCAL_TIMEZONE)
    )

    return local_dt.strftime("%-I:%M")


def format_local_date(date_string):
    utc_dt = datetime.fromisoformat(
        date_string.replace("Z", "+00:00")
    )

    local_dt = utc_dt.astimezone(
        ZoneInfo(LOCAL_TIMEZONE)
    )

    return local_dt.strftime("%b %-d")


def get_record(team):
    records = team.get("records", [])

    if not records:
        return 0, 0

    summary = records[0]["summary"]

    wins, losses = summary.split("-")

    return int(wins), int(losses)


def get_today_games():
    response = _session.get(
        NBA_SCOREBOARD_URL,
        timeout=HTTP_TIMEOUT,
        verify=CA_BUNDLE,
    )

    response.raise_for_status()

    data = response.json()

    games = []

    for event in data.get("events", []):

        competition = event["competitions"][0]

        competitors = competition["competitors"]

        away = next(
            c for c in competitors
            if c["homeAway"] == "away"
        )

        home = next(
            c for c in competitors
            if c["homeAway"] == "home"
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
            clock = status.get("displayClock", "")

        else:
            game_status = "Final"
            quarter = status.get("period", 4)
            clock = ""

        games.append(
            BasketballGame(
                away=away_team,
                home=home_team,

                status=game_status,

                start_time=format_local_time(event["date"]),
                date=format_local_date(event["date"]),

                away_score=int(away["score"]),
                home_score=int(home["score"]),

                away_wins=away_wins,
                away_losses=away_losses,

                home_wins=home_wins,
                home_losses=home_losses,

                quarter=quarter,
                clock=clock,
            )
        )

    return games