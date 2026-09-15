from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import quote
import json
import re
import subprocess
import time

from common.settings import get_settings
from stocks.models import StockQuote


POPULAR_SYMBOLS = [
    ("SPY", "S&P 500"),
    ("QQQ", "Nasdaq 100"),
    ("DIA", "Dow Jones"),
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("NVDA", "Nvidia"),
    ("AMZN", "Amazon"),
    ("GOOGL", "Alphabet"),
    ("META", "Meta"),
    ("TSLA", "Tesla"),
    ("BTC-USD", "Bitcoin"),
]

DEFAULT_STOCK_SYMBOLS = [
    "SPY",
    "QQQ",
    "AAPL",
    "NVDA",
    "MSFT",
]

POPULAR_SYMBOL_SET = {
    symbol
    for symbol, _ in POPULAR_SYMBOLS
}

YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/"
    "{symbol}?interval=5m&range=5d"
)
YAHOO_SEARCH_URL = (
    "https://query1.finance.yahoo.com/v1/finance/search"
    "?q={query}&quotesCount=12&newsCount=0"
)

HTTP_TIMEOUT = (3.05, 10)
MAX_SYMBOLS = 20
SEARCHABLE_TYPES = {
    "EQUITY",
    "ETF",
    "CRYPTOCURRENCY",
    "INDEX",
    "MUTUALFUND",
}
SYMBOL_PATTERN = re.compile(
    r"^\^?[A-Z0-9][A-Z0-9.\-]{0,14}$"
)


def normalize_symbol(value):
    symbol = str(value or "").strip().upper()
    symbol = symbol.replace(" ", "")

    if not symbol:
        return ""

    if not SYMBOL_PATTERN.fullmatch(symbol):
        return ""

    return symbol


def parse_symbol_list(value):
    if isinstance(value, str):
        parts = re.split(r"[\s,;]+", value)
    elif isinstance(value, list):
        parts = value
    else:
        return []

    symbols = []
    seen = set()

    for part in parts:
        symbol = normalize_symbol(part)

        if not symbol or symbol in seen:
            continue

        seen.add(symbol)
        symbols.append(symbol)

        if len(symbols) >= MAX_SYMBOLS:
            break

    return symbols


def get_selected_symbols():
    settings = get_settings()
    stocks = settings.get("stocks", {})

    if not isinstance(stocks, dict):
        return DEFAULT_STOCK_SYMBOLS.copy()

    selected = parse_symbol_list(
        stocks.get("symbols", DEFAULT_STOCK_SYMBOLS)
    )

    return selected


def _curl_json(url):
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--fail-with-body",
        "--location",
        "--compressed",
        "--max-time",
        str(HTTP_TIMEOUT[1]),
        "--header",
        "Accept: application/json",
        "--header",
        "User-Agent: Mozilla/5.0",
        url,
    ]

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "curl is required but is not installed"
        ) from exc
    except subprocess.CalledProcessError as exc:
        response_text = (
            exc.stdout
            or exc.stderr
            or "No response body"
        ).strip()

        raise RuntimeError(
            f"Yahoo request failed: {response_text[:200]}"
        ) from exc

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Yahoo returned invalid JSON"
        ) from exc

    return data


def search_symbols(query, limit=8):
    query = str(query or "").strip()

    if len(query) < 1:
        return []

    data = _curl_json(
        YAHOO_SEARCH_URL.format(
            query=quote(query)
        )
    )
    results = []
    seen = set()

    for row in data.get("quotes") or []:
        if not isinstance(row, dict):
            continue

        quote_type = str(
            row.get("quoteType") or ""
        ).upper()

        if quote_type not in SEARCHABLE_TYPES:
            continue

        symbol = normalize_symbol(row.get("symbol"))

        if not symbol or symbol in seen:
            continue

        name = str(
            row.get("shortname")
            or row.get("longname")
            or ""
        ).strip()
        exchange = str(
            row.get("exchDisp")
            or row.get("exchange")
            or ""
        ).strip()

        seen.add(symbol)
        results.append(
            {
                "symbol": symbol,
                "name": name,
                "type": quote_type,
                "exchange": exchange,
            }
        )

        if len(results) >= limit:
            break

    return results


def fetch_yahoo_chart(symbol):
    encoded = quote(symbol, safe="-^")
    url = YAHOO_CHART_URL.format(symbol=encoded)

    data = _curl_json(url)

    result_rows = (
        (data.get("chart") or {}).get("result")
        or []
    )

    if not result_rows:
        error = (data.get("chart") or {}).get("error")
        raise ValueError(
            f"{symbol} has no quote data: {error}"
        )

    return result_rows[0]


def _local_date(timestamp, gmt_offset):
    moment = datetime.fromtimestamp(
        int(timestamp) + int(gmt_offset),
        timezone.utc,
    )
    return moment.date().isoformat()


def _regular_session(meta):
    trading = meta.get("currentTradingPeriod") or {}
    regular = trading.get("regular") or {}

    try:
        start = int(regular.get("start") or 0)
        end = int(regular.get("end") or 0)
    except (TypeError, ValueError):
        return 0, 0

    return start, end


def _extract_day_points(chart, live):
    meta = chart.get("meta") or {}
    timestamps = chart.get("timestamp") or []
    quotes = (
        (chart.get("indicators") or {}).get("quote")
        or [{}]
    )
    closes = quotes[0].get("close") or []
    gmt_offset = int(meta.get("gmtoffset") or 0)

    days = {}

    for timestamp, close in zip(timestamps, closes):
        if timestamp is None or close is None:
            continue

        try:
            timestamp = int(timestamp)
            close = float(close)
        except (TypeError, ValueError):
            continue

        day = _local_date(timestamp, gmt_offset)
        days.setdefault(day, []).append(
            (timestamp, close)
        )

    if not days:
        return tuple(), 0, 0, None

    now = time.time()
    today = _local_date(now, gmt_offset)
    session_start, session_end = _regular_session(meta)
    sorted_days = sorted(days)

    if live and today in days:
        current_day = today
        points = days[current_day]

        if not session_start or not session_end:
            session_start = points[0][0]
            session_end = max(points[-1][0], int(now))
    else:
        current_day = sorted_days[-1]
        points = days[current_day]
        session_start = points[0][0]
        session_end = points[-1][0]

    previous_days = [
        day for day in sorted_days if day < current_day
    ]
    previous_close = None

    if previous_days:
        previous_close = days[previous_days[-1]][-1][1]

    return (
        tuple(points),
        session_start,
        session_end,
        previous_close,
    )


def parse_quote(symbol, chart):
    meta = chart.get("meta") or {}
    price = meta.get("regularMarketPrice")

    if price is None:
        raise ValueError(
            f"{symbol} is missing a market price"
        )

    price = float(price)
    now = time.time()
    session_start, session_end = _regular_session(meta)
    live = bool(
        session_start
        and session_end
        and session_start <= now < session_end
    )

    (
        day_points,
        graph_start,
        graph_end,
        session_previous,
    ) = _extract_day_points(chart, live)

    previous = session_previous

    if previous is None:
        try:
            previous = float(meta.get("previousClose"))
        except (TypeError, ValueError):
            previous = None

    if previous is None:
        previous = price

    change = price - previous

    if previous:
        change_percent = (change / previous) * 100
    else:
        change_percent = 0.0

    return StockQuote(
        symbol=str(
            meta.get("symbol") or symbol
        ).upper(),
        name=str(
            meta.get("shortName")
            or meta.get("longName")
            or symbol
        ),
        price=price,
        change=change,
        change_percent=change_percent,
        market_state="LIVE" if live else "CLOSED",
        currency=str(
            meta.get("currency") or "USD"
        ),
        previous_close=previous,
        session_start=graph_start,
        session_end=graph_end,
        day_points=day_points,
    )


def fetch_quote(symbol):
    return parse_quote(
        symbol,
        fetch_yahoo_chart(symbol),
    )


def get_today_games():
    symbols = get_selected_symbols()

    if not symbols:
        return []

    quotes = []
    errors = []

    with ThreadPoolExecutor(
        max_workers=min(4, len(symbols)),
        thread_name_prefix="stocks-api",
    ) as executor:
        future_to_symbol = {
            executor.submit(fetch_quote, symbol): symbol
            for symbol in symbols
        }

        quotes_by_symbol = {}

        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]

            try:
                quotes_by_symbol[symbol] = future.result()
            except Exception as exc:
                errors.append(f"{symbol}: {exc}")

    for symbol in symbols:
        quote = quotes_by_symbol.get(symbol)

        if quote is not None:
            quotes.append(quote)

    if errors and not quotes:
        raise RuntimeError(
            "Stock refresh failed: "
            + "; ".join(errors)
        )

    return quotes
