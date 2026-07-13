from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from nhl.models import HockeyGame

NHL_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"

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
        return 0, 0, 0

    summary = records[0].get("summary", "0-0-0")
    parts = summary.split("-")

    wins = int(parts[0]) if len(parts) > 0 else 0
    losses = int(parts[1]) if len(parts) > 1 else 0
    ot_losses = int(parts[2]) if len(parts) > 2 else 0

    return wins, losses, ot_losses


def get_period_status(status):
    state = status["type"]["state"]
    name = status["type"].get("name", "")
    detail = status["type"].get("detail", "")
    short_detail = status["type"].get("shortDetail", "")

    period = status.get("period", 0)
    clock = status.get("displayClock", "")

    intermission = False
    overtime = False
    shootout = False

    if state == "pre":
        game_status = "Scheduled"
        period = 0
        clock = ""

    elif state == "in":
        game_status = "Live"

        text = f"{name} {detail} {short_detail}".lower()

        if "intermission" in text:
            game_status = "Intermission"
            intermission = True

        if period > 3 or "overtime" in text or " ot" in text:
            game_status = "Overtime"
            overtime = True

        if "shootout" in text:
            game_status = "Shootout"
            shootout = True

    else:
        game_status = "Final"

        text = f"{name} {detail} {short_detail}".lower()

        if "shootout" in text:
            shootout = True

        if "overtime" in text or " ot" in text:
            overtime = True

    return game_status, period, clock, intermission, overtime, shootout


def get_today_games():
    response = _session.get(
        NHL_SCOREBOARD_URL,
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

        away_wins, away_losses, away_ot_losses = get_record(away)
        home_wins, home_losses, home_ot_losses = get_record(home)

        status = competition["status"]

        (
            game_status,
            period,
            clock,
            intermission,
            overtime,
            shootout,
        ) = get_period_status(status)

        games.append(
            HockeyGame(
                away=away_team,
                home=home_team,

                status=game_status,
                start_time=format_local_time(event["date"]),
                date=format_local_date(event["date"]),

                away_score=int(away.get("score", 0)),
                home_score=int(home.get("score", 0)),

                away_wins=away_wins,
                away_losses=away_losses,
                away_ot_losses=away_ot_losses,

                home_wins=home_wins,
                home_losses=home_losses,
                home_ot_losses=home_ot_losses,

                period=period,
                clock=clock,

                intermission=intermission,
                overtime=overtime,
                shootout=shootout,
            )
        )

    return games