"""How often each league is fetched.

Visible live games use the settings interval. A live game that is
hidden still updates every minute. Pregame waits 10 minutes, and a
league that is only finals (or has nothing today) waits 30.

A game still marked scheduled counts as live once its start time
arrives, so the board does not wait out the pregame interval.
"""

from datetime import datetime, timezone

from common.countdown import parse_kickoff
from common.game_ids import game_is_shown, sport_for_game


PREGAME_REFRESH_SECONDS = 10 * 60
HIDDEN_LIVE_REFRESH_SECONDS = 60
QUIET_REFRESH_SECONDS = 30 * 60


def as_utc(moment):
    if moment is None:
        moment = datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def live_refresh_seconds(settings):
    try:
        return max(5, int((settings or {}).get("refresh_interval", 30)))
    except (TypeError, ValueError):
        return 30


def status_phase(game):
    """live, pregame, or final from the feed status. Stocks use the session."""
    if sport_for_game(game) == "stocks":
        state = str(getattr(game, "market_state", "") or "").upper()
        return "live" if state == "LIVE" else "final"

    status = (
        str(getattr(game, "status", "") or "")
        .upper()
        .replace("_", " ")
        .replace("-", " ")
    )

    if any(
        word in status
        for word in (
            "FINAL",
            "COMPLETE",
            "POSTPONED",
            "CANCELED",
            "CANCELLED",
            "FORFEIT",
        )
    ):
        return "final"

    if (
        "SCHEDULE" in status
        or "PREVIEW" in status
        or status.strip() in {"PRE", "PREGAME"}
    ):
        return "pregame"

    return "live"


def game_phase(game, moment=None):
    """Feed status, except a scheduled game is live once it has started."""
    phase = status_phase(game)
    if phase != "pregame":
        return phase
    kickoff = parse_kickoff(getattr(game, "start_at", "") or "")
    if kickoff is not None and kickoff <= as_utc(moment):
        return "live"
    return "pregame"


def next_kickoff(games, moment):
    """Next start that should move a scheduled game onto the live cadence."""
    moment = as_utc(moment)
    upcoming = None
    for game in games:
        if status_phase(game) != "pregame":
            continue
        kickoff = parse_kickoff(getattr(game, "start_at", "") or "")
        if kickoff is None or kickoff <= moment:
            continue
        if upcoming is None or kickoff < upcoming:
            upcoming = kickoff
    return upcoming


def schedule_is_current(revision, mark, until, games_revision, settings_mark, moment):
    """False once a scheduled game's start time has arrived."""
    moment = as_utc(moment)
    return (
        revision == games_revision
        and mark == settings_mark
        and (until is None or moment < until)
    )


def sport_refresh_seconds(sport, games, settings, moment=None, sport_of=sport_for_game):
    """Shortest interval this league needs right now."""
    live_interval = live_refresh_seconds(settings)
    sport_games = [game for game in games if sport_of(game) == sport]

    if sport == "fantasy":
        fantasy = (settings or {}).get("fantasy") or {}
        if not fantasy.get("enabled"):
            return QUIET_REFRESH_SECONDS
        try:
            configured = int(fantasy.get("refresh_interval") or 120)
        except (TypeError, ValueError):
            configured = 120
        return max(60, configured)

    if sport == "stocks":
        shown = [
            game for game in sport_games
            if game_is_shown(game, settings)
        ]
        if not shown:
            return QUIET_REFRESH_SECONDS
        if any(game_phase(game, moment) == "live" for game in shown):
            return live_interval
        return PREGAME_REFRESH_SECONDS

    if not sport_games:
        return QUIET_REFRESH_SECONDS

    shown_live = False
    hidden_live = False
    any_pregame = False

    for game in sport_games:
        phase = game_phase(game, moment)
        if phase == "live":
            if game_is_shown(game, settings):
                shown_live = True
            else:
                hidden_live = True
        elif phase == "pregame":
            any_pregame = True

    if shown_live:
        return live_interval
    if hidden_live:
        return HIDDEN_LIVE_REFRESH_SECONDS
    if any_pregame:
        return PREGAME_REFRESH_SECONDS
    return QUIET_REFRESH_SECONDS


def due_sports(fetched_at, intervals, now):
    due = []
    for sport, interval in intervals.items():
        fetched = fetched_at.get(sport)
        if fetched is None or now - fetched >= interval:
            due.append(sport)
    return due
