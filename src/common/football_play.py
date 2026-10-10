import json
import threading
import time

from common.http import get_body


def parse_last_play(last_play):
    last_play = last_play if isinstance(last_play, dict) else {}
    play_type = last_play.get("type") or {}

    if isinstance(play_type, dict):
        type_text = str(
            play_type.get("text")
            or play_type.get("abbreviation")
            or ""
        )
    else:
        type_text = str(play_type or "")

    team = last_play.get("team") or {}
    play_team = str(
        (team.get("abbreviation") if isinstance(team, dict) else "")
        or ""
    ).upper()

    if play_team == "WAS":
        play_team = "WSH"
    elif play_team == "LA":
        play_team = "LAR"

    yardage = last_play.get("statYardage")
    try:
        yardage = int(yardage)
    except (TypeError, ValueError):
        yardage = 0

    athletes = []
    involved = last_play.get("athletesInvolved")
    if isinstance(involved, list):
        athletes.extend(involved)

    nested_athletes = last_play.get("athletes")
    if isinstance(nested_athletes, list):
        athletes.extend(nested_athletes)

    participants = last_play.get("participants")
    if isinstance(participants, list):
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            athlete = participant.get("athlete")
            if isinstance(athlete, dict):
                athletes.append(athlete)

    ids = []
    names = []
    seen = set()

    for athlete in athletes:
        if not isinstance(athlete, dict):
            continue

        athlete_id = str(athlete.get("id") or "").strip()
        name = str(
            athlete.get("shortName")
            or athlete.get("displayName")
            or athlete.get("fullName")
            or ""
        ).strip()
        key = athlete_id or name.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        if athlete_id:
            ids.append(athlete_id)
        if name:
            names.append(name)

    score_value = last_play.get("scoreValue")
    try:
        score_value = int(score_value or 0)
    except (TypeError, ValueError):
        score_value = 0

    scoring = bool(last_play.get("scoringPlay", False)) or score_value > 0

    return {
        "last_play_type": type_text,
        "last_play_yardage": yardage,
        "last_play_team": play_team,
        "last_play_athlete_ids": tuple(ids),
        "last_play_athlete_names": tuple(names),
        "scoring_play": scoring,
    }


def short_down_text(situation):
    if not isinstance(situation, dict):
        return ""
    return str(situation.get("shortDownDistanceText") or "").strip()


def play_under_review(situation, last_play, status_type=None):
    parts = []
    if isinstance(situation, dict):
        if situation.get("isPlayUnderReview") in (True, "true", "True", 1, "1"):
            return True
        parts.extend(
            [
                situation.get("downDistanceText"),
                situation.get("shortDownDistanceText"),
            ]
        )
    if isinstance(last_play, dict):
        play_type = last_play.get("type") or {}
        if isinstance(play_type, dict):
            parts.append(play_type.get("text"))
        parts.append(last_play.get("text"))
    if isinstance(status_type, dict):
        parts.extend(
            [
                status_type.get("description"),
                status_type.get("detail"),
                status_type.get("name"),
            ]
        )

    blob = " ".join(str(part or "") for part in parts).lower()
    if "under review" in blob or "play review" in blob:
        return True
    if "reviewed" in blob:
        return False
    if "challenge" in blob and "review" in blob:
        return True
    return False


NFL_SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
)
CFB_SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "football/college-football/summary"
)
BOX_TIMEOUT = (2.05, 5)
BOX_TTL = 20.0
BOX_ERROR_TTL = 8.0

_box_lock = threading.Lock()
_box_cache = {}


def _empty_box_totals():
    return {
        "away_rush_yards": None,
        "away_pass_yards": None,
        "away_turnovers": None,
        "home_rush_yards": None,
        "home_pass_yards": None,
        "home_turnovers": None,
    }


def _int_box_stat(stats, name):
    for item in stats or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "") != name:
            continue
        raw = item.get("displayValue")
        if raw in (None, ""):
            raw = item.get("value")
        try:
            return int(float(str(raw).split("-")[0].split("/")[0]))
        except (TypeError, ValueError):
            return None
    return None


def _parse_box_totals(payload):
    totals = _empty_box_totals()
    teams = ((payload or {}).get("boxscore") or {}).get("teams") or []
    for entry in teams:
        if not isinstance(entry, dict):
            continue
        side = str(entry.get("homeAway") or "").strip().lower()
        if side not in {"home", "away"}:
            continue
        stats = entry.get("statistics") or []
        totals[f"{side}_rush_yards"] = _int_box_stat(stats, "rushingYards")
        totals[f"{side}_pass_yards"] = _int_box_stat(stats, "netPassingYards")
        totals[f"{side}_turnovers"] = _int_box_stat(stats, "turnovers")
    return totals


def _wants_box_totals(status_name):
    status = str(status_name or "").upper()
    return any(
        token in status
        for token in (
            "IN_PROGRESS",
            "HALFTIME",
            "HALF",
            "FINAL",
            "END_PERIOD",
            "END_OF",
        )
    )


def box_totals_for(league, event_id, status_name=""):
    empty = _empty_box_totals()
    event_id = str(event_id or "").strip()
    if not event_id or not _wants_box_totals(status_name):
        return empty

    now = time.monotonic()
    cache_key = f"{league}:{event_id}"
    cached = None
    with _box_lock:
        cached = _box_cache.get(cache_key)
        if cached and now < cached[0]:
            return dict(cached[1])

    url = NFL_SUMMARY_URL if league == "nfl" else CFB_SUMMARY_URL
    try:
        body = get_body(
            f"{url}?event={event_id}",
            BOX_TIMEOUT,
        )
        payload = json.loads(body)
        totals = _parse_box_totals(payload)
        ttl = BOX_TTL
    except Exception:
        totals = dict(cached[1]) if cached else empty
        ttl = BOX_ERROR_TTL

    with _box_lock:
        _box_cache[cache_key] = (now + ttl, dict(totals))
    return totals
