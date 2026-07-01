from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from mlb.models import BaseballGame

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
LOCAL_TIMEZONE = "America/Chicago"
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

TEAM_ABBR = {
    108: "LAA", 109: "ARI", 110: "BAL", 111: "BOS", 112: "CHC",
    113: "CIN", 114: "CLE", 115: "COL", 116: "DET", 117: "HOU",
    118: "KC", 119: "LAD", 120: "WSH", 121: "NYM", 133: "ATH",
    134: "PIT", 135: "SD", 136: "SEA", 137: "SF", 138: "STL",
    139: "TB", 140: "TEX", 141: "TOR", 142: "MIN", 143: "PHI",
    144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
}


def get_team_abbr(team):
    return TEAM_ABBR.get(team["id"], team["name"][:3].upper())


def format_local_time(utc_time_str):
    utc_dt = datetime.fromisoformat(
        utc_time_str.replace("Z", "+00:00")
    )

    local_dt = utc_dt.astimezone(
        ZoneInfo(LOCAL_TIMEZONE)
    )

    return local_dt.strftime("%-I:%M")


def get_record(team_data):
    record = team_data.get("leagueRecord", {})

    return {
        "wins": record.get("wins", 0),
        "losses": record.get("losses", 0),
    }


def get_today_games():
    today = datetime.now(
        ZoneInfo(LOCAL_TIMEZONE)
    ).strftime("%Y-%m-%d")

    params = {
        "sportId": 1,
        "date": today,
        "hydrate": "probablePitcher,linescore,team",
    }

    response = requests.get(
        MLB_SCHEDULE_URL,
        params=params,
        timeout=10,
        verify=CA_BUNDLE,
    )

    response.raise_for_status()

    data = response.json()
    games = []

    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            linescore = game.get("linescore", {})

            away_data = game["teams"]["away"]
            home_data = game["teams"]["home"]

            away_team = away_data["team"]
            home_team = home_data["team"]

            away_record = get_record(away_data)
            home_record = get_record(home_data)

            games.append(
                BaseballGame(
                    away=get_team_abbr(away_team),
                    home=get_team_abbr(home_team),

                    status=game["status"]["abstractGameState"],
                    start_time=format_local_time(game["gameDate"]),

                    away_score=away_data.get("score", 0),
                    home_score=home_data.get("score", 0),

                    away_wins=away_record["wins"],
                    away_losses=away_record["losses"],
                    home_wins=home_record["wins"],
                    home_losses=home_record["losses"],

                    inning=linescore.get("currentInning", 0),
                    top_inning=linescore.get("inningHalf") == "Top",

                    first=bool(linescore.get("offense", {}).get("first")),
                    second=bool(linescore.get("offense", {}).get("second")),
                    third=bool(linescore.get("offense", {}).get("third")),

                    outs=linescore.get("outs", 0),
                )
            )

    return games