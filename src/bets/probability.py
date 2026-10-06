from __future__ import annotations

import math
from typing import Any

from bets.catalog import is_over_direction, is_under_direction


# Need a bit of the game in the books so a 2-yard carry does not blow up the pace.
MIN_ELAPSED = 0.10


def estimate_hit_chance(
    *,
    current: float | None,
    line: float | None,
    direction: str,
    remaining_fraction: float | None,
    final: bool = False,
) -> dict[str, Any]:
    """Live pace vs the line from current production and time left.

    Example: over 100 rush yards, 25 after one quarter (75% left) is on pace
    for 100, so about 50%. No historical logs. Not a sportsbook price.
    """
    if current is None:
        if (
            remaining_fraction is not None
            and 0 < float(remaining_fraction) < 0.95
        ):
            current = 0.0
        else:
            return _empty("Waiting on live stats")
    if line is None:
        return _empty("Waiting on live stats")
    try:
        current_value = float(current)
        line_value = float(line)
    except (TypeError, ValueError):
        return _empty("Waiting on live stats")
    if line_value <= 0:
        return _empty("No live pace for this market")

    if final or (
        remaining_fraction is not None and float(remaining_fraction) <= 0
    ):
        if is_over_direction(direction):
            chance = 99.0 if current_value > line_value else 1.0
        elif is_under_direction(direction):
            chance = 99.0 if current_value < line_value else 1.0
        else:
            return _empty("No live pace for this market")
        return _result(chance, "Final value compared with the line.")

    if remaining_fraction is None:
        return _empty("Waiting on the game")
    remaining = max(0.0, min(1.0, float(remaining_fraction)))
    elapsed = 1.0 - remaining
    if elapsed < MIN_ELAPSED:
        return _empty("Too early to pace")

    projected = current_value / elapsed
    left_pct = int(round(remaining * 100))
    note = f"On pace for {projected:.0f} with {left_pct}% of the game left."

    # Confidence rises as more of the game is played. On pace (projected ==
    # line) sits at 50%.
    steepness = 3.5 + 9.0 * elapsed
    ratio = projected / line_value

    if is_over_direction(direction):
        if current_value > line_value:
            return _result(99.0, "Already over the line.")
        raw = 1.0 / (1.0 + math.exp(-steepness * (ratio - 1.0)))
    elif is_under_direction(direction):
        if current_value > line_value:
            return _result(1.0, "Already over the under.")
        raw = 1.0 / (1.0 + math.exp(-steepness * (1.0 - ratio)))
    else:
        return _empty("No live pace for this market")

    return _result(max(1.0, min(99.0, round(raw * 100.0, 1))), note)


def combine_independent(chances: list[float | None]) -> dict[str, Any]:
    if any(item is None for item in chances) or not chances:
        return _empty("Waiting on every leg")
    if any(float(chance) <= 0 for chance in chances):
        return _result(0.0, "A leg is already dead.")
    joint = 100.0
    for chance in chances:
        joint *= float(chance) / 100.0
    return _result(
        max(0.1, min(99.0, round(joint, 1))),
        "Live pace for each leg, multiplied.",
    )


def _empty(reason: str) -> dict[str, Any]:
    return {
        "chance": None,
        "label": "—",
        "note": reason,
        "source": "Live pace",
    }


def _result(chance: float, note: str) -> dict[str, Any]:
    return {
        "chance": chance,
        "label": f"{chance:.0f}%",
        "note": note,
        "source": "Live pace",
    }
