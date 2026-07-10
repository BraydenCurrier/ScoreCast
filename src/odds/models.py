from dataclasses import dataclass


@dataclass
class BettingOdds:
    away: str
    home: str

    moneyline_away: int | None = None
    moneyline_home: int | None = None

    spread: float | None = None
    spread_price: int | None = None

    total: float | None = None
    over_price: int | None = None
    under_price: int | None = None

    sportsbook: str = ""