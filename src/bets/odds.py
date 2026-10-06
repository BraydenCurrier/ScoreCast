from __future__ import annotations

from typing import Iterable


def parse_american_odds(value) -> int | None:
    if value is None or value == "":
        return None

    text = str(value).strip().replace(",", "")
    if not text:
        return None

    percent = _parse_percent(text)
    if percent is not None:
        return implied_percent_to_american(percent)

    if text.endswith("%"):
        raise ValueError("Percentage must be between 0 and 100.")

    try:
        odds = int(float(text))
    except (TypeError, ValueError) as error:
        raise ValueError("Odds must be a percentage or an American number.") from error

    if odds == 0 or -99 <= odds <= 99:
        raise ValueError("American odds cannot be between -99 and +99.")
    if abs(odds) > 100000:
        raise ValueError("Odds are out of range.")
    return odds


def _parse_percent(text: str) -> float | None:
    raw = str(text or "").strip().replace(",", "")
    if not raw:
        return None
    marked = raw.endswith("%")
    if marked:
        raw = raw[:-1].strip()
    if raw.startswith(("+", "-")) and not marked:
        return None
    try:
        percent = float(raw)
    except (TypeError, ValueError):
        return None
    if marked:
        return percent
    if 0 < percent < 100:
        return percent
    return None


def implied_percent_to_american(percent: float) -> int:
    if percent <= 0 or percent >= 100:
        raise ValueError("Percentage must be between 0 and 100.")
    chance = percent / 100.0
    if abs(chance - 0.5) < 1e-9:
        return 100
    if chance > 0.5:
        return int(round(-100.0 * chance / (1.0 - chance)))
    return int(round(100.0 * (1.0 - chance) / chance))


def american_to_implied_percent(odds: int) -> float:
    if odds < 0:
        return round(100.0 * abs(odds) / (abs(odds) + 100.0), 2)
    return round(100.0 * 100.0 / (odds + 100.0), 2)


def parse_stake(value) -> float | None:
    if value is None or value == "":
        return None

    text = str(value).strip().replace("$", "").replace(",", "")
    if not text:
        return None

    try:
        stake = float(text)
    except (TypeError, ValueError) as error:
        raise ValueError("Stake must be a number.") from error

    if stake <= 0 or stake > 1_000_000:
        raise ValueError("Stake must be greater than 0.")
    return round(stake, 2)


def american_to_decimal(odds: int) -> float:
    if odds > 0:
        return 1.0 + (odds / 100.0)
    return 1.0 + (100.0 / abs(odds))


def decimal_to_american(decimal_odds: float) -> int:
    if decimal_odds <= 1:
        raise ValueError("Decimal odds must be greater than 1.")
    if decimal_odds >= 2:
        return int(round((decimal_odds - 1.0) * 100))
    return int(round(-100.0 / (decimal_odds - 1.0)))


def profit_from_american(stake: float, odds: int) -> float:
    if odds > 0:
        return round(stake * (odds / 100.0), 2)
    return round(stake * (100.0 / abs(odds)), 2)


def payout_from_american(stake: float, odds: int) -> float:
    return round(stake + profit_from_american(stake, odds), 2)


def combine_american_odds(legs: Iterable[int]) -> int:
    decimal = 1.0
    count = 0
    for odds in legs:
        decimal *= american_to_decimal(int(odds))
        count += 1
    if count == 0:
        raise ValueError("Parlay odds need at least one leg.")
    return decimal_to_american(decimal)


def format_american(odds: int) -> str:
    if odds > 0:
        return f"+{odds}"
    return str(odds)


def format_money(amount: float, *, signed: bool = False) -> str:
    value = abs(float(amount))
    text = f"{value:,.2f}"
    if signed:
        if amount > 0:
            return f"+{text}"
        if amount < 0:
            return f"-{text}"
    return text


def result_profit(
    status: str,
    stake: float | None,
    odds: int | None,
) -> float | None:
    if stake is None or odds is None:
        return None
    if status == "won":
        return profit_from_american(stake, odds)
    if status == "lost":
        return round(-stake, 2)
    if status in {"push", "void"}:
        return 0.0
    return None
