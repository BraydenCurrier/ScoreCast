import re
from pathlib import Path

import requests

from common.settings import get_settings, update_settings
from fantasy.models import FantasyMatchup

BASE_URL = "https://api.sleeper.app/v1"
PROJECTIONS_URL = "https://api.sleeper.com/projections/nfl"
AVATAR_URL = "https://sleepercdn.com/avatars/thumbs"
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

HTTP_TIMEOUT = (3.05, 10)
AVATAR_CACHE = Path("/tmp/scorecast-fantasy-avatars")

_session = requests.Session()
_session.headers.update({
    "User-Agent": "ScoreCast/1.0",
    "Accept": "application/json",
})


def sleeper_get(path):
    response = _session.get(
        f"{BASE_URL}{path}",
        timeout=HTTP_TIMEOUT,
        verify=CA_BUNDLE,
    )
    response.raise_for_status()
    return response.json()


def get_user(username_or_id):
    if not username_or_id:
        return None
    return sleeper_get(f"/user/{username_or_id}")


def get_user_leagues(user_id, season):
    if not user_id:
        return []
    return sleeper_get(f"/user/{user_id}/leagues/nfl/{season}")


def get_nfl_state():
    return sleeper_get("/state/nfl")


def get_league_rosters(league_id):
    return sleeper_get(f"/league/{league_id}/rosters")


def get_league_users(league_id):
    return sleeper_get(f"/league/{league_id}/users")


def get_league_matchups(league_id, week):
    return sleeper_get(f"/league/{league_id}/matchups/{week}")


def get_weekly_projections(season, week):
    """Return Sleeper player projection records keyed by player_id.

    This endpoint is separate from the documented v1 league API, so any
    failure simply disables projected totals rather than breaking fantasy cards.
    """
    try:
        response = _session.get(
            f"{PROJECTIONS_URL}/{season}/{week}",
            params={"season_type": "regular"},
            timeout=HTTP_TIMEOUT,
            verify=CA_BUNDLE,
        )
        response.raise_for_status()

        records = response.json() or []

        return {
            str(record.get("player_id")): record
            for record in records
            if record.get("player_id") is not None
        }

    except Exception as exc:
        print(f"Fantasy projections unavailable: {exc}")
        return {}


def connect_sleeper_user(username):
    user = get_user(username)

    if not user:
        return None

    settings = get_settings()
    fantasy = settings.get("fantasy", {})

    fantasy["username"] = user.get("username", username)
    fantasy["user_id"] = user.get("user_id", "")
    fantasy["enabled"] = True

    update_settings({
        "fantasy": fantasy
    })

    return user


def get_current_week():
    """Return the correct fantasy matchup week.

    Sleeper's NFL state can report a preseason week such as Week 2 or Week 3.
    Fantasy matchups should remain on Week 1 until the NFL regular season
    begins.

    During the regular season, Sleeper's 'leg' value is preferred because it
    represents the active football week. 'week' is used as a fallback.
    """
    state = get_nfl_state() or {}

    season_type = str(
        state.get("season_type", "")
    ).lower()

    # Sleeper's raw NFL week during preseason should not advance fantasy
    # matchups beyond Week 1.
    if season_type == "pre":
        return 1

    value = state.get(
        "leg",
        state.get("week", 1)
    )

    try:
        return max(1, int(value))

    except (TypeError, ValueError):
        return 1


def get_owner_info_map(users):
    owners = {}

    for user in users:
        user_id = user.get("user_id")
        metadata = user.get("metadata") or {}

        name = (
            metadata.get("team_name")
            or user.get("display_name")
            or user.get("username")
            or "Team"
        )

        owners[user_id] = {
            "name": str(name),
            "avatar": user.get("avatar") or "",
        }

    return owners


def get_roster_owner_map(rosters):
    return {
        roster.get("roster_id"): roster.get("owner_id")
        for roster in rosters
    }


def team_abbreviation(name, roster_id=None):
    """Create a stable, readable 2-4 character fantasy team abbreviation."""

    text = re.sub(
        r"[^A-Za-z0-9 ]+",
        " ",
        str(name or "")
    ).strip().upper()

    words = [
        word
        for word in text.split()
        if word
    ]

    if len(words) >= 2:
        acronym = "".join(
            word[0]
            for word in words[:4]
        )

        if len(acronym) >= 2:
            return acronym[:4]

    compact = "".join(
        ch
        for ch in text
        if ch.isalnum()
    )

    if compact:
        return compact[:4]

    return f"T{roster_id or 0}"[:4]


def cache_avatar(avatar_id):
    if not avatar_id:
        return ""

    try:
        AVATAR_CACHE.mkdir(
            parents=True,
            exist_ok=True
        )

        path = AVATAR_CACHE / f"{avatar_id}.png"

        if not path.exists():
            response = _session.get(
                f"{AVATAR_URL}/{avatar_id}",
                timeout=HTTP_TIMEOUT,
                verify=CA_BUNDLE,
            )

            response.raise_for_status()
            path.write_bytes(response.content)

        return str(path)

    except Exception as exc:
        print(
            f"Fantasy avatar unavailable "
            f"({avatar_id}): {exc}"
        )

        return ""


def projected_team_points(
    team,
    projections,
    scoring_settings
):
    """Sum projected points for starters using the league's scoring rules."""

    total = 0.0
    found = False

    for player_id in team.get("starters") or []:
        record = projections.get(
            str(player_id)
        ) or {}

        stats = record.get("stats") or {}

        if not stats:
            continue

        player_total = 0.0
        player_found = False

        for stat_name, multiplier in (
            scoring_settings or {}
        ).items():

            try:
                stat_value = float(
                    stats.get(stat_name, 0) or 0
                )

                multiplier_value = float(
                    multiplier or 0
                )

            except (TypeError, ValueError):
                continue

            if stat_value:
                player_found = True

            player_total += (
                stat_value * multiplier_value
            )

        if player_found:
            found = True

        total += player_total

    return round(total, 2) if found else 0.0


def get_team_info(
    roster_id,
    roster_owner_map,
    owner_info_map
):
    owner_id = roster_owner_map.get(
        roster_id
    )

    info = owner_info_map.get(
        owner_id,
        {}
    )

    name = (
        info.get("name")
        or f"Roster {roster_id}"
    )

    return {
        "name": str(name),

        "abbrev": team_abbreviation(
            name,
            roster_id
        ),

        "logo": cache_avatar(
            info.get("avatar")
        ),
    }


def get_today_games():
    settings = get_settings()
    fantasy = settings.get(
        "fantasy",
        {}
    )

    if not fantasy.get(
        "enabled",
        False
    ):
        return []

    user_id = fantasy.get(
        "user_id",
        ""
    )

    season = fantasy.get(
        "season",
        "2026"
    )

    if not user_id:
        return []

    # Determine the fantasy matchup week.
    #
    # During preseason this deliberately returns Week 1 instead of Sleeper's
    # current preseason NFL week.
    week = get_current_week()

    leagues = get_user_leagues(
        user_id,
        season
    )

    selected_leagues = set(
        fantasy.get(
            "selected_leagues",
            []
        )
    )

    # Player projections only need to be downloaded once because all selected
    # leagues use the same NFL season/week player projections. Each league's
    # scoring_settings are applied later when calculating projected totals.
    projections = get_weekly_projections(
        season,
        week
    )

    games = []

    for league in leagues:
        league_id = league.get(
            "league_id"
        )

        league_name = league.get(
            "name",
            "Sleeper"
        )

        if (
            selected_leagues
            and league_id not in selected_leagues
        ):
            continue

        rosters = get_league_rosters(
            league_id
        )

        users = get_league_users(
            league_id
        )

        matchups = get_league_matchups(
            league_id,
            week
        )

        owner_info_map = get_owner_info_map(
            users
        )

        roster_owner_map = get_roster_owner_map(
            rosters
        )

        scoring_settings = (
            league.get("scoring_settings")
            or {}
        )

        by_matchup = {}

        for team in matchups:
            matchup_id = team.get(
                "matchup_id"
            )

            if matchup_id is not None:
                by_matchup.setdefault(
                    matchup_id,
                    []
                ).append(team)

        for matchup_id, teams in by_matchup.items():

            if len(teams) != 2:
                continue

            away_team, home_team = teams

            away_roster_id = away_team.get(
                "roster_id"
            )

            home_roster_id = home_team.get(
                "roster_id"
            )

            away_info = get_team_info(
                away_roster_id,
                roster_owner_map,
                owner_info_map
            )

            home_info = get_team_info(
                home_roster_id,
                roster_owner_map,
                owner_info_map
            )

            away_score = float(
                away_team.get(
                    "points",
                    0.0
                ) or 0.0
            )

            home_score = float(
                home_team.get(
                    "points",
                    0.0
                ) or 0.0
            )

            away_projected = projected_team_points(
                away_team,
                projections,
                scoring_settings
            )

            home_projected = projected_team_points(
                home_team,
                projections,
                scoring_settings
            )

            games.append(
                FantasyMatchup(
                    away=away_info["abbrev"],
                    home=home_info["abbrev"],

                    status="Live",
                    start_time="",
                    date=f"Wk {week}",

                    away_score=away_score,
                    home_score=home_score,

                    league_id=league_id,
                    league_name=league_name,

                    away_roster_id=away_roster_id,
                    home_roster_id=home_roster_id,

                    week=week,
                    matchup_id=matchup_id,

                    away_projected=away_projected,
                    home_projected=home_projected,

                    away_owner=away_info["name"],
                    home_owner=home_info["name"],

                    away_abbrev=away_info["abbrev"],
                    home_abbrev=home_info["abbrev"],

                    away_logo=away_info["logo"],
                    home_logo=home_info["logo"],
                )
            )

    return games