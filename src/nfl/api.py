from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from nfl.models import FootballGame

NFL_SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
LOCAL_TIMEZONE = "America/Chicago"
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

HTTP_TIMEOUT = (3.05, 10)

_session = requests.Session()
_session.headers.update({
    "User-Agent": "P4SportsTicker/1.0",
    "Accept": "application/json",
})

def get_team_abbr(team):
    return team.get("abbreviation", team.get("name", "")[:3].upper())


def format_local_time(utc_time_str):
    utc_dt = datetime.fromisoformat(
        utc_time_str.replace("Z", "+00:00")
    )

    local_dt = utc_dt.astimezone(
        ZoneInfo(LOCAL_TIMEZONE)
    )

    return local_dt.strftime("%-I:%M")


def get_record(team_data):
    records = team_data.get("records", [])
    if not records:
        return {"wins": 0, "losses": 0}
        
    summary = records[0].get("summary", "0-0")
    try:
        parts = summary.split("-")
        return {
            "wins": int(parts[0]),
            "losses": int(parts[1]),
        }
    except (ValueError, IndexError):
        return {"wins": 0, "losses": 0}

def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def get_today_games():
    response = _session.get(
        NFL_SCHEDULE_URL,
        timeout=HTTP_TIMEOUT,
        verify=CA_BUNDLE,
    )

    response.raise_for_status()

    data = response.json()
    games = []

    for event in data.get("events", []):
        competition = event["competitions"][0]
        status_info = event["status"]
        situation = competition.get("situation", {})

        home_data = competition["competitors"][0]
        away_data = competition["competitors"][1]

        home_team = home_data["team"]
        away_team = away_data["team"]

        home_record = get_record(home_data)
        away_record = get_record(away_data)

        possession_id = situation.get("possession")
        possession_abbr = ""
        if possession_id:
            for comp in [home_data, away_data]:
                if comp["id"] == str(possession_id):
                    possession_abbr = comp["team"].get("abbreviation", "")

        yardline_side = ""
        if "lastPlay" in situation:
            yardline_side = situation["lastPlay"].get("type", {}).get("text", "")[:3]

        raw_date_string = event.get("date", "")
        formatted_date = ""

        if raw_date_string:
            try:
                clean_date = raw_date_string.replace("Z", "")
                dt = datetime.fromisoformat(clean_date)
                formatted_date = dt.strftime("%b %d").upper()
            except ValueError:
                formatted_date = raw_date_string

        games.append(
            FootballGame(
                away=get_team_abbr(away_team),
                home=get_team_abbr(home_team),

                status=status_info["type"]["name"],
                start_time=format_local_time(event["date"]),

                away_score=safe_int(away_data.get("score")),
                home_score=safe_int(home_data.get("score")),

                away_wins=away_record["wins"],
                away_losses=away_record["losses"],
                home_wins=home_record["wins"],
                home_losses=home_record["losses"],

                quarter=int(status_info.get("period", 0)),
                clock=status_info.get("displayClock", ""),

                possession=possession_abbr,
                down=int(situation.get("down", 0)),
                distance=int(situation.get("distance", 0)),

                yardline_side=yardline_side,
                yardline_number=int(situation.get("yardline", 0)),
                date=formatted_date,
                week=int(data.get("week", {}).get("number", 0)),
            )
        )

    return games