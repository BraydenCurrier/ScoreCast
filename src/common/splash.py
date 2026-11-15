"""Idle GameLine screen for an empty scoreboard and for updates."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

from common.clock_themes import active_theme, clock_palette, paint_theme, theme_signature
from common.countdown import countdown_line
from common.fonts import (
    gfx_5x7_width,
    get_4x5_width,
    print_4x5,
    print_4x5_centered,
    print_gfx_5x7,
    print_gfx_5x7_centered,
    print_gfx_7x11,
)
from common.timezone import clock_face, get_local_timezone
from common.weather import standby_weather


NAVY = (11, 17, 32)
BLUE = (37, 99, 235)
CYAN = (0, 212, 255)
WHITE = (248, 250, 252)
MUTED = (148, 163, 184)
BAR_OFF = (32, 48, 72)

# How often the idle screen re-reads the clock. The picture itself
# only changes when the second, date, or signal bars change.
STANDBY_REFRESH_SECONDS = 0.05
LINK_REFRESH_SECONDS = 15.0
# How long each live score stays on the line under the clock.
LIVE_HOLD_SECONDS = 4.0

_LEAGUE_NAMES = {
    "FootballGame": "NFL",
    "CollegeFootballGame": "CFB",
    "BasketballGame": "NBA",
    "HockeyGame": "NHL",
    "BaseballGame": "MLB",
}
_QUIET_STATUSES = {
    "",
    "SCHEDULED",
    "STATUS_SCHEDULED",
    "PRE",
    "PREVIEW",
    "PRE_GAME",
    "STATUS_PREVIEW",
    "STATUS_PRE_GAME",
    "FINAL",
    "STATUS_FINAL",
    "STATUS_FULL_TIME",
    "FULL_TIME",
    "CLOSED",
    "COMPLETE",
    "COMPLETED",
    "POSTPONED",
    "STATUS_POSTPONED",
    "DELAYED",
    "STATUS_DELAYED",
    "CANCELED",
    "CANCELLED",
    "STATUS_CANCELED",
    "STATUS_CANCELLED",
    "ABANDONED",
    "STATUS_ABANDONED",
    "SUSPENDED",
    "STATUS_SUSPENDED",
    "QUOTE",
    "TBD",
    "IF_NECESSARY",
    "STATUS_IF_NECESSARY",
}

_BAR_HEIGHTS = (3, 6, 8, 11)
_BAR_PITCH = 3
_SIGNAL_WIDTH = _BAR_PITCH * (len(_BAR_HEIGHTS) - 1) + 2

_splash_cache: dict[tuple, Image.Image] = {}
_standby_cache: dict[str, object] = {
    "image": None,
    "key": None,
    "checked_at": 0.0,
}
_zone_cache: dict[str, object] = {"zone": None, "at": 0.0}
_link_cache: dict[str, object] = {
    "bars": 0,
    "kind": "off",
    "at": 0.0,
}
_theme_cache: dict[str, object] = {"theme": None, "at": 0.0}


def render_idle_splash(width, height, caption="", games=None):
    """Screen shown when the scoreboard has nothing to scroll.

    A caption (used while scores are updating) keeps the centered
    wordmark. The empty board shows the clock, date, and link status,
    with weather or live games on a line under the clock.
    """
    caption = str(caption or "").strip().upper()
    if caption:
        return _render_caption_splash(width, height, caption)
    return _render_standby(width, height, games)


def _render_caption_splash(width, height, caption):
    cache_key = (width, height, caption)
    cached = _splash_cache.get(cache_key)
    if cached is not None:
        return cached

    image = Image.new("RGB", (width, height), NAVY)
    draw = ImageDraw.Draw(image)

    word = "GAMELINE"
    word_width = gfx_5x7_width(word)
    center_x = width // 2
    text_y = 7
    caption_y = 19
    line_pad = 10
    line_left = center_x - word_width // 2 - line_pad
    line_right = center_x + (word_width + 1) // 2 + line_pad

    draw.line(
        [(line_left, text_y - 4), (line_right, text_y - 4)],
        fill=CYAN,
    )
    print_gfx_5x7_centered(draw, word, center_x, text_y, BLUE)
    print_4x5_centered(draw, caption, center_x, caption_y, CYAN)

    _splash_cache[cache_key] = image
    return image


def _live_slides(games):
    slides = []
    for game in games or ():
        slide = _live_slide(game)
        if slide is not None:
            slides.append(slide)
    slides.sort(key=lambda slide: (slide[0], slide[1], slide[2]))
    return slides


def _live_slide(game):
    league = _league_label(game)
    away = _team_abbr(getattr(game, "away_abbrev", "") or getattr(game, "away", ""))
    home = _team_abbr(getattr(game, "home_abbrev", "") or getattr(game, "home", ""))
    if not league or not away or not home or not _is_live(game):
        return None
    try:
        away_points = float(getattr(game, "away_score", 0) or 0)
        home_points = float(getattr(game, "home_score", 0) or 0)
    except (TypeError, ValueError):
        return None
    return (
        league,
        away,
        home,
        away_points,
        home_points,
        _format_score(away_points),
        _format_score(home_points),
        _situation(game),
    )


def _league_label(game):
    name = game.__class__.__name__
    if name == "SoccerGame":
        short = str(getattr(game, "league_short", "") or "")
        short = "".join(char for char in short.upper() if char.isalnum())[:8]
        return short or "SOCCER"
    return _LEAGUE_NAMES.get(name, "")


def _team_abbr(value):
    text = "".join(char for char in str(value or "").upper() if char.isalnum())
    return text[:4]


def _is_live(game):
    status = str(getattr(game, "status", "") or "").strip().upper().replace(" ", "_")
    return status not in _QUIET_STATUSES


def _format_score(value):
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}"


def _situation(game):
    """Quarter and clock, hockey period and clock, or the soccer match clock."""
    name = game.__class__.__name__
    clock = _clock_text(getattr(game, "clock", ""))
    status = str(getattr(game, "status", "") or "").strip().upper().replace(" ", "_")
    if "HALF" in status:
        return "HT"

    if name in {"FootballGame", "CollegeFootballGame", "BasketballGame"}:
        return _join_situation(_quarter_label(getattr(game, "quarter", 0)), clock)

    if name == "HockeyGame":
        return _join_situation(_period_label(game, status), clock)

    if name == "SoccerGame":
        return clock

    return ""


def _quarter_label(quarter):
    try:
        quarter = int(quarter or 0)
    except (TypeError, ValueError):
        return ""
    if quarter >= 6:
        return f"{quarter - 4}OT"
    if quarter == 5:
        return "OT"
    if quarter >= 1:
        return f"Q{quarter}"
    return ""


def _period_label(game, status):
    if getattr(game, "shootout", False) or status == "SHOOTOUT":
        return "SO"
    if getattr(game, "intermission", False) or status == "INTERMISSION":
        return "INT"
    try:
        period = int(getattr(game, "period", 0) or 0)
    except (TypeError, ValueError):
        period = 0
    if getattr(game, "overtime", False) or period > 3:
        return "OT"
    if period >= 1:
        return f"P{period}"
    return ""


def _clock_text(value):
    text = str(value or "").strip().upper().replace(" ", "")
    cleaned = "".join(
        char for char in text if char.isdigit() or char in ":+."
    )
    if cleaned in {"", "0"}:
        return ""
    return cleaned


def _join_situation(label, clock):
    if label and clock:
        return f"{label} {clock}"
    return label or clock


def _standby_layers(games, weather, countdown):
    """What sits above the clock, and what sits under it.

    A countdown owns the line above the time. Weather uses that line
    only while a live score is under the clock and no countdown is
    set. A countdown together with a live score leaves weather off.
    """
    bottom = _bottom_item(games)
    live = bool(bottom and bottom[0] == "game")
    if countdown:
        above = ("countdown", countdown)
        if not live and bottom is None and weather:
            bottom = ("weather", weather)
    elif live and weather:
        above = ("weather", weather)
    else:
        above = None
        if bottom is None and weather:
            bottom = ("weather", weather)
    return above, bottom


def _bottom_item(games):
    """The line under the clock. Live games take turns there.

    Weather does not join that rotation. It sits above the clock
    while a live score is showing, and under the clock when the
    board is quiet. A game countdown takes the upper line instead.
    """
    slides = _live_slides(games)
    if not slides:
        return None
    if len(slides) == 1:
        return ("game", slides[0])
    index = int(time.monotonic() // LIVE_HOLD_SECONDS) % len(slides)
    return ("game", slides[index])


def _render_standby(width, height, games=None):
    now_mono = time.monotonic()
    cached_image = _standby_cache["image"]
    if (
        isinstance(cached_image, Image.Image)
        and cached_image.size == (width, height)
        and now_mono - float(_standby_cache["checked_at"])
        < STANDBY_REFRESH_SECONDS
    ):
        return cached_image

    _standby_cache["checked_at"] = now_mono
    clock = datetime.now(_display_zone())
    time_text, period = clock_face(clock, seconds=True)
    bars, kind = _link_snapshot()
    weather = standby_weather()
    countdown = countdown_line(games)
    above, bottom = _standby_layers(games, weather, countdown)
    theme = _standby_theme()
    # Ten frames a second is enough for snow on this panel, and it
    # keeps the Pi from repainting the clock on every refresh.
    frame = int(now_mono * 10) if theme else 0
    key = (
        width,
        height,
        time_text,
        period,
        bars,
        kind,
        bottom,
        above,
        theme_signature(theme),
        frame,
    )
    if key == _standby_cache["key"] and isinstance(cached_image, Image.Image):
        return cached_image

    image = _draw_standby(
        width,
        height,
        clock,
        bars,
        bottom,
        above,
        time_text,
        period,
        theme=theme,
        phase=frame / 10 if theme else None,
    )
    _standby_cache["key"] = key
    _standby_cache["image"] = image
    return image


def _draw_standby(
    width,
    height,
    clock,
    bars,
    bottom=None,
    above=None,
    time_text="",
    period="",
    theme=None,
    phase=None,
):
    image = Image.new("RGB", (width, height), NAVY)
    if theme:
        when = time.monotonic() if phase is None else float(phase)
        paint_theme(image, theme, when)
    draw = ImageDraw.Draw(image)

    date_text = clock.strftime("%a %b %-d").upper()

    clock_y = max(0, (height - 11) // 2)
    center_y = clock_y + 5

    colors = _theme_colors(theme)
    ink = colors["ink"] if colors else None
    mark = colors["mark"] if colors else None
    margin = 14 if width >= 320 else 6
    mark_right = _draw_mark(
        draw,
        margin,
        center_y,
        text=mark or BLUE,
        rule=mark or CYAN,
    )

    time_width = _clock_width(time_text)
    period_width = get_4x5_width(period) if period else 0
    group_gap = 5 if period else 0
    group_width = time_width + group_gap + period_width
    group_x = (width - group_width) // 2
    min_group_x = mark_right + 12
    if group_x < min_group_x:
        group_x = min_group_x

    _draw_clock(
        draw,
        time_text,
        group_x,
        clock_y,
        ink or WHITE,
        colon=ink or CYAN,
    )
    if period:
        print_4x5(
            draw,
            period,
            group_x + time_width + group_gap,
            clock_y,
            ink or MUTED,
        )
    center_x = group_x + group_width // 2
    if above is not None:
        kind, payload = above
        if kind == "countdown":
            _draw_countdown_line(
                draw,
                payload,
                center_x,
                clock_y,
                width,
                colors=colors,
            )
        else:
            _draw_weather_line(
                draw,
                payload,
                center_x,
                clock_y,
                height,
                width,
                y=max(0, clock_y - 8),
                colors=colors,
            )
    if bottom is not None:
        kind, payload = bottom
        if kind == "weather":
            _draw_weather_line(
                draw,
                payload,
                center_x,
                clock_y,
                height,
                width,
                colors=colors,
            )
        else:
            _draw_live_line(
                draw,
                payload,
                center_x,
                clock_y,
                height,
                width,
                colors=colors,
            )

    date_width = get_4x5_width(date_text)
    signal_x = width - margin - _SIGNAL_WIDTH
    date_x = signal_x - 10 - date_width
    date_y = clock_y + (11 - 5) // 2
    if date_x > group_x + group_width + 8:
        print_4x5(
            draw,
            date_text,
            date_x,
            date_y,
            colors["soft"] if colors else MUTED,
        )
        _draw_signal(
            draw,
            signal_x,
            clock_y,
            bars,
            on=mark or CYAN,
            off=colors["dim"] if colors else BAR_OFF,
        )

    return image


def _theme_colors(theme):
    """Main color for the time, alternate color for the rest of the clock."""
    return clock_palette(theme)


def _draw_countdown_line(draw, countdown, center_x, clock_y, width, colors=None):
    teams, remaining = countdown
    team_color = colors["mark"] if colors else MUTED
    time_color = colors["ink"] if colors else WHITE
    parts = []
    if teams:
        parts.append((str(teams), team_color))
    if remaining:
        parts.append((str(remaining), time_color))
    if not parts:
        return
    gap = 6
    widths = [get_4x5_width(text) for text, _color in parts]
    total = sum(widths) + gap * (len(parts) - 1)
    x = max(2, center_x - total // 2)
    if x + total > width - 2:
        x = max(2, width - 2 - total)
    y = max(0, clock_y - 8)
    for text, color in parts:
        print_4x5(draw, text, x, y, color)
        x += get_4x5_width(text) + gap


def _draw_weather_line(draw, weather, center_x, clock_y, height, width, y=None, colors=None):
    place, temperature, condition = weather
    place_color = colors["soft"] if colors else MUTED
    temp_color = colors["ink"] if colors else CYAN
    condition_color = colors["mark"] if colors else WHITE
    parts = []
    if place:
        parts.append((place, place_color))
    parts.append((f"{temperature}°", temp_color))
    if condition:
        parts.append((condition, condition_color))
    gap = 6
    widths = [get_4x5_width(text) for text, _color in parts]
    total = sum(widths) + gap * (len(parts) - 1)
    if place and total > width - 4:
        parts = parts[1:]
        widths = widths[1:]
        total = sum(widths) + gap * (max(0, len(parts) - 1))
    x = max(2, center_x - total // 2)
    if x + total > width - 2:
        x = max(2, width - 2 - total)
    if y is None:
        y = min(clock_y + 14, height - 5)
    for text, color in parts:
        print_4x5(draw, text, x, y, color)
        x += get_4x5_width(text) + gap


def _draw_live_line(draw, slide, center_x, clock_y, height, width, colors=None):
    league, away, home = slide[0], slide[1], slide[2]
    away_text, home_text = slide[5], slide[6]
    situation = slide[7] if len(slide) > 7 else ""
    score = f"{away} {away_text}  {home} {home_text}"
    league_width = get_4x5_width(league)
    score_width = get_4x5_width(score)
    situation_width = get_4x5_width(situation) if situation else 0
    gap = 6
    total = league_width + gap + score_width
    if situation:
        total += gap + situation_width
    x = center_x - total // 2
    if x < 2:
        x = 2
    if x + total > width - 2:
        x = max(2, width - 2 - total)
    y = min(clock_y + 14, height - 5)
    league_color = colors["mark"] if colors else CYAN
    score_color = colors["ink"] if colors else WHITE
    situation_color = colors["soft"] if colors else MUTED
    print_4x5(draw, league, x, y, league_color)
    score_x = x + league_width + gap
    print_4x5(draw, score, score_x, y, score_color)
    if situation:
        print_4x5(draw, situation, score_x + score_width + gap, y, situation_color)


def _draw_mark(draw, x, center_y, text=BLUE, rule=CYAN):
    word = "GAMELINE"
    word_width = gfx_5x7_width(word)
    text_y = center_y - 3
    line_pad = 8
    line_left = x
    line_right = x + line_pad + word_width + line_pad
    draw.line(
        [(line_left, text_y - 4), (line_right, text_y - 4)],
        fill=rule,
    )
    print_gfx_5x7(draw, word, x + line_pad, text_y, text)
    draw.line(
        [(line_left, text_y + 10), (line_right, text_y + 10)],
        fill=rule,
    )
    return line_right


def _clock_width(text):
    width = 0
    last = len(text) - 1
    for index, char in enumerate(text):
        if char == ":":
            width += 2 if index == last else 4
        else:
            width += 7 if index == last else 9
    return width


def _draw_clock(draw, text, x, y, color, colon=CYAN):
    cursor = x
    last = len(text) - 1
    for index, char in enumerate(text):
        if char == ":":
            draw.rectangle(
                [cursor, y + 3, cursor + 1, y + 4],
                fill=colon,
            )
            draw.rectangle(
                [cursor, y + 7, cursor + 1, y + 8],
                fill=colon,
            )
            cursor += 2 if index == last else 4
            continue
        print_gfx_7x11(draw, char, cursor, y, color)
        cursor += 7 if index == last else 9
    return cursor


def _draw_signal(draw, x, top, bars, on=CYAN, off=BAR_OFF):
    lit = max(0, min(len(_BAR_HEIGHTS), int(bars)))
    for index, height in enumerate(_BAR_HEIGHTS):
        color = on if index < lit else off
        left = x + index * _BAR_PITCH
        bottom = top + 10
        draw.rectangle(
            [left, bottom - height + 1, left + 1, bottom],
            fill=color,
        )


def _standby_theme():
    now = time.monotonic()
    if now - float(_theme_cache["at"]) < 0.4:
        return _theme_cache["theme"]
    theme = active_theme()
    _theme_cache["theme"] = theme
    _theme_cache["at"] = now
    return theme


def _display_zone():
    now = time.monotonic()
    zone = _zone_cache["zone"]
    if zone is not None and now - float(_zone_cache["at"]) < 30:
        return zone
    zone = get_local_timezone()
    _zone_cache["zone"] = zone
    _zone_cache["at"] = now
    return zone


def _link_snapshot():
    now = time.monotonic()
    if now - float(_link_cache["at"]) < LINK_REFRESH_SECONDS:
        return _link_cache["bars"], _link_cache["kind"]
    bars, kind = _read_link()
    _link_cache["bars"] = bars
    _link_cache["kind"] = kind
    _link_cache["at"] = now
    return bars, kind


def _read_link():
    net = Path("/sys/class/net")
    if not net.is_dir():
        return 0, "off"

    wifi_bars = None
    ethernet_up = False
    try:
        names = [entry.name for entry in net.iterdir()]
    except OSError:
        return 0, "off"

    for name in names:
        if name == "lo":
            continue
        iface = net / name
        oper = _read_text(iface / "operstate")
        wireless = (iface / "wireless").exists() or (
            iface / "phy80211"
        ).exists()
        if wireless:
            if oper == "up":
                wifi_bars = _bars_for_quality(_wireless_quality(name))
        elif oper == "up":
            ethernet_up = True

    if wifi_bars is not None:
        return wifi_bars, "wifi"
    if ethernet_up:
        return len(_BAR_HEIGHTS), "lan"
    return 0, "off"


def _bars_for_quality(quality):
    if quality is None:
        return len(_BAR_HEIGHTS)
    if quality < 25:
        return 1
    if quality < 45:
        return 2
    if quality < 65:
        return 3
    return 4


def _wireless_quality(name):
    try:
        lines = Path("/proc/net/wireless").read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except OSError:
        return None

    prefix = f"{name}:"
    for line in lines:
        if not line.startswith(prefix):
            continue
        parts = line.split()
        if len(parts) < 3:
            return None
        try:
            return int(float(parts[2]))
        except ValueError:
            return None
    return None


def _read_text(path):
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
