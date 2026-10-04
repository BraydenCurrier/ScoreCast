import time

from PIL import Image, ImageDraw
from common.logo_store import draw_logo

from common.config import PANEL_WIDTH, PANEL_HEIGHT
from common.fonts import print_gfx_5x7, gfx_5x7_width

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


def render_possession_alert(alert, now):
    if now is None:
        now = time.monotonic()

    return _render_alert_card(alert)
