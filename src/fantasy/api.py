import hashlib
import io
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from PIL import Image

from common.settings import get_settings, update_settings
from fantasy.models import FantasyMatchup


BASE_URL = "https://api.sleeper.app/v1"
PROJECTIONS_URL = "https://api.sleeper.com/projections/nfl"
AVATAR_URL = "https://sleepercdn.com/avatars/thumbs"
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

HTTP_TIMEOUT = (3.05, 10)
AVATAR_TIMEOUT = (5, 12)
LOGO_STORE_SIZE = 64
# A 64px logo is a few kilobytes. Full player photos saved earlier are not.
SMALL_LOGO_BYTES = 48_000


def _safe_error(exc: Exception) -> str:
    """Drop account ids that requests puts in the exception text."""
    text = str(exc)
    text = re.sub(r"/user/\d+", "/user/…", text)
    text = re.sub(r"/\d{6,}", "/…", text)
    return text

AVATAR_CACHE = Path("/tmp/scorecast-fantasy-avatars")

NFL_STATE_CACHE_SECONDS = 300
USER_LEAGUES_CACHE_SECONDS = 3600
LEAGUE_DATA_CACHE_SECONDS = 3600
PROJECTION_CACHE_SECONDS = 900

_session = requests.Session()
_session.headers.update({
    "User-Agent": "GameLine/1.0",
    "Accept": "application/json",
})


_nfl_state_cache = None
_nfl_state_cache_time = 0.0

_user_leagues_cache = {}
_user_leagues_cache_time = {}

_league_roster_cache = {}
_league_user_cache = {}
_league_data_cache_time = {}

_projection_cache = {}
_projection_cache_time = {}


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

    return sleeper_get(
        f"/user/{user_id}/leagues/nfl/{season}"
    )


def get_nfl_state():
    return sleeper_get("/state/nfl")


def get_league_rosters(league_id):
    return sleeper_get(
        f"/league/{league_id}/rosters"
    )


def get_league_users(league_id):
    return sleeper_get(
        f"/league/{league_id}/users"
    )


def get_league_matchups(league_id, week):
    return sleeper_get(
        f"/league/{league_id}/matchups/{week}"
    )


def get_cached_nfl_state():
    global _nfl_state_cache
    global _nfl_state_cache_time

    now = time.monotonic()

    if (
        _nfl_state_cache is not None
        and now - _nfl_state_cache_time
        < NFL_STATE_CACHE_SECONDS
    ):
        return _nfl_state_cache

    try:
        state = get_nfl_state() or {}

        _nfl_state_cache = state
        _nfl_state_cache_time = now

        return state

    except Exception as exc:
        print(
            f"Fantasy NFL state unavailable: {_safe_error(exc)}"
        )

        return _nfl_state_cache or {}


def get_cached_user_leagues(
    user_id,
    season,
    force_refresh=False
):
    cache_key = (
        str(user_id),
        str(season),
    )

    now = time.monotonic()

    cached = _user_leagues_cache.get(
        cache_key
    )

    cached_at = (
        _user_leagues_cache_time.get(
            cache_key,
            0
        )
    )

    if (
        not force_refresh
        and cached is not None
        and now - cached_at
        < USER_LEAGUES_CACHE_SECONDS
    ):
        return cached

    try:
        leagues = get_user_leagues(
            user_id,
            season
        )

        _user_leagues_cache[
            cache_key
        ] = leagues

        _user_leagues_cache_time[
            cache_key
        ] = now

        return leagues

    except Exception as exc:
        print(
            f"Fantasy leagues unavailable: {_safe_error(exc)}"
        )

        return cached or []


def get_cached_league_data(
    league_id,
    force_refresh=False
):
    now = time.monotonic()

    rosters = _league_roster_cache.get(
        league_id
    )

    users = _league_user_cache.get(
        league_id
    )

    cached_at = (
        _league_data_cache_time.get(
            league_id,
            0
        )
    )

    if (
        not force_refresh
        and rosters is not None
        and users is not None
        and now - cached_at
        < LEAGUE_DATA_CACHE_SECONDS
    ):
        return rosters, users

    old_rosters = rosters or []
    old_users = users or []

    try:
        rosters = get_league_rosters(
            league_id
        )

        users = get_league_users(
            league_id
        )

        _league_roster_cache[
            league_id
        ] = rosters

        _league_user_cache[
            league_id
        ] = users

        _league_data_cache_time[
            league_id
        ] = now

        return rosters, users

    except Exception as exc:
        print(
            f"Fantasy league data unavailable "
            f"({league_id}): {_safe_error(exc)}"
        )

        return old_rosters, old_users


def get_weekly_projections(
    season,
    week,
    force_refresh=False
):
    cache_key = (
        str(season),
        int(week),
    )

    now = time.monotonic()

    cached = _projection_cache.get(
        cache_key
    )

    cached_at = (
        _projection_cache_time.get(
            cache_key,
            0
        )
    )

    if (
        not force_refresh
        and cached is not None
        and now - cached_at
        < PROJECTION_CACHE_SECONDS
    ):
        return cached

    try:
        response = _session.get(
            f"{PROJECTIONS_URL}/{season}/{week}",
            params={
                "season_type": "regular"
            },
            timeout=HTTP_TIMEOUT,
            verify=CA_BUNDLE,
        )

        response.raise_for_status()

        records = response.json() or []

        projections = {
            str(
                record.get(
                    "player_id"
                )
            ): record
            for record in records
            if record.get(
                "player_id"
            ) is not None
        }

        _projection_cache[
            cache_key
        ] = projections

        _projection_cache_time[
            cache_key
        ] = now

        return projections

    except Exception as exc:
        print(
            f"Fantasy projections unavailable: "
            f"{_safe_error(exc)}"
        )

        return cached or {}


def connect_sleeper_user(username):
    user = get_user(username)

    if not user:
        return None

    settings = get_settings()
    fantasy = settings.get(
        "fantasy",
        {}
    )

    fantasy["username"] = user.get(
        "username",
        username
    )

    fantasy["user_id"] = user.get(
        "user_id",
        ""
    )

    fantasy["enabled"] = True

    update_settings({
        "fantasy": fantasy
    })

    clear_fantasy_api_cache()

    return user


def get_current_week():
    state = get_cached_nfl_state() or {}

    season_type = str(
        state.get(
            "season_type",
            ""
        )
    ).lower()

    if season_type == "pre":
        return 1

    value = state.get(
        "leg",
        state.get(
            "week",
            1
        )
    )

    try:
        return max(
            1,
            int(value)
        )

    except (
        TypeError,
        ValueError
    ):
        return 1


def _user_avatar(user):
    """Team logo first, then the Sleeper profile picture."""
    metadata = user.get("metadata") if isinstance(user, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    for key in ("avatar", "team_avatar", "team_logo"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return str((user or {}).get("avatar") or "").strip()


def get_owner_info_map(users):
    owners = {}

    for user in users:
        user_id = user.get(
            "user_id"
        )

        metadata = (
            user.get("metadata")
            or {}
        )

        name = (
            metadata.get("team_name")
            or user.get("display_name")
            or user.get("username")
            or "Team"
        )

        owners[user_id] = {
            "name": str(name),
            "avatar": _user_avatar(user),
        }

    return owners


def get_roster_owner_map(rosters):
    return {
        roster.get("roster_id"):
            roster.get("owner_id")
        for roster in rosters
    }


def team_abbreviation(
    name,
    roster_id=None
):
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


_avatar_failures = {}
AVATAR_RETRY_SECONDS = 600


def _avatar_key(avatar_id):
    avatar_id = str(avatar_id or "").strip()
    if re.fullmatch(r"[A-Za-z0-9]+", avatar_id):
        return avatar_id
    if not avatar_id:
        return ""
    return hashlib.sha256(avatar_id.encode()).hexdigest()


def _avatar_urls(avatar_id):
    avatar_id = str(avatar_id or "").strip()
    if avatar_id.startswith(("http://", "https://")):
        return [avatar_id]
    return [
        f"{AVATAR_URL}/{avatar_id}",
        f"https://sleepercdn.com/avatars/{avatar_id}",
    ]


def get_cached_avatar(avatar_id):
    key = _avatar_key(avatar_id)
    if not key:
        return ""

    path = AVATAR_CACHE / f"{key}.png"
    if path.is_file():
        return str(path)

    return ""


def _load_svg_renderer():
    try:
        import cairosvg
        return cairosvg
    except ImportError:
        vendor = Path(__file__).resolve().parents[1] / "third_party"
        if str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
        import cairosvg
        return cairosvg


def _is_svg(content, content_type):
    if "svg" in str(content_type or "").lower():
        return True
    head = content[:400].lstrip().lower()
    return head.startswith(b"<svg") or head.startswith(b"<?xml") and b"<svg" in head


def _png_bytes(image):
    """Keep only enough pixels for the 30px board slot."""
    fitted = image.convert("RGBA")
    if fitted.width > LOGO_STORE_SIZE or fitted.height > LOGO_STORE_SIZE:
        fitted.thumbnail(
            (LOGO_STORE_SIZE, LOGO_STORE_SIZE),
            Image.Resampling.BOX,
        )
    output = io.BytesIO()
    fitted.save(output, format="PNG")
    return output.getvalue()


def _as_png(content, content_type):
    """Pillow cannot read ESPN's SVG logos, so those are drawn to PNG first."""
    if _is_svg(content, content_type):
        content = _load_svg_renderer().svg2png(
            bytestring=content,
            output_width=LOGO_STORE_SIZE,
            output_height=LOGO_STORE_SIZE,
        )

    with Image.open(io.BytesIO(content)) as image:
        image.load()
        return _png_bytes(image)


def _shrink_logo_file(path):
    """Rewrite a cached full-size photo so the next open is small."""
    try:
        if not path.is_file() or path.stat().st_size <= SMALL_LOGO_BYTES:
            return
        with Image.open(path) as image:
            image.load()
            png = _png_bytes(image)
        if len(png) >= path.stat().st_size:
            return
        temp_path = path.with_suffix(".shrink")
        temp_path.write_bytes(png)
        temp_path.replace(path)
    except Exception:
        return


def _espn_image_cookies():
    try:
        fantasy = get_settings().get("fantasy") or {}
    except Exception:
        return None
    swid = unquote(str(fantasy.get("espn_swid") or "").strip())
    secret = str(fantasy.get("espn_s2") or "").strip()
    if not swid or not secret:
        return None
    return {"SWID": swid, "espn_s2": secret}


def _image_request_kwargs(url):
    headers = {
        "Accept": "image/png,image/jpeg,image/webp,image/svg+xml,*/*",
    }
    cookies = None
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("fantasy.espn.com"):
        headers["Referer"] = "https://fantasy.espn.com/"
        cookies = _espn_image_cookies()
    return {"headers": headers, "cookies": cookies}


def _fetch_avatar(url):
    """One request, one connection.

    The shared API session is not safe to use from the logo threads, and a
    new board downloads every logo at once. A fresh request keeps that from
    failing the whole set.
    """
    image_kwargs = _image_request_kwargs(url)
    headers = {"User-Agent": "GameLine/1.0"}
    headers.update(image_kwargs["headers"])
    verify = CA_BUNDLE if Path(CA_BUNDLE).is_file() else True
    return requests.get(
        url,
        headers=headers,
        cookies=image_kwargs["cookies"],
        timeout=AVATAR_TIMEOUT,
        verify=verify,
    )


def download_avatar(avatar_id):
    key = _avatar_key(avatar_id)
    if not key:
        return ""

    path = AVATAR_CACHE / f"{key}.png"
    if path.is_file():
        _shrink_logo_file(path)
        return str(path)

    temp_path = AVATAR_CACHE / f"{key}.tmp"

    try:
        AVATAR_CACHE.mkdir(
            parents=True,
            exist_ok=True
        )

        png = None
        last_error = None
        for url in _avatar_urls(avatar_id):
            try:
                response = _fetch_avatar(url)
                response.raise_for_status()
                png = _as_png(
                    response.content,
                    response.headers.get("content-type"),
                )
                break
            except Exception as exc:
                host = urlparse(url).hostname or "avatar"
                last_error = RuntimeError(f"{host}: {_safe_error(exc)}")
                png = None
        if png is None:
            raise last_error or RuntimeError("avatar download failed")

        temp_path.write_bytes(png)
        temp_path.replace(path)
        return str(path)

    except Exception as exc:
        print(
            f"Fantasy avatar download failed "
            f"({_safe_error(exc)})"
        )

        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

        if path.is_file():
            return str(path)

        return ""


def ensure_avatar(avatar_id):
    """Return a cached logo, downloading it when the startup fetch missed."""
    cached = get_cached_avatar(avatar_id)
    if cached:
        return cached

    key = _avatar_key(avatar_id)
    if not key:
        return ""

    failed_at = _avatar_failures.get(key, 0)
    if failed_at and time.monotonic() - failed_at < AVATAR_RETRY_SECONDS:
        return ""

    path = download_avatar(avatar_id)
    if path:
        _avatar_failures.pop(key, None)
        return path

    _avatar_failures[key] = time.monotonic()
    return ""


def prefetch_avatars(avatar_ids):
    """Download missing logos together. A saved file is not fetched again."""
    pending = []
    seen = set()
    for avatar_id in avatar_ids:
        key = _avatar_key(avatar_id)
        if not key or key in seen:
            continue
        seen.add(key)
        path = AVATAR_CACHE / f"{key}.png"
        if path.is_file() and path.stat().st_size <= SMALL_LOGO_BYTES:
            continue
        failed_at = _avatar_failures.get(key, 0)
        if (
            not path.is_file()
            and failed_at
            and time.monotonic() - failed_at < AVATAR_RETRY_SECONDS
        ):
            continue
        pending.append(avatar_id)
    if not pending:
        return
    workers = min(4, len(pending))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(download_avatar, pending))


def refresh_league_avatars(
    league_id
):
    if not league_id:
        return

    try:
        _, users = get_cached_league_data(
            league_id,
            force_refresh=True
        )

    except Exception as exc:
        print(
            f"Unable to load fantasy avatars "
            f"for league {league_id}: {_safe_error(exc)}"
        )
        return

    downloaded = []
    seen = set()
    for user in users:
        avatar_id = _user_avatar(user)
        if not avatar_id or avatar_id in seen:
            continue
        seen.add(avatar_id)
        downloaded.append(avatar_id)
    prefetch_avatars(downloaded)

    print(
        f"Fantasy avatar cache refreshed "
        f"for league {league_id}: "
        f"{len(downloaded)} avatars"
    )


def refresh_fantasy_avatars_on_startup():
    settings = get_settings()

    fantasy = settings.get(
        "fantasy",
        {}
    )

    if not fantasy.get(
        "enabled",
        False
    ):
        return

    user_id = fantasy.get(
        "user_id",
        ""
    )

    season = fantasy.get(
        "season",
        "2026"
    )

    if not user_id:
        return

    leagues = get_cached_user_leagues(
        user_id,
        season,
        force_refresh=True
    )

    selected_leagues = set(
        str(league_id)
        for league_id in fantasy.get(
            "selected_leagues",
            []
        )
    )

    for league in leagues:
        league_id = str(
            league.get(
                "league_id",
                ""
            )
        )

        if not league_id:
            continue

        if (
            selected_leagues
            and league_id
            not in selected_leagues
        ):
            continue

        refresh_league_avatars(
            league_id
        )

def projected_team_points(
    team,
    projections,
    scoring_settings
):
    total = 0.0
    found = False

    scoring_settings = (
        scoring_settings
        or {}
    )

    try:
        reception_points = float(
            scoring_settings.get(
                "rec",
                0
            )
            or 0
        )

    except (
        TypeError,
        ValueError
    ):
        reception_points = 0.0

    # Sleeper provides three ready-made
    # fantasy point projections.
    #
    # Choose the one that most closely
    # matches the league's reception
    # scoring.
    if reception_points >= 0.75:
        projection_field = "pts_ppr"

    elif reception_points >= 0.25:
        projection_field = (
            "pts_half_ppr"
        )

    else:
        projection_field = "pts_std"

    for player_id in (
        team.get("starters")
        or []
    ):
        record = projections.get(
            str(player_id)
        ) or {}

        # Depending on the Sleeper
        # projection response format,
        # fantasy-point fields may be
        # directly on the record or
        # inside its stats dictionary.
        stats = (
            record.get("stats")
            or {}
        )

        projected_points = (
            record.get(
                projection_field
            )
        )

        if projected_points is None:
            projected_points = (
                stats.get(
                    projection_field
                )
            )

        if projected_points is None:
            continue

        try:
            projected_points = float(
                projected_points
            )

        except (
            TypeError,
            ValueError
        ):
            continue

        total += projected_points
        found = True

    if not found:
        return 0.0

    return round(
        total,
        2
    )

def get_team_info(
    roster_id,
    roster_owner_map,
    owner_info_map
):
    owner_id = (
        roster_owner_map.get(
            roster_id
        )
    )

    info = (
        owner_info_map.get(
            owner_id,
            {}
        )
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

        "logo": ensure_avatar(
            info.get("avatar")
        ),
    }


def clear_fantasy_api_cache():
    global _nfl_state_cache
    global _nfl_state_cache_time

    _nfl_state_cache = None
    _nfl_state_cache_time = 0.0

    _user_leagues_cache.clear()
    _user_leagues_cache_time.clear()

    _league_roster_cache.clear()
    _league_user_cache.clear()
    _league_data_cache_time.clear()

    _projection_cache.clear()
    _projection_cache_time.clear()


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
        return _with_espn_matchups([], fantasy)

    selected_leagues = set(
        str(league_id)
        for league_id in fantasy.get(
            "selected_leagues",
            []
        )
    )

    if not selected_leagues:
        return _with_espn_matchups([], fantasy)

    week = get_current_week()

    leagues = get_cached_user_leagues(
        user_id,
        season
    )

    selected = [
        league
        for league in leagues
        if str(
            league.get(
                "league_id",
                ""
            )
        ) in selected_leagues
    ]

    if not selected:
        return []

    projections = (
        get_weekly_projections(
            season,
            week
        )
    )

    games = []

    for league in selected:
        league_id = str(
            league.get(
                "league_id",
                ""
            )
        )

        if not league_id:
            continue

        league_name = league.get(
            "name",
            "Sleeper"
        )

        try:
            rosters, users = (
                get_cached_league_data(
                    league_id
                )
            )

            matchups = (
                get_league_matchups(
                    league_id,
                    week
                )
            )

        except Exception as exc:
            print(
                f"Fantasy matchup refresh "
                f"failed ({league_id}): "
                f"{_safe_error(exc)}"
            )
            continue

        owner_info_map = (
            get_owner_info_map(
                users
            )
        )
        prefetch_avatars(
            info.get("avatar")
            for info in owner_info_map.values()
            if isinstance(info, dict)
        )

        roster_owner_map = (
            get_roster_owner_map(
                rosters
            )
        )

        scoring_settings = (
            league.get(
                "scoring_settings"
            )
            or {}
        )

        by_matchup = {}

        for team in matchups:
            matchup_id = team.get(
                "matchup_id"
            )

            if matchup_id is None:
                continue

            by_matchup.setdefault(
                matchup_id,
                []
            ).append(team)

        for (
            matchup_id,
            teams
        ) in by_matchup.items():

            if len(teams) != 2:
                continue

            away_team = teams[0]
            home_team = teams[1]

            away_roster_id = (
                away_team.get(
                    "roster_id"
                )
            )

            home_roster_id = (
                home_team.get(
                    "roster_id"
                )
            )

            records = {
                roster.get("roster_id"): roster.get("settings") or {}
                for roster in rosters
                if isinstance(roster, dict)
            }
            away_settings = records.get(away_roster_id) or {}
            home_settings = records.get(home_roster_id) or {}

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
                )
                or 0.0
            )

            home_score = float(
                home_team.get(
                    "points",
                    0.0
                )
                or 0.0
            )

            away_projected = (
                projected_team_points(
                    away_team,
                    projections,
                    scoring_settings
                )
            )

            home_projected = (
                projected_team_points(
                    home_team,
                    projections,
                    scoring_settings
                )
            )

            games.append(
                FantasyMatchup(
                    away=away_info[
                        "abbrev"
                    ],

                    home=home_info[
                        "abbrev"
                    ],

                    status="Live",

                    start_time="",

                    date=f"Wk {week}",

                    away_score=away_score,
                    home_score=home_score,

                    league_id=league_id,
                    league_name=league_name,

                    away_roster_id=(
                        away_roster_id
                    ),

                    home_roster_id=(
                        home_roster_id
                    ),

                    week=week,

                    matchup_id=(
                        matchup_id
                    ),

                    away_projected=(
                        away_projected
                    ),

                    home_projected=(
                        home_projected
                    ),

                    away_owner=(
                        away_info[
                            "name"
                        ]
                    ),

                    home_owner=(
                        home_info[
                            "name"
                        ]
                    ),

                    away_abbrev=(
                        away_info[
                            "abbrev"
                        ]
                    ),

                    home_abbrev=(
                        home_info[
                            "abbrev"
                        ]
                    ),

                    away_logo=(
                        away_info[
                            "logo"
                        ]
                    ),

                    home_logo=(
                        home_info[
                            "logo"
                        ]
                    ),

                    away_wins=int(away_settings.get("wins") or 0),
                    away_losses=int(away_settings.get("losses") or 0),
                    away_ties=int(away_settings.get("ties") or 0),
                    home_wins=int(home_settings.get("wins") or 0),
                    home_losses=int(home_settings.get("losses") or 0),
                    home_ties=int(home_settings.get("ties") or 0),
                )
            )

    return _with_espn_matchups(games, fantasy)


def _with_espn_matchups(games, fantasy):
    try:
        from fantasy.espn import matchups_for_settings
        games.extend(matchups_for_settings(fantasy))
    except Exception as exc:
        print(f"ESPN fantasy refresh failed: {_safe_error(exc)}")
    return games