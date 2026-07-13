from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from soccer.models import SoccerGame

ESPN_WORLD_CUP_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
)

CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
LOCAL_TIMEZONE = "America/Chicago"

HTTP_TIMEOUT = (3.05, 10)

_session = requests.Session()
_session.headers.update({
    "User-Agent": "P4SportsTicker/1.0",
    "Accept": "application/json",
})

def format_local_time(utc_time_str):
    utc_dt = datetime.fromisoformat(
        utc_time_str.replace("Z", "+00:00")
    )

    local_dt = utc_dt.astimezone(
        ZoneInfo(LOCAL_TIMEZONE)
    )

    return local_dt.strftime("%-I:%M")


def get_game_status(status_type):
    detail = (
        status_type.get("shortDetail")
        or status_type.get("detail")
        or status_type.get("description")
        or status_type.get("name")
        or "Scheduled"
    )

    return str(detail).upper()

def format_game_date(utc_time_str):
    utc_dt = datetime.fromisoformat(
        utc_time_str.replace("Z", "+00:00")
    )

    local_dt = utc_dt.astimezone(
        ZoneInfo(LOCAL_TIMEZONE)
    )

    return local_dt.strftime("%b %d").upper()

def get_minute(status_type):
    detail = status_type.get("shortDetail", "")

    if "'" not in detail:
        return 0

    minute_text = detail.split("'")[0]

    try:
        return int(minute_text)
    except Exception:
        return 0


def get_stoppage(status_type):
    detail = status_type.get("shortDetail", "")

    if "+" not in detail:
        return ""

    try:
        return "+" + detail.split("+")[1].replace("'", "")
    except Exception:
        return ""


def get_team_abbr(competitor):
    team = competitor.get("team", {})

    return (
        team.get("abbreviation")
        or team.get("shortDisplayName")
        or team.get("displayName", "TBD")[:3]
    ).upper()


def get_score(competitor):
    score = competitor.get("score", 0)

    try:
        return int(score)
    except Exception:
        return 0


def get_today_games():
    now = datetime.now(ZoneInfo(LOCAL_TIMEZONE))

    start_date = now.strftime("%Y%m%d")
    end_date = (now + timedelta(days=3)).strftime("%Y%m%d")

    params = {
        "dates": f"{start_date}-{end_date}",
        "limit": 100,
    }

    response = _session.get(
        ESPN_WORLD_CUP_URL,
        params=params,
        timeout=HTTP_TIMEOUT,
        verify=CA_BUNDLE,
    )

    response.raise_for_status()

    data = response.json()
    games = []

    for event in data.get("events", []):
        competition = event.get("competitions", [{}])[0]
        competitors = competition.get("competitors", [])

        away = None
        home = None

        for competitor in competitors:
            if competitor.get("homeAway") == "away":
                away = competitor
            elif competitor.get("homeAway") == "home":
                home = competitor

        if not away or not home:
            continue

        status_type = competition.get("status", {}).get("type", {})

        games.append(
            SoccerGame(
                away=get_team_abbr(away),
                home=get_team_abbr(home),

                away_score=get_score(away),
                home_score=get_score(home),

                status=get_game_status(status_type),
                start_time=format_local_time(event["date"]),
                date=format_game_date(event["date"]),

                minute=get_minute(status_type),
                stoppage=get_stoppage(status_type),

                tournament="FIFA WORLD CUP",
                stage=event.get("season", {}).get("slug", "Group Stage")
            )
        )

    return games