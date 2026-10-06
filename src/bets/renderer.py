from __future__ import annotations

from PIL import Image, ImageDraw

from common.fonts import (
    gfx_5x7_width,
    get_4x5_width,
    print_4x5,
    print_4x5_right,
    print_gfx_5x7,
)
from mlb.colors import WHITE, YELLOW

from bets.catalog import STATUS_LIVE, STATUS_LOST, STATUS_PENDING, STATUS_WON
from bets.tracker import BetTicket


CARD_WIDTH = 148
CARD_HEIGHT = 32
BLACK = (0, 0, 0)
DIM = (150, 150, 156)
GREY = (88, 88, 94)
GREEN = (80, 220, 120)
RED = (255, 80, 80)
BAR = (40, 40, 46)
LIVE = (126, 227, 168)
HAIR = (36, 36, 40)


def _team_color(league: str, team: str):
    team = str(team or "").upper()
    try:
        if league == "nfl":
            from nfl.colors import team_color
            return team_color(team)
        if league == "cfb":
            from cfb.colors import team_color
            return team_color(team)
        from mlb.colors import team_color
        return team_color(team)
    except Exception:
        return WHITE


def _fit(text: str, max_width: int) -> str:
    value = str(text or "").upper()
    while value and get_4x5_width(value) > max_width:
        value = value[:-1]
    return value


def _status_color(status: str):
    if status == STATUS_WON:
        return GREEN
    if status == STATUS_LOST:
        return RED
    if status == STATUS_LIVE:
        return LIVE
    return GREY


def _leg_fields(leg) -> tuple[str, str, str, str, str]:
    status = str(leg[0] if leg else STATUS_PENDING)
    name = str(leg[1] if len(leg) > 1 else "")
    stat = str(leg[2] if len(leg) > 2 else "")
    chance = str(leg[3] if len(leg) > 3 else "")
    unit = str(leg[6] if len(leg) > 6 else "")
    return status, name, stat, chance, unit


def _draw_pip(draw, x, y, status: str):
    color = _status_color(status)
    if status in {STATUS_WON, STATUS_LOST, STATUS_LIVE}:
        draw.rectangle([x, y, x + 2, y + 2], fill=color)
    else:
        draw.rectangle([x, y, x + 2, y + 2], outline=GREY)


def _render_parlay(ticket: BetTicket) -> Image.Image:
    width = max(168, min(320, int(ticket.width or 176)))
    image = Image.new("RGB", (width, CARD_HEIGHT), BLACK)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 2, CARD_HEIGHT - 1], fill=GREY)

    print_4x5(draw, "PARLAY", 5, 1, DIM)
    legs = ticket.legs or ()
    count = len(legs)
    if count:
        print_4x5(draw, _fit(f"{count} LEG", 40), 42, 1, DIM)

    odds = str(ticket.clock or "")
    chance_text = ""
    if ticket.chance is not None:
        chance_text = f"{ticket.chance:.0f}%"
    right = width - 3
    if chance_text:
        print_4x5_right(draw, chance_text, right, 1, LIVE)
        right -= get_4x5_width(chance_text) + 5
    if odds:
        print_gfx_5x7(draw, odds[:8], right - gfx_5x7_width(odds[:8]), 0, YELLOW)

    pip_y = 9
    for index, leg in enumerate(legs[:8]):
        _draw_pip(draw, 5 + index * 5, pip_y, _leg_fields(leg)[0])
    if ticket.need:
        print_4x5(
            draw,
            _fit(str(ticket.need), 70),
            5 + min(count, 8) * 5 + 4,
            8,
            DIM,
        )
    draw.line([(5, 13), (width - 4, 13)], fill=HAIR)

    cols = 1 if count <= 3 else 2 if count <= 6 else 3
    col_w = max(52, (width - 8) // max(1, cols))
    rows = (count + cols - 1) // cols if count else 0
    ys = (16, 24) if rows <= 2 else (15, 21, 27)
    for index, leg in enumerate(legs):
        status, name, stat, chance, unit = _leg_fields(leg)
        row = index // cols
        if row >= len(ys):
            break
        col = index % cols
        x = 5 + col * col_w
        y = ys[row]
        name_color = DIM if status in {STATUS_WON, STATUS_LOST} else WHITE
        stat_color = _status_color(status) if status in {STATUS_WON, STATUS_LOST} else YELLOW
        _draw_pip(draw, x, y + 1, status)
        cell_right = x + col_w - 3
        if chance:
            print_4x5_right(draw, _fit(chance, 24), cell_right, y, LIVE)
            cell_right -= get_4x5_width(_fit(chance, 24)) + 4
        if unit:
            print_4x5_right(draw, unit, cell_right, y, DIM)
            cell_right -= get_4x5_width(unit) + 4
        cursor = x + 5
        name_text = _fit(name, max(20, cell_right - cursor - 36))
        print_4x5(draw, name_text, cursor, y, name_color)
        if name_text:
            cursor += get_4x5_width(name_text) + 4
        if stat:
            print_4x5(draw, _fit(stat, max(12, cell_right - cursor)), cursor, y, stat_color)
    return image


def render_bet_ticket(ticket: BetTicket) -> Image.Image:
    if getattr(ticket, "kind", "single") == "parlay":
        return _render_parlay(ticket)

    width = max(CARD_WIDTH, int(ticket.width or CARD_WIDTH))
    image = Image.new("RGB", (width, CARD_HEIGHT), BLACK)
    draw = ImageDraw.Draw(image)
    color = _team_color(ticket.league, ticket.team)
    draw.rectangle([0, 0, 2, CARD_HEIGHT - 1], fill=color)

    live = str(ticket.status or "").lower() == "live"
    badge = "LIVE" if live else "BET"
    print_4x5(draw, badge, 5, 1, LIVE if live else DIM)

    title = _fit(ticket.title, width - 58)
    print_gfx_5x7(draw, title[:14], 5, 8, color if ticket.team else WHITE)

    if ticket.chance is not None:
        print_4x5_right(draw, f"{ticket.chance:.0f}%", width - 3, 1, LIVE)

    print_4x5(draw, _fit(ticket.detail, width - 12), 5, 17, YELLOW)

    if ticket.progress is not None:
        bar_left = 5
        bar_right = width - 6
        draw.rectangle([bar_left, 23, bar_right, 25], fill=BAR)
        fill = RED if ticket.under else GREEN
        fill_w = int((bar_right - bar_left) * max(0.0, min(1.0, ticket.progress)))
        if fill_w > 0:
            draw.rectangle([bar_left, 23, bar_left + fill_w, 25], fill=fill)

    footer = " ".join(part for part in (ticket.clock, ticket.need) if part)
    if ticket.progress is None:
        print_4x5(
            draw,
            _fit(footer, width - 10),
            5,
            25,
            LIVE if live else DIM,
        )
    elif footer:
        print_4x5_right(
            draw,
            _fit(footer, width - 12),
            width - 3,
            26,
            LIVE if live else DIM,
        )
    return image


def render_bet_notice(notice: dict) -> Image.Image:
    image = Image.new("RGB", (384, 32), BLACK)
    draw = ImageDraw.Draw(image)
    title = str(notice.get("title") or "BET").upper()
    detail = str(notice.get("detail") or "").upper()
    print_gfx_5x7(draw, title[:22], 8, 4, YELLOW)
    if detail:
        print_4x5(draw, _fit(detail, 360), 8, 20, WHITE)
    return image


def render_game_strip_onto(image, draw, ticket, x, settings):
    card = render_bet_ticket(ticket)
    image.paste(card, (x, 0))
