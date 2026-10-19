from __future__ import annotations

from PIL import Image, ImageDraw

from common.fonts import print_4x5, print_gfx_5x7
from setup.qr import dashboard_payload, draw_qr, wifi_payload
from setup.state import (
    PHASE_ACCOUNT,
    PHASE_CONNECTING,
    PHASE_HOMESCREEN,
    PHASE_HOTSPOT,
    PHASE_STARTING,
    load_setup_state,
)

NAVY = (11, 17, 32)
BLUE = (37, 99, 235)
CYAN = (0, 212, 255)
WHITE = (248, 250, 252)
GREY = (100, 116, 139)


def _text_block(draw, lines, x, y):
    cursor = y
    for text, color, kind in lines:
        if kind == "5x7":
            print_gfx_5x7(draw, text, x, cursor, color)
            cursor += 9
        else:
            print_4x5(draw, text, x, cursor, color)
            cursor += 7
    return cursor


def render_setup_display(width=384, height=32) -> Image.Image:
    state = load_setup_state()
    phase = state.get("phase") or PHASE_STARTING
    image = Image.new("RGB", (width, height), NAVY)
    draw = ImageDraw.Draw(image)

    if phase == PHASE_HOTSPOT:
        ssid = str(state.get("ssid") or "GAMELINE")
        size = draw_qr(image, wifi_payload(ssid), x=1, y=1)
        _text_block(
            draw,
            (
                ("SCAN", CYAN, "5x7"),
                ("WIFI", WHITE, "5x7"),
                (ssid.upper()[:18], GREY, "4x5"),
            ),
            size + 4,
            3,
        )
        return image

    if phase in {PHASE_HOMESCREEN, PHASE_ACCOUNT}:
        url = dashboard_payload(state.get("dashboard_url") or "")
        if url:
            size = draw_qr(image, url, x=1, y=1)
        else:
            size = 31
        ip_address = str(state.get("lan_ip") or "").upper()
        label = "APP" if phase == PHASE_HOMESCREEN else "SETUP"
        _text_block(
            draw,
            (
                ("SCAN", CYAN, "5x7"),
                (label, WHITE, "5x7"),
                ((ip_address or "PHONE")[:18], GREY, "4x5"),
            ),
            size + 4,
            3,
        )
        return image

    caption = {
        PHASE_CONNECTING: "CONNECTING",
        PHASE_STARTING: "SETUP",
    }.get(phase, "SETUP")

    print_gfx_5x7(draw, "GAMELINE", 12, 7, BLUE)
    print_4x5(draw, caption, 12, 19, CYAN)
    return image
