"""Decide which cards a mode puts on the board.

A mode lists the sports it controls. While its window is open, those
sports come from the mode instead of the Scores checkboxes. Everything
else stays as the user set it. An overlay mode also takes its sports
off the board outside the window, which is how market hours removes
stocks after the close. A night-game rule can pin one live game.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from common.game_ids import game_id, is_stock_id, sport_for_game
from common.timezone import get_local_timezone


EASTERN = ZoneInfo("America/New_York")
MAX_CUSTOM_MODES = 12

SPORT_CHOICES = (
    ("nfl", "NFL"),
    ("cfb", "College football"),
    ("nba", "NBA"),
    ("nhl", "NHL"),
    ("mlb", "MLB"),
    ("soccer", "Soccer"),
    ("pga", "Golf"),
    ("stocks", "Stocks"),
    ("fantasy", "Fantasy"),
    ("players", "Player cards"),
    ("bets", "Bet slips"),
)
SPORT_IDS = {key for key, _label in SPORT_CHOICES}
SPORT_LABELS = dict(SPORT_CHOICES)
TEAM_SPORTS = {"nfl", "cfb", "nba", "nhl", "mlb", "soccer"}
FOCUS_SPORTS = {"nfl", "cfb", "nba", "mlb"}
PHASES = ("pregame", "live", "final")
LEADING_SPORTS = {"players", "bets"}

# Weekday closings. The board does not try to track early closes.
MARKET_HOLIDAYS = {
    # 2026
    (2026, 1, 1),
    (2026, 1, 19),
    (2026, 2, 16),
    (2026, 4, 3),
    (2026, 5, 25),
    (2026, 6, 19),
    (2026, 7, 3),
    (2026, 9, 7),
    (2026, 11, 26),
    (2026, 12, 25),
    # 2027
    (2027, 1, 1),
    (2027, 1, 18),
    (2027, 2, 15),
    (2027, 3, 26),
    (2027, 5, 31),
    (2027, 6, 18),
    (2027, 7, 5),
    (2027, 9, 6),
    (2027, 11, 25),
    (2027, 12, 24),
}

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _mode(
    mode_id,
    name,
    summary,
    *,
    kind="filter",
    days=(),
    start="",
    end="",
    clock="local",
    window_zone="",
    slate_zone="",
    sports=(),
    phases=("pregame", "live"),
    live_only_after="",
    focus_after="",
    favorites_only=False,
    cfb_top25=False,
):
    return {
        "id": mode_id,
        "name": name,
        "summary": summary,
        "builtin": True,
        "kind": kind,
        "days": list(days),
        "start": start,
        "end": end,
        "clock": clock,
        "window_zone": window_zone,
        "slate_zone": slate_zone,
        "sports": list(sports),
        "phases": list(phases),
        "live_only_after": live_only_after,
        "focus_after": focus_after,
        "favorites_only": bool(favorites_only),
        "cfb_top25": bool(cfb_top25),
    }


PRESETS = (
    _mode(
        "nfl-sunday",
        "NFL Sunday",
        "Sunday games follow the slate. Early kickoffs stay up "
        "from the preview until the final. Later games appear "
        "when they start and leave when they end. The night "
        "game fills the screen once it is live.",
        days=(6,),
        start="09:00",
        end="23:59",
        window_zone="America/New_York",
        slate_zone="America/New_York",
        sports=("nfl",),
        phases=("pregame", "live"),
        live_only_after="16:00",
        focus_after="19:00",
    ),
    _mode(
        "nfl-primetime",
        "NFL Prime Time",
        "Monday, Thursday, and Sunday night. Only a live NFL "
        "game is added, and it fills the screen.",
        days=(0, 3, 6),
        start="18:00",
        end="23:59",
        window_zone="America/New_York",
        slate_zone="America/New_York",
        sports=("nfl",),
        phases=("live",),
        focus_after="18:00",
    ),
    _mode(
        "cfb-saturday",
        "College Saturday",
        "Saturday games with a Top 25 team. Early kickoffs "
        "stay from the preview through the final. Later games "
        "appear when they start. Finished games come off.",
        days=(5,),
        start="10:00",
        end="23:59",
        sports=("cfb",),
        phases=("pregame", "live"),
        live_only_after="16:00",
        cfb_top25=True,
    ),
    _mode(
        "nba-tonight",
        "NBA Tonight",
        "From late afternoon, NBA games stay up until they "
        "end, then come off the board.",
        days=(0, 1, 2, 3, 4, 5, 6),
        start="17:00",
        end="23:59",
        sports=("nba",),
        phases=("pregame", "live"),
    ),
    _mode(
        "live-only",
        "Live Only",
        "The board keeps only games that are in progress "
        "across the major leagues. Previews and finals stay off.",
        days=(0, 1, 2, 3, 4, 5, 6),
        sports=("nfl", "cfb", "nba", "nhl", "mlb", "soccer"),
        phases=("live",),
    ),
    _mode(
        "market-hours",
        "Market Hours",
        "Stock quotes go on while the New York market is open "
        "and come off when it closes, including weekends and "
        "market holidays.",
        kind="overlay",
        clock="market",
        sports=("stocks",),
        phases=("pregame", "live", "final"),
    ),
)

PRESET_BY_ID = {mode["id"]: mode for mode in PRESETS}


def mode_settings(settings):
    block = (settings or {}).get("modes") or {}
    if not isinstance(block, dict):
        block = {}
    enabled = []
    for raw in block.get("enabled") or []:
        mode_id = str(raw or "").strip()
        if mode_id and mode_id not in enabled:
            enabled.append(mode_id)
    custom = []
    for raw in block.get("custom") or []:
        cleaned = _clean_custom(raw)
        if cleaned is not None:
            custom.append(cleaned)
    held = []
    for raw in block.get("held") or []:
        text = str(raw or "").strip()
        if text and text not in held:
            held.append(text)
    return {
        "enabled": enabled[:24],
        "custom": custom[:MAX_CUSTOM_MODES],
        "held": held,
    }


def all_modes(settings):
    stored = mode_settings(settings)
    custom_ids = {mode["id"] for mode in stored["custom"]}
    modes = [dict(mode) for mode in PRESETS if mode["id"] not in custom_ids]
    modes.extend(stored["custom"])
    enabled = set(stored["enabled"])
    for mode in modes:
        mode["enabled"] = mode["id"] in enabled
    return modes


def enabled_modes(settings):
    return [mode for mode in all_modes(settings) if mode["enabled"]]


def mode_token(settings, now=None):
    """Changes when a mode window opens or closes, not every minute."""
    instant = _instant(now)
    stored = mode_settings(settings)
    windows = tuple(
        (mode["id"], int(_window_open(mode, instant)))
        for mode in enabled_modes(settings)
    )
    payload = json.dumps(stored, sort_keys=True, default=str)
    return f"{payload}|{windows}|{int(market_is_open(instant))}"


def market_is_open(instant):
    eastern = _instant(instant).astimezone(EASTERN)
    if eastern.weekday() >= 5:
        return False
    if (eastern.year, eastern.month, eastern.day) in MARKET_HOLIDAYS:
        return False
    minutes = eastern.hour * 60 + eastern.minute
    return (9 * 60 + 30) <= minutes < (16 * 60)


def apply_mode_selection(games, settings, now=None):
    """Check and uncheck the Scores list for the modes that are on.

    Returns a settings patch, or None when the list is already right.
    Games the user checked stay checked. A mode only adds and removes
    the games it is responsible for. Those stay checked until the mode
    is turned off or its window closes, and then only the mode's games
    come off.
    """
    instant = _instant(now)
    stored = mode_settings(settings)
    held = _held_map(stored.get("held") or [])
    controlled, hiding = _active_sports(settings, instant)
    active = set(controlled) | set(hiding)
    by_sport = {}

    for game in games or []:
        by_sport.setdefault(sport_for_game(game), []).append(game)

    if not active and not held:
        return None

    selected = _id_list((settings or {}).get("selected_games"))
    hidden = _id_list((settings or {}).get("hidden_games"))
    order = _id_list((settings or {}).get("game_order"))
    selected_set = {item for item in selected if not is_stock_id(item)}
    hidden_set = set(hidden)

    for sport in list(held):
        if sport in active:
            continue
        _restore_sport(
            sport,
            held.pop(sport),
            by_sport.get(sport, []),
            selected_set,
            hidden_set,
        )

    for sport, owners in controlled.items():
        _take_sport(
            sport,
            owners,
            by_sport.get(sport, []),
            held,
            selected,
            selected_set,
            hidden_set,
            instant,
            settings,
            show=True,
        )

    for sport in hiding:
        _take_sport(
            sport,
            [],
            by_sport.get(sport, []),
            held,
            selected,
            selected_set,
            hidden_set,
            instant,
            settings,
            show=False,
        )

    new_selected = [item for item in selected if item in selected_set]
    for item in selected_set:
        if item not in new_selected:
            new_selected.append(item)

    new_hidden = [item for item in hidden if item in hidden_set]
    for item in hidden_set:
        if item not in new_hidden:
            new_hidden.append(item)

    seen = set()
    new_order = []
    for item in order + new_selected + new_hidden:
        if item and item not in seen:
            seen.add(item)
            new_order.append(item)

    new_held = _held_list(held)
    if (
        new_selected == [item for item in selected if not is_stock_id(item)]
        and new_hidden == hidden
        and new_held == list(stored.get("held") or [])
        and new_order == order
    ):
        return None

    return {
        "selected_games": new_selected,
        "hidden_games": new_hidden,
        "game_order": new_order,
        "modes": _modes_block(stored, held=new_held),
    }


def mode_locked_ids(games, settings, now=None):
    """Ids a mode currently has checked. These cannot be cleared."""
    instant = _instant(now)
    controlled, _hiding = _active_sports(settings, instant)
    locked = []
    seen = set()

    for sport, owners in controlled.items():
        if sport == "stocks":
            continue
        for game in games or []:
            if sport_for_game(game) != sport:
                continue
            if not any(
                _allows(mode, game, instant, settings)
                for mode in owners
            ):
                continue
            identifier = game_id(game)
            if identifier in seen:
                continue
            seen.add(identifier)
            locked.append(identifier)

    return locked


def focus_games_for_board(visible_games, settings, now=None):
    """Focus from the games already selected for the scroll."""
    instant = _instant(now)
    chosen = []
    seen = set()

    for mode in enabled_modes(settings):
        if not _window_open(mode, instant):
            continue
        for game in _focus_picks(mode, visible_games, instant, settings):
            identifier = game_id(game)
            if identifier in seen:
                continue
            seen.add(identifier)
            chosen.append(game)

    if chosen:
        return chosen

    open_modes = [
        mode for mode in enabled_modes(settings)
        if _window_open(mode, instant)
    ]
    if not open_modes:
        return []

    games = [
        game for game in visible_games or []
        if sport_for_game(game) in TEAM_SPORTS
    ]
    if len(games) != 1 or sport_for_game(games[0]) not in FOCUS_SPORTS:
        return []

    sport = sport_for_game(games[0])
    if any(sport in set(mode.get("sports") or []) for mode in open_modes):
        return games
    return []


def mode_focus_games(
    all_games,
    settings,
    now=None,
    manual_games=None,
    leading=None,
):
    instant = _instant(now)
    chosen = []
    seen = set()

    for mode in enabled_modes(settings):
        if not _window_open(mode, instant):
            continue
        for game in _focus_picks(mode, all_games, instant, settings):
            identifier = game_id(game)
            if identifier in seen:
                continue
            seen.add(identifier)
            chosen.append(game)

    if chosen:
        return chosen

    return _single_game_focus(
        all_games,
        manual_games,
        leading,
        settings,
        instant,
    )


def mode_ticker(all_games, manual_games, leading, settings, now=None):
    """The ticker list while modes are changing it.

    None means no enabled mode is changing the board right now.
    """
    instant = _instant(now)
    modes = enabled_modes(settings)
    if not modes:
        return None

    controlled = {}
    hiding = set()

    for mode in modes:
        sports = [sport for sport in mode["sports"] if sport in SPORT_IDS]
        if _window_open(mode, instant):
            for sport in sports:
                controlled.setdefault(sport, []).append(mode)
        elif mode["kind"] == "overlay":
            hiding.update(sports)

    hiding -= set(controlled)
    if not controlled and not hiding:
        return None

    kept = []
    seen = set()

    for game in list(leading or []) + list(manual_games or []):
        sport = sport_for_game(game)
        if sport in controlled or sport in hiding:
            continue
        identifier = game_id(game)
        if identifier in seen:
            continue
        seen.add(identifier)
        kept.append(game)

    front = []
    back = []

    for sport, owners in controlled.items():
        source = leading if sport in LEADING_SPORTS else all_games
        for game in source or []:
            if sport_for_game(game) != sport:
                continue
            if not any(_allows(mode, game, instant, settings) for mode in owners):
                continue
            identifier = game_id(game)
            if identifier in seen:
                continue
            seen.add(identifier)
            if sport in LEADING_SPORTS:
                front.append(game)
            else:
                back.append(game)

    return front + kept + back


def describe_mode(mode):
    if mode.get("clock") == "market":
        return (
            "Weekdays, 9:30 AM to 4:00 PM Eastern. "
            "Stocks are added while the market is open and "
            "removed when it is closed."
        )

    parts = [_when_text(mode)]
    sports = [
        SPORT_LABELS.get(sport, sport)
        for sport in mode.get("sports") or []
    ]
    if sports:
        parts.append(", ".join(sports) + ".")
    parts.append(_phase_text(mode))
    if mode.get("live_only_after"):
        parts.append(
            "Kickoffs at "
            f"{_clock_text(mode['live_only_after'])} or later "
            "wait until the game starts."
        )
    if mode.get("focus_after"):
        parts.append(
            "A live game that starts at "
            f"{_clock_text(mode['focus_after'])} or later "
            "fills the screen."
        )
    if mode.get("favorites_only"):
        parts.append("Only favorite teams.")
    if mode.get("cfb_top25"):
        parts.append("College football is limited to Top 25 games.")
    if mode.get("kind") == "overlay":
        parts.append("Outside these hours, those items come off the board.")
    return " ".join(part for part in parts if part)


def status_line(mode, settings, now=None):
    if not mode.get("enabled"):
        return "Off"

    instant = _instant(now)
    if mode.get("clock") == "market":
        if market_is_open(instant):
            return "On now. Stocks are on the board."
        return "On. The market is closed, so stocks stay off."

    if _window_open(mode, instant):
        if mode.get("focus_after"):
            return "On now. A late live game would fill the screen."
        return "On now."

    return "Waiting for its next window."


def save_custom_mode(settings, fields, mode_id=""):
    """Return an updated modes block, or raise ValueError."""
    stored = mode_settings(settings)
    mode = _mode_from_fields(fields, mode_id)
    custom = [
        existing for existing in stored["custom"]
        if existing["id"] != mode["id"]
    ]
    if len(custom) >= MAX_CUSTOM_MODES and mode["id"] not in {
        existing["id"] for existing in stored["custom"]
    }:
        raise ValueError(f"You can save up to {MAX_CUSTOM_MODES} modes.")
    custom.append(mode)
    return _modes_block(stored, custom=custom)


def delete_custom_mode(settings, mode_id):
    stored = mode_settings(settings)
    mode_id = str(mode_id or "").strip()
    return _modes_block(
        stored,
        enabled=[
            item for item in stored["enabled"]
            if item != mode_id
        ],
        custom=[
            mode for mode in stored["custom"]
            if mode["id"] != mode_id
        ],
    )


def set_mode_enabled(settings, mode_id, enabled):
    stored = mode_settings(settings)
    mode_id = str(mode_id or "").strip()
    known = {mode["id"] for mode in PRESETS}
    known.update(mode["id"] for mode in stored["custom"])
    if mode_id not in known:
        raise ValueError("That mode is not available.")
    selected = [item for item in stored["enabled"] if item != mode_id]
    if enabled:
        selected.append(mode_id)
    return _modes_block(stored, enabled=selected)


def _modes_block(stored, enabled=None, custom=None, held=None):
    return {
        "enabled": stored["enabled"] if enabled is None else enabled,
        "custom": stored["custom"] if custom is None else custom,
        "held": stored.get("held") or [] if held is None else held,
    }


def _mode_from_fields(fields, mode_id):
    name = " ".join(str(fields.get("name") or "").split())
    if not name:
        raise ValueError("Give the mode a name.")
    name = name[:40]

    days = []
    for raw in fields.get("days") or []:
        if str(raw) in {str(day) for day in range(7)}:
            day = int(raw)
            if day not in days:
                days.append(day)

    sports = []
    for raw in fields.get("sports") or []:
        sport = str(raw or "").strip()
        if sport in SPORT_IDS and sport not in sports:
            sports.append(sport)
    if not sports:
        raise ValueError("Pick at least one thing for this mode to show.")

    phases = [
        phase for phase in PHASES
        if phase in set(fields.get("phases") or [])
    ]
    if not phases:
        phases = ["live"]

    mode_id = str(mode_id or "").strip()
    if not mode_id or mode_id in PRESET_BY_ID or not mode_id.startswith("custom-"):
        mode_id = _new_custom_id()

    return {
        "id": mode_id,
        "name": name,
        "summary": "",
        "builtin": False,
        "kind": "overlay" if fields.get("hide_outside") else "filter",
        "days": days,
        "start": _clean_clock(fields.get("start")),
        "end": _clean_clock(fields.get("end")),
        "clock": "local",
        "window_zone": "",
        "slate_zone": "",
        "sports": sports,
        "phases": phases,
        "live_only_after": _clean_clock(fields.get("live_only_after")),
        "focus_after": _clean_clock(fields.get("focus_after")),
        "favorites_only": bool(fields.get("favorites_only")),
        "cfb_top25": bool(fields.get("cfb_top25")),
    }


def _clean_custom(raw):
    if not isinstance(raw, dict):
        return None
    try:
        mode = _mode_from_fields(
            {
                "name": raw.get("name"),
                "days": raw.get("days") or [],
                "sports": raw.get("sports") or [],
                "phases": raw.get("phases") or [],
                "start": raw.get("start"),
                "end": raw.get("end"),
                "live_only_after": raw.get("live_only_after"),
                "focus_after": raw.get("focus_after"),
                "hide_outside": raw.get("kind") == "overlay",
                "favorites_only": raw.get("favorites_only"),
                "cfb_top25": raw.get("cfb_top25"),
            },
            raw.get("id"),
        )
    except ValueError:
        return None
    if not str(raw.get("id") or "").startswith("custom-"):
        return None
    mode["id"] = str(raw.get("id"))
    return mode


def _new_custom_id():
    from uuid import uuid4
    return f"custom-{uuid4().hex[:8]}"


def _window_open(mode, instant):
    if mode.get("clock") == "market":
        return market_is_open(instant)

    zone = _named_zone(mode.get("window_zone")) or get_local_timezone()
    local = instant.astimezone(zone)
    days = mode.get("days") or []
    if days and local.weekday() not in days:
        return False

    start = _parse_hhmm(mode.get("start"))
    end = _parse_hhmm(mode.get("end"))
    if start is None and end is None:
        return True

    minutes = local.hour * 60 + local.minute
    start = 0 if start is None else start
    end = (24 * 60) - 1 if end is None else end
    if start <= end:
        return start <= minutes <= end
    return minutes >= start or minutes <= end


def _allows(mode, game, instant, settings):
    sport = sport_for_game(game)
    if sport not in set(mode.get("sports") or []):
        return False
    if mode.get("favorites_only") and sport in TEAM_SPORTS:
        if not _is_favorite(game, settings, sport):
            return False
    if sport == "cfb" and mode.get("cfb_top25") and not _is_top25(game):
        return False
    if sport not in TEAM_SPORTS:
        return True

    phase = game_phase(game)
    if phase not in set(mode.get("phases") or []):
        return False

    cutoff = _parse_hhmm(mode.get("live_only_after"))
    if cutoff is None or phase != "pregame":
        return True

    kickoff = _kickoff_minutes(game, _slate_zone(mode))
    if kickoff is None:
        return True
    return kickoff < cutoff


def _active_sports(settings, instant):
    controlled = {}
    hiding = set()

    for mode in enabled_modes(settings):
        sports = [
            sport for sport in mode.get("sports") or []
            if sport not in LEADING_SPORTS and sport in SPORT_IDS
        ]
        if _window_open(mode, instant):
            for sport in sports:
                controlled.setdefault(sport, []).append(mode)
        elif mode.get("kind") == "overlay":
            hiding.update(sports)

    hiding -= set(controlled)
    return controlled, hiding


def _take_sport(
    sport,
    owners,
    games,
    held,
    selected,
    selected_set,
    hidden_set,
    instant,
    settings,
    show,
):
    ids = [game_id(game) for game in games]
    if sport not in held:
        if sport == "stocks":
            held[sport] = [item for item in ids if item in hidden_set]
        else:
            held[sport] = [
                item for item in selected
                if _id_sport(item) == sport
            ]

    if sport == "stocks":
        for item in ids:
            if show:
                hidden_set.discard(item)
            else:
                hidden_set.add(item)
        return

    if show:
        desired = {
            game_id(game)
            for game in games
            if any(
                _allows(mode, game, instant, settings)
                for mode in owners
            )
        }
    else:
        desired = set()

    for item in ids:
        if item in desired:
            selected_set.add(item)
            hidden_set.discard(item)
        else:
            selected_set.discard(item)
            hidden_set.add(item)


def _restore_sport(sport, saved, games, selected_set, hidden_set):
    saved_set = set(saved)
    ids = [game_id(game) for game in games]

    if sport == "stocks":
        for item in ids:
            if item in saved_set:
                hidden_set.add(item)
            else:
                hidden_set.discard(item)
        return

    for item in ids:
        if item in saved_set:
            selected_set.add(item)
            hidden_set.discard(item)
        else:
            selected_set.discard(item)
            hidden_set.add(item)
    for item in list(selected_set):
        if _id_sport(item) == sport and item not in saved_set:
            selected_set.discard(item)
    selected_set.update(saved_set)


def _held_map(items):
    found = {}
    for item in items or []:
        text = str(item or "")
        if text.startswith("held:"):
            sport = text.split(":", 1)[1]
            if sport:
                found.setdefault(sport, [])
            continue
        sport = _id_sport(text)
        if not sport:
            continue
        found.setdefault(sport, [])
        if text not in found[sport]:
            found[sport].append(text)
    return found


def _held_list(held):
    items = []
    for sport in sorted(held):
        items.append(f"held:{sport}")
        for item in held[sport]:
            if item not in items:
                items.append(item)
    return items


def _id_list(values):
    if isinstance(values, str):
        values = [values]
    found = []
    for item in values or []:
        text = str(item or "").strip()
        if text and text not in found:
            found.append(text)
    return found


def _id_sport(identifier):
    text = str(identifier or "")
    if text.startswith("stocks:"):
        return "stocks"
    if ":" not in text:
        return ""
    return text.split(":", 1)[0]


def _single_game_focus(all_games, manual_games, leading, settings, instant):
    """Pin the board when a mode has left one game scrolling."""
    ticker = mode_ticker(
        all_games,
        manual_games,
        leading,
        settings,
        instant,
    )
    if not ticker:
        return []

    games = [
        game for game in ticker
        if sport_for_game(game) in TEAM_SPORTS
    ]
    if len(games) != 1:
        return []
    if sport_for_game(games[0]) not in FOCUS_SPORTS:
        return []
    return games


def _focus_picks(mode, games, instant, settings):
    threshold = _parse_hhmm(mode.get("focus_after"))
    if threshold is None:
        return []

    zone = _slate_zone(mode)
    picks = []

    for game in games or []:
        sport = sport_for_game(game)
        if sport not in FOCUS_SPORTS or sport not in set(mode.get("sports") or []):
            continue
        if game_phase(game) != "live":
            continue
        if mode.get("favorites_only") and not _is_favorite(game, settings, sport):
            continue
        if sport == "cfb" and mode.get("cfb_top25") and not _is_top25(game):
            continue
        kickoff = _kickoff_minutes(game, zone)
        if kickoff is None or kickoff < threshold:
            continue
        picks.append(game)

    return picks


def game_phase(game):
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
        or status.strip() in {"PRE", "PREGAME", "PRE GAME"}
    ):
        return "pregame"
    return "live"


def _is_top25(game):
    for rank in (
        getattr(game, "away_rank", None),
        getattr(game, "home_rank", None),
    ):
        try:
            number = int(rank)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 25:
            return True
    return False


def _is_favorite(game, settings, sport):
    favorites = ((settings or {}).get("favorite_teams") or {}).get(sport) or []
    if isinstance(favorites, str):
        favorites = [favorites]
    wanted = {str(team).strip().upper() for team in favorites if str(team).strip()}
    if not wanted:
        return False
    away = str(getattr(game, "away", "") or "").strip().upper()
    home = str(getattr(game, "home", "") or "").strip().upper()
    return away in wanted or home in wanted


def _kickoff_minutes(game, zone):
    raw = str(getattr(game, "start_at", "") or "").strip()
    if not raw:
        return None
    try:
        kickoff = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    local = kickoff.astimezone(zone)
    return local.hour * 60 + local.minute


def _slate_zone(mode):
    return _named_zone(mode.get("slate_zone")) or _named_zone(
        mode.get("window_zone")
    ) or get_local_timezone()


def _named_zone(name):
    text = str(name or "").strip()
    if not text:
        return None
    try:
        return ZoneInfo(text)
    except Exception:
        return None


def _instant(now):
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now


def _parse_hhmm(value):
    text = str(value or "").strip()
    if not text or ":" not in text:
        return None
    hour_text, minute_text = text.split(":", 1)
    if not hour_text.isdigit() or not minute_text[:2].isdigit():
        return None
    hour = int(hour_text)
    minute = int(minute_text[:2])
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _clean_clock(value):
    minutes = _parse_hhmm(value)
    if minutes is None:
        return ""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _clock_text(value):
    minutes = _parse_hhmm(value)
    if minutes is None:
        return ""
    hour = minutes // 60
    minute = minutes % 60
    suffix = "AM" if hour < 12 else "PM"
    shown = hour % 12 or 12
    return f"{shown}:{minute:02d} {suffix}"


def _when_text(mode):
    days = mode.get("days") or []
    if not days or len(days) == 7:
        when = "Every day"
    else:
        when = ", ".join(DAY_NAMES[day] for day in sorted(days))
    start = _clock_text(mode.get("start"))
    end = _clock_text(mode.get("end"))
    if start and end:
        when += f", {start} to {end}"
    elif start:
        when += f", from {start}"
    elif end:
        when += f", until {end}"
    zone = mode.get("window_zone") or ""
    if zone == "America/New_York":
        when += " Eastern"
    return when + "."


def _phase_text(mode):
    phases = [
        phase for phase in PHASES
        if phase in set(mode.get("phases") or [])
    ]
    labels = {
        "pregame": "previews",
        "live": "live games",
        "final": "finals",
    }
    if not phases or len(phases) == len(PHASES):
        return "Previews, live games, and finals."
    return ", ".join(labels[phase] for phase in phases).capitalize() + "."
