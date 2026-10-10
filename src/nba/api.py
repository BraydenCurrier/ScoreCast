from datetime import datetime
import json

import requests

from common.espn_scoreboard import (
    bonus_side,
    possession_abbr,
    team_abbr,
    timeouts_remaining,
)
from common.http import failure_text, get_body
from common.timezone import get_local_timezone

from nba.models import BasketballGame


NBA_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "basketball/nba/scoreboard"
)


HTTP_TIMEOUT = (3.05, 10)


def fetch_nba_scoreboard():
    try:
        body = get_body(
            NBA_SCOREBOARD_URL,
            HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "NBA ESPN request failed: "
            f"{failure_text(exc)[:300]}"
        ) from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "NBA ESPN endpoint returned invalid JSON: "
            f"{body[:300]}"
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

from common.broadcast import format_broadcast as _get_broadcast

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

        away_team = team_abbr(away)
        home_team = team_abbr(home)
        situation = competition.get("situation") or {}

        away_wins, away_losses = get_record(away)
        home_wins, home_losses = get_record(home)

        status = competition["status"]
        status_type = status.get("type") or {}
        state = str(status_type.get("state") or "").lower()
        detail = " ".join(
            [
                str(status_type.get("name") or ""),
                str(status_type.get("description") or ""),
                str(status_type.get("detail") or ""),
                str(status_type.get("shortDetail") or ""),
            ]
        ).lower()

        quarter = int(status.get("period") or 0)
        clock = str(status.get("displayClock") or "").strip()
        if clock in {"0.0", "0:00", "0"}:
            clock = ""

        if state == "pre":
            game_status = "Scheduled"
            quarter = 0
            clock = ""
        elif "halftime" in detail or "half-time" in detail:
            game_status = "Halftime"
            clock = ""
        elif state == "in":
            game_status = "Live"
        else:
            game_status = "Final"
            clock = ""
            if quarter < 4:
                quarter = 4

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
                possession=possession_abbr(
                    situation,
                    home,
                    away,
                ),
                away_timeouts=timeouts_remaining(
                    situation,
                    "away",
                    cap=7,
                ),
                home_timeouts=timeouts_remaining(
                    situation,
                    "home",
                    cap=7,
                ),
                bonus=bonus_side(
                    situation,
                    home_team,
                    away_team,
                ),
            )
        )

    return games