from datetime import datetime
import json

import requests

from common.espn_scoreboard import (
    competitor_stat_int,
    safe_int,
    team_abbr,
)
from common.http import failure_text, get_body
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

    try:
        body = get_body(
            url,
            HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "Soccer ESPN request failed: "
            f"{failure_text(exc)[:300]}"
        ) from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Soccer ESPN endpoint returned invalid JSON: "
            f"{body[:300]}"
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


def format_soccer_clock(display_clock, added_time=None):
    clock = str(display_clock or "").strip()
    clock = clock.replace("'", "")
    clock = clock.replace(" ", "")

    if not clock or clock in {"0", "0:00"}:
        clock = ""

    extra = safe_int(added_time)
    if extra and extra > 0:
        if "+" in clock:
            return clock
        base = clock or "45"
        return f"{base}+{extra}"

    return clock


def _status_text(status):
    status_type = status.get("type") or {}
    return " ".join(
        [
            str(status_type.get("name") or ""),
            str(status_type.get("description") or ""),
            str(status_type.get("detail") or ""),
            str(status_type.get("shortDetail") or ""),
        ]
    ).lower()


def _red_card_count(competitor, details):
    counted = competitor_stat_int(
        competitor,
        "redCards",
        "redcards",
        "red_cards",
    )
    if counted is not None:
        return max(0, counted)

    team_ids = {
        str(competitor.get("id") or ""),
        str((competitor.get("team") or {}).get("id") or ""),
    }
    total = 0
    for detail in details or []:
        if not isinstance(detail, dict):
            continue
        type_blob = detail.get("type") or {}
        type_id = str(type_blob.get("id") or "")
        type_text = str(type_blob.get("text") or type_blob.get("name") or "").lower()
        is_red = (
            type_id in {"71", "72", "138", "139"}
            or "red card" in type_text
            or "second yellow" in type_text
        )
        if not is_red:
            continue
        detail_team = str((detail.get("team") or {}).get("id") or "")
        if detail_team and detail_team not in team_ids:
            continue
        if not detail_team:
            continue
        total += 1
    return total


def _aggregate_scores(competition, home, away):
    series = competition.get("series") or {}
    if not isinstance(series, dict):
        series = {}

    for blob in (
        series,
        competition.get("aggregate") or {},
    ):
        if not isinstance(blob, dict):
            continue
        competitors = blob.get("competitors") or []
        away_val = None
        home_val = None
        for entry in competitors:
            if not isinstance(entry, dict):
                continue
            entry_id = str(
                entry.get("id")
                or (entry.get("team") or {}).get("id")
                or ""
            )
            score = safe_int(
                entry.get("score", entry.get("value")),
            )
            if score is None:
                continue
            if entry_id in {
                str(away.get("id") or ""),
                str((away.get("team") or {}).get("id") or ""),
            }:
                away_val = score
            elif entry_id in {
                str(home.get("id") or ""),
                str((home.get("team") or {}).get("id") or ""),
            }:
                home_val = score
        if away_val is not None and home_val is not None:
            return away_val, home_val

        summary = str(
            blob.get("summary")
            or blob.get("title")
            or blob.get("shortDetail")
            or ""
        )
        digits = []
        token = ""
        for char in summary:
            if char.isdigit():
                token += char
            elif token:
                digits.append(int(token))
                token = ""
        if token:
            digits.append(int(token))
        if len(digits) >= 2:
            return digits[0], digits[1]

    return None, None


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
        status.get("displayClock", ""),
        status.get("addedTime", status.get("injuryTime")),
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

    if state == "in":
        if "penalt" in text or "shootout" in text:
            return "Penalties", period, clock
        if "extra" in text or "aet" in text:
            return "Extra Time", max(period, 3), clock
        return "Live", period, clock

    return "Final", period, clock


from common.broadcast import format_broadcast as _get_broadcast


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
        status_blob = competition.get("status", {})
        text = _status_text(status_blob)
        extra_time = (
            game_status == "Extra Time"
            or "extra" in text
            or "aet" in text
        )
        penalties = (
            game_status == "Penalties"
            or "penalt" in text
            or "shootout" in text
        )
        details = (
            competition.get("details")
            or event.get("details")
            or []
        )
        away_agg, home_agg = _aggregate_scores(
            competition,
            home,
            away,
        )

        away_wins, away_draws, away_losses = get_record(
            away
        )
        home_wins, home_draws, home_losses = get_record(
            home
        )

        games.append(
            SoccerGame(
                away=team_abbr(away),
                home=team_abbr(home),
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
                extra_time=extra_time,
                penalties=penalties,
                away_reds=_red_card_count(away, details),
                home_reds=_red_card_count(home, details),
                away_pk=safe_int(away.get("shootoutScore")),
                home_pk=safe_int(home.get("shootoutScore")),
                away_agg=away_agg,
                home_agg=home_agg,
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
