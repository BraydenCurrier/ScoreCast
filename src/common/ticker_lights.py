"""Christmas lights and snow along the scrolling scoreboard.

The wire runs straight along the top of each card and sags between
them. Bulbs on that wire twinkle, and each gap holds its own pile of
snow. Both scroll with the cards.
"""

import math

from common.clock_themes import (
    _STRING_BULBS,
    _scale,
    active_theme,
)


_WIRE = (44, 96, 56)
_EVERY = 13
# How far the wire drops between cards.
_SAG = 8
# How far that dip reaches onto the card on either side of the gap.
_REACH = 20
# How far a snow pile spreads onto the logo on either side of the gap.
_SNOW_REACH = 14
# A few bulbs sit a little dimmer, the way a real string never matches.
_GAINS = (1.0, 0.84, 0.94, 0.76, 0.9, 0.82)
# Offsets from the center of the bulb, which sits on the wire.
_LAMP = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0), (0, 0), (1, 0),
    (-1, 1), (0, 1), (1, 1),
    (0, 2),
)


def christmas_lights_enabled(settings):
    """True only while the standby clock is the Christmas scene."""
    theme = active_theme(settings or {})
    if not theme:
        return False
    return theme.get("scene") == "christmas" or theme.get("id") == "christmas"


def drape_christmas_lights(image, spans, moment=0.0):
    """Lay the swag, the snow, and the bulbs for this moment.

    spans is (x, card_width, step). The step includes the black gap
    after the card. x may be negative when a card is scrolling on.
    """
    if image is None or not spans:
        return
    width, height = image.size
    if height < 16 or width < 8:
        return
    pixels = image.load()
    # A strip that fills the image is tiled while it scrolls, so a pile
    # that crosses the end has to reappear at the start.
    tiled = (
        int(spans[0][0]) == 0
        and int(spans[-1][0]) + max(int(spans[-1][1]), int(spans[-1][2])) == width
    )
    for index, (origin, card_width, step) in enumerate(spans):
        _drape_span(
            pixels, width, height,
            int(origin), max(0, int(card_width)), max(0, int(step)),
            moment, index, tiled,
        )
    _lay_ground(pixels, width, height, spans)


class Twinkle:
    """Repaint bulbs whose brightness changed, and leave the rest alone.

    The ticker scrolls by shifting a cached strip. Rewriting the whole
    strip every frame makes the panel pulse, so only a bulb that
    stepped to a new brightness is written back.
    """

    def __init__(self, image, spans):
        self.image = image
        self.width, self.height = image.size
        self.rgb = bytearray(image.tobytes())
        self.pixels = image.load()
        self.lamps = _lamp_list(self.width, self.height, spans)
        self.gain = [None] * len(self.lamps)
        self.seen = {}

    def advance(self, moment):
        """Store this moment's brightness into the strip."""
        for index, lamp in enumerate(self.lamps):
            gain = _twinkle_step(moment, lamp["index"])
            if gain == self.gain[index]:
                continue
            self.gain[index] = gain
            self._write(lamp, gain)

    def sync(self, canvas_id):
        """The canvas was just copied from the strip."""
        self.seen[canvas_id] = list(self.gain)

    def pokes(self, canvas_id, origin, view_width):
        """View pixels whose bulb changed since this canvas was drawn."""
        seen = self.seen.setdefault(canvas_id, [None] * len(self.lamps))
        period = self.width
        pokes = []
        for index, lamp in enumerate(self.lamps):
            if seen[index] == self.gain[index]:
                continue
            seen[index] = self.gain[index]
            lit, core = _bulb_colors(lamp["color"], lamp["static"], self.gain[index])
            for dx, dy in _LAMP:
                x = lamp["x"] + dx
                y = lamp["y"] + dy
                if not 0 <= x < period or not 0 <= y < self.height:
                    continue
                color = core if dx == 0 and dy == 0 else lit
                view = (x - origin) % period
                while view < view_width:
                    pokes.append((view, y, color[0], color[1], color[2]))
                    view += period
        return pokes

    def _write(self, lamp, gain):
        lit, core = _bulb_colors(lamp["color"], lamp["static"], gain)
        for dx, dy in _LAMP:
            x = lamp["x"] + dx
            y = lamp["y"] + dy
            if not 0 <= x < self.width or not 0 <= y < self.height:
                continue
            color = core if dx == 0 and dy == 0 else lit
            self.pixels[x, y] = color
            offset = (y * self.width + x) * 3
            self.rgb[offset] = color[0]
            self.rgb[offset + 1] = color[1]
            self.rgb[offset + 2] = color[2]


def _drape_span(pixels, width, height, origin, card_width, step, moment, pile_index, tiled):
    step = max(card_width, step)
    _lay_snow(pixels, width, height, origin, card_width, step, pile_index, tiled)
    previous = None
    for local in range(step):
        x = origin + local
        y = _wire_row(local, card_width, step)
        if previous is not None and abs(y - previous) > 1 and 0 <= x < width:
            direction = 1 if y > previous else -1
            for fill in range(previous + direction, y, direction):
                _lay_wire(pixels, width, height, x, fill)
        _lay_wire(pixels, width, height, x, y)
        previous = y

    for local in range(step):
        x = origin + local
        if (x - _EVERY // 2) % _EVERY != 0 or not 0 <= x < width:
            continue
        index = x // _EVERY
        _lamp(
            pixels, width, height, x, _wire_row(local, card_width, step) + 1,
            _STRING_BULBS[index % len(_STRING_BULBS)],
            _GAINS[index % len(_GAINS)],
            _twinkle_step(moment, index),
        )


def _wire_row(local, card_width, step):
    """Flat on the card. A wide dip centered on the gap at either end."""
    gap = step - card_width
    if gap <= 1:
        return 0
    half = _REACH + gap / 2
    sag = 0
    for center in (-gap / 2, card_width + gap / 2):
        distance = abs(local - center)
        if distance >= half:
            continue
        span = 1 - distance / half
        hang = math.sin(math.pi * span / 2) ** 2
        sag = max(sag, int(round(hang * _SAG)))
    return sag


def _lay_wire(pixels, width, height, x, y):
    if not 0 <= x < width or not 0 <= y < height:
        return
    pixels[x, y] = _WIRE


def _lay_ground(pixels, width, height, spans):
    """One white line along the bottom, under every card."""
    y = height - 1
    if y < 0:
        return
    for origin, card_width, step in spans:
        step = max(int(card_width), int(step))
        origin = int(origin)
        for local in range(step):
            x = origin + local
            if 0 <= x < width:
                pixels[x, y] = (255, 255, 255)


def _drift_heights(width, index):
    """A rounded drift: short face into the wind, long tail downwind."""
    if width < 2:
        return [0] * width
    kind = index % 4
    peak = (6, 8, 5, 7)[kind] + (index % 3) - 1
    peak = max(5, min(8, peak))
    crest = (0.40, 0.32, 0.5, 0.34)[kind]
    if (index // 4) % 2:
        crest = 1 - crest
    # Larger means a narrower face. The lee side stays the long one.
    wind = (2.6, 3.2, 1.7, 2.8)[kind]
    lee = (1.8, 2.0, 1.45, 2.2)[kind]
    heights = []
    for column in range(width):
        t = column / (width - 1)
        height = _drift_curve(t, crest, wind, lee)
        if kind == 3:
            other = 0.72 if crest < 0.5 else 0.28
            height += 0.62 * _drift_curve(t, other, 3.0, 2.4)
        elif kind == 0:
            other = crest + (0.24 if crest < 0.5 else -0.24)
            height += 0.28 * _drift_curve(t, other, 3.4, 3.4)
        heights.append(height)
    tallest = max(heights) or 1
    return [max(0, int(round(value / tallest * peak))) for value in heights]


def _drift_curve(t, crest, wind, lee):
    """A peaked drift with a long skirt. 1 at the crest."""
    crest = min(0.72, max(0.28, crest))
    if t <= crest:
        u = (crest - t) / crest
        sharp = wind
    else:
        u = (t - crest) / (1 - crest)
        sharp = lee
    return 1.0 / (1.0 + (u * sharp) ** 2)


def _snow_color(from_top, rows, shade, crest, sparkle):
    """One lit face and one shaded face, darker toward the ground."""
    if sparkle:
        return (255, 255, 255)
    if from_top == 0:
        if crest or shade < 0.2:
            return (255, 255, 255)
        return _blend((240, 246, 252), (206, 220, 234), shade)
    depth = from_top / max(1, rows - 1)
    top = _blend((230, 240, 248), (184, 202, 220), shade)
    bottom = _blend((196, 214, 228), (150, 170, 194), shade)
    return _blend(top, bottom, depth ** 0.85)


def _blend(start, end, amount):
    amount = max(0.0, min(1.0, amount))
    return tuple(
        int(start[channel] + (end[channel] - start[channel]) * amount)
        for channel in range(3)
    )


def _lay_snow(pixels, width, height, origin, card_width, step, index, tiled):
    """A wind-shaped drift centered on the gap, resting on both logos."""
    gap = step - card_width
    if gap < 6:
        return
    reach = min(_SNOW_REACH, max(0, card_width // 2))
    heights = _drift_heights(gap + 2 * reach, index)
    crest_at = max(range(len(heights)), key=lambda column: (heights[column], -column))
    lee_run = max(6, len(heights) - crest_at)
    for dx, pile in enumerate(heights):
        if pile <= 0:
            continue
        x = origin + card_width - reach + dx
        rows = min(pile, 8, height - 16)
        if rows <= 0:
            continue
        # The whole face on the far side of the crest is in shade, so the
        # pile reads as a solid drift instead of a row of striped columns.
        if dx <= crest_at:
            shade = 0.0
        else:
            shade = min(1.0, (dx - crest_at) / lee_run)
        left = heights[dx - 1] if dx else pile
        right = heights[dx + 1] if dx + 1 < len(heights) else pile
        crest = pile >= left and pile >= right and pile >= 4 and shade < 0.35
        for layer in range(rows):
            y = height - 1 - layer
            if y < 0:
                break
            from_top = rows - 1 - layer
            sparkle = (
                shade < 0.25
                and rows >= 6
                and from_top == 1
                and (index * 11 + dx * 5) % 17 == 0
            )
            color = _snow_color(from_top, rows, shade, crest, sparkle)
            _plot_snow(pixels, width, height, x, y, color, tiled)


def _plot_snow(pixels, width, height, x, y, color, tiled):
    if 0 <= y < height and 0 <= x < width:
        pixels[x, y] = color
    if not tiled:
        return
    if x >= width:
        wrapped = x - width
    elif x < 0:
        wrapped = x + width
    else:
        return
    if 0 <= wrapped < width:
        pixels[wrapped, y] = color


def _lamp(pixels, width, height, cx, cy, color, static_gain, twinkle):
    lit, core = _bulb_colors(color, static_gain, twinkle)
    for dx, dy in _LAMP:
        xx = cx + dx
        yy = cy + dy
        if not 0 <= xx < width or not 0 <= yy < height:
            continue
        pixels[xx, yy] = core if dx == 0 and dy == 0 else lit


def _bulb_colors(color, static_gain, twinkle):
    if twinkle <= 0:
        return (0, 0, 0), (0, 0, 0)
    amount = (0.35 + 0.65 * static_gain) * twinkle
    lit = _scale(color, amount)
    core = _mix(lit, (255, 255, 255), 0.28)
    return lit, core


def _twinkle_step(moment, index):
    """Stay lit. Each bulb dims briefly on its own slow clock."""
    period = 8.0 + (index % 7) * 0.7
    phase = (index * 0.61803398875) % 1.0
    local = (moment / period + phase) % 1.0
    # About half a second. The bulb stays colored, just quieter.
    if local < 0.5 / period:
        return 0.4
    return 1.0


def _lamp_list(width, height, spans):
    lamps = []
    for origin, card_width, step in spans:
        card_width = max(0, int(card_width))
        step = max(card_width, int(step))
        origin = int(origin)
        for local in range(step):
            x = origin + local
            if (x - _EVERY // 2) % _EVERY != 0 or not 0 <= x < width:
                continue
            index = x // _EVERY
            lamps.append({
                "x": x,
                "y": _wire_row(local, card_width, step) + 1,
                "index": index,
                "color": _STRING_BULBS[index % len(_STRING_BULBS)],
                "static": _GAINS[index % len(_GAINS)],
            })
    return lamps


def _mix(base, color, amount):
    return tuple(
        int(base[index] * (1 - amount) + color[index] * amount)
        for index in range(3)
    )
