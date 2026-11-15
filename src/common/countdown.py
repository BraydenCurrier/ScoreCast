"""Countdown above the standby clock for one chosen game."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from common.game_ids import game_id as shared_game_id
from common.settings import get_settings


def empty_countdown():
    return {
        "game_id": "",
        "away": "",
        "home": "",
        "start_at": "",
    }


def saved_countdown(settings):
    raw = settings.get("countdown") if isinstance(settings, dict) else None
    if not isinstance(raw, dict):
        raw = {}
    return {
        "game_id": str(raw.get("game_id") or "").strip(),
        "away": str(raw.get("away") or "").strip().upper(),
        "home": str(raw.get("home") or "").strip().upper(),
        "start_at": str(raw.get("start_at") or "").strip(),
    }


def parse_kickoff(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        kickoff = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    return kickoff.astimezone(timezone.utc)


def format_remaining(seconds):
    remaining = int(seconds)
    if remaining <= 0:
        return ""
    days, rest = divmod(remaining, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    clock = f"{hours}:{minutes:02d}:{secs:02d}"
    if days:
        return f"{days}D {clock}"
    return clock


# Statuses that still belong to a game that has not started.
_WAITING = {
    "",
    "SCHEDULED",
    "STATUS_SCHEDULED",
    "PREVIEW",
    "STATUS_PREVIEW",
    "DELAYED",
    "STATUS_DELAYED",
    "POSTPONED",
    "STATUS_POSTPONED",
}


def game_has_started(game):
    status = str(getattr(game, "status", "") or "").upper().replace(" ", "_")
    return status not in _WAITING


def can_countdown(game, now=None):
    if game is None or game_has_started(game):
        return False
    kickoff = parse_kickoff(getattr(game, "start_at", ""))
    if kickoff is None:
        return False
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return kickoff > moment.astimezone(timezone.utc)


def countdown_settings_for(game):
    if not can_countdown(game):
        return None
    return {
        "game_id": shared_game_id(game),
        "away": str(getattr(game, "away", "") or "").strip().upper(),
        "home": str(getattr(game, "home", "") or "").strip().upper(),
        "start_at": str(getattr(game, "start_at", "") or "").strip(),
    }


def countdown_button(game_id, active):
    value = "" if active else str(game_id or "")
    label = "On the clock" if active else "Countdown"
    safe_value = escape(value, quote=True)
    pressed = "true" if active else "false"
    return (
        '<button type="submit" form="clock-countdown" name="game" '
        f'value="{safe_value}" class="quiet-button countdown-button" '
        f'aria-pressed="{pressed}">{label}</button>'
    )


def countdown_line(games=None, now=None, settings=None):
    """Teams and remaining time for the line above the clock."""
    if settings is None:
        try:
            settings = get_settings()
        except Exception:
            return None
    saved = saved_countdown(settings)
    if not saved["game_id"] and not saved["start_at"]:
        return None
    away = saved["away"]
    home = saved["home"]
    start_at = saved["start_at"]
    wanted = saved["game_id"]
    for game in games or []:
        if shared_game_id(game) != wanted:
            continue
        if game_has_started(game):
            return None
        live_start = str(getattr(game, "start_at", "") or "").strip()
        if live_start:
            start_at = live_start
        away = str(getattr(game, "away", "") or away).strip().upper()
        home = str(getattr(game, "home", "") or home).strip().upper()
        break
    kickoff = parse_kickoff(start_at)
    if kickoff is None:
        return None
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    text = format_remaining(
        (kickoff - moment.astimezone(timezone.utc)).total_seconds()
    )
    if not text:
        return None
    teams = " ".join(part for part in (away, home) if part)
    return (teams, text)
