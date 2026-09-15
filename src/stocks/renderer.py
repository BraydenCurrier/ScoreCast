from common.fonts import (
    gfx_5x7_width,
    print_4x5_centered,
    print_gfx_5x7,
)

WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)
GREY = (70, 70, 70)
GREEN = (0, 220, 80)
RED = (220, 50, 50)
DIM_GREEN = (0, 70, 28)
DIM_RED = (70, 16, 16)

CARD_WIDTH = 120
GRAPH_X = 2
GRAPH_Y = 11
GRAPH_HEIGHT = 13
GRAPH_RIGHT_PAD = 2


def change_color(game):
    if game.change > 0:
        return GREEN
    if game.change < 0:
        return RED
    return GREY


def format_price(price):
    value = abs(float(price))

    if value >= 10000:
        text = f"{price:.0f}"
    elif value >= 1000:
        text = f"{price:.1f}"
    else:
        text = f"{price:.2f}"

    return text


def format_change(value):
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}"


def format_percent(value):
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def _graph_columns(game, width):
    points = game.day_points or ()

    if not points or width <= 1:
        return [None] * width

    start = int(game.session_start or points[0][0])
    end = int(game.session_end or points[-1][0])

    if end <= start:
        end = start + 1

    columns = [None] * width
    last_index = -1

    for timestamp, price in points:
        try:
            timestamp = int(timestamp)
            price = float(price)
        except (TypeError, ValueError):
            continue

        x = int(
            (timestamp - start)
            / (end - start)
            * (width - 1)
        )
        x = max(0, min(width - 1, x))
        columns[x] = price
        last_index = max(last_index, x)

    if last_index < 0:
        return columns

    last_price = None

    for index in range(last_index + 1):
        if columns[index] is None:
            columns[index] = last_price
        else:
            last_price = columns[index]

    return columns


def _price_to_y(price, low, high, top, height):
    if high <= low:
        return top + height // 2

    scale = (price - low) / (high - low)
    return (
        top
        + height
        - 1
        - int(scale * (height - 1))
    )


def draw_day_graph(draw, game, offset_x):
    width = CARD_WIDTH - GRAPH_X - GRAPH_RIGHT_PAD
    columns = _graph_columns(game, width)
    values = [price for price in columns if price is not None]

    if len(values) < 2:
        return

    low = min(values)
    high = max(values)
    pad = max((high - low) * 0.08, 1e-6)
    low -= pad
    high += pad
    previous = float(game.previous_close or 0)

    if high - low < 1e-9:
        high = low + 1e-9

    color = change_color(game)
    fill = DIM_GREEN if game.change >= 0 else DIM_RED
    baseline = GRAPH_Y + GRAPH_HEIGHT - 1
    last_y = None

    for index, price in enumerate(columns):
        if price is None:
            last_y = None
            continue

        x = offset_x + GRAPH_X + index
        y = _price_to_y(
            price,
            low,
            high,
            GRAPH_Y,
            GRAPH_HEIGHT,
        )

        for fill_y in range(y + 1, baseline + 1):
            draw.point((x, fill_y), fill=fill)

        if last_y is not None:
            step = 1 if y >= last_y else -1
            for line_y in range(last_y, y + step, step):
                draw.point((x, line_y), fill=color)
        else:
            draw.point((x, y), fill=color)

        last_y = y

    if previous:
        previous_y = _price_to_y(
            previous,
            low,
            high,
            GRAPH_Y,
            GRAPH_HEIGHT,
        )

        if GRAPH_Y <= previous_y <= GRAPH_Y + GRAPH_HEIGHT - 1:
            for x in range(width):
                if x % 2 == 0:
                    draw.point(
                        (
                            offset_x + GRAPH_X + x,
                            previous_y,
                        ),
                        fill=GREY,
                    )


def render_game_strip_onto(image, draw, game, offset_x, settings):
    color = change_color(game)
    symbol = str(game.symbol or "").upper()
    price = format_price(game.price)
    change = format_change(game.change)
    percent = format_percent(game.change_percent)

    print_gfx_5x7(
        draw,
        symbol,
        2 + offset_x,
        2,
        WHITE,
    )

    price_width = gfx_5x7_width(price)
    print_gfx_5x7(
        draw,
        price,
        offset_x + CARD_WIDTH - 2 - price_width,
        2,
        YELLOW,
    )

    draw_day_graph(draw, game, offset_x)

    print_4x5_centered(
        draw,
        f"{change}  {percent}",
        offset_x + CARD_WIDTH // 2,
        26,
        color,
    )
