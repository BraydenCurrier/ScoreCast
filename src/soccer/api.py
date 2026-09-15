from datetime import datetime
import json
import subprocess

from common.settings import get_settings
from common.timezone import get_local_timezone
from soccer.models import SoccerGame


SOCCER_LEAGUES = {
    "eng.1": "Premier League",
    "uefa.champions": "Champions League",
    "usa.1": "MLS",
    "esp.1": "La Liga",
    "ger.1": "Bundesliga",
    "ita.1": "Serie A",
    "mex.1": "Liga MX",
}

SOCCER_LEAGUE_SHORT = {
    "eng.1": "EPL",
    "uefa.champions": "UCL",
    "usa.1": "MLS",
    "esp.1": "LIGA",
    "ger.1": "BUND",
    "ita.1": "SERA",
    "mex.1": "MX",
}

DEFAULT_SOCCER_LEAGUES = [
    "eng.1",
    "uefa.champions",
    "usa.1",
]

SOCCER_SCOREBOARD_URL = (
    "https://site.web.api.espn.com/apis/site/v2/"
    "sports/soccer/{league}/scoreboard"
)

HTTP_TIMEOUT = (3.05, 10)

SKIP_STATUS_NAMES = {
    "STATUS_POSTPONED",
    "STATUS_CANCELED",
    "STATUS_CANCELLED",
    "STATUS_ABANDONED",
    "STATUS_SUSPENDED",
}


def get_selected_leagues():
    settings = get_settings()
    soccer_settings = settings.get("soccer", {})
    selected = soccer_settings.get(
        "selected_leagues",
        DEFAULT_SOCCER_LEAGUES,
    )

    if not isinstance(selected, list):
        return DEFAULT_SOCCER_LEAGUES.copy()

    selected = [
        str(league_id)
        for league_id in selected
        if str(league_id) in SOCCER_LEAGUES
    ]

    if not selected:
        return DEFAULT_SOCCER_LEAGUES.copy()

    return selected


def fetch_soccer_scoreboard(league_id):
    url = SOCCER_SCOREBOARD_URL.format(
        league=league_id
    )

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
        url,
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
            "Soccer ESPN request failed: "
            f"{response_text[:300]}"
        ) from exc

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Soccer ESPN endpoint returned invalid JSON: "
            f"{result.stdout[:300]}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            "Unexpected soccer ESPN response type: "
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
        return 0, 0, 0

    summary = records[0].get(
        "summary",
        "0-0-0",
    )
    parts = str(summary).split("-")

    wins = int(parts[0]) if len(parts) > 0 else 0
    draws = int(parts[1]) if len(parts) > 1 else 0
    losses = int(parts[2]) if len(parts) > 2 else 0

    return wins, draws, losses


def format_soccer_clock(display_clock):
    clock = str(display_clock or "").strip()
    clock = clock.replace("'", "")
    clock = clock.replace(" ", "")

    if not clock or clock in {"0", "0:00"}:
        return ""

    return clock


def get_match_status(status):
    status_type = status.get("type", {})
    state = str(status_type.get("state", "")).lower()
    name = str(status_type.get("name", "")).upper()
    detail = str(status_type.get("detail", "")).lower()
    short_detail = str(
        status_type.get("shortDetail", "")
    ).lower()
    description = str(
        status_type.get("description", "")
    ).lower()

    period = int(status.get("period") or 0)
    clock = format_soccer_clock(
        status.get("displayClock", "")
    )

    text = (
        f"{name} {detail} {short_detail} {description}"
    )

    if name in SKIP_STATUS_NAMES:
        return None

    if state == "pre":
        return "Scheduled", 0, ""

    if "halftime" in text or "half-time" in text:
        return "Halftime", max(period, 1), ""

    if "penalty" in text or "shootout" in text:
        return "Penalties", period, clock

    if "extra" in text or "aet" in text:
        return "Extra Time", max(period, 3), clock

    if state == "in":
        return "Live", period, clock

    return "Final", period, clock


def _get_broadcast(event, competition):
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


def _parse_events(data, league_id):
    games = []
    league_name = SOCCER_LEAGUES.get(
        league_id,
        "Soccer",
    )
    league_short = SOCCER_LEAGUE_SHORT.get(
        league_id,
        "SOC",
    )

    leagues = data.get("leagues") or []
    if leagues and isinstance(leagues[0], dict):
        league_name = leagues[0].get(
            "name",
            league_name,
        ) or league_name

    for event in data.get("events", []):
        competitions = event.get("competitions") or []

        if not competitions:
            continue

        competition = competitions[0]
        competitors = competition.get(
            "competitors",
            [],
        )

        try:
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
        except (StopIteration, KeyError, TypeError):
            continue

        parsed_status = get_match_status(
            competition.get("status", {})
        )

        if parsed_status is None:
            continue

        game_status, period, clock = parsed_status

        away_wins, away_draws, away_losses = get_record(
            away
        )
        home_wins, home_draws, home_losses = get_record(
            home
        )

        games.append(
            SoccerGame(
                away=away["team"]["abbreviation"],
                home=home["team"]["abbreviation"],
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
                away_score=int(away.get("score", 0) or 0),
                home_score=int(home.get("score", 0) or 0),
                away_wins=away_wins,
                away_draws=away_draws,
                away_losses=away_losses,
                home_wins=home_wins,
                home_draws=home_draws,
                home_losses=home_losses,
                period=period,
                clock=clock,
                league_id=league_id,
                league_name=league_name,
                league_short=league_short,
                event_id=str(event.get("id", "")),
            )
        )

    return games


def get_today_games():
    games = []
    seen_event_ids = set()
    errors = []

    for league_id in get_selected_leagues():
        try:
            data = fetch_soccer_scoreboard(league_id)
            league_games = _parse_events(
                data,
                league_id,
            )
        except Exception as exc:
            errors.append(f"{league_id}: {exc}")
            continue

        for game in league_games:
            event_key = game.event_id or (
                f"{game.league_id}:"
                f"{game.away}@{game.home}"
            )

            if event_key in seen_event_ids:
                continue

            seen_event_ids.add(event_key)
            games.append(game)

    if errors and not games:
        raise RuntimeError(
            "Soccer refresh failed: "
            + "; ".join(errors)
        )

    return games
