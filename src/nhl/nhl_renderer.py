from PIL import Image

from common.broadcast import resolve_broadcast_identifier
from common.fonts import (
    get_3x5_width,
    get_4x5_width,
    gfx_5x7_width,
    print_3x5,
    print_3x5_right,
    print_4x5,
    print_4x5_centered,
    print_4x5_right,
    print_clock,
    print_gfx_5x7,
)
from common.logo_store import draw_logo, get_selected_logo_variant, load_logo
from nhl.colors import team_color

WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)
GREY = (80, 80, 80)
ORANGE = (255, 130, 40)

LOGO_SIZE = 30
CARD_WIDTH = 96
GAME_GAP = 5
GAME_WIDTH = LOGO_SIZE + CARD_WIDTH + LOGO_SIZE

PAD_CX = CARD_WIDTH // 2
NAME_Y = 2
CLOCK_Y = 9
SCORE_Y = 16
AWAY_GOALIE_Y = 19
HOME_GOALIE_Y = 25
DATE_Y = 11
RECORD_Y = 22


def _status(game):
    return str(game.status or "").strip().upper()


def is_live(game):
    return _status(game) in {
        "LIVE",
        "IN PROGRESS",
        "OVERTIME",
    }


def is_intermission(game):
    return bool(game.intermission) or _status(game) == "INTERMISSION"


def is_shootout(game):
    return bool(game.shootout) or _status(game) == "SHOOTOUT"


def is_final(game):
    return "FINAL" in _status(game)


def is_scheduled(game):
    return _status(game) in {"SCHEDULED", "PRE", "PREVIEW", "STATUS_SCHEDULED"}


def period_label(game):
    if is_shootout(game):
        return "SO"
    if game.overtime or int(game.period or 0) > 3:
        return "OT"
    labels = {1: "1ST", 2: "2ND", 3: "3RD"}
    period = int(game.period or 0)
    return labels.get(period, "")


def final_label(game):
    if game.shootout:
        return "F-SO"
    if game.overtime:
        return "F-OT"
    return "FINAL"


def _record_text(wins, losses, ot_losses):
    return f"{int(wins or 0)}-{int(losses or 0)}-{int(ot_losses or 0)}"


def draw_team_logo(image, team_abbreviation, x_start, y_start, settings):
    variant = get_selected_logo_variant(
        settings,
        "nhl",
        team_abbreviation,
    )
    return draw_logo(
        destination=image,
        league="nhl",
        identifier=team_abbreviation,
        x=x_start,
        y=y_start,
        variant=variant,
    )


def _draw_abbrs(draw, game, offset_x):
    print_gfx_5x7(draw, game.away, 2 + offset_x, NAME_Y, team_color(game.away))
    home_width = gfx_5x7_width(game.home)
    print_gfx_5x7(
        draw,
        game.home,
        CARD_WIDTH - 2 - home_width + offset_x,
        NAME_Y,
        team_color(game.home),
    )


def _draw_scores(draw, game, offset_x):
    away = str(game.away_score)
    home = str(game.home_score)
    print_gfx_5x7(draw, away, 2 + offset_x, SCORE_Y, YELLOW)
    print_gfx_5x7(
        draw,
        home,
        CARD_WIDTH - 2 - gfx_5x7_width(home) + offset_x,
        SCORE_Y,
        YELLOW,
    )


def _fit_goalie_name(name, save_pct, max_width):
    name = " ".join(str(name or "").upper().replace(".", " ").split())
    save_pct = str(save_pct or "").strip()
    parts = name.split()
    if len(parts) >= 2 and len(parts[0]) == 1:
        parts = parts[1:]
    last = " ".join(parts)
    if not last:
        return "", save_pct if get_3x5_width(save_pct) <= max_width else ""

    def fits(surname):
        width = get_4x5_width(surname)
        if save_pct:
            width += 2 + get_3x5_width(save_pct)
        return width <= max_width

    if fits(last):
        return last, save_pct

    while last and not fits(last):
        last = last[:-1].strip()
    if last and fits(last):
        return last, save_pct
    return "", ""


def _draw_goalie_line(draw, game, offset_x, y, side):
    if side == "away":
        name = game.away_goalie
        save_pct = game.away_save_pct
        color = team_color(game.away)
    else:
        name = game.home_goalie
        save_pct = game.home_save_pct
        color = team_color(game.home)

    max_width = CARD_WIDTH - 4
    shown, pct = _fit_goalie_name(name, save_pct, max_width)
    if not shown and not pct:
        return

    name_width = get_4x5_width(shown) if shown else 0
    pct_width = get_3x5_width(pct) if pct else 0
    gap = 2 if shown and pct else 0
    total = name_width + gap + pct_width
    start = offset_x + (CARD_WIDTH - total) // 2
    if shown:
        print_4x5(draw, shown, start, y, color)
    if pct:
        print_3x5(draw, pct, start + name_width + gap, y, GREY)


def _draw_goalies(draw, game, offset_x):
    _draw_goalie_line(draw, game, offset_x, AWAY_GOALIE_Y, "away")
    _draw_goalie_line(draw, game, offset_x, HOME_GOALIE_Y, "home")


def _draw_puck(draw, x, y):
    draw.point((x + 1, y), fill=WHITE)
    draw.line([(x, y + 1), (x + 2, y + 1)], fill=WHITE)
    draw.point((x + 1, y + 2), fill=WHITE)


def _draw_situation_marks(draw, game, offset_x):
    possession = str(game.possession or "").upper()
    power_play = str(game.power_play or "").upper()

    if power_play == str(game.away).upper():
        print_4x5(draw, "PP", 2 + offset_x, CLOCK_Y + 1, ORANGE)
    elif possession == str(game.away).upper() and not is_intermission(game):
        _draw_puck(draw, 2 + offset_x, CLOCK_Y + 1)

    if power_play == str(game.home).upper():
        print_4x5_right(
            draw,
            "PP",
            CARD_WIDTH - 2 + offset_x,
            CLOCK_Y + 1,
            ORANGE,
        )
    elif possession == str(game.home).upper() and not is_intermission(game):
        _draw_puck(draw, CARD_WIDTH - 5 + offset_x, CLOCK_Y + 1)


def _draw_broadcast(image, broadcast, offset_x, away_record, home_record, settings):
    identifier = resolve_broadcast_identifier(broadcast)
    if not identifier:
        return

    try:
        variant = get_selected_logo_variant(settings or {}, "broadcast", identifier)
        logo = load_logo(league="broadcast", identifier=identifier, variant=variant)
    except (FileNotFoundError, ValueError, OSError, KeyError):
        return

    left_end = 2 + get_3x5_width(away_record)
    right_start = CARD_WIDTH - 2 - get_3x5_width(home_record)
    max_w = right_start - left_end - 2
    if max_w < 8:
        return

    center_y = RECORD_Y + 2
    # One clear row under the date, then the mark can hang through the record line.
    max_h = (center_y - (DATE_Y + 6)) * 2 + 1
    scale = min(max_w / logo.width, max_h / logo.height, 1)
    if scale < 1:
        logo = logo.resize(
            (max(1, round(logo.width * scale)), max(1, round(logo.height * scale))),
            Image.Resampling.NEAREST,
        )

    image.paste(
        logo,
        (
            PAD_CX + offset_x - logo.width // 2,
            center_y - logo.height // 2,
        ),
        logo,
    )


def _draw_pregame(image, draw, game, offset_x, settings):
    time_width = get_3x5_width(game.start_time)
    print_3x5(
        draw,
        game.start_time,
        (CARD_WIDTH - time_width) // 2 + offset_x,
        NAME_Y,
        YELLOW,
    )
    print_4x5_centered(draw, game.date, PAD_CX + offset_x, DATE_Y, WHITE)
    away_record = _record_text(game.away_wins, game.away_losses, game.away_ot_losses)
    home_record = _record_text(game.home_wins, game.home_losses, game.home_ot_losses)
    if game.broadcast:
        _draw_broadcast(image, game.broadcast, offset_x, away_record, home_record, settings)
    print_3x5(draw, away_record, 2 + offset_x, RECORD_Y, GREY)
    print_3x5_right(draw, home_record, CARD_WIDTH - 2 + offset_x, RECORD_Y, GREY)


def render_hockey_game_onto(image, draw, game, offset_x, settings):
    _draw_abbrs(draw, game, offset_x)

    if is_scheduled(game):
        _draw_pregame(image, draw, game, offset_x, settings)
        return

    _draw_scores(draw, game, offset_x)
    _draw_goalies(draw, game, offset_x)

    if is_final(game):
        print_4x5_centered(
            draw,
            final_label(game),
            PAD_CX + offset_x,
            CLOCK_Y,
            YELLOW,
        )
        return

    label = period_label(game)
    if label:
        print_4x5_centered(draw, label, PAD_CX + offset_x, NAME_Y, YELLOW)

    if is_intermission(game):
        print_4x5_centered(draw, "INT", PAD_CX + offset_x, CLOCK_Y, YELLOW)
        return

    if is_shootout(game):
        if game.away_so_goals is not None and game.home_so_goals is not None:
            print_4x5_centered(
                draw,
                f"{game.away_so_goals}-{game.home_so_goals}",
                PAD_CX + offset_x,
                CLOCK_Y,
                YELLOW,
            )
        return

    if game.clock:
        print_clock(draw, game.clock, PAD_CX + offset_x, CLOCK_Y, YELLOW)

    _draw_situation_marks(draw, game, offset_x)


def render_game_strip_onto(image, draw, game, offset_x, settings):
    draw_team_logo(image, game.away, offset_x, 1, settings)
    render_hockey_game_onto(
        image,
        draw,
        game,
        offset_x + LOGO_SIZE,
        settings,
    )
    draw_team_logo(
        image,
        game.home,
        offset_x + LOGO_SIZE + CARD_WIDTH,
        1,
        settings,
    )
