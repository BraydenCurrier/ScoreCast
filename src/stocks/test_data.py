from stocks.models import StockQuote


TEST_GAMES_STOCKS = [
    StockQuote(
        symbol="AAPL",
        name="Apple",
        price=227.52,
        change=1.84,
        change_percent=0.81,
        market_state="CLOSED",
        previous_close=225.68,
        session_start=0,
        session_end=77,
        day_points=tuple(
            (index, 225.68 + (index / 77) * 1.84)
            for index in range(78)
        ),
    ),
    StockQuote(
        symbol="NVDA",
        name="Nvidia",
        price=131.28,
        change=-2.15,
        change_percent=-1.61,
        market_state="CLOSED",
        previous_close=133.43,
        session_start=0,
        session_end=77,
        day_points=tuple(
            (index, 133.43 - (index / 77) * 2.15)
            for index in range(78)
        ),
    ),
    StockQuote(
        symbol="SPY",
        name="S&P 500",
        price=562.10,
        change=3.42,
        change_percent=0.61,
        market_state="LIVE",
        previous_close=558.68,
        session_start=0,
        session_end=77,
        day_points=tuple(
            (index, 558.68 + (index / 40) * 3.42)
            for index in range(41)
        ),
    ),
]
