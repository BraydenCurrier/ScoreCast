from datetime import datetime, timedelta
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

NFL_SEARCH_DAYS = 45
NFL_SLATE_DAYS = 6

_session = requests.Session()
_session.headers.update({
    "User-Agent": "ScoreCast/1.0",
    "Accept": "application/json",
})

_session_lock = threading.Lock()

_slate_lock = threading.Lock()
_slate_refresh_lock = threading.Lock()

_slate_cache = {
    # Local calendar date when the slate was selected.
    "selected_on": None,

    # Inclusive date range containing the selected slate.
    "start_date": None,
    "end_date": None,

    # Event IDs prevent an overlapping date range from accidentally
    # including a game from the following NFL week.
    "event_ids": frozenset(),
}

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

def _parse_event_datetime(event):
    """Parse an ESPN event timestamp as a timezone-aware datetime."""
    raw_date = event.get("date")

    if not raw_date:
        return None

    try:
        return datetime.fromisoformat(
            str(raw_date).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None


def _get_local_today():
    """Return the current date in ScoreCast's configured timezone."""
    return datetime.now(
        ZoneInfo(LOCAL_TIMEZONE)
    ).date()


def _fetch_events_between(start_date, end_date):
    """Fetch ESPN NFL data for an inclusive local-date range."""
    params = {
        "dates": (
            f"{start_date.strftime('%Y%m%d')}-"
            f"{end_date.strftime('%Y%m%d')}"
        ),
        "limit": 1000,
    }

    with _session_lock:
        response = _session.get(
            NFL_SCHEDULE_URL,
            params=params,
            timeout=HTTP_TIMEOUT,
            verify=CA_BUNDLE,
        )

    response.raise_for_status()
    return response.json()


def _get_event_slate_key(event):
    """Return a stable season/week key when ESPN provides one."""
    season = event.get("season", {})
    season_year = safe_int(
        season.get("year") if isinstance(season, dict) else None,
        0,
    )
    season_type = safe_int(
        season.get("type") if isinstance(season, dict) else None,
        0,
    )
    week_number = _get_event_week(event)

    if season_year and season_type and week_number:
        return season_year, season_type, week_number

    return None


def _select_next_slate(events):
    """
    Select the nearest unfinished NFL slate.

    ESPN's season type and week number are preferred so a future Thursday
    game is not mixed into the current week's Sunday/Monday slate. A bounded
    date window is used only when week metadata is unavailable.
    """
    utc_timezone = ZoneInfo("UTC")
    now_utc = datetime.now(
        ZoneInfo(LOCAL_TIMEZONE)
    ).astimezone(utc_timezone)

    upcoming_events = []
    seen_event_ids = set()

    for event in events:
        event_time = _parse_event_datetime(event)

        if event_time is None:
            continue

        status_type = (
            event.get("status", {})
            .get("type", {})
        )

        if bool(status_type.get("completed", False)):
            continue

        state = str(
            status_type.get("state", "")
        ).lower()

        # Preserve games ESPN identifies as active after scheduled kickoff.
        if event_time < now_utc and state != "in":
            continue

        event_id = str(event.get("id", ""))

        if event_id and event_id in seen_event_ids:
            continue

        if event_id:
            seen_event_ids.add(event_id)

        upcoming_events.append(event)

    upcoming_events.sort(
        key=lambda event: (
            _parse_event_datetime(event)
            or datetime.max.replace(tzinfo=utc_timezone)
        )
    )

    if not upcoming_events:
        return []

    first_event = upcoming_events[0]
    first_game_time = _parse_event_datetime(first_event)

    if first_game_time is None:
        return []

    first_slate_key = _get_event_slate_key(first_event)

    if first_slate_key is not None:
        same_week_events = [
            event
            for event in upcoming_events
            if _get_event_slate_key(event) == first_slate_key
        ]

        if same_week_events:
            return same_week_events

    # Fallback for incomplete ESPN metadata. Six days is wide enough for
    # normal Thursday-through-Monday slates, but is used only when a week
    # identity cannot be established.
    slate_end = first_game_time + timedelta(
        days=NFL_SLATE_DAYS
    )

    return [
        event
        for event in upcoming_events
        if (
            (event_time := _parse_event_datetime(event))
            is not None
            and event_time <= slate_end
        )
    ]

def _find_next_slate_dates(today):
    """Search once for the nearest slate and return its local date range."""
    search_end = today + timedelta(
        days=NFL_SEARCH_DAYS
    )

    data = _fetch_events_between(
        today,
        search_end,
    )

    events = _select_next_slate(
        data.get("events", [])
    )

    if not events:
        return None, None, frozenset()

    local_timezone = ZoneInfo(LOCAL_TIMEZONE)
    event_dates = []
    event_ids = set()

    for event in events:
        event_time = _parse_event_datetime(event)

        if event_time is None:
            continue

        event_dates.append(
            event_time.astimezone(
                local_timezone
            ).date()
        )

        event_id = str(event.get("id", ""))
        if event_id:
            event_ids.add(event_id)

    if not event_dates:
        return None, None, frozenset()

    return (
        min(event_dates),
        max(event_dates),
        frozenset(event_ids),
    )


def _get_slate_dates():
    """
    Return the slate selected for the current local date.

    The wide schedule search runs on the first call after startup and on
    the first normal API refresh after the local date changes at midnight.
    """
    today = _get_local_today()

    with _slate_lock:
        if _slate_cache["selected_on"] == today:
            return (
                _slate_cache["start_date"],
                _slate_cache["end_date"],
                _slate_cache["event_ids"],
            )

    # Serialize the expensive daily search without holding the state lock.
    with _slate_refresh_lock:
        with _slate_lock:
            if _slate_cache["selected_on"] == today:
                return (
                    _slate_cache["start_date"],
                    _slate_cache["end_date"],
                    _slate_cache["event_ids"],
                )

        start_date, end_date, event_ids = _find_next_slate_dates(
            today
        )

        with _slate_lock:
            _slate_cache["selected_on"] = today
            _slate_cache["start_date"] = start_date
            _slate_cache["end_date"] = end_date
            _slate_cache["event_ids"] = event_ids

        return start_date, end_date, event_ids


def _get_event_week(event, default_week=0):
    """Read the week number from an event when ESPN provides it."""
    event_week = event.get("week", {})

    if isinstance(event_week, dict):
        week_number = safe_int(
            event_week.get("number"),
            0,
        )

        if week_number:
            return week_number

    season = event.get("season", {})

    if isinstance(season, dict):
        week_number = safe_int(
            season.get("week"),
            0,
        )

        if week_number:
            return week_number

    return default_week

def _get_broadcast(event, competition):
    """
    Return a readable broadcast string such as:
    "ESPN", "CBS", or "ESPN, ABC".
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
    slate_start, slate_end, slate_event_ids = _get_slate_dates()

    if slate_start is None or slate_end is None:
        return []

    # Normal application refreshes still update this slate's live data.
    # Only the wide slate-selection search is limited to once per local day.
    data = _fetch_events_between(
        slate_start,
        slate_end,
    )

    events = data.get("events", [])

    if slate_event_ids:
        events = [
            event
            for event in events
            if str(event.get("id", "")) in slate_event_ids
        ]

    default_week = safe_int(
        data.get("week", {}).get("number"),
        0,
    )

    games = []

    for event in events:
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

        last_play = situation.get("lastPlay") or {}

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

            broadcast=_get_broadcast(
                event,
                competition,
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

            last_play_id=str(last_play.get("id", "")),
            last_play_text=str(last_play.get("text", "")),
            scoring_play=bool(last_play.get("scoringPlay", False)),

            yardline_side=yardline_side,
            yardline_number=yardline_number,

            date=_format_event_date(
                raw_event_date
            ),

            week=_get_event_week(
                event,
                default_week,
            ),

            event_id=str(
                event.get("id", "")
            ),
        )

        games.append(game)

    return games