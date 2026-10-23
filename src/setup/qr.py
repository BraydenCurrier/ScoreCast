from __future__ import annotations

from PIL import Image

NAVY = (11, 17, 32)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

MAX_MODULES = 29


def escape_wifi_text(value: str) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace(":", "\\:")
        .replace('"', '\\"')
    )


def wifi_payload(ssid: str, password: str = "") -> str:
    name = escape_wifi_text(ssid)
    secret = escape_wifi_text(password)
    if secret:
        return f"WIFI:T:WPA;S:{name};P:{secret};;"
    return f"WIFI:T:nopass;S:{name};;"


def dashboard_payload(url: str) -> str:
    return str(url or "").strip()


def qr_matrix(payload: str, max_modules: int = MAX_MODULES):
    text = str(payload or "").strip()
    if not text:
        raise ValueError("QR payload is empty")

    import segno

    qr = None
    last_error = None
    for error in ("m", "l"):
        try:
            qr = segno.make(text, error=error, micro=False)
            if qr.symbol_size(border=0)[0] <= max_modules:
                break
        except Exception as exc:
            last_error = exc
            qr = None

    if qr is None:
        raise ValueError(f"Could not encode QR: {last_error}")

    size = qr.symbol_size(border=0)[0]
    if size > max_modules:
        raise ValueError(f"QR is {size} modules; max is {max_modules}")

    return tuple(tuple(bool(cell) for cell in row) for row in qr.matrix)


def draw_qr(
    image: Image.Image,
    payload: str,
    x: int = 1,
    y: int = 1,
    max_modules: int = MAX_MODULES,
) -> int:
    """Draw a high-contrast QR and return its outer size in pixels."""
    matrix = qr_matrix(payload, max_modules=max_modules)
    modules = len(matrix)
    quiet = 1
    outer = modules + quiet * 2

    for row in range(outer):
        for col in range(outer):
            image.putpixel((x + col, y + row), WHITE)

    for row, line in enumerate(matrix):
        for col, dark in enumerate(line):
            if dark:
                image.putpixel(
                    (x + quiet + col, y + quiet + row),
                    BLACK,
                )

    return outer
