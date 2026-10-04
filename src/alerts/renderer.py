import time

from PIL import Image, ImageDraw
from common.logo_store import draw_logo

from common.config import PANEL_WIDTH, PANEL_HEIGHT
from common.fonts import print_gfx_5x7, gfx_5x7_width
from alerts.models import CHANT_BLANK_SECONDS, CHANT_WORD_SECONDS

DISPLAY_WIDTH = PANEL_WIDTH
DISPLAY_HEIGHT = PANEL_HEIGHT
ALERT_BACKGROUND = (0, 0, 0)
ALERT_META = (180, 184, 192)
LOGO_SIZE = 30
TEXT_LEFT = 38
TEXT_RIGHT = DISPLAY_WIDTH - 38

TYPE_BADGES = {
    "TOUCHDOWN": "TD",
    "FIELD_GOAL": "FG",
    "REDZONE": "RED ZONE",
    "POSSESSION": "BALL",
    "HOME_RUN": "HR",
    "WIN": "WIN",
    "CLOSE_GAME": "CLOSE",
    "INTERCEPTION": "PICK",
    "SACK": "SACK",
    "FUMBLE": "FUMBLE",
    "SAFETY": "SAFETY",
    "TWO_POINT": "2-PT",
    "BIG_PLAY": "BIG PLAY",
}


def draw_team_logo(
    image,
    league,
    team_abbreviation,
    x_start,
    y_start,
):
    return draw_logo(
        destination=image,
        league=league,
        identifier=team_abbreviation,
        x=x_start,
        y=y_start,
    )


def _field_position_text(alert):
    side = str(alert.yardline_side or "").upper()
    number = int(alert.yardline_number or 0)
    team = str(alert.team or "").upper()

    if number == 50:
        return "50"

    if not 0 < number < 50:
        return ""

    if not side:
        return f"{number}"

    if side == team:
        return f"OWN {number}"

    return f"{side} {number}"


def _fit_5x7(text, max_width, ellipsis=False):
    text = str(text or "").upper().strip()

    if not text or max_width < 5:
        return ""

    if gfx_5x7_width(text) <= max_width:
        return text

    if ellipsis and gfx_5x7_width("...") <= max_width:
        trimmed = text

        while trimmed and gfx_5x7_width(trimmed + "...") > max_width:
            trimmed = trimmed[:-1]

        trimmed = trimmed.rstrip(" .-")

        if trimmed:
            return trimmed + "..."

        return "..."

    while text and gfx_5x7_width(text) > max_width:
        text = text[:-1].rstrip(" .-")

    return text


def _period_text(alert):
    clock = str(getattr(alert, "clock", "") or "").strip().upper()
    league = str(getattr(alert, "league", "") or "").lower()

    if league == "mlb":
        return clock

    if clock.startswith("Q") or clock in {"OT", "FINAL"}:
        return clock

    quarter = int(getattr(alert, "quarter", 0) or 0)

    if quarter >= 5:
        period = "OT"
    elif quarter > 0:
        period = f"Q{quarter}"
    else:
        period = ""

    if period and clock:
        return f"{period} {clock}"

    return period or clock


def _title_text(alert):
    if getattr(alert, "is_player_alert", False):
        return str(
            getattr(alert, "player_name", "")
            or alert.headline
            or "PLAYER"
        )

    return str(
        alert.headline
        or alert.alert_type
        or ""
    ).replace("_", " ")


def _badge_text(alert):
    if getattr(alert, "is_player_alert", False):
        return str(alert.detail or "").upper()

    alert_type = str(alert.alert_type or "").upper()
    field_position = _field_position_text(alert)

    if alert_type in {"TOUCHDOWN", "FIELD_GOAL", "REDZONE", "POSSESSION"}:
        return field_position or TYPE_BADGES.get(alert_type, "")

    if alert_type == "HOME_RUN":
        detail = str(alert.detail or "")
        if "GRAND SLAM" in detail:
            return "GRAND SLAM"
        if "SOLO" in detail:
            return "SOLO HR"
        return "HR"

    return TYPE_BADGES.get(alert_type, alert_type.replace("_", " "))


def _body_text(alert):
    play_text = str(getattr(alert, "play_text", "") or "").strip()

    if play_text:
        return play_text

    detail = str(alert.detail or "").strip()
    badge = _badge_text(alert)

    if detail and detail != badge:
        return detail

    return badge


def _render_alert_card(alert):
    image = Image.new(
        "RGB",
        (DISPLAY_WIDTH, DISPLAY_HEIGHT),
        ALERT_BACKGROUND,
    )
    draw = ImageDraw.Draw(image)

    draw.rectangle(
        (0, 0, 2, DISPLAY_HEIGHT - 1),
        fill=alert.accent,
    )

    logo_y = (DISPLAY_HEIGHT - LOGO_SIZE) // 2
    draw_team_logo(
        image,
        alert.league,
        alert.team,
        5,
        logo_y,
    )

    opponent = str(alert.opponent or "").upper()

    if opponent:
        draw_team_logo(
            image,
            alert.league,
            opponent,
            DISPLAY_WIDTH - LOGO_SIZE - 5,
            logo_y,
        )

    text_width = max(1, TEXT_RIGHT - TEXT_LEFT)
    title = _fit_5x7(_title_text(alert), text_width)
    badge = str(_badge_text(alert) or "").upper()
    badge_width = gfx_5x7_width(badge) if badge else 0

    if badge:
        title = _fit_5x7(
            _title_text(alert),
            max(12, text_width - badge_width - 8),
        )

    print_gfx_5x7(draw, title, TEXT_LEFT, 2, alert.accent)

    if badge:
        print_gfx_5x7(
            draw,
            badge,
            TEXT_RIGHT - badge_width,
            2,
            (255, 255, 255),
        )

    body = _fit_5x7(_body_text(alert), text_width, ellipsis=True)
    print_gfx_5x7(draw, body, TEXT_LEFT, 12, (255, 255, 255))

    away = str(getattr(alert, "away", "") or "").upper()
    home = str(getattr(alert, "home", "") or "").upper()
    away_score = int(getattr(alert, "away_score", 0) or 0)
    home_score = int(getattr(alert, "home_score", 0) or 0)
    period = _period_text(alert)

    score = ""

    if away and home:
        score = f"{away} {away_score}-{home_score} {home}"

    score = _fit_5x7(score, text_width // 2 + 24)
    period = _fit_5x7(period, text_width // 2)

    if score:
        print_gfx_5x7(draw, score, TEXT_LEFT, 23, ALERT_META)

    if period:
        print_gfx_5x7(
            draw,
            period,
            TEXT_RIGHT - gfx_5x7_width(period),
            23,
            ALERT_META,
        )

    return image


def _create_chant_frame(alert):
    image = Image.new(
        "RGB",
        (DISPLAY_WIDTH, DISPLAY_HEIGHT),
        ALERT_BACKGROUND,
    )
    draw = ImageDraw.Draw(image)

    draw.rectangle(
        (0, 0, 2, DISPLAY_HEIGHT - 1),
        fill=alert.accent,
    )

    logo_y = (DISPLAY_HEIGHT - LOGO_SIZE) // 2
    draw_team_logo(image, alert.league, alert.team, 5, logo_y)
    draw_team_logo(
        image,
        alert.league,
        alert.team,
        DISPLAY_WIDTH - LOGO_SIZE - 5,
        logo_y,
    )

    return image, draw


def _render_chant_frame(alert, chant_index):
    image, draw = _create_chant_frame(alert)
    words = alert.chant_words()
    chant_text = str(words[chant_index]).upper()

    text_left = LOGO_SIZE + 12
    text_right = DISPLAY_WIDTH - LOGO_SIZE - 12
    available_width = max(1, text_right - text_left)
    text_width = max(1, gfx_5x7_width(chant_text))
    source = Image.new("RGB", (text_width, 7), ALERT_BACKGROUND)
    source_draw = ImageDraw.Draw(source)
    print_gfx_5x7(source_draw, chant_text, 0, 0, alert.accent)

    scale_x = max(1, available_width // source.width)
    scale_y = max(1, DISPLAY_HEIGHT // source.height)
    scale = max(1, min(scale_x, scale_y))

    scaled_text = source.resize(
        (source.width * scale, source.height * scale),
        Image.Resampling.NEAREST,
    )
    text_x = text_left + (available_width - scaled_text.width) // 2
    text_y = (DISPLAY_HEIGHT - scaled_text.height) // 2
    image.paste(scaled_text, (text_x, text_y))

    return image


def render_possession_alert(alert, now):
    if now is None:
        now = time.monotonic()

    elapsed = max(0.0, now - alert.created_at)
    words = alert.chant_words()

    if words:
        current_time = 0.0

        for chant_index, _word in enumerate(words):
            word_end = current_time + CHANT_WORD_SECONDS

            if elapsed < word_end:
                return _render_chant_frame(alert, chant_index)

            current_time = word_end
            blank_end = current_time + CHANT_BLANK_SECONDS

            if elapsed < blank_end:
                image, _ = _create_chant_frame(alert)
                return image

            current_time = blank_end

    return _render_alert_card(alert)
