from datetime import datetime
import re
import threading
from zoneinfo import ZoneInfo

import requests

from nfl.models import FootballGame


NFL_SCHEDULE_URL = (
    "https://site.api.espn.com/apis/site/v2/"
    "sports/football/nfl/scoreboard"
)

LOCAL_TIMEZONE = "America/Chicago"
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

HTTP_TIMEOUT = (3.05, 10)


_session = requests.Session()
_session.headers.update({
    "User-Agent": "ScoreCast/1.0",
    "Accept": "application/json",
})

_session_lock = threading.Lock()


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_team_abbr(team):
    abbreviation = team.get("abbreviation")

    if abbreviation:
        return str(abbreviation).upper()

    name = str(team.get("name", ""))

    return name[:3].upper()


def format_local_time(utc_time_str):
    if not utc_time_str:
        return ""

    try:
        utc_dt = datetime.fromisoformat(
            str(utc_time_str).replace("Z", "+00:00")
        )
    except ValueError:
        return str(utc_time_str)

    local_dt = utc_dt.astimezone(
        ZoneInfo(LOCAL_TIMEZONE)
    )

    return local_dt.strftime("%-I:%M")


def get_record(team_data):
    records = team_data.get("records", [])

    if not records:
        return {
            "wins": 0,
            "losses": 0,
        }

    summary = str(
        records[0].get("summary", "0-0")
    )

    try:
        parts = summary.split("-")

        return {
            "wins": int(parts[0]),
            "losses": int(parts[1]),
        }
    except (ValueError, IndexError):
        return {
            "wins": 0,
            "losses": 0,
        }


def _get_home_and_away(competition):

    competitors = competition.get(
        "competitors",
        [],
    )

    home_data = next(
        (
            competitor
            for competitor in competitors
            if competitor.get("homeAway") == "home"
        ),
        None,
    )

    away_data = next(
        (
            competitor
            for competitor in competitors
            if competitor.get("homeAway") == "away"
        ),
        None,
    )

    if home_data is None and competitors:
        home_data = competitors[0]

    if away_data is None and len(competitors) > 1:
        away_data = competitors[1]

    return home_data or {}, away_data or {}


def _get_possession_abbr(
    situation,
    home_data,
    away_data,
):

    possession_id = situation.get("possession")

    if possession_id is None:
        return ""

    possession_id = str(possession_id)

    for competitor in (home_data, away_data):
        competitor_id = str(
            competitor.get("id", "")
        )

        if competitor_id != possession_id:
            continue

        team = competitor.get("team", {})

        return get_team_abbr(team)

    return ""


def _parse_field_position(
    situation,
    away_abbr,
    home_abbr,
):
    
    raw_yardline = safe_int(
        situation.get("yardline"),
        0,
    )

    valid_sides = {
        abbreviation
        for abbreviation in (
            away_abbr,
            home_abbr,
        )
        if abbreviation
    }

    last_play = situation.get("lastPlay") or {}

    candidate_texts = [
        situation.get("possessionText", ""),
        situation.get(
            "shortDownDistanceText",
            "",
        ),
        situation.get(
            "downDistanceText",
            "",
        ),
        last_play.get("text", ""),
    ]

    for candidate in candidate_texts:
        text = str(candidate or "").upper()

        if not text:
            continue

        matches = re.findall(
            r"\b([A-Z]{2,3})\s+(\d{1,2})\b",
            text,
        )

        for side, number_text in reversed(matches):
            if side not in valid_sides:
                continue

            number = safe_int(
                number_text,
                raw_yardline,
            )

            if 0 < number <= 50:
                return side, number

        if re.search(r"\b50\b", text):
            return "", 50

    if raw_yardline == 50:
        return "", 50

    if 0 < raw_yardline < 50:
        return "", raw_yardline

    return "", 0


def _format_event_date(raw_date_string):
    if not raw_date_string:
        return ""

    try:
        parsed_date = datetime.fromisoformat(
            str(raw_date_string).replace(
                "Z",
                "+00:00",
            )
        )

        local_date = parsed_date.astimezone(
            ZoneInfo(LOCAL_TIMEZONE)
        )

        return local_date.strftime(
            "%b %d"
        ).upper()

    except ValueError:
        return str(raw_date_string)


def get_today_games():
    with _session_lock:
        response = _session.get(
            NFL_SCHEDULE_URL,
            timeout=HTTP_TIMEOUT,
            verify=CA_BUNDLE,
        )

    response.raise_for_status()

    data = response.json()
    games = []

    for event in data.get("events", []):
        competitions = event.get(
            "competitions",
            [],
        )

        if not competitions:
            continue

        competition = competitions[0]
        status_info = event.get("status", {})
        status_type = status_info.get(
            "type",
            {},
        )

        situation = competition.get(
            "situation",
            {},
        ) or {}

        home_data, away_data = (
            _get_home_and_away(
                competition
            )
        )

        home_team = home_data.get(
            "team",
            {},
        )

        away_team = away_data.get(
            "team",
            {},
        )

        home_abbr = get_team_abbr(
            home_team
        )

        away_abbr = get_team_abbr(
            away_team
        )

        # Ignore malformed events that do not contain two teams.
        if not home_abbr or not away_abbr:
            continue

        home_record = get_record(
            home_data
        )

        away_record = get_record(
            away_data
        )

        possession_abbr = (
            _get_possession_abbr(
                situation,
                home_data,
                away_data,
            )
        )

        (
            yardline_side,
            yardline_number,
        ) = _parse_field_position(
            situation,
            away_abbr,
            home_abbr,
        )

        raw_event_date = event.get(
            "date",
            "",
        )

        game = FootballGame(
            away=away_abbr,
            home=home_abbr,

            status=str(
                status_type.get(
                    "name",
                    "",
                )
            ),

            start_time=format_local_time(
                raw_event_date
            ),

            away_score=safe_int(
                away_data.get("score")
            ),

            home_score=safe_int(
                home_data.get("score")
            ),

            away_wins=away_record["wins"],
            away_losses=away_record["losses"],

            home_wins=home_record["wins"],
            home_losses=home_record["losses"],

            quarter=safe_int(
                status_info.get("period"),
                0,
            ),

            clock=str(
                status_info.get(
                    "displayClock",
                    "",
                )
            ),

            possession=possession_abbr,

            down=safe_int(
                situation.get("down"),
                0,
            ),

            distance=safe_int(
                situation.get("distance"),
                0,
            ),

            yardline_side=yardline_side,
            yardline_number=yardline_number,

            date=_format_event_date(
                raw_event_date
            ),

            week=safe_int(
                data.get(
                    "week",
                    {},
                ).get("number"),
                0,
            ),

            event_id=str(
                event.get("id", "")
            ),
        )

        games.append(game)

    return games