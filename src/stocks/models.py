from dataclasses import dataclass, field


@dataclass
class StockQuote:
    symbol: str
    name: str
    price: float
    change: float
    change_percent: float
    market_state: str = "CLOSED"
    currency: str = "USD"
    previous_close: float = 0.0
    session_start: int = 0
    session_end: int = 0
    day_points: tuple = field(default_factory=tuple)

    @property
    def away(self):
        return self.symbol

    @property
    def home(self):
        return ""

    @property
    def status(self):
        return self.market_state

    @property
    def away_score(self):
        return self.price

    @property
    def home_score(self):
        return self.change_percent
