from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from cfb.models import CollegeFootballGame 

from common.settings import get_settings

CFB_CONFERENCES = {
    "80": "All FBS",
    "8": "SEC",
    "5": "Big Ten",
    "1": "ACC",
    "4": "Big 12",
    "17": "Mountain West",
}

DEFAULT_CONFERENCE_GROUPS = ["80"]

NCAAF_SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
LOCAL_TIMEZONE = "America/Chicago"
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

HTTP_TIMEOUT = (3.05, 10)

_session = requests.Session()
_session.headers.update({
    "User-Agent": "P4SportsTicker/1.0",
    "Accept": "application/json",
})

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
    params = {
        "groups": str(group_id),
        "limit": 200,
    }

    response = _session.get(
        NCAAF_SCHEDULE_URL,
        params=params,
        timeout=HTTP_TIMEOUT,
        verify=CA_BUNDLE,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise ValueError(
            f"Unexpected CFB response for group {group_id}"
        )

    return data

def get_team_abbr(team):
    # Fetch the team's unique ESPN ID
    team_id = str(team.get("id", ""))
    
    # handle specific duoplicate team abbreviations, more to be added when discovered
    if team_id == "2579":
        return "USCG"  # South Carolina Gamecocks
    if team_id == "30":
        return "USC"   # Southern California Trojans

    # fallback to standard abbreviation if not one of the special cases
    raw_abbr = team.get("abbreviation", team.get("name", "")[:3].upper())
    
    # handle specific overrides for team abbreviations, more to be added as needed
    OVERRIDES = {
        "TA&M": "TAMU",
        "M-OH": "MOH",
        "AFA": "AF",
    }
    
    return OVERRIDES.get(raw_abbr, raw_abbr)


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
    selected_groups = get_selected_conference_groups()

    events_by_id = {}
    week_number = 0

    for group_id in selected_groups:
        try:
            data = fetch_scoreboard_group(group_id)
        except Exception as error:
            print(
                f"CFB conference fetch failed "
                f"for group {group_id}: {error}"
            )
            continue

        if not week_number:
            week_number = safe_int(
                (data.get("week") or {}).get("number"),
                0,
            )

        for event in data.get("events", []):
            event_id = str(event.get("id", "")).strip()

            if not event_id:
                # Emergency fallback when ESPN does not provide an ID.
                event_id = (
                    f"{event.get('date', '')}:"
                    f"{event.get('name', '')}"
                )

            events_by_id[event_id] = event

    games = []

    for event in events_by_id.values():
        competition = event["competitions"][0]
        status_info = event["status"]
        situation = competition.get("situation", {})

        home_data = competition["competitors"][0]
        away_data = competition["competitors"][1]

        home_team = home_data["team"]
        away_team = away_data["team"]

        home_record = get_record(home_data)
        away_record = get_record(away_data)

        # get rankings, default to 0 if not present
        home_rank_raw = home_data.get("curatedRankings", {}).get("current", 0)
        away_rank_raw = away_data.get("curatedRankings", {}).get("current", 0)
        
        # set to none if rank is 0 or not present
        home_rank = int(home_rank_raw) if home_rank_raw > 0 else None
        away_rank = int(away_rank_raw) if away_rank_raw > 0 else None

        # determine possession team abbreviation, default to empty string if not present
        possession_id = situation.get("possession")
        possession_abbr = ""
        if possession_id:
            for comp in [home_data, away_data]:
                if comp["id"] == str(possession_id):
                    possession_abbr = comp["team"].get("abbreviation", "")

        # extract yardline side details
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
            CollegeFootballGame(
                away=get_team_abbr(away_team),
                home=get_team_abbr(home_team),
                
                away_rank=away_rank,
                home_rank=home_rank,

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
                week=week_number,
            )
        )

    return games