from __future__ import annotations

from bets.catalog import (
    DIR_ML_AWAY,
    DIR_ML_HOME,
    DIR_SPREAD_AWAY,
    DIR_SPREAD_HOME,
    DIR_TEAM_AWAY_OVER,
    DIR_TEAM_AWAY_UNDER,
    DIR_TEAM_HOME_OVER,
    DIR_TEAM_HOME_UNDER,
    DIR_TOTAL_OVER,
    DIR_TOTAL_UNDER,
    MARKETS,
    STATUS_LIVE,
    STATUS_LOST,
    STATUS_PENDING,
    STATUS_PUSH,
    STATUS_REVIEW,
    STATUS_VOID,
    STATUS_WON,
    is_over_direction,
    is_under_direction,
)


def _is_integer_line(line: float) -> bool:
    return abs(line - round(line)) < 1e-9


def grade_over_under(
    value: float,
    line: float,
    direction: str,
    *,
    final: bool,
    monotonic: bool = True,
) -> str | None:
    """Return a settled status, or None if the bet is still open.

    Overs on monotonic stats can clinch before the event ends.
    Unders and non-monotonic markets wait for a final result.
    """
    if is_over_direction(direction):
        if value > line:
            return STATUS_WON
        if not final:
            return None
        if value < line:
            return STATUS_LOST
        if _is_integer_line(line) and abs(value - line) < 1e-9:
            return STATUS_PUSH
        return STATUS_LOST

    if is_under_direction(direction):
        if not final:
            if monotonic and value > line:
                return STATUS_LOST
            return None
        if value < line:
            return STATUS_WON
        if value > line:
            return STATUS_LOST
        if _is_integer_line(line) and abs(value - line) < 1e-9:
            return STATUS_PUSH
        return STATUS_LOST

    return None


def grade_moneyline(away_score: int, home_score: int, direction: str) -> str:
    if away_score == home_score:
        return STATUS_PUSH
    away_won = away_score > home_score
    if direction == DIR_ML_AWAY:
        return STATUS_WON if away_won else STATUS_LOST
    if direction == DIR_ML_HOME:
        return STATUS_WON if not away_won else STATUS_LOST
    return STATUS_REVIEW


def grade_spread(
    away_score: int,
    home_score: int,
    line: float,
    direction: str,
) -> str:
    """`line` is the handicap for the selected team (e.g. +3.5 or -7)."""
    if direction == DIR_SPREAD_AWAY:
        value = away_score + line
        opponent = home_score
    elif direction == DIR_SPREAD_HOME:
        value = home_score + line
        opponent = away_score
    else:
        return STATUS_REVIEW

    if value > opponent:
        return STATUS_WON
    if value < opponent:
        return STATUS_LOST
    return STATUS_PUSH


def grade_game_market(
    *,
    market: str,
    direction: str,
    line: float | None,
    away_score: int,
    home_score: int,
    final: bool,
) -> str | None:
    if not final and market == "moneyline":
        return None
    if not final and market == "spread":
        return None

    if market == "moneyline":
        return grade_moneyline(away_score, home_score, direction)

    if market == "spread":
        if line is None:
            return STATUS_REVIEW
        return grade_spread(away_score, home_score, line, direction)

    if market == "total":
        if line is None:
            return STATUS_REVIEW
        total = away_score + home_score
        mapped = (
            "over" if direction == DIR_TOTAL_OVER else
            "under" if direction == DIR_TOTAL_UNDER else
            direction
        )
        return grade_over_under(total, line, mapped, final=final, monotonic=True)

    if market == "team_total":
        if line is None:
            return STATUS_REVIEW
        if direction in {DIR_TEAM_AWAY_OVER, DIR_TEAM_AWAY_UNDER}:
            value = away_score
            mapped = "over" if direction == DIR_TEAM_AWAY_OVER else "under"
        elif direction in {DIR_TEAM_HOME_OVER, DIR_TEAM_HOME_UNDER}:
            value = home_score
            mapped = "over" if direction == DIR_TEAM_HOME_OVER else "under"
        else:
            return STATUS_REVIEW
        return grade_over_under(value, line, mapped, final=final, monotonic=True)

    return STATUS_REVIEW


def grade_player_market(
    *,
    market: str,
    direction: str,
    line: float | None,
    value: float | None,
    final: bool,
) -> str | None:
    if line is None or value is None:
        if final:
            return STATUS_REVIEW
        return None

    spec = MARKETS.get(market)
    monotonic = True if spec is None else spec.monotonic
    return grade_over_under(
        value,
        line,
        direction,
        final=final,
        monotonic=monotonic,
    )


def remaining_to_line(value: float | None, line: float | None, direction: str) -> float | None:
    if value is None or line is None:
        return None
    if is_over_direction(direction):
        return round(line - value, 2)
    if is_under_direction(direction):
        return round(line - value, 2)
    return None


def settle_parlay(leg_statuses: list[str]) -> str:
    if not leg_statuses:
        return STATUS_REVIEW
    if any(status == STATUS_LOST for status in leg_statuses):
        return STATUS_LOST
    if any(status == STATUS_REVIEW for status in leg_statuses):
        return STATUS_REVIEW
    if any(status in {STATUS_PENDING, STATUS_LIVE} for status in leg_statuses):
        if any(status == STATUS_LIVE for status in leg_statuses):
            return STATUS_LIVE
        return STATUS_PENDING

    remaining = [
        status
        for status in leg_statuses
        if status not in {STATUS_PUSH, STATUS_VOID}
    ]
    if not remaining:
        if all(status == STATUS_VOID for status in leg_statuses):
            return STATUS_VOID
        return STATUS_PUSH
    if all(status == STATUS_WON for status in remaining):
        return STATUS_WON
    return STATUS_REVIEW
