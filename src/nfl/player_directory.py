import json
import re
import threading
import time
from pathlib import Path

import requests

from common.settings import SETTINGS_DIR
from fantasy.api import (
    get_cached_league_data,
    get_user_leagues,
)


PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
HTTP_TIMEOUT = (3.05, 45)

CACHE_FILE = SETTINGS_DIR / "nfl_player_directory.json"
CACHE_TTL_SECONDS = 24 * 3600

ALLOWED_POSITIONS = ("QB", "RB", "WR", "TE", "K")
POSITION_RANK = {
    "QB": 0,
    "RB": 1,
    "WR": 2,
    "TE": 3,
    "K": 4,
}

TEAM_ALIASES = {
    "WAS": "WSH",
    "WSH": "WSH",
    "LA": "LAR",
}

MAX_WATCHED_PLAYERS = 24
SEARCH_LIMIT = 20

_lock = threading.Lock()
_directory = None
_directory_loaded_at = 0.0
_by_id = None

_session = requests.Session()
_session.headers.update({
    "User-Agent": "ScoreCast/1.0",
    "Accept": "application/json",
})


def normalize_team(abbreviation):
    team = str(abbreviation or "").strip().upper()

    if not team or team in {"FA", "NONE"}:
        return ""

    return TEAM_ALIASES.get(team, team)


def compact_player(raw, player_id=""):
    if not isinstance(raw, dict):
        return None

    position = str(raw.get("position") or "").upper()

    if position not in POSITION_RANK:
        return None

    player_id = str(
        raw.get("player_id")
        or player_id
        or ""
    ).strip()

    if not player_id:
        return None

    first = str(raw.get("first_name") or "").strip()
    last = str(raw.get("last_name") or "").strip()
    name = str(raw.get("full_name") or "").strip()

    if not name:
        name = " ".join(
            part
            for part in (first, last)
            if part
        ).strip()

    if not name:
        return None

    team = normalize_team(raw.get("team"))
    status = str(raw.get("status") or "").strip()
    espn_id = str(raw.get("espn_id") or "").strip()

    if not team and status.lower() not in {
        "active",
        "injured reserve",
        "pup",
        "suspension",
        "doubtful",
        "questionable",
        "out",
    }:
        return None

    search = " ".join(
        (
            name,
            first,
            last,
            team,
            position,
        )
    ).lower()

    return {
        "id": player_id,
        "name": name,
        "first": first,
        "last": last,
        "team": team,
        "position": position,
        "espn_id": espn_id,
        "search": search,
    }


def _write_cache(players):
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "updated_at": time.time(),
        "players": players,
    }

    temp_path = CACHE_FILE.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    temp_path.replace(CACHE_FILE)


def _read_cache():
    try:
        payload = json.loads(
            CACHE_FILE.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None, 0.0

    if not isinstance(payload, dict):
        return None, 0.0

    players = payload.get("players")
    updated_at = payload.get("updated_at", 0.0)

    if not isinstance(players, list):
        return None, 0.0

    try:
        updated_at = float(updated_at)
    except (TypeError, ValueError):
        updated_at = 0.0

    return players, updated_at


def _download_players():
    response = _session.get(
        PLAYERS_URL,
        timeout=HTTP_TIMEOUT,
        verify=CA_BUNDLE,
    )
    response.raise_for_status()
    raw = response.json() or {}

    if not isinstance(raw, dict):
        return []

    players = []

    for player_id, record in raw.items():
        compact = compact_player(record, player_id)

        if compact is not None:
            players.append(compact)

    players.sort(
        key=lambda player: (
            POSITION_RANK.get(player["position"], 9),
            player["last"].lower(),
            player["name"].lower(),
        )
    )

    return players


def _set_directory(players):
    global _directory
    global _directory_loaded_at
    global _by_id

    _directory = players
    _directory_loaded_at = time.monotonic()
    _by_id = {
        player["id"]: player
        for player in players
    }


def load_player_directory(force_refresh=False):
    global _directory

    with _lock:
        if (
            not force_refresh
            and _directory is not None
        ):
            return _directory

        cached, updated_at = _read_cache()
        cache_fresh = (
            cached is not None
            and time.time() - updated_at < CACHE_TTL_SECONDS
        )

        if cached is not None and (cache_fresh or not force_refresh):
            _set_directory(cached)

            if cache_fresh:
                return _directory

        try:
            players = _download_players()
        except Exception as exc:
            print(
                f"NFL player directory unavailable: {exc}",
                flush=True,
            )

            if _directory is not None:
                return _directory

            if cached is not None:
                _set_directory(cached)
                return _directory

            _set_directory([])
            return _directory

        try:
            _write_cache(players)
        except OSError as exc:
            print(
                f"NFL player directory cache not saved: {exc}",
                flush=True,
            )

        _set_directory(players)
        return _directory


def get_player(player_id):
    load_player_directory()

    if _by_id is None:
        return None

    return _by_id.get(str(player_id or "").strip())


def search_players(query, limit=SEARCH_LIMIT):
    query = re.sub(r"\s+", " ", str(query or "")).strip().lower()

    if len(query) < 2:
        return []

    players = load_player_directory()
    tokens = query.split()
    scored = []

    for player in players:
        haystack = player.get("search", "")

        if not all(token in haystack for token in tokens):
            continue

        name = player["name"].lower()
        last = player["last"].lower()
        score = 3

        if last.startswith(query) or name.startswith(query):
            score = 0
        elif last.startswith(tokens[0]):
            score = 1
        elif query in name:
            score = 2

        scored.append((score, player["name"].lower(), player))

    scored.sort(key=lambda item: (item[0], item[1]))

    return [
        {
            "id": player["id"],
            "name": player["name"],
            "team": player["team"],
            "position": player["position"],
            "espn_id": player["espn_id"],
            "first": player["first"],
            "last": player["last"],
        }
        for _, _, player in scored[: max(1, int(limit))]
    ]


def public_player(player):
    if not isinstance(player, dict):
        return None

    player_id = str(player.get("id") or "").strip()
    name = str(player.get("name") or "").strip()

    if not player_id or not name:
        return None

    return {
        "id": player_id,
        "name": name,
        "first": str(player.get("first") or "").strip(),
        "last": str(player.get("last") or "").strip(),
        "team": normalize_team(player.get("team")),
        "position": str(player.get("position") or "").upper(),
        "espn_id": str(player.get("espn_id") or "").strip(),
    }


def hydrate_watched_players(player_ids, previous=None):
    previous_by_id = {}

    for record in previous or []:
        public = public_player(record)

        if public is not None:
            previous_by_id[public["id"]] = public

    watched = []
    seen = set()

    for raw_id in player_ids:
        player_id = str(raw_id or "").strip()

        if not player_id or player_id in seen:
            continue

        seen.add(player_id)
        public = public_player(get_player(player_id))

        if public is None:
            public = previous_by_id.get(player_id)

        if public is None:
            continue

        watched.append(public)

        if len(watched) >= MAX_WATCHED_PLAYERS:
            break

    return watched


def watched_nfl_players(alerts_settings):
    players_by_league = (alerts_settings or {}).get("players", {})

    if not isinstance(players_by_league, dict):
        return []

    raw_players = players_by_league.get("nfl", [])

    if not isinstance(raw_players, list):
        return []

    watched = []
    seen = set()

    for record in raw_players:
        public = public_player(record)

        if public is None:
            continue

        if public["id"] in seen:
            continue

        seen.add(public["id"])
        watched.append(public)

        if len(watched) >= MAX_WATCHED_PLAYERS:
            break

    return watched


def get_fantasy_alert_rosters():
    from common.settings import get_settings

    settings = get_settings()
    fantasy = settings.get("fantasy", {})

    if not isinstance(fantasy, dict):
        return {
            "connected": False,
            "leagues": [],
        }

    user_id = str(fantasy.get("user_id") or "").strip()
    season = str(fantasy.get("season") or "2026").strip()
    selected = [
        str(league_id)
        for league_id in fantasy.get("selected_leagues", [])
        if str(league_id)
    ]

    if not user_id or not selected:
        return {
            "connected": bool(user_id),
            "leagues": [],
        }

    load_player_directory()

    try:
        leagues = get_user_leagues(user_id, season) or []
    except Exception as exc:
        print(f"Fantasy leagues unavailable: {exc}", flush=True)
        leagues = []

    league_names = {
        str(league.get("league_id")): str(
            league.get("name") or "League"
        )
        for league in leagues
        if isinstance(league, dict)
    }

    result = []

    for league_id in selected:
        rosters, users = get_cached_league_data(league_id)
        owners = {}

        for user in users or []:
            if not isinstance(user, dict):
                continue

            owner_id = str(user.get("user_id") or "")
            metadata = user.get("metadata") or {}
            name = (
                metadata.get("team_name")
                or user.get("display_name")
                or user.get("username")
                or "Team"
            )
            owners[owner_id] = str(name)

        teams = []

        for roster in rosters or []:
            if not isinstance(roster, dict):
                continue

            owner_id = str(roster.get("owner_id") or "")
            roster_id = roster.get("roster_id")
            player_ids = roster.get("players") or []

            if not isinstance(player_ids, list):
                player_ids = []

            players = []

            for player_id in player_ids:
                record = get_player(player_id)
                public = public_player(record)

                if public is None:
                    continue

                players.append(public)

            players.sort(
                key=lambda player: (
                    POSITION_RANK.get(player["position"], 9),
                    player["name"].lower(),
                )
            )

            teams.append({
                "roster_id": roster_id,
                "owner_id": owner_id,
                "mine": owner_id == user_id,
                "name": owners.get(owner_id) or f"Roster {roster_id}",
                "players": players,
            })

        teams.sort(
            key=lambda team: (
                0 if team["mine"] else 1,
                team["name"].lower(),
            )
        )

        result.append({
            "league_id": league_id,
            "name": league_names.get(league_id, "League"),
            "teams": teams,
        })

    return {
        "connected": True,
        "leagues": result,
    }
