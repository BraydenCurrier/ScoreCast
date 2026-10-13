"""PGA Tour leaderboard from ESPN."""

from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common.espn_scoreboard import safe_int
from common.http import failure_text, get_body

from pga.models import GolfPlayer, GolfTournament


LEADERBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/"
    "sports/golf/leaderboard?league=pga"
)
SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/"
    "sports/golf/pga/scoreboard"
)
PGA_LOGO_URL = (
    "https://a.espncdn.com/combiner/i?"
    "img=/i/teamlogos/leagues/500/pgatour.png&w=64&h=64"
)
SCHEDULE_URL = "https://www.pgatour.com/schedule"
LOGO_URL_CACHE = Path("/tmp/scorecast-pga-logo-urls.json")
LOGO_URL_TTL_SECONDS = 6 * 60 * 60
CALENDAR_CACHE = Path("/tmp/scorecast-pga-calendar.json")
CALENDAR_TTL_SECONDS = 6 * 60 * 60

HTTP_TIMEOUT = (3.05, 10)
LEADER_COUNT = 24
DISPLAY_TZ = ZoneInfo("America/Chicago")

SKIP_STATUSES = {
    "STATUS_CUT",
    "STATUS_WD",
    "STATUS_WITHDRAWN",
    "STATUS_DQ",
    "STATUS_DISQUALIFIED",
    "STATUS_DNS",
    "STATUS_MDF",
}
FINISHED_STATUSES = {
    "STATUS_FINISH",
    "STATUS_COMPLETE",
    "STATUS_FINAL",
    "STATUS_OFFICIAL",
}
SKIP_POSITIONS = {"CUT", "WD", "DQ", "DNS", "MDF"}


def fetch_leaderboard(event_id: str = ""):
    url = LEADERBOARD_URL
    if event_id:
        url = f"{LEADERBOARD_URL}&event={event_id}"
    try:
        body = get_body(url, HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise RuntimeError(
            "PGA ESPN request failed: "
            f"{failure_text(exc)[:300]}"
        ) from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "PGA ESPN endpoint returned invalid JSON: "
            f"{body[:300]}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            "Unexpected PGA ESPN response type: "
            f"{type(data).__name__}"
        )

    return data


def get_today_games():
    data = fetch_leaderboard()
    events = [
        event
        for event in data.get("events") or []
        if isinstance(event, dict)
    ]
    event = _choose_event(events)
    if event is None:
        return []
    event = _event_for_this_week(event)

    tournament = tournament_from_event(event)
    if tournament is None:
        return []
    if not tournament.players and tournament.status != "Scheduled":
        return []
    return [
        GolfTournament(
            event_id=tournament.event_id,
            name=tournament.name,
            status=tournament.status,
            logo_url=resolve_tournament_logo(tournament.name),
            players=tournament.players,
            when=tournament.when,
        )
    ]


def tournament_from_event(event: dict) -> GolfTournament | None:
    competitions = event.get("competitions") or []
    competition = competitions[0] if competitions else {}
    if not isinstance(competition, dict):
        competition = {}

    players = []
    competitors = competition.get("competitors") or []
    ordered = [
        item for item in competitors if isinstance(item, dict)
    ]
    event_over = _event_is_over(event)
    today = datetime.now().astimezone(DISPLAY_TZ).date()
    if not event_over and _tournament_status(event) == "Scheduled":
        ordered.sort(key=lambda item: (_tee_sort_value(item), _sort_key(item)))
    else:
        ordered.sort(key=_sort_key)
    for competitor in ordered:
        player = player_from_competitor(
            competitor,
            today=today,
            event_over=event_over,
        )
        if player is None:
            continue
        if not player.position and not (player.awaiting_tee and not player.score):
            player = GolfPlayer(
                name=player.name,
                position=str(len(players) + 1),
                score=player.score,
                score_value=player.score_value,
                marker=player.marker,
                finished_round=player.finished_round,
                awaiting_tee=player.awaiting_tee,
            )
        players.append(player)
        if len(players) >= LEADER_COUNT:
            break

    name = str(
        event.get("shortName")
        or event.get("name")
        or "PGA"
    ).strip()
    event_id = str(event.get("id") or name)

    return GolfTournament(
        event_id=event_id,
        name=name,
        status=_tournament_status(event),
        logo_url="",
        players=tuple(players),
        when=_date_label(event),
    )


def player_from_competitor(
    competitor: dict,
    today: date | None = None,
    event_over: bool = False,
) -> GolfPlayer | None:
    status = competitor.get("status") or {}
    if not isinstance(status, dict):
        status = {}

    type_info = status.get("type") or {}
    if not isinstance(type_info, dict):
        type_info = {}

    type_name = str(type_info.get("name") or "").upper()
    position = status.get("position") or {}
    position_name = ""
    if isinstance(position, dict):
        position_name = str(position.get("displayName") or "").upper()

    if type_name in SKIP_STATUSES or position_name in SKIP_POSITIONS:
        return None

    athlete = competitor.get("athlete") or {}
    if not isinstance(athlete, dict):
        athlete = {}
    name = _leader_name(athlete)
    if not name:
        return None

    linescores = competitor.get("linescores") or []
    if not isinstance(linescores, list):
        linescores = []
    score, score_value = _to_par(competitor)
    today = today or datetime.now().astimezone(DISPLAY_TZ).date()
    if _awaiting_tee(status, type_name, type_info, linescores, today, event_over):
        return GolfPlayer(
            name=name,
            position=_position_label(position_name),
            score=score if _has_scored_round(linescores) else "",
            score_value=score_value if _has_scored_round(linescores) else 0,
            marker=_format_tee(_current_tee_time(status, linescores, today)),
            finished_round=False,
            awaiting_tee=True,
        )

    finished = _round_is_finished(status, type_name, type_info)
    if finished:
        marker = _round_strokes(linescores)
        if not marker:
            marker = "F"
    else:
        marker = _hole_label(status)

    return GolfPlayer(
        name=name,
        position=_position_label(position_name),
        score=score,
        score_value=score_value,
        marker=marker,
        finished_round=finished,
    )


def resolve_tournament_logo(name: str) -> str:
    """Return the tournament wordmark, or the PGA Tour mark if it is missing."""
    key = _normalize_name(name)
    cached = _cached_logo_url(key)
    if cached:
        return cached

    url = ""
    try:
        html = get_body(
            SCHEDULE_URL,
            HTTP_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html",
            },
        )
        url = logo_from_schedule(html, name)
    except (OSError, requests.RequestException, ValueError, TypeError):
        url = ""

    if not url:
        url = PGA_LOGO_URL
    _store_logo_url(key, url)
    return url


def logo_from_schedule(html: str, name: str) -> str:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
    )
    if not match:
        return ""
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return ""

    wanted = _normalize_name(name)
    found = []

    def walk(node):
        if isinstance(node, dict):
            tournament_name = node.get("tournamentName")
            logos = node.get("tournamentLogo")
            url = ""
            if isinstance(logos, list) and logos:
                url = str(logos[0] or "")
            if isinstance(tournament_name, str) and url.startswith("http"):
                found.append((_normalize_name(tournament_name), url))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    for tournament_name, url in found:
        if tournament_name == wanted:
            return url
    for tournament_name, url in found:
        if wanted and (wanted in tournament_name or tournament_name in wanted):
            return url
    return ""


def _normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold())
    return " ".join(text.split())


def _cached_logo_url(key: str) -> str:
    try:
        payload = json.loads(LOGO_URL_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return ""
    entry = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(entry, dict):
        return ""
    url = str(entry.get("url") or "")
    fetched_at = entry.get("at")
    if not url or not isinstance(fetched_at, (int, float)):
        return ""
    if time.time() - fetched_at > LOGO_URL_TTL_SECONDS:
        return ""
    return url


def _store_logo_url(key: str, url: str) -> None:
    try:
        payload = json.loads(LOGO_URL_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload[key] = {"url": url, "at": time.time()}
    try:
        LOGO_URL_CACHE.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def _event_for_this_week(event: dict) -> dict:
    """Keep a finished tournament through Sunday, then move to the next one.

    A round still being played stays on the board, including a Monday finish.
    """
    state = str(
        ((event.get("status") or {}).get("type") or {}).get("state") or ""
    )
    end = _event_day(event.get("endDate"))
    today = datetime.now().astimezone().date()
    next_id = next_event_id(
        _season_calendar(today),
        str(event.get("id") or ""),
        end,
        today,
        state,
    )
    if not next_id:
        return event
    try:
        data = fetch_leaderboard(next_id)
    except (OSError, requests.RequestException, ValueError, TypeError):
        return event
    events = [
        item
        for item in data.get("events") or []
        if isinstance(item, dict)
    ]
    for item in events:
        if str(item.get("id") or "") == next_id:
            return item
    return _choose_event(events) or event


def next_event_id(calendar, featured_id, featured_end, today, featured_state):
    """Return the next tournament id once the featured event's end date has passed."""
    if str(featured_state or "") == "in":
        return None
    if featured_end is None or today <= featured_end:
        return None
    featured_id = str(featured_id or "")
    upcoming = [
        item
        for item in calendar or []
        if item.get("start")
        and item["start"] > featured_end
        and str(item.get("id") or "") != featured_id
    ]
    upcoming.sort(key=lambda item: (item["start"], item.get("end") or item["start"], str(item.get("id"))))
    if not upcoming:
        return None
    return str(upcoming[0]["id"])


def _season_calendar(today: date):
    cached = _cached_calendar()
    if cached is not None:
        return cached
    try:
        body = get_body(
            f"{SCOREBOARD_URL}?dates={today:%Y%m%d}",
            HTTP_TIMEOUT,
        )
        payload = json.loads(body)
    except (OSError, requests.RequestException, json.JSONDecodeError, ValueError, TypeError):
        return []
    calendar = _calendar_events(payload)
    _store_calendar(calendar)
    return calendar


def _calendar_events(payload: dict):
    leagues = payload.get("leagues") or []
    league = leagues[0] if leagues and isinstance(leagues[0], dict) else {}
    events = []
    for item in league.get("calendar") or []:
        if not isinstance(item, dict):
            continue
        event_id = str(item.get("id") or "")
        start = _event_day(item.get("startDate"))
        end = _event_day(item.get("endDate")) or start
        if not event_id or start is None or end is None:
            continue
        events.append({
            "id": event_id,
            "name": str(item.get("label") or ""),
            "start": start,
            "end": end,
        })
    return events


def _event_day(value) -> date | None:
    text = str(value or "")
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _date_label(event: dict) -> str:
    start = _event_day(event.get("date"))
    end = _event_day(event.get("endDate")) or start
    if start is None:
        return ""
    if end is None or end == start:
        return f"{start.strftime('%b').upper()} {start.day}"
    if start.month == end.month:
        return f"{start.strftime('%b').upper()} {start.day}-{end.day}"
    return (
        f"{start.strftime('%b').upper()} {start.day}"
        f"-{end.strftime('%b').upper()} {end.day}"
    )


def _cached_calendar():
    try:
        payload = json.loads(CALENDAR_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    fetched_at = payload.get("at")
    events = payload.get("events")
    if not isinstance(fetched_at, (int, float)) or not isinstance(events, list):
        return None
    if time.time() - fetched_at > CALENDAR_TTL_SECONDS:
        return None
    calendar = []
    for item in events:
        if not isinstance(item, dict):
            continue
        start = _event_day(item.get("start"))
        end = _event_day(item.get("end")) or start
        event_id = str(item.get("id") or "")
        if not event_id or start is None or end is None:
            continue
        calendar.append({
            "id": event_id,
            "name": str(item.get("name") or ""),
            "start": start,
            "end": end,
        })
    return calendar


def _store_calendar(calendar) -> None:
    payload = {
        "at": time.time(),
        "events": [
            {
                "id": item["id"],
                "name": item.get("name") or "",
                "start": item["start"].isoformat(),
                "end": item["end"].isoformat(),
            }
            for item in calendar
        ],
    }
    try:
        CALENDAR_CACHE.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def _choose_event(events: list[dict]) -> dict | None:
    if not events:
        return None

    def rank(event):
        state = str(
            ((event.get("status") or {}).get("type") or {}).get("state")
            or ""
        )
        if state == "in":
            return 0
        if state == "pre":
            return 1
        return 2

    return min(events, key=rank)


def _tournament_status(event: dict) -> str:
    kind = (event.get("status") or {}).get("type") or {}
    if not isinstance(kind, dict):
        kind = {}
    state = str(kind.get("state") or "")
    name = str(kind.get("name") or "").upper()
    if state == "in" or "PROGRESS" in name:
        return "Live"
    if state == "pre" or "SCHEDULE" in name or name.endswith("_PRE"):
        return "Scheduled"
    return "Final"


def _event_is_over(event: dict) -> bool:
    kind = (event.get("status") or {}).get("type") or {}
    if not isinstance(kind, dict):
        return False
    name = str(kind.get("name") or "").upper()
    return bool(kind.get("completed")) and (
        "FINAL" in name or name in {"STATUS_COMPLETE", "STATUS_OFFICIAL"}
    )


def _awaiting_tee(status, type_name, type_info, linescores, today, event_over) -> bool:
    """True until the player has started the round scheduled for today."""
    if event_over:
        return False
    state = str(type_info.get("state") or "")
    if state == "in" or type_name == "STATUS_IN_PROGRESS":
        return False

    period = safe_int(status.get("period")) or 0
    scored_today = _period_has_strokes(linescores, period)
    played_on = _round_day(linescores, period, status)
    if scored_today and _round_is_finished(status, type_name, type_info):
        return played_on is not None and played_on < today
    if state == "pre" or "SCHEDULE" in type_name:
        return True
    scored = _scored_periods(linescores)
    if period and scored and period not in scored and max(scored) < period:
        return True
    if played_on is not None and played_on < today:
        return True
    return False


def _current_tee_time(status: dict, linescores, today: date) -> str:
    candidates = []
    tee_time = str(status.get("teeTime") or "").strip()
    if tee_time:
        candidates.append(tee_time)
    for item in linescores:
        if (
            isinstance(item, dict)
            and item.get("teeTime")
            and not _linescore_has_strokes(item)
        ):
            candidates.append(str(item.get("teeTime")))
    for option in candidates:
        played_on = _tee_day(option)
        if played_on is None or played_on >= today:
            return option
    return ""


def _tee_day(value) -> date | None:
    parsed = _parse_tee(value)
    if parsed is None:
        return None
    return parsed.astimezone(DISPLAY_TZ).date()


def _format_tee(value: str) -> str:
    parsed = _parse_tee(value)
    if parsed is None:
        return ""
    local = parsed.astimezone(DISPLAY_TZ)
    hour = local.hour % 12 or 12
    suffix = "A" if local.hour < 12 else "P"
    return f"{hour}:{local.minute:02d}{suffix}"


def _parse_tee(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _tee_sort_value(competitor: dict) -> datetime:
    status = competitor.get("status") or {}
    if not isinstance(status, dict):
        status = {}
    parsed = _parse_tee(status.get("teeTime"))
    if parsed is None:
        return datetime.max.replace(tzinfo=timezone.utc)
    return parsed


def _round_day(linescores, period: int, status: dict) -> date | None:
    for item in linescores:
        if not isinstance(item, dict):
            continue
        if period and safe_int(item.get("period")) not in {None, period}:
            continue
        if not _linescore_has_strokes(item):
            continue
        parsed = _parse_tee(item.get("teeTime"))
        if parsed is not None:
            return parsed.astimezone(DISPLAY_TZ).date()
    parsed = _parse_tee(status.get("teeTime"))
    if parsed is None:
        return None
    return parsed.astimezone(DISPLAY_TZ).date()


def _scored_periods(linescores) -> set[int]:
    periods = set()
    for item in linescores:
        if isinstance(item, dict) and _linescore_has_strokes(item):
            period = safe_int(item.get("period"))
            if period:
                periods.add(period)
    return periods


def _period_has_strokes(linescores, period: int) -> bool:
    if not period:
        return any(
            isinstance(item, dict) and _linescore_has_strokes(item)
            for item in linescores
        )
    return period in _scored_periods(linescores)


def _linescore_has_strokes(item: dict) -> bool:
    strokes = safe_int(item.get("value"))
    if strokes is not None and strokes > 0:
        return True
    text = str(item.get("displayValue") or "").strip()
    return bool(text) and text not in {"--", "0"}


def _has_scored_round(linescores) -> bool:
    return any(
        isinstance(item, dict) and _linescore_has_strokes(item)
        for item in linescores
    )


def _round_is_finished(status: dict, type_name: str, type_info: dict) -> bool:
    display_thru = str(status.get("displayThru") or "").strip().upper()
    thru = safe_int(status.get("thru"), 0) or 0
    if type_name in FINISHED_STATUSES or display_thru == "F":
        return True
    return bool(type_info.get("completed")) and thru >= 18


def _hole_label(status: dict) -> str:
    hole = safe_int(status.get("hole"))
    if hole is not None and 1 <= hole <= 18:
        state = str(
            ((status.get("type") or {}).get("state") or "")
        )
        display_thru = str(status.get("displayThru") or "").strip()
        if state == "in" or display_thru.isdigit():
            return str(hole)

    display_thru = str(status.get("displayThru") or "").strip()
    if display_thru.isdigit():
        return display_thru

    detail = str(status.get("displayValue") or "").strip()
    if detail and len(detail) <= 7:
        return detail.upper()
    return "--"


def _round_strokes(linescores) -> str:
    if not isinstance(linescores, list) or not linescores:
        return ""
    last = linescores[-1]
    if not isinstance(last, dict):
        return ""
    strokes = safe_int(last.get("value"))
    if strokes is None or strokes <= 0:
        text = str(last.get("displayValue") or "").strip()
        return text
    return str(strokes)


def _to_par(competitor: dict) -> tuple[str, int]:
    for stat in competitor.get("statistics") or []:
        if not isinstance(stat, dict):
            continue
        if str(stat.get("name") or "") != "scoreToPar":
            continue
        return _format_to_par(
            stat.get("displayValue"),
            safe_int(stat.get("value")),
        )

    score = competitor.get("score") or {}
    if not isinstance(score, dict):
        score = {}
    return _format_to_par(score.get("displayValue"), None)


def _format_to_par(display, value: int | None) -> tuple[str, int]:
    text = str(display or "").strip().upper()
    if text in {"E", "EVEN", "0", "+0", "-0"}:
        return "E", 0
    if value is None:
        value = _parse_signed(text)
    if value == 0 and text in {"", "E", "EVEN"}:
        return "E", 0
    if value is None:
        return text or "--", 0
    if value == 0:
        return "E", 0
    if text and text not in {"--"}:
        shown = text if text[0] in "+-" else (
            f"+{value}" if value > 0 else str(value)
        )
        return shown, value
    if value > 0:
        return f"+{value}", value
    return str(value), value


def _parse_signed(text: str) -> int | None:
    if not text or text in {"--", "E", "EVEN"}:
        return 0 if text in {"E", "EVEN"} else None
    return safe_int(text.replace("+", ""))


def _position_label(display: str) -> str:
    label = "".join(
        char for char in str(display or "").upper() if char.isalnum()
    )
    if not label or label in SKIP_POSITIONS:
        return ""
    return label[:3]


def _leader_name(athlete: dict) -> str:
    last = str(athlete.get("lastName") or "").strip()
    if not last:
        full = str(athlete.get("displayName") or "").strip()
        parts = full.split()
        last = parts[-1] if parts else ""
    decomposed = unicodedata.normalize("NFKD", last)
    letters = []
    for char in decomposed:
        if unicodedata.combining(char):
            continue
        if char.isalpha() or char == " ":
            letters.append(char)
    return " ".join("".join(letters).upper().split())


def _sort_key(competitor: dict):
    order = safe_int(competitor.get("sortOrder"))
    if order is None:
        order = 10000
    return order
