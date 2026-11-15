"""Animated pictures behind the standby clock.

Themes paint the whole panel first. The clock, wordmark, weather,
and scores are drawn on top, so a theme has to stay dark enough
to read. Motion is slow on purpose: a 32-pixel panel looks busy
when everything twinkles at once.
"""

from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path


NAVY = (11, 17, 32)


CHRISTMAS = {
    "id": "christmas",
    "name": "Christmas",
    "scene": "christmas",
    "builtin": True,
    "detail": "A snowy village with flickering lights",
    "search": "christmas holiday snow night lights",
    "swatch": "background:linear-gradient(180deg,#07111c 0%,#0c2418 62%,#c4a15a 100%);",
    "palette": {
        "ink": [255, 236, 200],
        "mark": [255, 96, 108],
        "soft": [255, 214, 150],
    },
    "sky_top": [5, 10, 26],
    "sky_bottom": [4, 18, 16],
    "stars": True,
    "star_count": 70,
    "snow": True,
    "snow_count": 96,
    "snow_speed": 6,
    "lights": True,
    "light_gap": 10,
    "light_colors": [
        [255, 186, 72],
        [208, 52, 70],
        [64, 184, 112],
        [255, 228, 186],
    ],
    "trees": True,
    "ground": True,
}

SEASONS = (CHRISTMAS,)
_SEASON_BY_ID = {theme["id"]: theme for theme in SEASONS}


def theme_choices(_settings=None):
    """Built-in choices. Team themes live on the clock themes page."""
    return [("off", "Solid background")] + [
        (theme["id"], theme["name"]) for theme in SEASONS
    ]


def season_cards():
    """Picker cards for the seasonal scenes."""
    cards = []
    for theme in SEASONS:
        cards.append({
            "id": theme["id"],
            "name": theme["name"],
            "detail": theme.get("detail") or "",
            "search": theme.get("search") or theme["name"].lower(),
            "scene": theme.get("scene") or theme["id"],
            "swatch": theme.get("swatch") or "",
        })
    return cards


def theme_name(theme_id):
    """A short label for the theme currently on the clock."""
    text = str(theme_id or "").strip()
    if text in {"", "off", "none"}:
        return "Solid background"
    theme = theme_by_id(text)
    if theme is None:
        return "Solid background"
    return str(theme.get("name") or "Solid background")


def theme_league(theme_id):
    theme = theme_by_id(theme_id)
    if not theme:
        return "featured"
    return str(theme.get("league") or "featured")


def active_theme(settings=None):
    """The theme on the clock, or None for the solid background."""
    if settings is None:
        from common.settings import get_settings

        settings = get_settings()
    theme_id = str((settings or {}).get("clock_theme") or "off").strip()
    if theme_id in {"", "off", "none"}:
        return None
    return with_logo_choice(theme_by_id(theme_id, settings), settings)


def with_logo_choice(theme, settings):
    """Use the logo variant selected for this team, when there is one."""
    if not theme or theme.get("scene") != "team":
        return theme
    try:
        from common.logo_store import get_selected_logo_variant

        theme["logo_variant"] = get_selected_logo_variant(
            settings or {},
            theme.get("league") or "",
            theme.get("abbreviation") or "",
        )
    except ValueError:
        theme["logo_variant"] = "current"
    return theme


def clock_ink(theme):
    """Color for the standby digits, bright enough to read on that theme."""
    palette = clock_palette(theme)
    if not palette:
        return (248, 250, 252)
    return palette["ink"]


def clock_palette(theme):
    """Clock color plus the team's alternate, both bright enough to read."""
    if not theme:
        return None
    custom = theme.get("palette")
    if isinstance(custom, dict):
        ink = _rgb(custom.get("ink"), (248, 250, 252))
        mark = _rgb(custom.get("mark"), ink)
        soft = _rgb(custom.get("soft"), mark)
        return {
            "ink": ink,
            "mark": mark,
            "soft": soft,
            "dim": _tint(mark, 0.4),
        }
    if theme.get("scene") != "team":
        ink = (248, 250, 252)
        return {
            "ink": ink,
            "mark": ink,
            "soft": _tint(ink, 0.62),
            "dim": _tint(ink, 0.28),
        }
    primary = _rgb(theme.get("primary"), (248, 250, 252))
    alternate = _rgb(theme.get("accent"), primary)
    ink = _show_color(primary)
    if not _reads(primary) and _reads(alternate):
        ink = alternate
    elif not _reads(primary):
        ink = _show_color(primary if max(primary) >= max(alternate) else alternate)
    mark = alternate if _gap(ink, primary) <= _gap(ink, alternate) else primary
    mark = _show_color(mark)
    if _gap(ink, mark) < 70:
        mark = (242, 242, 242) if max(ink) < 230 else _show_color(primary)
    if _gap(ink, mark) < 70:
        mark = (242, 242, 242)
    return {
        "ink": ink,
        "mark": mark,
        "soft": mark,
        "dim": _tint(mark, 0.38),
    }


def _show_color(color):
    """Lift a dark uniform color so it still reads as that color."""
    if _reads(color):
        return color
    if max(color) < 22:
        return (236, 236, 236)
    peak = max(color) or 1
    scale = 200 / peak
    return tuple(min(255, int(channel * scale)) for channel in color)


def _tint(color, amount):
    return tuple(max(0, min(255, int(channel * amount))) for channel in color)


def _gap(left, right):
    return sum(abs(int(left[index]) - int(right[index])) for index in range(3))


def _rgb(value, fallback):
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return fallback
    try:
        return tuple(max(0, min(255, int(channel))) for channel in value[:3])
    except (TypeError, ValueError):
        return fallback


def _reads(color):
    """Saturated team colors read on the matrix even when luminance is low."""
    return max(color) >= 170 or (
        (0.3 * color[0]) + (0.59 * color[1]) + (0.11 * color[2])
    ) >= 150


def theme_by_id(theme_id, _settings=None):
    theme_id = str(theme_id or "").strip()
    season = _SEASON_BY_ID.get(theme_id)
    if season is not None:
        return deepcopy(season)
    if theme_id.startswith("team_"):
        from common.team_clock import theme_for_id

        theme = theme_for_id(theme_id)
        if theme is not None:
            return deepcopy(theme)
    return None


def normalize_clock_theme(value, settings=None):
    text = str(value or "").strip()
    if text in {"", "off", "none"}:
        return "off"
    if theme_by_id(text, settings) is None:
        return "off"
    return text


def theme_signature(theme):
    if not theme:
        return ""
    lights = tuple(tuple(color) for color in theme.get("light_colors") or [])
    return (
        theme.get("id"),
        tuple(theme.get("sky_top") or []),
        tuple(theme.get("sky_bottom") or []),
        bool(theme.get("stars")),
        int(theme.get("star_count") or 0),
        bool(theme.get("snow")),
        int(theme.get("snow_count") or 0),
        int(theme.get("snow_speed") or 0),
        bool(theme.get("lights")),
        int(theme.get("light_gap") or 0),
        lights,
        bool(theme.get("trees")),
        bool(theme.get("ground")),
        theme.get("scene") or "",
        tuple(theme.get("primary") or ()),
        tuple(theme.get("accent") or ()),
        theme.get("logo_variant") or "",
    )


def paint_theme(image, theme, seconds):
    """Draw one frame of a theme onto an existing image."""
    if not theme:
        return
    moment = float(seconds or 0)
    scene = theme.get("scene") or ""
    if scene == "team":
        _paint_team(image, theme, moment)
        return
    if scene == "christmas" or theme.get("id") == "christmas":
        _paint_christmas(image, theme, moment)


def render_preview(theme, phase, width=384, height=32):
    """One still frame of a theme, with no clock drawn on top."""
    from PIL import Image

    image = Image.new("RGB", (width, height), NAVY)
    if theme:
        paint_theme(image, theme, phase)
    return image


def team_field_color(color):
    """A dark, even version of a team color. Gray stays neutral."""
    red, green, blue = _rgb(color, (11, 17, 32))
    if max(red, green, blue) - min(red, green, blue) < 28:
        return (8, 10, 16)
    peak = max(red, green, blue, 1)
    scale = 40 / peak
    return tuple(max(0, min(48, int(channel * scale))) for channel in (red, green, blue))


# Sit between GAMELINE and the clock, and between the clock and the date.
_LOGO_SLOTS = ((100, 1), (254, 1))
_LOGO_CACHE = {}


def _clock_logo(league, identifier, variant):
    key = (str(league), str(identifier).upper(), str(variant or "current"))
    if key in _LOGO_CACHE:
        return _LOGO_CACHE[key]
    logo = None
    try:
        from common.logo_store import load_logo

        logo = load_logo(key[0], key[1], key[2])
    except (FileNotFoundError, ValueError, OSError):
        logo = None
    if logo is not None and logo.size != (30, 30):
        from PIL import Image

        fitted = Image.new("RGBA", (30, 30), (0, 0, 0, 0))
        copy = logo.copy()
        copy.thumbnail((30, 30), Image.Resampling.LANCZOS)
        fitted.paste(
            copy,
            ((30 - copy.width) // 2, (30 - copy.height) // 2),
            copy,
        )
        logo = fitted
    _LOGO_CACHE[key] = logo
    return logo


def _theme_logo(theme):
    league = str(theme.get("league") or "")
    abbreviation = str(theme.get("abbreviation") or "")
    variant = str(theme.get("logo_variant") or "current")
    leagues = [league]
    if league == "cbb":
        leagues.append("cfb")
    variants = [variant] if variant == "current" else [variant, "current"]
    for item in leagues:
        for choice in variants:
            logo = _clock_logo(item, abbreviation, choice)
            if logo is not None:
                return logo
    return None


def _paint_team(image, theme, moment):
    """An even dark field in the team color, with a logo on each side."""
    width, height = image.size
    pixels = image.load()
    field = team_field_color(theme.get("primary"))
    for y in range(height):
        for x in range(width):
            pixels[x, y] = field

    logo = _theme_logo(theme)
    mark = _show_color(_rgb(theme.get("accent"), field))
    for origin_x, origin_y in _LOGO_SLOTS:
        if logo is not None:
            image.paste(logo, (origin_x, origin_y), logo)
        else:
            _paint_monogram(
                image,
                str(theme.get("abbreviation") or ""),
                origin_x,
                origin_y,
                mark,
            )


def _paint_monogram(image, abbreviation, origin_x, origin_y, color):
    from PIL import ImageDraw

    from common.fonts import gfx_5x7_width, print_gfx_5x7

    label = "".join(character for character in abbreviation.upper() if character.isalnum())[:3]
    if not label:
        return
    draw = ImageDraw.Draw(image)
    text_width = gfx_5x7_width(label)
    print_gfx_5x7(
        draw,
        label,
        origin_x + max(0, (30 - text_width) // 2),
        origin_y + 11,
        color,
    )


def _put(pixels, width, height, x, y, color):
    if color is None or not 0 <= x < width or not 0 <= y < height:
        return
    pixels[x, y] = color


def _at(pixels, width, height, x, y):
    if not 0 <= x < width or not 0 <= y < height:
        return (0, 0, 0)
    return pixels[x, y]


def _lerp(start, end, blend):
    return tuple(
        int(start[index] + (end[index] - start[index]) * blend)
        for index in range(3)
    )


def _scale(color, amount):
    return tuple(max(0, min(255, int(part * amount))) for part in color)


def _mix(base, color, amount):
    return tuple(
        int(base[index] * (1 - amount) + color[index] * amount)
        for index in range(3)
    )


def _unit(index, salt):
    return (index * 1103515245 + salt * 12345 + 0x9E3779B9) & 0x7FFFFFFF


def _field(pixels, width, height, zenith, horizon, accent):
    """Dark through the clock, with the season's color at the floor."""
    for y in range(height):
        if y <= 22:
            row = _lerp(zenith, horizon, (y / 22) ** 1.8 * 0.4)
        else:
            row = _lerp(horizon, accent, ((y - 22) / max(1, height - 23)) ** 1.1)
        for x in range(width):
            edge = abs(x - (width / 2)) / (width / 2)
            lift = (edge ** 2.5) * (0.14 if y < 23 else 0.7)
            pixels[x, y] = _lerp(row, accent, lift)


def _wash(pixels, width, height, cx, cy, radius, color, strength):
    reach = int(math.ceil(radius))
    for dy in range(-reach, reach + 1):
        yy = int(round(cy + dy))
        if not 0 <= yy < height:
            continue
        for dx in range(-reach, reach + 1):
            distance = math.hypot(dx, dy)
            if distance > radius:
                continue
            xx = int(round(cx + dx))
            if not 0 <= xx < width:
                continue
            falloff = (1 - distance / radius) ** 2
            if 152 <= xx <= 238 and 9 <= yy <= 21:
                falloff *= 0.1
            pixels[xx, yy] = _mix(
                pixels[xx, yy], color, min(0.88, strength * falloff),
            )


def _motes(pixels, width, height, moment, count, color, speed, drift, rise=False):
    for index in range(count):
        phase = (_unit(index, 17) % 1000) / 1000
        travel = (phase + moment * speed) % 1
        y = ((1 - travel) if rise else travel) * (height + 6) - 3
        x = (
            (_unit(index, 29) % width)
            + math.sin(moment * 0.25 + index * 0.8) * drift
        ) % width
        ix = int(x) % width
        iy = int(y)
        if not 0 <= iy < height or (148 <= ix <= 242 and 8 <= iy <= 22):
            continue
        depth = 0.42 + (_unit(index, 5) % 50) / 100
        shade = _scale(color, depth)
        _put(pixels, width, height, ix, iy, shade)
        if _unit(index, 3) % 4 == 0:
            soft = _scale(shade, 0.38)
            for neighbor in ((ix - 1, iy), (ix + 1, iy)):
                base = _at(pixels, width, height, neighbor[0], neighbor[1])
                _put(
                    pixels, width, height, neighbor[0], neighbor[1],
                    _mix(base, soft, 0.65),
                )


def _floor(pixels, width, height, color, moment, rows=2):
    for x in range(width):
        wave = 0.62 + 0.38 * math.sin(x * 0.09 + moment * 0.5)
        pixels[x, height - 1] = _scale(color, wave)
        if rows > 1 and math.sin(x * 0.05 + 0.4) > -0.15:
            pixels[x, height - 2] = _scale(color, wave * 0.42)


# Panel rows mapped onto the village. The photo's light string is skipped
# so a drawn string can hang in that sky instead.
_VILLAGE_BANDS = (
    (0.00, 0.24, 0.19, 0.38),
    (0.24, 0.70, 0.36, 0.76),
    (0.70, 1.00, 0.76, 1.00),
)
_STRING_BULBS = (
    (232, 18, 28),
    (255, 148, 16),
    (18, 186, 62),
    (36, 104, 255),
    (255, 214, 96),
    (255, 46, 54),
    (28, 204, 168),
    (255, 242, 214),
)
_CHRISTMAS_ART = (
    Path(__file__).resolve().parents[2] / "assets" / "clock" / "christmas.jpg"
)
_CHRISTMAS_SOURCE = None
_CHRISTMAS_PLATE = {}
_SNOW = {}


def _paint_christmas(image, theme, moment):
    """The village picture, with lights that breathe and snow that settles."""
    width, height = image.size
    plate = None if width < 16 or height < 8 else _christmas_plate(width, height)
    if plate is None:
        _paint_christmas_plain(image.load(), width, height, theme, moment)
        return
    image.paste(plate["image"])
    pixels = image.load()
    _flicker_lights(pixels, plate, width, height, moment)
    _paint_snow(pixels, width, height, moment)
    _paint_string_lights(pixels, width, height, moment)


def _paint_christmas_plain(pixels, width, height, theme, moment):
    """The old night scene, used when the village picture is missing."""
    del theme
    _field(pixels, width, height, (3, 8, 18), (5, 14, 22), (14, 32, 28))
    _wash(pixels, width, height, 272, 5, 7.5, (220, 224, 208), 0.8)
    bulbs = ((255, 198, 112), (188, 48, 58), (255, 232, 206), (52, 140, 96))
    for x in range(width):
        sag = 1 + int(abs(math.sin(x * 0.028)) > 0.92)
        pixels[x, sag] = _mix(pixels[x, sag], (16, 26, 24), 0.7)
    for index, bulb_x in enumerate(range(18, width - 12, 28)):
        color = bulbs[index % len(bulbs)]
        pulse = 0.5 + 0.5 * (0.5 + 0.5 * math.sin(moment * 0.7 + index * 0.9))
        _wash(pixels, width, height, bulb_x, 2, 2.2, color, 0.62 * pulse)
    _motes(pixels, width, height, moment, 16, (236, 242, 248), 0.04, 5)
    _floor(pixels, width, height, (176, 198, 208), moment)


def _christmas_source():
    global _CHRISTMAS_SOURCE
    if _CHRISTMAS_SOURCE is not None:
        return _CHRISTMAS_SOURCE
    from PIL import Image

    with Image.open(_CHRISTMAS_ART) as source:
        _CHRISTMAS_SOURCE = source.convert("RGB")
    return _CHRISTMAS_SOURCE


def _christmas_plate(width, height):
    key = (width, height)
    if key in _CHRISTMAS_PLATE:
        return _CHRISTMAS_PLATE[key]
    try:
        plate = _build_christmas_plate(width, height)
    except (OSError, ValueError):
        plate = None
    _CHRISTMAS_PLATE[key] = plate
    return plate


def _band_t(amount):
    amount = min(1.0, max(0.0, amount))
    for start, end, source_start, source_end in _VILLAGE_BANDS:
        if amount <= end:
            span = end - start
            blend = 0 if span <= 0 else (amount - start) / span
            return source_start + (source_end - source_start) * blend
    return 1.0


def _build_christmas_plate(width, height):
    """Fit the whole village onto the strip and remember which pixels are lights."""
    from PIL import Image

    source = _christmas_source()
    src_w, src_h = source.size
    wide_h = max(height, round(src_h * (width / src_w)))
    wide = source.resize((width, wide_h), Image.Resampling.LANCZOS)
    wide_px = wide.load()
    raw = Image.new("RGB", (width, height))
    raw_px = raw.load()
    last = max(1, wide_h - 1)
    for y in range(height):
        span = max(1, height - 1)
        top = _band_t((y - 0.5) / span) * last
        bottom = _band_t((y + 0.5) / span) * last
        if bottom < top:
            top, bottom = bottom, top
        y0 = int(top)
        y1 = min(wide_h - 1, max(y0, int(math.ceil(bottom))))
        for x in range(width):
            acc_r = acc_g = acc_b = 0
            count = 0
            best = None
            best_score = 0
            for sy in range(y0, y1 + 1):
                red, green, blue = wide_px[x, sy]
                acc_r += red
                acc_g += green
                acc_b += blue
                count += 1
                score = (max(red, green, blue) - min(red, green, blue)) * max(red, green, blue)
                if score > best_score:
                    best_score = score
                    best = (red, green, blue)
            average = (acc_r / count, acc_g / count, acc_b / count)
            # The overhead string lives in the top of the photo. Keep that
            # sky as sky so those bulbs are not baked into the picture.
            if y > height * 0.24 and best is not None and best_score > 7000:
                raw_px[x, y] = _mix(average, best, 0.78)
            else:
                raw_px[x, y] = tuple(int(channel) for channel in average)

    _scrub_overhead_lights(raw_px, width, height)
    _quiet_overhead_sky(raw_px, width, height)
    dark = raw.copy()
    dark_px = dark.load()
    lights = {}
    for y in range(height):
        for x in range(width):
            color = raw_px[x, y]
            if _is_village_light(color, x, y, width, height, raw_px):
                lights[(x, y)] = color
            dark_px[x, y] = _shade_village(x, y, color, width, height)
    return {"image": dark, "bulbs": _group_lights(lights, height)}


def _looks_like_a_bulb(color):
    red, green, blue = color
    peak = max(red, green, blue)
    span = peak - min(red, green, blue)
    return peak >= 135 and span >= 52 and span >= peak * 0.36


def _scrub_overhead_lights(raw_px, width, height):
    """Replace the photo's light string with the night sky behind it."""
    limit = max(3, int(round(height * 0.26)))
    hits = [
        (x, y)
        for y in range(limit)
        for x in range(width)
        if _looks_like_a_bulb(raw_px[x, y])
    ]
    if not hits:
        return
    hit = set(hits)
    for x, y in hits:
        found = []
        for ny in range(limit, min(height, limit + 4)):
            for nx in range(max(0, x - 4), min(width, x + 5)):
                sample = raw_px[nx, ny]
                if (nx, ny) not in hit and not _looks_like_a_bulb(sample):
                    found.append(sample)
            if found:
                break
        if not found:
            for nx in range(max(0, x - 6), min(width, x + 7)):
                sample = raw_px[nx, min(limit, height - 1)]
                if not _looks_like_a_bulb(sample):
                    found.append(sample)
        raw_px[x, y] = (
            (8, 14, 28)
            if not found
            else tuple(sum(sample[channel] for sample in found) // len(found) for channel in range(3))
        )


def _quiet_overhead_sky(raw_px, width, height):
    """Take the colored spill of the old string out of the night sky."""
    limit = max(3, int(round(height * 0.28)))
    for y in range(limit):
        for x in range(width):
            red, green, blue = raw_px[x, y]
            luma = 0.3 * red + 0.59 * green + 0.11 * blue
            if luma > 72:
                continue
            span = max(red, green, blue) - min(red, green, blue)
            if span < 16:
                continue
            night = (
                luma * 0.25 + 5,
                luma * 0.38 + 8,
                luma * 0.7 + 14,
            )
            raw_px[x, y] = _mix((red, green, blue), night, 0.86)


def _is_village_light(color, x, y, width, height, raw_px):
    """Window pixels that are brighter than their neighbors."""
    yn = y / max(1, height - 1)
    red, green, blue = color
    peak = max(red, green, blue)
    if yn < 0.26 or yn > 0.78:
        return False
    if red < 185 or red < blue + 55 or peak < 175:
        return False
    brighter = 0
    for nx in (x - 1, x + 1):
        if not 0 <= nx < width:
            continue
        neighbor = max(raw_px[nx, y])
        if peak > neighbor + 18:
            brighter += 1
    return brighter >= 1


def _shade_village(x, y, color, width, height):
    """Keep the strip dark enough that the clock, wordmark, and date read."""
    yn = y / max(1, height - 1)
    if yn < 0.18:
        gain = 0.58
    elif yn < 0.72:
        gain = 0.34
    else:
        gain = 0.30
    if 0.28 <= yn <= 0.70:
        mid = 1 - abs(yn - 0.48) / 0.22
        gain *= 1 - 0.58 * max(0, min(1, mid))
    dx = (x - width * 0.5) / (width * 0.16)
    dy = (y - height * 0.48) / (height * 0.22)
    well = dx * dx + dy * dy
    if well < 1:
        gain *= 0.42 + 0.58 * well
    return tuple(max(0, min(255, int(channel * gain))) for channel in color)


def _group_lights(points, height):
    remaining = set(points)
    bulbs = []
    while remaining:
        start = remaining.pop()
        stack = [start]
        group = [start]
        while stack:
            x, y = stack.pop()
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if (nx, ny) in remaining:
                    remaining.remove((nx, ny))
                    stack.append((nx, ny))
                    group.append((nx, ny))
        pixels = [(x, y, points[(x, y)]) for x, y in group]
        mean_y = sum(y for _x, y, _color in pixels) / len(pixels)
        kind = "bulb" if mean_y < height * 0.22 else "glow"
        if kind == "bulb":
            xs = [pixel[0] for pixel in pixels]
            if max(xs) - min(xs) > 6:
                continue
        bulbs.append({
            "kind": kind,
            "phase": (_unit(len(bulbs) + 3, 23) % 628) / 100,
            "pixels": pixels,
        })
    return bulbs


def _clock_well(x, y, width, height):
    dx = (x - width * 0.5) / (width * 0.17)
    dy = (y - height * 0.48) / (height * 0.24)
    return dx * dx + dy * dy


def _light_room(x, y, width, height):
    """How hard a light may glow here. The digits need the middle kept dim."""
    if _clock_well(x, y, width, height) < 0.55:
        return 0
    yn = y / max(1, height - 1)
    xn = abs(x - width * 0.5) / (width * 0.5)
    if yn < 0.26:
        # Weather sits in the top center, so those bulbs stay softer.
        center = max(0, 1 - xn / 0.42)
        return 1 - 0.5 * center
    if yn > 0.74:
        return 0.8
    return 0.32


def _punch(color):
    peak = max(color) or 1
    lifted = [min(255, int(channel * (255 / peak))) for channel in color]
    floor = min(lifted)
    return tuple(min(255, max(0, int(channel - floor * 0.42))) for channel in lifted)


def _light_gain(moment, phase, kind):
    slow = 0.5 + 0.5 * math.sin(moment * 1.45 + phase)
    if kind != "bulb":
        return 0.84 + 0.16 * slow
    blink = math.sin(moment * (2.1 + (phase % 1.5)) + phase * 2.7)
    gain = 0.34 + 0.66 * slow
    if blink > 0.94:
        gain *= 0.18
    elif blink > 0.8:
        gain *= 0.58
    return gain * (0.9 + 0.1 * math.sin(moment * 0.65))


def _string_gain(moment, index):
    """A quiet shimmer, then a short dip. Bulbs stay lit."""
    tempo = 3.1 + (index % 5) * 0.55
    shimmer = 0.84 + 0.16 * math.sin(moment * tempo + index * 1.7)
    dip = math.sin(moment * (6.2 + (index % 4) * 0.7) + index * 2.4)
    if dip > 0.9:
        return shimmer * 0.42
    if dip > 0.74:
        return shimmer * 0.68
    return shimmer


# C9: green socket, glass widest under the socket, tapering to a point.
# Offsets are from the glass center. The socket sits on the wire.
_BULB_SHAPE = (
    (-1, -2, "socket"),
    (0, -2, "socket"),
    (1, -2, "socket"),
    (-2, -1, "rim"),
    (-1, -1, "shine"),
    (0, -1, "glass"),
    (1, -1, "glass"),
    (2, -1, "rim"),
    (-1, 0, "glass"),
    (0, 0, "core"),
    (1, 0, "glass"),
    (-1, 1, "edge"),
    (0, 1, "glass"),
    (1, 1, "edge"),
    (0, 2, "tip"),
)
_SOCKET = (14, 102, 58)
_SOCKET_SHADE = (8, 62, 34)


def _draw_glass_bulb(pixels, width, height, cx, cy, color, gain):
    """A C9 bulb. The socket stays put; the glass takes the flicker."""
    lit = _scale(color, 0.22 + 0.78 * gain)
    for dx, dy, kind in _BULB_SHAPE:
        xx = cx + dx
        yy = cy + dy
        if not 0 <= xx < width or not 0 <= yy < height:
            continue
        if kind == "socket":
            pixels[xx, yy] = _SOCKET if dx == 0 else _SOCKET_SHADE
            continue
        glass = lit
        if kind == "shine":
            glass = _mix(lit, (255, 255, 255), 0.62)
        elif kind == "rim":
            glass = _scale(lit, 0.55)
        elif kind == "edge":
            glass = _scale(lit, 0.7)
        elif kind == "core":
            glass = _mix(lit, (255, 248, 230), 0.18)
        pixels[xx, yy] = glass


def _string_drop(x, width):
    """Four catenaries, pinned at the edges, the quarters, and the middle.

    Each span falls steeply off its pins and bottoms out in the middle.
    """
    swags = 4
    span = width / swags
    swag = min(swags - 1, max(0, int(x / span)))
    local = (x - swag * span) / span
    pinch = 3.2
    raw = math.cosh(pinch * (local - 0.5))
    edge = math.cosh(pinch * 0.5)
    hang = (edge - raw) / (edge - 1.0)
    depths = (5.0, 4.4, 4.8, 4.2)
    return hang * depths[swag]


def _paint_string_lights(pixels, width, height, moment):
    """Glass bulbs on a wire that drapes across the sky."""
    if height < 8 or width < 48:
        return
    gap = 16 if width >= 300 else 12
    margin = max(14, gap // 2)
    xs = list(range(margin, width - 12, gap))
    if len(xs) < 2:
        return
    wire = (14, 20, 18)

    def wire_y(x):
        return max(0, min(height - 5, int(round(_string_drop(x, width)))))

    def center_y(x):
        return wire_y(x) + 2

    for index, x in enumerate(xs):
        color = _STRING_BULBS[index % len(_STRING_BULBS)]
        _wash(
            pixels, width, height, x, center_y(x), 3.3, color,
            0.46 * _string_gain(moment, index),
        )
    previous = None
    for x in range(width):
        y = wire_y(x)
        if previous is not None and abs(y - previous) > 1:
            for fill in range(min(previous, y), max(previous, y) + 1):
                pixels[x, fill] = _mix(pixels[x, fill], wire, 0.9)
        pixels[x, y] = _mix(pixels[x, y], wire, 0.9)
        previous = y
    for index, x in enumerate(xs):
        color = _STRING_BULBS[index % len(_STRING_BULBS)]
        _draw_glass_bulb(
            pixels, width, height, x, center_y(x), color,
            _string_gain(moment, index),
        )


def _flicker_lights(pixels, plate, width, height, moment):
    for bulb in plate["bulbs"]:
        gain = _light_gain(moment, bulb["phase"], bulb["kind"])
        owned = {(x, y) for x, y, _color in bulb["pixels"]}
        for x, y, color in bulb["pixels"]:
            room = _light_room(x, y, width, height)
            if room <= 0:
                continue
            if bulb["kind"] == "bulb":
                shown = _scale(_punch(color), (0.48 + 0.52 * gain) * room)
                pixels[x, y] = shown
                halo = 0.22 * gain * room
                for nx, ny in ((x - 1, y), (x + 1, y)):
                    if (nx, ny) in owned or not 0 <= nx < width:
                        continue
                    if _light_room(nx, y, width, height) <= 0:
                        continue
                    pixels[nx, ny] = _mix(pixels[nx, ny], shown, halo)
            else:
                shown = _scale(color, (0.5 + 0.5 * gain) * min(1, room + 0.35))
                pixels[x, y] = _mix(pixels[x, y], shown, 0.72 * room)


def _snowfall(moment):
    """A long storm, then a slow thaw. Heaps shrink, they do not vanish."""
    cycle = (moment % 48) / 48
    if cycle < 0.64:
        blend = cycle / 0.64
        return blend * blend * (3 - 2 * blend)
    blend = (cycle - 0.64) / 0.36
    fade = blend * blend * (3 - 2 * blend)
    return 1 - fade


def _snow_cap(x, width):
    """Short under the score line, taller toward the trees."""
    center = abs(x - width * 0.5) / (width * 0.5)
    if center < 0.30:
        return 2.6
    return 2.6 + (center - 0.30) / 0.70 * 3.6


def _pile_sites(width):
    """Places snow prefers to settle. Each one becomes its own drift."""
    count = max(3, min(7, width // 62))
    sites = []
    for index in range(count):
        slot = 0.5 if count == 1 else index / (count - 1)
        jitter = ((_unit(index, 47) % 100) - 50) / 50 * 0.025
        sites.append({
            "x": min(width - 8, max(8, (slot + jitter) * (width - 1))),
            "grab": 0.72 + (_unit(index, 59) % 55) / 100,
        })
    return sites


def _pack_height(x, width, state):
    return min(_snow_cap(x, width), max(0.0, state["depth"][x]))


def _seed_piles(depth, sites, amount):
    """Start a thaw or a storm with heaps already formed, not a flat sheet."""
    width = len(depth)
    for index, site in enumerate(sites):
        peak = (2.4 + (_unit(index, 71) % 18) / 10) * amount * site["grab"]
        radius = 9 + (_unit(index, 73) % 7)
        for x in range(width):
            dist = abs(x - site["x"]) / radius
            if dist >= 1:
                continue
            hump = (1 - dist * dist) ** 1.8
            depth[x] = min(_snow_cap(x, width), max(depth[x], peak * hump))


def _flake_home(sites, salt, index, width, wander):
    """Where this flake is headed. Wanderers dust the gaps between drifts."""
    if wander:
        return (_unit(salt, index + 9) % 10000) / 10000 * width, 1.0
    site = sites[_unit(salt, index + 7) % len(sites)]
    spread = 4 + (_unit(salt, index + 13) % 6)
    wobble = ((_unit(salt, index + 19) % 1000) / 1000 - 0.5) * 2 * spread
    home = min(width - 1, max(0.0, site["x"] + wobble))
    return home, site["grab"]


def _make_flake(index, width, height, sites, moment, salt):
    """Far flakes are dim and slow. Near ones are bright and fall faster."""
    kind = index % 5
    layer = 0 if kind in (0, 1) else 2 if kind == 4 else 1
    if layer == 0:
        speed = 0.07 + (_unit(index, 3) % 50) / 1000
        bright = 0.4 + (_unit(index, 5) % 18) / 100
    elif layer == 1:
        speed = 0.16 + (_unit(index, 3) % 90) / 1000
        bright = 0.74 + (_unit(index, 5) % 22) / 100
    else:
        speed = 0.32 + (_unit(index, 3) % 120) / 1000
        bright = 0.94
    phase = (_unit(index, 17) % 1000) / 1000
    wander = _unit(salt, index + 3) % 3 == 0
    home, feed = _flake_home(sites, salt, index, width, wander)
    return {
        "x": (home + ((_unit(index, 29) % 9) - 4)) % width,
        "y": ((phase + moment * speed) % 1) * (height + 4) - 2,
        "speed": speed,
        "phase": phase * math.tau,
        "bright": bright,
        "layer": layer,
        "home": home,
        "feed": feed,
        "wander": wander,
        "flutter": 1.2 + (_unit(index, 7) % 14) / 10,
        "wind": 0.4 + layer * 0.32,
    }


def _fresh_snow(width, height, moment):
    sites = _pile_sites(width)
    count = max(48, width // 5)
    salt = 1
    flakes = [
        _make_flake(index, width, height, sites, moment, salt + index)
        for index in range(count)
    ]
    depth = [0.0] * width
    _seed_piles(depth, sites, _snowfall(moment))
    return {
        "v": 3,
        "t": moment,
        "height": height,
        "salt": salt + count,
        "sites": sites,
        "depth": depth,
        "flakes": flakes,
    }


def _snow_state(width, height, moment):
    key = (width, height)
    state = _SNOW.get(key)
    if (
        state is None
        or state.get("v") != 3
        or len(state["depth"]) != width
        or moment < state["t"] - 0.05
        or moment - state["t"] > 4
    ):
        state = _fresh_snow(width, height, moment)
        _SNOW[key] = state
        return state
    dt = moment - state["t"]
    if dt > 0:
        remaining = dt
        while remaining > 0.0001:
            step = min(0.1, remaining)
            state["t"] += step
            _step_snow(state, width, step, state["t"])
            remaining -= step
    return state


def _settle_piles(depth, width):
    """Snow slides only when a face is steep, so heaps stay heaps."""
    slope = 0.34
    for _pass in range(4):
        for x in range(width - 1):
            diff = depth[x] - depth[x + 1]
            if abs(diff) <= slope:
                continue
            flow = (abs(diff) - slope) * 0.62
            if diff > 0:
                take = min(flow, depth[x])
                depth[x] -= take
                depth[x + 1] += take
            else:
                take = min(flow, depth[x + 1])
                depth[x + 1] -= take
                depth[x] += take


def _step_snow(state, width, dt, moment):
    depth = state["depth"]
    storm = _snowfall(moment)
    for x in range(width):
        cap = _snow_cap(x, width)
        # A thaw melts every heap down, slowly. Peaks above the cap go first.
        loss = 0.006 + (1 - storm) * 0.16
        if depth[x] > cap:
            loss += (depth[x] - cap) * 2.8
        depth[x] = max(0.0, depth[x] - loss * dt)
    _settle_piles(depth, width)
    for x in range(width):
        depth[x] = min(depth[x], _snow_cap(x, width) + 0.3)
    height = state["height"]
    stick = storm * storm
    # A patchy skiff between the drifts, with bare gaps left on purpose.
    if stick > 0.2:
        for x in range(width):
            if depth[x] >= 0.6 or _unit(x, 17) % 3 == 0:
                continue
            depth[x] = min(0.6, depth[x] + stick * dt * 0.08)
    gust = math.sin(moment * 0.21) * 5.5 + math.sin(moment * 0.06 + 0.8) * 2.5
    for index, flake in enumerate(state["flakes"]):
        flake["y"] += flake["speed"] * height * dt
        fall = min(1.0, max(0.0, flake["y"]) / max(1, height))
        flake["x"] += gust * flake["wind"] * dt
        flake["x"] += math.sin(flake["y"] * 0.45 + flake["phase"]) * flake["flutter"] * dt
        if not flake["wander"]:
            delta = flake["home"] - flake["x"]
            if delta > width / 2:
                delta -= width
            elif delta < -width / 2:
                delta += width
            flake["x"] += delta * (0.05 + 0.18 * fall) * dt
        flake["x"] %= width
        column = int(flake["x"]) % width
        ground = height - _pack_height(column, width, state)
        if flake["y"] < ground:
            continue
        mass = (1.15 if flake["wander"] else 2.7) * stick * flake["feed"]
        if flake["layer"] == 2:
            mass *= 1.15
        parts = ((0, 1.0),) if flake["wander"] else ((0, 1.0), (-1, 0.42), (1, 0.42))
        for offset, part in parts:
            x = column + offset
            if 0 <= x < width:
                depth[x] = min(_snow_cap(x, width) + 0.35, depth[x] + mass * part)
        state["salt"] += 1
        salt = state["salt"]
        flake["wander"] = _unit(salt, index + 3) % 3 == 0
        flake["home"], flake["feed"] = _flake_home(
            state["sites"], salt, index, width, flake["wander"]
        )
        flake["x"] = flake["home"]
        flake["y"] = -1 - (_unit(salt, index + 5) % 7) * 0.35


def _flake_hidden(x, y, width, height):
    """Keep flakes off the digits. The sky above the clock still snows."""
    return (
        width * 0.36 <= x <= width * 0.66
        and height * 0.30 <= y <= height * 0.72
    )


def _paint_snow(pixels, width, height, moment):
    state = _snow_state(width, height, moment)
    _draw_pack(pixels, width, height, state, moment)
    _draw_flakes(pixels, width, height, state, moment)


def _draw_flakes(pixels, width, height, state, moment):
    """Far specks, mid flakes, then a few close ones with a soft glow."""
    del moment
    flakes = sorted(state["flakes"], key=lambda flake: flake["layer"])
    for flake in flakes:
        x = int(flake["x"]) % width
        y = int(flake["y"])
        if not 0 <= y < height or _flake_hidden(x, y, width, height):
            continue
        layer = flake["layer"]
        if layer == 0:
            pixels[x, y] = _mix(pixels[x, y], (206, 216, 228), 0.42)
            continue
        if layer == 1:
            pixels[x, y] = _mix(pixels[x, y], (248, 250, 252), 0.82)
            continue
        _wash(pixels, width, height, x, y, 1.7, (255, 255, 255), 0.28)
        pixels[x, y] = (255, 255, 255)


def _draw_pack(pixels, width, height, state, moment):
    """The real drifts, with a bright crest and a cool body."""
    del moment
    levels = state["depth"]
    width = len(levels)
    for x in range(width):
        shown = _pack_height(x, width, state)
        if shown <= 0.1:
            continue
        left = levels[x - 1] if x else shown
        right = levels[x + 1] if x + 1 < width else shown
        crest = shown >= left and shown >= right and shown > 1.6
        rows = int(math.ceil(shown))
        for layer in range(rows):
            y = height - 1 - layer
            if y < 0:
                break
            covered = 1.0 if layer < int(shown) else shown - int(shown)
            if covered <= 0.04:
                continue
            surface = layer == rows - 1
            if not surface:
                down = (rows - 1 - layer) / max(1, rows)
                color = _lerp((232, 240, 246), (196, 214, 228), down * 0.7)
                pixels[x, y] = _mix(pixels[x, y], color, 0.96)
                continue
            if shown < 1.0:
                pixels[x, y] = _mix(
                    pixels[x, y], (236, 242, 248), 0.34 + 0.4 * covered,
                )
                continue
            color = (255, 255, 255) if crest else (248, 250, 252)
            pixels[x, y] = _mix(pixels[x, y], color, 0.78 + 0.22 * covered)
