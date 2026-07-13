import requests

from common.settings import get_settings, update_settings
from fantasy.models import FantasyMatchup

BASE_URL = "https://api.sleeper.app/v1"
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

HTTP_TIMEOUT = (3.05, 10)

_session = requests.Session()
_session.headers.update({
    "User-Agent": "P4SportsTicker/1.0",
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


def connect_sleeper_user(username):
    user = get_user(username)

    if not user:
        return None

    settings = get_settings()
    fantasy = settings.get("fantasy", {})

    fantasy["username"] = user.get("username", username)
    fantasy["user_id"] = user.get("user_id", "")
    fantasy["enabled"] = True

    update_settings({"fantasy": fantasy})

    return user


def get_current_week():
    state = get_nfl_state()
    return int(state.get("week", 1))


def get_owner_name_map(users):
    owner_names = {}

    for user in users:
        user_id = user.get("user_id")
        display_name = (
            user.get("metadata", {}).get("team_name")
            or user.get("display_name")
            or user.get("username")
            or "Team"
        )

        owner_names[user_id] = display_name

    return owner_names


def get_roster_owner_map(rosters):
    roster_owners = {}

    for roster in rosters:
        roster_owners[roster.get("roster_id")] = roster.get("owner_id")

    return roster_owners


def get_matchup_team_name(roster_id, roster_owner_map, owner_name_map):
    owner_id = roster_owner_map.get(roster_id)
    name = owner_name_map.get(owner_id, f"Roster {roster_id}")

    # Keep ticker labels short
    return str(name).upper()[:8]


def get_today_games():
    settings = get_settings()
    fantasy = settings.get("fantasy", {})

    if not fantasy.get("enabled", False):
        return []

    user_id = fantasy.get("user_id", "")
    season = fantasy.get("season", "2026")

    if not user_id:
        return []

    week = get_current_week()
    leagues = get_user_leagues(user_id, season)

    selected_leagues = set(fantasy.get("selected_leagues", []))

    games = []

    for league in leagues:
        league_id = league.get("league_id")
        league_name = league.get("name", "Sleeper")

        if selected_leagues and league_id not in selected_leagues:
            continue

        rosters = get_league_rosters(league_id)
        users = get_league_users(league_id)
        matchups = get_league_matchups(league_id, week)

        owner_name_map = get_owner_name_map(users)
        roster_owner_map = get_roster_owner_map(rosters)

        by_matchup = {}

        for team in matchups:
            matchup_id = team.get("matchup_id")

            if matchup_id is None:
                continue

            by_matchup.setdefault(matchup_id, []).append(team)

        for matchup_id, teams in by_matchup.items():
            if len(teams) != 2:
                continue

            away_team = teams[0]
            home_team = teams[1]

            away_roster_id = away_team.get("roster_id")
            home_roster_id = home_team.get("roster_id")

            away_name = get_matchup_team_name(
                away_roster_id,
                roster_owner_map,
                owner_name_map,
            )

            home_name = get_matchup_team_name(
                home_roster_id,
                roster_owner_map,
                owner_name_map,
            )

            games.append(
                FantasyMatchup(
                    away=away_name,
                    home=home_name,
                    status="Live",
                    start_time="",
                    date=f"Wk {week}",

                    away_score=float(away_team.get("points", 0.0) or 0.0),
                    home_score=float(home_team.get("points", 0.0) or 0.0),

                    league_id=league_id,
                    league_name=league_name,

                    away_roster_id=away_roster_id,
                    home_roster_id=home_roster_id,

                    week=week,
                    matchup_id=matchup_id,

                    away_owner=away_name,
                    home_owner=home_name,
                )
            )

    return games