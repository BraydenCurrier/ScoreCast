"""A designed message for the 384x32 board."""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, UnidentifiedImageError

from common.fonts import gfx_5x7_width, get_4x5_width, print_4x5, print_gfx_5x7
from common.settings import SETTINGS_DIR


BOARD_WIDTH = 384
BOARD_HEIGHT = 32
MAX_STRIP = 2048
MAX_X = 1600
MAX_ITEMS = 40
MAX_TEXT = 64
MAX_IMAGES = 16
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_SOURCE_PIXELS = 4000
LOOP_GAP = 48
SPEED_MIN = 5
SPEED_MAX = 120

MESSAGE_DIR = SETTINGS_DIR / "messages"

_ID = re.compile(r"^[a-f0-9]{8}$")
_IMAGE_ID = re.compile(r"^[a-f0-9]{16}$")

_cache_lock = threading.Lock()
_cache_key = None
_cache_strip = None


class MessageError(ValueError):
    """Raised when a message image cannot be saved."""


def empty_message():
    return {
        "enabled": False,
        "scroll": True,
        "speed": 30,
        "background": "#000000",
        "items": [],
    }


def _color(value, default="#ffffff"):
    text = str(value or "").strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", text):
        return text.lower()
    if re.fullmatch(r"#[0-9A-Fa-f]{3}", text):
        doubled = "".join(character * 2 for character in text[1:])
        return f"#{doubled.lower()}"
    return default


def _rgb(value):
    text = _color(value)
    return tuple(int(text[index:index + 2], 16) for index in (1, 3, 5))


def _number(value, default, low, high):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _item_id(value):
    text = str(value or "").strip().lower()
    if _ID.fullmatch(text):
        return text
    return ""


def _image_id(value):
    text = str(value or "").strip().lower()
    if _IMAGE_ID.fullmatch(text):
        return text
    return ""


def _normalize_item(raw):
    if not isinstance(raw, dict):
        return None
    item_id = _item_id(raw.get("id")) or secrets.token_hex(4)
    kind = str(raw.get("kind") or "").strip().lower()
    x = _number(raw.get("x"), 0, 0, MAX_X)
    y = _number(raw.get("y"), 0, 0, BOARD_HEIGHT - 1)
    if kind == "image":
        image_id = _image_id(raw.get("image"))
        if not image_id:
            return None
        return {
            "id": item_id,
            "kind": "image",
            "image": image_id,
            "x": x,
            "y": y,
        }
    if kind != "text":
        return None
    text = str(raw.get("text") or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip().upper()[:MAX_TEXT]
    font = str(raw.get("font") or "5x7").strip().lower()
    if font not in {"5x7", "4x5"}:
        font = "5x7"
    return {
        "id": item_id,
        "kind": "text",
        "text": text,
        "x": x,
        "y": y,
        "color": _color(raw.get("color")),
        "font": font,
    }


def normalize_message(raw):
    if not isinstance(raw, dict):
        raw = {}
    items = []
    seen = set()
    for item in raw.get("items") or []:
        normalized = _normalize_item(item)
        if normalized is None or normalized["id"] in seen:
            continue
        seen.add(normalized["id"])
        items.append(normalized)
        if len(items) >= MAX_ITEMS:
            break
    scroll = raw.get("scroll", True)
    return {
        "enabled": bool(raw.get("enabled")),
        "scroll": True if scroll is True else str(scroll).strip().lower() in {"1", "true", "yes", "on"},
        "speed": _number(raw.get("speed"), 30, SPEED_MIN, SPEED_MAX),
        "background": _color(raw.get("background"), "#000000"),
        "items": items,
    }


def message_from_settings(settings):
    raw = settings.get("message") if isinstance(settings, dict) else None
    return normalize_message(raw)


def message_from_form(form):
    """Build a message from the design form fields."""
    items = []
    for raw_id in form.getlist("item"):
        item_id = _item_id(raw_id)
        if not item_id:
            continue
        kind = str(form.get(f"kind_{item_id}") or "").strip().lower()
        items.append({
            "id": item_id,
            "kind": kind,
            "text": form.get(f"text_{item_id}") or "",
            "image": form.get(f"image_{item_id}") or "",
            "x": form.get(f"x_{item_id}"),
            "y": form.get(f"y_{item_id}"),
            "color": form.get(f"color_{item_id}") or "",
            "font": form.get(f"font_{item_id}") or "",
        })
    return normalize_message({
        "enabled": form.get("enabled") == "1",
        "scroll": form.get("scroll") == "1",
        "speed": form.get("speed"),
        "background": form.get("background") or "",
        "items": items,
    })


def message_token(message):
    payload = repr(normalize_message(message)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def text_width(item):
    text = str(item.get("text") or "")
    if not text:
        return 0
    if item.get("font") == "4x5":
        return max(get_4x5_width(text), 0)
    return max(gfx_5x7_width(text), 0)


def image_path(image_id):
    image_id = _image_id(image_id)
    if not image_id:
        return None
    path = (MESSAGE_DIR / f"{image_id}.png").resolve()
    try:
        path.relative_to(MESSAGE_DIR.resolve())
    except ValueError:
        return None
    return path


def list_images():
    if not MESSAGE_DIR.is_dir():
        return []
    found = []
    for path in sorted(MESSAGE_DIR.glob("*.png")):
        image_id = _image_id(path.stem)
        if image_id and path.is_file():
            found.append(image_id)
    return found


def _open_image(image_id):
    path = image_path(image_id)
    if path is None or not path.is_file():
        return None
    try:
        with Image.open(path) as source:
            image = source.convert("RGBA")
            image.load()
        return image
    except (OSError, ValueError):
        return None


def content_right(message):
    right = 0
    for item in message.get("items") or []:
        if item.get("kind") == "text":
            width = text_width(item)
        else:
            image = _open_image(item.get("image"))
            width = image.width if image is not None else 0
        right = max(right, int(item.get("x") or 0) + width)
    return right


def strip_width(message):
    if not message.get("scroll"):
        return BOARD_WIDTH
    right = content_right(message)
    if right <= 0:
        return BOARD_WIDTH
    return min(MAX_STRIP, max(right + LOOP_GAP, BOARD_WIDTH))


def render_strip(message):
    message = normalize_message(message)
    width = strip_width(message)
    strip = Image.new("RGB", (width, BOARD_HEIGHT), _rgb(message["background"]))
    draw = ImageDraw.Draw(strip)
    for item in message["items"]:
        if item["kind"] == "text":
            if not item["text"]:
                continue
            color = _rgb(item["color"])
            if item["font"] == "4x5":
                print_4x5(draw, item["text"], item["x"], item["y"], color)
            else:
                print_gfx_5x7(draw, item["text"], item["x"], item["y"], color)
            continue
        image = _open_image(item["image"])
        if image is None:
            continue
        strip.paste(image, (item["x"], item["y"]), image)
    return strip


def render_frame(message, offset=0):
    message = normalize_message(message)
    strip = render_strip(message)
    frame = Image.new("RGB", (BOARD_WIDTH, BOARD_HEIGHT), _rgb(message["background"]))
    if not message["scroll"]:
        frame.paste(strip.crop((0, 0, BOARD_WIDTH, BOARD_HEIGHT)), (0, 0))
        return frame
    width = strip.width
    if width <= 0:
        return frame
    shift = int(offset) % width
    frame.paste(strip, (-shift, 0))
    frame.paste(strip, (-shift + width, 0))
    return frame


def _signature(message):
    parts = [message_token(message)]
    for image_id in list_images():
        path = image_path(image_id)
        try:
            parts.append(f"{image_id}:{path.stat().st_mtime_ns}")
        except OSError:
            parts.append(image_id)
    return tuple(parts)


def render_message_frame(settings, now):
    """384x32 frame, or None when the message is off."""
    global _cache_key, _cache_strip

    message = message_from_settings(settings)
    if not message["enabled"]:
        return None
    key = _signature(message)
    with _cache_lock:
        if key != _cache_key or _cache_strip is None:
            try:
                strip = render_strip(message)
            except (OSError, ValueError):
                _cache_key = key
                _cache_strip = None
                return None
            _cache_key = key
            _cache_strip = strip
        strip = _cache_strip
    if strip is None:
        return None
    if not message["scroll"]:
        offset = 0
    else:
        offset = int(float(now) * message["speed"]) % max(strip.width, 1)
    frame = Image.new("RGB", (BOARD_WIDTH, BOARD_HEIGHT), _rgb(message["background"]))
    if not message["scroll"]:
        frame.paste(strip.crop((0, 0, min(strip.width, BOARD_WIDTH), BOARD_HEIGHT)), (0, 0))
        return frame
    shift = int(offset) % strip.width
    frame.paste(strip, (-shift, 0))
    frame.paste(strip, (-shift + strip.width, 0))
    return frame


def new_item_id():
    return secrets.token_hex(4)


def render_play_strip(message):
    """The design, repeated once so a scrolling preview can loop."""
    message = normalize_message(message)
    strip = render_strip(message)
    if not message["scroll"]:
        return strip
    loop = Image.new("RGB", (strip.width * 2, BOARD_HEIGHT), _rgb(message["background"]))
    loop.paste(strip, (0, 0))
    loop.paste(strip, (strip.width, 0))
    return loop


def clear_message_cache():
    global _cache_key, _cache_strip
    with _cache_lock:
        _cache_key = None
        _cache_strip = None


def save_message_image(payload: bytes) -> str:
    if not payload:
        raise MessageError("Choose an image file to upload.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise MessageError("That image is too large. Use a file under 2 MB.")
    if len(list_images()) >= MAX_IMAGES:
        raise MessageError("The board already has 16 images. Delete one first.")
    try:
        with Image.open(BytesIO(payload)) as source:
            source.seek(0)
            source.load()
            width, height = source.size
            if width < 1 or height < 1:
                raise MessageError("That image could not be read.")
            if width > MAX_SOURCE_PIXELS or height > MAX_SOURCE_PIXELS:
                raise MessageError("That image is too large.")
            image = source.convert("RGBA")
    except UnidentifiedImageError as error:
        raise MessageError("Use a PNG, JPEG, WebP, or GIF image.") from error
    except OSError as error:
        raise MessageError("That image could not be read.") from error

    image.thumbnail((BOARD_WIDTH, BOARD_HEIGHT), Image.Resampling.LANCZOS)
    image_id = secrets.token_hex(8)
    MESSAGE_DIR.mkdir(parents=True, exist_ok=True)
    image.save(MESSAGE_DIR / f"{image_id}.png", format="PNG")
    clear_message_cache()
    return image_id


def delete_message_image(image_id):
    path = image_path(image_id)
    if path is None or not path.is_file():
        raise MessageError("That image was not found.")
    path.unlink()
    clear_message_cache()


def drop_image_items(message, image_id):
    image_id = _image_id(image_id)
    message = normalize_message(message)
    message["items"] = [
        item for item in message["items"]
        if item.get("image") != image_id
    ]
    return message
