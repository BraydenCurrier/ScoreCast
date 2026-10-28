from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from common.fonts import (
    get_4x5_width,
    gfx_5x7_width,
    print_4x5,
    print_gfx_5x7,
)
from nfl.colors import team_color


HEAD_SIZE = 30
HEAD_X = 1
HEAD_Y = 1
TEXT_X = 36
NAME_Y = 1
META_Y = 10
HERO_Y = 16
DETAIL_Y = 25
WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)
GREY = (150, 150, 150)
LIVE = (255, 45, 35)
ON_FIELD = (70, 220, 90)
MIN_TEXT = 40
RIGHT_PAD = 4
STAT_GAP = 6
COLUMN_GAP = 8


def card_width(game):
    return TEXT_X + _content_width(game) + RIGHT_PAD


def render_game_strip_onto(image, draw, game, offset_x, settings):
    color = team_color(getattr(game, "team", ""))
    _draw_portrait(image, draw, game, offset_x, color)
    text_x = offset_x + TEXT_X
    stats = tuple(getattr(game, "stats", ()) or ())
    content = _content_width(game)
    status_width = _status_width(game)
    name_room = content - (COLUMN_GAP + status_width if status_width else 0)
    name = _fit_5x7(_display_name(game), max(8, name_room))

    if name:
        print_gfx_5x7(draw, name, text_x, NAME_Y, WHITE)

    _draw_meta(draw, game, text_x, color)
    _draw_status(draw, game, text_x + content)
    _draw_stats(draw, stats, text_x)


def _draw_portrait(image, draw, game, offset_x, color):
    plate = Image.new("RGBA", (HEAD_SIZE, HEAD_SIZE), (0, 0, 0, 0))
    photo = _load_head(getattr(game, "headshot", ""))

    if photo is not None:
        fitted = photo.resize(
            (HEAD_SIZE, HEAD_SIZE),
            Image.Resampling.LANCZOS,
        )
        plate.paste(fitted, (0, 0), fitted)
    else:
        ImageDraw.Draw(plate).rectangle(
            (0, 0, HEAD_SIZE - 1, HEAD_SIZE - 1),
            fill=color,
        )

    image.paste(
        plate,
        (offset_x + HEAD_X, HEAD_Y),
        plate,
    )

    if photo is not None:
        return

    initials = _initials(game)

    if not initials:
        return

    width = get_4x5_width(initials)
    print_4x5(
        draw,
        initials,
        offset_x + HEAD_X + max(0, (HEAD_SIZE - width) // 2),
        HEAD_Y + (HEAD_SIZE - 5) // 2,
        WHITE,
    )


def _content_width(game):
    stats = tuple(getattr(game, "stats", ()) or ())
    identity = max(
        gfx_5x7_width(_display_name(game)),
        _meta_width(game),
    )
    status_width = _status_width(game)
    header = identity

    if status_width:
        header += COLUMN_GAP + status_width

    stat_width = max(
        (_row_width(row) for row in _stat_rows(stats)),
        default=0,
    )
    return max(header, stat_width, MIN_TEXT)


def _status_marks(game):
    state = str(getattr(game, "game_state", "") or "")
    field = str(getattr(game, "on_field", "") or "")

    if state == "live":
        marks = [("LIVE", LIVE)]
        if field == "on":
            marks.append(("ON", ON_FIELD))
        elif field == "off":
            marks.append(("OFF", GREY))
        return marks

    if state == "final":
        return [("FINAL", GREY)]

    return []


def _status_width(game):
    marks = _status_marks(game)

    if not marks:
        return 0

    return max(get_4x5_width(text) for text, _color in marks)


def _draw_status(draw, game, right):
    marks = _status_marks(game)

    if not marks:
        return

    text, color = marks[0]
    print_4x5(draw, text, right - get_4x5_width(text), NAME_Y + 1, color)

    if len(marks) > 1:
        text, color = marks[1]
        print_4x5(draw, text, right - get_4x5_width(text), META_Y, color)


def _stat_rows(stats):
    blocks = []

    for index, pair in enumerate(tuple(stats or ())):
        value, label = pair
        large = index == 0
        blocks.append((
            str(value),
            str(label),
            large,
            _block_width(value, label, large),
        ))

    return _support_rows(blocks)


def _support_rows(blocks):
    if len(blocks) <= 1:
        return [blocks] if blocks else []

    one_row = _row_width(blocks)
    best = None
    best_score = None

    for split in range(1, len(blocks)):
        rows = [blocks[:split], blocks[split:]]
        score = max(_row_width(row) for row in rows)
        if best_score is None or score < best_score:
            best_score = score
            best = rows

    if one_row <= best_score:
        return [blocks]

    return best


def _block_width(value, label, large=False):
    width = gfx_5x7_width(value) if large else get_4x5_width(value)

    if label:
        width += 4 + get_4x5_width(label)

    return width


def _row_width(blocks):
    if not blocks:
        return 0

    return sum(block[3] for block in blocks) + STAT_GAP * (len(blocks) - 1)


def _draw_stats(draw, stats, text_x):
    for index, blocks in enumerate(_stat_rows(stats)):
        cursor = text_x
        on_first = index == 0

        for block_index, (value, label, large, width) in enumerate(blocks):
            if block_index:
                cursor += STAT_GAP

            if large:
                print_gfx_5x7(draw, value, cursor, HERO_Y, YELLOW)
                label_x = cursor + gfx_5x7_width(value) + 4
                label_y = HERO_Y + 2
            else:
                number_y = HERO_Y + 2 if on_first else DETAIL_Y
                print_4x5(draw, value, cursor, number_y, YELLOW)
                label_x = cursor + get_4x5_width(value) + 4
                label_y = number_y

            if label:
                print_4x5(draw, label, label_x, label_y, GREY)

            cursor += width


def _meta_parts(game):
    team = str(getattr(game, "team", "") or "").upper()
    detail = str(getattr(game, "opponent", "") or "").strip().upper()

    if team and detail.startswith(team + " "):
        detail = detail[len(team) + 1:].strip()

    if not detail:
        detail = str(getattr(game, "position", "") or "").upper()

    return team, detail


def _meta_width(game):
    team, detail = _meta_parts(game)
    width = 0

    if team:
        width += get_4x5_width(team)
    if team and detail:
        width += 4
    if detail:
        width += get_4x5_width(detail)

    return width


def _draw_meta(draw, game, text_x, color):
    team, detail = _meta_parts(game)
    cursor = text_x

    if team:
        print_4x5(draw, team, cursor, META_Y, color)
        cursor += get_4x5_width(team) + 4

    if detail:
        print_4x5(draw, detail, cursor, META_Y, GREY)


def _display_name(game):
    last = str(getattr(game, "last", "") or "").strip()

    if len(last) >= 2:
        return last.upper()

    return str(getattr(game, "name", "") or last).strip().upper()


def _initials(game):
    first = str(getattr(game, "first", "") or "").strip()
    last = str(getattr(game, "last", "") or "").strip()

    if first and last:
        return (first[0] + last[0]).upper()

    parts = str(getattr(game, "name", "") or "").split()

    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()

    return str(getattr(game, "name", "") or "")[:2].upper()


def _fit_5x7(text, max_width):
    text = str(text or "").upper()

    while text and gfx_5x7_width(text) > max_width:
        text = text[:-1]

    return text


def crop_portrait(image):
    """Square crop biased toward the face.

    ESPN headshots are wide busts. A centered square keeps the
    proportions, and a slight zoom drops the lower chest so the
    face fills a 30px tile.
    """
    source = image.convert("RGBA")
    width, height = source.size

    if width == height:
        return source

    side = min(width, height)
    zoom = max(8, int(side * 0.78))
    left = max(0, (width - zoom) // 2)

    if height > width:
        top = max(0, int((height - zoom) * 0.08))
    else:
        top = max(0, int(height * 0.04))

    if top + zoom > height:
        top = max(0, height - zoom)
    if left + zoom > width:
        left = max(0, width - zoom)

    return source.crop((left, top, left + zoom, top + zoom))


@lru_cache(maxsize=64)
def _load_head(path):
    if not path or not Path(path).is_file():
        return None

    try:
        with Image.open(path) as source:
            image = crop_portrait(source)
            if max(image.size) > 96:
                image.thumbnail((96, 96), Image.Resampling.LANCZOS)
            return image.copy()
    except Exception:
        return None
