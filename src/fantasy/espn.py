import hashlib
import re
import time

import requests

from fantasy.api import (
    HTTP_TIMEOUT,
    _safe_error,
    ensure_avatar,
    prefetch_avatars,
    team_abbreviation,
)
from fantasy.models import FantasyMatchup


ESPN_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games"
ESPN_SPORTS = {
    "ffl": "Football",
    "fba": "Basketball",
    "flb": "Baseball",
    "fhl": "Hockey",
}
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
CACHE_SECONDS = 60

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
})
_cache = {}


class EspnError(Exception):
    pass


def parse_league_ids(text):
    ids = []
    seen = set()
    for part in re.split(r"[\s,]+", str(text or "").strip()):
        if not part:
            continue
        if not part.isdigit():
            raise EspnError(f"{part} is not an ESPN league ID.")
        if part not in seen:
            seen.add(part)
            ids.append(part)
    return ids


def failure_message(status_code, messages):
    text = " ".join(str(item) for item in (messages or [])).lower()
    if "not authorized" in text or "not visible" in text or status_code in {401, 403}:
        return (
            "That league is private. Paste SWID and espn_s2 "
            "from fantasy.espn.com while you are logged in."
        )
    if status_code == 404 or "not found" in text:
        return "ESPN could not find that league for this season."
    return "ESPN rejected that league."


# Bench, injured reserve, and extra reserve do not count toward the projection.
_BENCH_SLOTS = {
    "ffl": {20, 21, 24},
    "fba": {12, 13},
    "flb": {16, 17},
    "fhl": {7, 8},
}


def _number(value):
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _points(side):
    if not isinstance(side, dict):
        return 0.0
    for key in ("totalPointsLive", "totalPoints"):
        value = side.get(key)
        if value in (None, ""):
            continue
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            continue
    return 0.0


def _scoring_period(sport, status):
    """Football weeks match the matchup. Other sports project the current day."""
    status = status if isinstance(status, dict) else {}
    try:
        matchup = int(status.get("currentMatchupPeriod") or 0)
    except (TypeError, ValueError):
        matchup = 0
    try:
        latest = int(status.get("latestScoringPeriod") or 0)
    except (TypeError, ValueError):
        latest = 0
    if sport == "ffl":
        return matchup or latest
    return latest or matchup


def _projected(side, sport, scoring_period=0):
    """ESPN's live matchup projection, or the sum of starter projections."""
    if not isinstance(side, dict):
        return 0.0
    live = _number(side.get("totalProjectedPointsLive"))
    if live is not None and live >= 0:
        return live

    roster = (
        side.get("rosterForCurrentScoringPeriod")
        or side.get("rosterForMatchupPeriod")
        or {}
    )
    entries = roster.get("entries") if isinstance(roster, dict) else None
    if not entries:
        return 0.0

    bench = _BENCH_SLOTS.get(sport, set())
    total = 0.0
    found = False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("lineupSlotId") in bench:
            continue
        player = (entry.get("playerPoolEntry") or {}).get("player") or {}
        points = _player_projection(player.get("stats") or [], scoring_period)
        if points is None:
            continue
        total += points
        found = True
    if not found:
        return 0.0
    return round(total, 2)


def _player_projection(stats, scoring_period):
    fallback = None
    for stat in stats:
        if not isinstance(stat, dict):
            continue
        if stat.get("statSourceId") != 1 or stat.get("statSplitTypeId") != 1:
            continue
        period_id = stat.get("scoringPeriodId")
        if not period_id:
            continue
        points = _number(stat.get("appliedTotal"))
        if points is None:
            continue
        if scoring_period and int(period_id) == int(scoring_period):
            return points
        if fallback is None:
            fallback = points
    if scoring_period:
        return None
    return fallback


def _record(team):
    overall = ((team or {}).get("record") or {}).get("overall")
    if not isinstance(overall, dict):
        return -1, -1, 0
    try:
        return (
            int(overall.get("wins") or 0),
            int(overall.get("losses") or 0),
            int(overall.get("ties") or 0),
        )
    except (TypeError, ValueError):
        return -1, -1, 0


def _abbrev(team, team_id):
    abbrev = str((team or {}).get("abbrev") or "").strip()
    if abbrev:
        return abbrev.upper()[:4]
    return team_abbreviation((team or {}).get("name"), team_id)


def matchups_from_payload(payload, sport, league_id):
    payload = payload if isinstance(payload, dict) else {}
    teams = {
        team.get("id"): team
        for team in (payload.get("teams") or [])
        if isinstance(team, dict) and team.get("id") is not None
    }
    period = int((payload.get("status") or {}).get("currentMatchupPeriod") or 0)
    scoring_period = _scoring_period(sport, payload.get("status"))
    league_name = str((payload.get("settings") or {}).get("name") or "ESPN")
    prefetch_avatars(team.get("logo") for team in teams.values())
    games = []
    for item in payload.get("schedule") or []:
        if not isinstance(item, dict):
            continue
        if int(item.get("matchupPeriodId") or 0) != period:
            continue
        home = item.get("home") if isinstance(item.get("home"), dict) else {}
        away = item.get("away") if isinstance(item.get("away"), dict) else {}
        if not home.get("teamId") or not away.get("teamId"):
            continue
        home_team = teams.get(home.get("teamId")) or {}
        away_team = teams.get(away.get("teamId")) or {}
        away_wins, away_losses, away_ties = _record(away_team)
        home_wins, home_losses, home_ties = _record(home_team)
        matchup_id = int(item.get("id") or home.get("teamId") or 0)
        games.append(FantasyMatchup(
            away=_abbrev(away_team, away.get("teamId")),
            home=_abbrev(home_team, home.get("teamId")),
            status="Live",
            start_time="",
            date=f"Wk {period}" if period else "",
            away_score=_points(away),
            home_score=_points(home),
            away_projected=_projected(away, sport, scoring_period),
            home_projected=_projected(home, sport, scoring_period),
            league_id=f"espn-{sport}-{league_id}",
            league_name=league_name,
            away_roster_id=int(away.get("teamId") or 0),
            home_roster_id=int(home.get("teamId") or 0),
            week=period,
            matchup_id=matchup_id,
            away_owner=str(away_team.get("name") or ""),
            home_owner=str(home_team.get("name") or ""),
            away_abbrev=_abbrev(away_team, away.get("teamId")),
            home_abbrev=_abbrev(home_team, home.get("teamId")),
            away_logo=ensure_avatar(away_team.get("logo")),
            home_logo=ensure_avatar(home_team.get("logo")),
            away_wins=away_wins,
            away_losses=away_losses,
            away_ties=away_ties,
            home_wins=home_wins,
            home_losses=home_losses,
            home_ties=home_ties,
        ))
    return games


def _cookie_key(swid, s2):
    token = f"{swid}|{s2}".encode()
    return hashlib.sha256(token).hexdigest()[:12]


def fetch_league(sport, season, league_id, swid="", s2=""):
    sport = str(sport or "ffl").strip().lower()
    if sport not in ESPN_SPORTS:
        raise EspnError("Pick an ESPN sport.")
    league_id = str(league_id or "").strip()
    if not league_id.isdigit():
        raise EspnError(f"{league_id} is not an ESPN league ID.")
    season = str(season or "").strip()
    cache_key = (sport, season, league_id, _cookie_key(swid, s2))
    cached = _cache.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]

    cookies = {}
    if str(swid or "").strip() and str(s2 or "").strip():
        cookies["SWID"] = str(swid).strip()
        cookies["espn_s2"] = str(s2).strip()
    url = (
        f"{ESPN_BASE}/{sport}/seasons/{season}/segments/0/leagues/{league_id}"
    )
    status_payload = _read_league(url, [("view", "mSettings")], cookies)
    scoring_period = _scoring_period(sport, status_payload.get("status"))
    params = [
        ("view", "mTeam"),
        ("view", "mSettings"),
        ("view", "mScoreboard"),
        ("view", "mMatchupScore"),
    ]
    if scoring_period:
        params.append(("scoringPeriodId", scoring_period))
    payload = _read_league(url, params, cookies)

    _cache[cache_key] = (now, payload)
    return payload


def _read_league(url, params, cookies):
    try:
        response = _session.get(
            url,
            params=params,
            cookies=cookies,
            timeout=HTTP_TIMEOUT,
            verify=CA_BUNDLE,
        )
    except requests.RequestException as exc:
        raise EspnError(f"ESPN did not respond: {_safe_error(exc)}") from exc

    payload = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        payload = {}

    if response.status_code >= 400:
        raise EspnError(failure_message(
            response.status_code,
            payload.get("messages"),
        ))
    return payload


def league_name(payload, league_id):
    name = str((payload.get("settings") or {}).get("name") or "").strip()
    return name or f"League {league_id}"


def form_settings(form, previous, season):
    """Read the Fantasy page fields. Check ESPN when the league login changed."""
    previous = previous if isinstance(previous, dict) else {}
    sport = str(form.get("espn_sport") or "ffl").strip().lower()
    if sport not in ESPN_SPORTS:
        sport = "ffl"
    posted_ids = parse_league_ids(form.get("espn_leagues", ""))
    posted_swid = str(form.get("espn_swid") or "").strip()
    posted_secret = str(form.get("espn_s2") or "").strip()
    swid = posted_swid or str(previous.get("espn_swid") or "")
    secret = posted_secret or str(previous.get("espn_s2") or "")
    previous_ids = [
        str(league_id)
        for league_id in (previous.get("espn_leagues") or [])
    ]
    removed = str(form.get("remove_league") or "")
    removed_id = removed.split(":", 1)[1].strip() if removed.startswith("espn:") else ""
    league_ids = []
    for league_id in previous_ids + posted_ids:
        if not league_id or league_id == removed_id or league_id in league_ids:
            continue
        league_ids.append(league_id)
    fields = {
        "espn_sport": sport,
        "espn_leagues": league_ids,
        "espn_swid": swid,
        "espn_s2": secret,
    }
    changed = (
        league_ids != previous_ids
        or sport != str(previous.get("espn_sport") or "ffl")
        or bool(posted_swid)
        or bool(posted_secret)
        or form.get("check_espn") == "1"
    )
    if league_ids and changed:
        for league_id in league_ids:
            fetch_league(sport, season, league_id, swid, secret)
    return fields


def matchups_for_settings(fantasy):
    fantasy = fantasy if isinstance(fantasy, dict) else {}
    league_ids = [
        str(league_id).strip()
        for league_id in (fantasy.get("espn_leagues") or [])
        if str(league_id).strip()
    ]
    if not league_ids:
        return []
    sport = str(fantasy.get("espn_sport") or "ffl")
    season = str(fantasy.get("season") or "2026")
    swid = str(fantasy.get("espn_swid") or "")
    secret = str(fantasy.get("espn_s2") or "")
    games = []
    for league_id in league_ids:
        try:
            payload = fetch_league(sport, season, league_id, swid, secret)
            games.extend(matchups_from_payload(payload, sport, league_id))
        except EspnError as exc:
            print(f"ESPN league {league_id}: {exc}")
        except Exception as exc:
            print(f"ESPN league {league_id}: {_safe_error(exc)}")
    return games
