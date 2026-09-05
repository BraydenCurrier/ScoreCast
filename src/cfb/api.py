from datetime import datetime

import json
import subprocess

from cfb.models import CollegeFootballGame
from common.settings import get_settings
from common.timezone import get_local_timezone


CFB_CONFERENCES = {
    "80": "All FBS",
    "8": "SEC",
    "5": "Big Ten",
    "1": "ACC",
    "4": "Big 12",
    "17": "Mountain West",
}

DEFAULT_CONFERENCE_GROUPS = ["80"]

NCAAF_SCHEDULE_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/"
    "college-football/scoreboard"
)
NCAAF_RANKINGS_URL = (
    "https://ncaa-api.henrygd.me/"
    "rankings/football/fbs/associated-press"
)

HTTP_TIMEOUT = (3.05, 10)

_rankings_cache = {}
_rankings_cache_date = None


def get_selected_conference_groups():
    settings = get_settings()
    cfb_settings = settings.get("cfb", {})
    selected = cfb_settings.get(
        "selected_conferences",
        DEFAULT_CONFERENCE_GROUPS,
    )

    if not isinstance(selected, list):
        return DEFAULT_CONFERENCE_GROUPS.copy()

    selected = [
        str(group_id)
        for group_id in selected
        if str(group_id) in CFB_CONFERENCES
    ]

    if not selected:
        return DEFAULT_CONFERENCE_GROUPS.copy()

    if "80" in selected:
        return ["80"]

    return selected


def fetch_scoreboard_group(group_id):
    url = (
        f"{NCAAF_SCHEDULE_URL}"
        f"?groups={str(group_id)}"
        "&limit=200"
    )

    command = [
        "curl",
        "--silent",
        "--show-error",
        "--fail-with-body",
        "--location",
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
            "curl is not installed on this system"
        ) from exc
    except subprocess.CalledProcessError as exc:
        response_text = (
            exc.stdout
            or exc.stderr
            or "No response body"
        ).strip()
        raise RuntimeError(
            "CFB curl request failed: "
            f"{response_text[:300]}"
        ) from exc

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "CFB endpoint returned invalid JSON: "
            f"{result.stdout[:300]}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Unexpected CFB response for group {group_id}"
        )

    return data


def _normalize_team_name(name):
    name = str(name or "").strip().lower()

    # Remove AP first-place vote counts:
    # "Ohio State (40)" -> "Ohio State"
    # "Miami (FL) (1)" -> "Miami (FL)"
    if name.endswith(")"):
        open_paren = name.rfind("(")

        if open_paren != -1:
            contents = name[open_paren + 1:-1].strip()

            if contents.isdigit():
                name = name[:open_paren].strip()

    name = (
        name
        .replace(".", "")
        .replace("-", " ")
        .replace("'", "")
    )
    name = " ".join(name.split())

    aliases = {
        "southern cal": "usc",
        "southern california": "usc",
        "miami fl": "miami",
        "miami (fl)": "miami",
        "miami fla": "miami",
        "texas a&m": "texas a&m",
        "ole miss": "ole miss",
    }

    return aliases.get(name, name)


def fetch_rankings():
    global _rankings_cache
    global _rankings_cache_date

    today = datetime.now(
        get_local_timezone()
    ).date()

    if (
        _rankings_cache
        and _rankings_cache_date == today
    ):
        return _rankings_cache

    command = [
        "curl",
        "--silent",
        "--show-error",
        "--fail-with-body",
        "--location",
        "--max-time",
        str(HTTP_TIMEOUT[1]),
        "--header",
        "Accept: application/json",
        NCAAF_RANKINGS_URL,
    ]

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout)
    except Exception as error:
        print(
            f"CFB rankings fetch failed: {error}"
        )
        return _rankings_cache

    rankings = {}

    for entry in data.get("data", []):
        raw_rank = str(
            entry.get("RANK", "")
        ).strip()

        rank_text = raw_rank.lstrip("Tt")
        rank = safe_int(rank_text, 0)

        school = (
            entry.get("SCHOOL (1ST VOTES)")
            or entry.get("SCHOOL")
            or ""
        )

        team_name = _normalize_team_name(school)

        if team_name and rank > 0:
            rankings[team_name] = rank

    if not rankings:
        print(
            "CFB rankings: AP poll returned "
            "no usable teams"
        )
        return _rankings_cache

    _rankings_cache = rankings
    _rankings_cache_date = today

    print(
        "CFB rankings: loaded "
        f"{len(rankings)} AP Top 25 teams"
    )

    return rankings


def get_team_rank(team, rankings):
    candidates = [
        team.get("location"),
        team.get("displayName"),
        team.get("shortDisplayName"),
        team.get("nickname"),
        team.get("name"),
        team.get("abbreviation"),
    ]

    for candidate in candidates:
        normalized = _normalize_team_name(candidate)

        if normalized in rankings:
            return rankings[normalized]

    return None


def get_team_abbr(team):
    team_id = str(team.get("id", ""))

    # Duplicate/special ESPN abbreviations.
    if team_id == "2579":
        return "USCG"  # South Carolina Gamecocks
    if team_id == "30":
        return "USC"   # Southern California Trojans

    raw_abbr = team.get(
        "abbreviation",
        team.get("name", "")[:3].upper(),
    )

    overrides = {
        "TA&M": "TAMU",
        "M-OH": "MOH",
        "AFA": "AF",
    }

    return overrides.get(raw_abbr, raw_abbr)


def format_local_time(utc_time_str):
    utc_dt = datetime.fromisoformat(
        utc_time_str.replace("Z", "+00:00")
    )
    local_dt = utc_dt.astimezone(
        get_local_timezone()
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


def _get_home_away_competitors(competition):
    """
    Resolve ESPN competitors by the explicit homeAway field instead of
    assuming array order.
    """
    competitors = competition.get("competitors", [])

    home_data = next(
        (
            comp
            for comp in competitors
            if str(comp.get("homeAway", "")).lower() == "home"
        ),
        None,
    )
    away_data = next(
        (
            comp
            for comp in competitors
            if str(comp.get("homeAway", "")).lower() == "away"
        ),
        None,
    )

    # Keep a compatibility fallback in case ESPN omits homeAway.
    if home_data is None and competitors:
        home_data = competitors[0]

    if away_data is None and len(competitors) > 1:
        away_data = competitors[1]

    return home_data, away_data


def _normalize_field_side(side, home_team, away_team):
    raw_side = str(side or "").strip().upper()

    if not raw_side:
        return ""

    for team in [home_team, away_team]:
        aliases = {
            str(team.get("abbreviation", "")).strip().upper(),
            str(team.get("shortDisplayName", "")).strip().upper(),
            str(team.get("displayName", "")).strip().upper(),
            str(team.get("location", "")).strip().upper(),
            str(team.get("name", "")).strip().upper(),
            get_team_abbr(team).strip().upper(),
        }

        if raw_side in aliases:
            return get_team_abbr(team)

    return raw_side


def _parse_possession_text(
    possession_text,
    home_team,
    away_team,
):
    """
    Parse ESPN strings such as:
      "UGA 35"
      "TEXAS A&M 42"
      "50"

    None means no usable field position. Zero is a valid yard line and
    therefore must not be used as the "missing" sentinel.
    """
    text = str(possession_text or "").strip()

    if not text:
        return "", None

    if text == "50":
        return "", 50

    parts = text.rsplit(" ", 1)

    if len(parts) != 2:
        return "", None

    side_text, yard_text = parts
    yardline_number = safe_int(yard_text, -1)

    if yardline_number < 0 or yardline_number > 50:
        return "", None

    yardline_side = _normalize_field_side(
        side_text,
        home_team,
        away_team,
    )

    return yardline_side, yardline_number


def _get_field_position(
    situation,
    home_team,
    away_team,
):
    """
    ESPN moves situation data around while a live feed transitions between
    plays. Prefer situation.possessionText when present because it describes
    the current situation, then fall back to lastPlay.end/start.
    """
    if not isinstance(situation, dict):
        return "", None

    candidates = [
        situation.get("possessionText"),
    ]

    last_play = situation.get("lastPlay") or {}

    if isinstance(last_play, dict):
        for spot_name in ("end", "start"):
            spot = last_play.get(spot_name) or {}

            if isinstance(spot, dict):
                candidates.append(
                    spot.get("possessionText")
                )

    for candidate in candidates:
        side, number = _parse_possession_text(
            candidate,
            home_team,
            away_team,
        )

        if number is not None:
            return side, number

    return "", None


def _get_possession_abbr(
    situation,
    home_data,
    away_data,
):
    """
    ESPN normally provides situation.possession as a team/competitor ID.
    Match against both competitor.id and competitor.team.id because either
    representation can appear across ESPN feeds.
    """
    if not isinstance(situation, dict):
        return ""

    possession_id = str(
        situation.get("possession") or ""
    ).strip()

    if not possession_id:
        return ""

    for competitor in (home_data, away_data):
        if not competitor:
            continue

        team = competitor.get("team") or {}

        possible_ids = {
            str(competitor.get("id") or "").strip(),
            str(team.get("id") or "").strip(),
        }

        if possession_id in possible_ids:
            return get_team_abbr(team)

    return ""


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
    selected_groups = get_selected_conference_groups()
    rankings = fetch_rankings()

    events_by_id = {}
    week_number = 0

    for group_id in selected_groups:
        try:
            data = fetch_scoreboard_group(group_id)
        except Exception as error:
            print(
                "CFB conference fetch failed "
                f"for group {group_id}: {error}"
            )
            continue

        if not week_number:
            week_number = safe_int(
                (data.get("week") or {}).get("number"),
                0,
            )

        for event in data.get("events", []):
            event_id = str(
                event.get("id", "")
            ).strip()

            if not event_id:
                event_id = (
                    f"{event.get('date', '')}:"
                    f"{event.get('name', '')}"
                )

            events_by_id[event_id] = event

    games = []

    for event in events_by_id.values():
        competitions = event.get("competitions") or []

        if not competitions:
            continue

        competition = competitions[0]
        status_info = event.get("status") or {}
        status_type = status_info.get("type") or {}
        situation = competition.get("situation") or {}

        home_data, away_data = _get_home_away_competitors(
            competition
        )

        if not home_data or not away_data:
            continue

        home_team = home_data.get("team") or {}
        away_team = away_data.get("team") or {}

        home_record = get_record(home_data)
        away_record = get_record(away_data)

        home_rank = get_team_rank(
            home_team,
            rankings,
        )
        away_rank = get_team_rank(
            away_team,
            rankings,
        )

        possession_abbr = _get_possession_abbr(
            situation,
            home_data,
            away_data,
        )

        yardline_side, yardline_number = (
            _get_field_position(
                situation,
                home_team,
                away_team,
            )
        )

        raw_date_string = event.get("date", "")
        formatted_date = ""

        if raw_date_string:
            try:
                clean_date = raw_date_string.replace(
                    "Z",
                    "+00:00",
                )
                dt = datetime.fromisoformat(clean_date)
                local_dt = dt.astimezone(
                    get_local_timezone()
                )
                formatted_date = local_dt.strftime(
                    "%b %d"
                ).upper()
            except ValueError:
                formatted_date = raw_date_string

        games.append(
            CollegeFootballGame(
                away=get_team_abbr(away_team),
                home=get_team_abbr(home_team),

                away_rank=away_rank,
                home_rank=home_rank,

                # Keep ESPN's native STATUS_* value. The renderer
                # normalizes it in one place.
                status=str(
                    status_type.get("name", "")
                ),
                start_time=(
                    format_local_time(event["date"])
                    if event.get("date")
                    else ""
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
                    or ""
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

                date=formatted_date,
                week=week_number,
            )
        )

    return games
