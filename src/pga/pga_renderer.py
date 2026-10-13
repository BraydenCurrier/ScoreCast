"""32px PGA leaderboard card.

The tournament logo sits to the left of the scorecard. A header band
carries the tournament name, the page, and the status. Six players
follow in two equal columns, three stacked in each. Further players
replace that page on a timer. Each row is position, name, score to
par, then the current hole or the latest round score.
"""

import time
from io import BytesIO
from pathlib import Path

from PIL import Image

from common.fonts import (
    get_4x5_width,
    gfx_5x7_width,
    print_4x5,
    print_gfx_5x7,
)
from common.http import CA_BUNDLE, session

from pga.models import GolfTournament


WHITE = (255, 255, 255)
UNDER = (255, 48, 48)
OVER = (255, 176, 40)
EVEN = (255, 255, 255)
HEADER = (255, 255, 255)
HEADER_BAND = (18, 46, 108)
POSITION = (132, 148, 176)
HOLE = (96, 176, 232)
ROUND = (214, 214, 214)
LIVE = (80, 255, 130)
QUIET = (168, 178, 196)
TEE = (170, 220, 255)
DIVIDER = (64, 88, 140)

LOGO_GAP = 4
MAX_LOGO_HEIGHT = 30
MAX_LOGO_WIDTH = 30
LEFT = 2
RIGHT = 2
NAME_GAP = 3
SCORE_GAP = 6
STATUS_GAP = 6
COLUMN_GUTTER = 9
HEADER_Y = 0
HEADER_BAND_BOTTOM = 7
ROW_Y = (8, 16, 24)
STACKED_PLAYERS = 3
COLUMN_COUNT = 2
PAGE_SIZE = STACKED_PLAYERS * COLUMN_COUNT
PAGE_HOLD_SECONDS = 8
MAX_CARD_WIDTH = 360
MIN_CARD_WIDTH = 96

_LOGO_CACHE = Path("/tmp/scorecast-pga-logo.png")
_LOGO_URL_CACHE = Path("/tmp/scorecast-pga-logo.url")
_memory_logo: dict[str, Image.Image | None] = {}


def score_color(score_value: int):
    if score_value < 0:
        return UNDER
    if score_value > 0:
        return OVER
    return EVEN


def display_page(players, now=None) -> int:
    """Which six-player page is on screen at this moment."""
    pages = page_count(players)
    if pages <= 1:
        return 0
    moment = time.time() if now is None else now
    return int(moment // PAGE_HOLD_SECONDS) % pages


def page_count(players) -> int:
    count = len(tuple(players or ()))
    if count <= 0:
        return 1
    return (count + PAGE_SIZE - 1) // PAGE_SIZE


def page_players(players, page: int):
    items = list(players or ())
    pages = page_count(items)
    if not items:
        return []
    start = (page % pages) * PAGE_SIZE
    return items[start:start + PAGE_SIZE]


def card_width(tournament: GolfTournament) -> int:
    players = tournament.players
    needed = _header_width(tournament)
    for page in range(page_count(players)):
        columns = _columns(players, page)
        if not columns:
            continue
        widest = max(_column_width(column) for column in columns)
        needed = max(
            needed,
            LEFT
            + widest * len(columns)
            + COLUMN_GUTTER * (len(columns) - 1)
            + RIGHT,
        )
    body = max(MIN_CARD_WIDTH, min(MAX_CARD_WIDTH, needed))
    return body + _logo_span(getattr(tournament, "logo_url", ""))


def render_game_strip_onto(image, draw, game, offset_x, settings):
    del settings
    logo = _logo_image(getattr(game, "logo_url", ""))
    span = 0
    if logo is not None:
        image.paste(
            logo,
            (offset_x, (image.size[1] - logo.size[1]) // 2),
            logo,
        )
        span = logo.size[0] + LOGO_GAP

    card_x = offset_x + span
    width = image.size[0] - card_x
    _draw_header(draw, game, card_x, width)

    columns = _columns(game.players, display_page(game.players))
    if not columns:
        _draw_upcoming(draw, game, card_x, width)
        return

    gutters = COLUMN_GUTTER * (len(columns) - 1)
    available = max(0, width - LEFT - RIGHT - gutters)
    widest = max(_column_width(column) for column in columns)
    widths = _equal_columns(len(columns), available, widest)
    cursor = card_x + LEFT
    for index, (column, column_width) in enumerate(zip(columns, widths)):
        _draw_column(draw, column, cursor, column_width)
        cursor += column_width
        if index < len(columns) - 1:
            line_x = cursor + COLUMN_GUTTER // 2
            draw.line(
                [(line_x, ROW_Y[0]), (line_x, image.size[1] - 1)],
                fill=DIVIDER,
            )
            cursor += COLUMN_GUTTER


def _draw_upcoming(draw, game, card_x, width):
    label = str(getattr(game, "when", "") or "")
    if not label or width <= 0:
        return
    text_width = _text_width(label)
    text_x = card_x + max(LEFT, (width - text_width) // 2)
    print_gfx_5x7(draw, label, text_x, 14, QUIET)


def _columns(players, page=None):
    if page is None:
        page = display_page(players)
    shown = page_players(players, page)
    columns = []
    for index in range(COLUMN_COUNT):
        start = index * STACKED_PLAYERS
        column = shown[start:start + STACKED_PLAYERS]
        if column:
            columns.append(column)
    return columns


def _draw_header(draw, game, card_x, width):
    if width <= 0:
        return
    draw.rectangle(
        [card_x, 0, card_x + width - 1, HEADER_BAND_BOTTOM],
        fill=HEADER_BAND,
    )
    players = getattr(game, "players", ())
    label = _status_label(getattr(game, "status", ""))
    label_width = get_4x5_width(label)
    page_label = _page_label(players, display_page(players))
    page_width = get_4x5_width(_widest_page_label(players))
    label_x = card_x + width - RIGHT - label_width
    page_x = label_x - (STATUS_GAP + page_width if page_label else 0)
    name_x = card_x + LEFT
    title_gap = STATUS_GAP if page_label or label else 0
    title_limit = page_x - title_gap - name_x
    title = _fit_gfx(getattr(game, "name", ""), title_limit)
    if title:
        print_gfx_5x7(draw, title, name_x, HEADER_Y, HEADER)
    if page_label:
        print_4x5(
            draw,
            page_label,
            page_x + page_width - get_4x5_width(page_label),
            1,
            QUIET,
        )
    if label and label_width < width - LEFT - RIGHT:
        if label == "LIVE":
            color = LIVE
        elif label == "TEE":
            color = TEE
        else:
            color = QUIET
        print_4x5(draw, label, label_x, 1, color)


def _draw_column(draw, column, x, width):
    position_width = max(_text_width(player.position) for player in column)
    score_width = max(_text_width(player.score) for player in column)
    marker_width = max(_text_width(player.marker) for player in column)
    for index, player in enumerate(column):
        if index >= len(ROW_Y):
            break
        y = ROW_Y[index]
        if player.position:
            print_gfx_5x7(
                draw,
                player.position,
                x + position_width - _text_width(player.position),
                y,
                POSITION,
            )

        marker = str(player.marker or "")
        score = str(player.score or "")
        mark_right = x + width
        if marker:
            if getattr(player, "awaiting_tee", False):
                color = TEE
            elif player.finished_round:
                color = ROUND
            else:
                color = HOLE
            print_gfx_5x7(
                draw,
                marker,
                mark_right - _text_width(marker),
                y,
                color,
            )
        score_right = mark_right - marker_width - (SCORE_GAP if marker_width else 0)
        if score:
            print_gfx_5x7(
                draw,
                score,
                score_right - _text_width(score),
                y,
                score_color(player.score_value),
            )

        name_x = x + position_width + (NAME_GAP if position_width else 0)
        name_limit = score_right - score_width - NAME_GAP - name_x
        fitted = _fit_gfx(player.name, name_limit)
        if fitted:
            print_gfx_5x7(draw, fitted, name_x, y, WHITE)


def _column_width(column) -> int:
    position_width = max(_text_width(player.position) for player in column)
    score_width = max(_text_width(player.score) for player in column)
    marker_width = max(_text_width(player.marker) for player in column)
    name_width = max(_text_width(player.name) for player in column)
    position_gap = NAME_GAP if position_width else 0
    name_gap = NAME_GAP if score_width or marker_width else 0
    if score_width and marker_width:
        between = SCORE_GAP
    elif marker_width:
        between = SCORE_GAP
    else:
        between = 0
    return (
        position_width
        + position_gap
        + name_width
        + name_gap
        + score_width
        + between
        + marker_width
    )


def _equal_columns(count, available, widest):
    if count <= 0:
        return []
    if widest * count <= available:
        spare = available - widest * count
        extra = spare // count
        remainder = spare - extra * count
        return [
            widest + extra + (1 if index < remainder else 0)
            for index in range(count)
        ]
    share = available // count
    remainder = available - share * count
    return [
        share + (1 if index < remainder else 0)
        for index in range(count)
    ]


def _status_label(status: str) -> str:
    text = str(status or "").strip().upper()
    if text == "LIVE":
        return "LIVE"
    if text == "SCHEDULED":
        return "TEE"
    if text:
        return "FINAL"
    return ""


def _page_label(players, page: int) -> str:
    if page_count(players) <= 1:
        return ""
    group = page_players(players, page)
    if not group:
        return ""
    start = (page % page_count(players)) * PAGE_SIZE + 1
    return f"{start}-{start + len(group) - 1}"


def _widest_page_label(players) -> str:
    labels = [
        _page_label(players, page)
        for page in range(page_count(players))
    ]
    labels = [label for label in labels if label]
    if not labels:
        return ""
    return max(labels, key=get_4x5_width)


def _header_width(tournament) -> int:
    title = _text_width(getattr(tournament, "name", "") or "PGA")
    status = get_4x5_width(_status_label(getattr(tournament, "status", "")))
    page = get_4x5_width(_widest_page_label(getattr(tournament, "players", ())))
    gap = STATUS_GAP if status else 0
    page_gap = STATUS_GAP if page else 0
    return LEFT + title + page_gap + page + gap + status + RIGHT


def _logo_span(url: str) -> int:
    logo = _logo_image(url)
    if logo is None:
        return 0
    return logo.size[0] + LOGO_GAP


def _text_width(text: str) -> int:
    text = str(text or "")
    if not text:
        return 0
    return gfx_5x7_width(text)


def _fit_gfx(text: str, width: int) -> str:
    fitted = str(text or "").upper()
    if width <= 0:
        return ""
    while fitted and gfx_5x7_width(fitted) > width:
        fitted = fitted[:-1].rstrip()
    return fitted


def _logo_image(url: str) -> Image.Image | None:
    url = str(url or "").strip()
    if not url:
        return None
    if url in _memory_logo:
        cached = _memory_logo[url]
        return None if cached is None else cached.copy()

    raw = _read_cached_logo(url)
    if raw is None:
        raw = _download_logo(url)
    if not raw:
        _memory_logo[url] = None
        return None

    try:
        with Image.open(BytesIO(raw)) as source:
            logo = source.convert("RGBA")
            logo.load()
    except (OSError, ValueError):
        _memory_logo[url] = None
        return None

    logo = _fit_mark(logo)
    if logo is None:
        _memory_logo[url] = None
        return None
    _memory_logo[url] = logo
    return logo.copy()


def _read_cached_logo(url: str) -> bytes | None:
    try:
        if (
            _LOGO_CACHE.is_file()
            and _LOGO_URL_CACHE.is_file()
            and _LOGO_URL_CACHE.read_text(encoding="utf-8").strip() == url
        ):
            return _LOGO_CACHE.read_bytes()
    except OSError:
        return None
    return None


def _download_logo(url: str) -> bytes | None:
    try:
        response = session().get(
            url,
            timeout=(3.05, 8),
            verify=CA_BUNDLE,
        )
    except OSError:
        return None
    if response.status_code >= 400 or not response.content:
        return None
    try:
        _LOGO_CACHE.write_bytes(response.content)
        _LOGO_URL_CACHE.write_text(url, encoding="utf-8")
    except OSError:
        pass
    return response.content


def _fit_mark(logo: Image.Image) -> Image.Image | None:
    if _has_white_background(logo):
        cleared = []
        for red, green, blue, alpha in logo.getdata():
            if alpha < 16 or (red > 235 and green > 235 and blue > 235):
                cleared.append((0, 0, 0, 0))
            else:
                cleared.append((red, green, blue, alpha))
        logo.putdata(cleared)
    else:
        logo = _lift_dark_logo(logo)

    bounds = logo.getbbox()
    if not bounds:
        return None
    logo = logo.crop(bounds)
    scale = min(
        MAX_LOGO_HEIGHT / logo.height,
        MAX_LOGO_WIDTH / logo.width,
    )
    size = (
        max(1, round(logo.width * scale)),
        max(1, round(logo.height * scale)),
    )
    return logo.resize(size, Image.Resampling.LANCZOS)


def _has_white_background(logo: Image.Image) -> bool:
    width, height = logo.size
    if width < 2 or height < 2:
        return False
    corners = (
        (0, 0),
        (width - 1, 0),
        (0, height - 1),
        (width - 1, height - 1),
    )
    white = 0
    for point in corners:
        red, green, blue, alpha = logo.getpixel(point)
        if alpha > 200 and red > 235 and green > 235 and blue > 235:
            white += 1
    return white >= 3


def _lift_dark_logo(logo: Image.Image) -> Image.Image:
    lifted = []
    for red, green, blue, alpha in logo.getdata():
        if alpha < 20:
            lifted.append((0, 0, 0, 0))
            continue
        if max(red, green, blue) < 80:
            lifted.append((40, 130, 220, alpha))
            continue
        lifted.append((red, green, blue, alpha))
    logo.putdata(lifted)
    return logo
