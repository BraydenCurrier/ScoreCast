from __future__ import annotations

import hashlib
import re
import threading
import time
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

from common.http import CA_BUNDLE, session
from common.logo_store import (
    get_selected_logo_variant,
    get_teams_with_logos,
    load_logo,
)


# Normalized ESPN/API label -> logo file identifiers to try, in order.
# Keys must be the output of _normalize_key().
BROADCAST_ALIASES = {
    "ABC": ("ABC",),
    "ACC NETWORK": ("ACCN",),
    "ACCN": ("ACCN",),
    "ACCNX": ("ACCNX", "ESPN_PLUS"),
    "ACC NETWORK EXTRA": ("ACCNX", "ESPN_PLUS"),
    "AMAZON": ("PRIMEVIDEO",),
    "AMAZON PRIME": ("PRIMEVIDEO",),
    "AMAZON PRIME VIDEO": ("PRIMEVIDEO",),
    "APPLE TV": ("APPLETV",),
    "APPLE TV PLUS": ("APPLETV",),
    "APPLETV": ("APPLETV",),
    "MLS SEASON PASS": ("APPLETV",),
    "BIG TEN NETWORK": ("BTN",),
    "BTN": ("BTN",),
    "CBS": ("CBS",),
    "CBS SPORTS": ("CBS",),
    "CBS SPORTS NETWORK": ("CBSSN",),
    "CBS SN": ("CBSSN",),
    "CBSSN": ("CBSSN",),
    "CW": ("CW",),
    "THE CW": ("CW",),
    "DAZN": ("DAZN",),
    "DISNEY PLUS": ("ESPN_PLUS",),
    "ESPN": ("ESPN",),
    "ESPN 2": ("ESPN2", "ESPN"),
    "ESPN2": ("ESPN2", "ESPN"),
    "ESPN DEPORTES": ("ESPN_DEPORTES", "ESPN"),
    "ESPND": ("ESPN_DEPORTES", "ESPN"),
    "ESPN PLUS": ("ESPN_PLUS",),
    "ESPNPLUS": ("ESPN_PLUS",),
    "ESPN UNLMTD": ("ESPN_PLUS",),
    "ESPN UNLIMITED": ("ESPN_PLUS",),
    "ESPNU": ("ESPNU",),
    "FANDANGO": ("FANDUEL",),
    "FANDUEL": ("FANDUEL",),
    "FANDUEL SPORTS NETWORK": ("FANDUEL",),
    "FLOSPORTS": ("FLOSPORTS",),
    "FOX": ("FOX",),
    "FOX ONE": ("FS1", "FOX"),
    "FOX SPORTS 1": ("FS1",),
    "FOX SPORTS 2": ("FS2",),
    "FOX DEPORTES": ("FOX",),
    "FS1": ("FS1",),
    "FS2": ("FS2",),
    "HBO MAX": ("MAX", "TNT"),
    "MAX": ("MAX", "TNT"),
    "ION": ("ION",),
    "MLS SEASONPASS": ("APPLETV",),
    "MOUNTAIN WEST PLUS": ("MW_PLUS",),
    "MW PLUS": ("MW_PLUS",),
    "NBA TV": ("NBATV",),
    "NBATV": ("NBATV",),
    "NBC": ("NBC",),
    "NETFLIX": ("NETFLIX",),
    "NFL NETWORK": ("NFL_NETWORK",),
    "NFL NET": ("NFL_NETWORK",),
    "NFLN": ("NFL_NETWORK",),
    "NFL REDZONE": ("NFL_REDZONE",),
    "NFL RED ZONE": ("NFL_REDZONE",),
    "NHL NETWORK": ("NHL_NETWORK",),
    "NHL NET": ("NHL_NETWORK",),
    "NHLN": ("NHL_NETWORK",),
    "PAC 12 NETWORK": ("PAC12",),
    "PAC12": ("PAC12",),
    "PARAMOUNT PLUS": ("PARAMOUNTPLUS",),
    "PARAMOUNTPLUS": ("PARAMOUNTPLUS",),
    "PEACOCK": ("PEACOCK", "NBC"),
    "PRIME VIDEO": ("PRIMEVIDEO",),
    "PRIMEVIDEO": ("PRIMEVIDEO",),
    "SEC NETWORK": ("SECN",),
    "SECN": ("SECN",),
    "SEC NETWORK PLUS": ("SECN_PLUS",),
    "SECN PLUS": ("SECN_PLUS",),
    "TBS": ("TBS",),
    "TELE": ("TELEMUNDO",),
    "TELEMUNDO": ("TELEMUNDO",),
    "TNT": ("TNT",),
    "TNT SPORTS": ("TNT",),
    "TRUTV": ("TRUTV",),
    "TUDN": ("TUDN",),
    "UNIVERSO": ("UNIVERSO",),
    "UNIVISION": ("UNIVISION",),
    "USA": ("USA",),
    "USA NET": ("USA",),
    "USA NETWORK": ("USA",),
    "YOUTUBE": ("YOUTUBE",),
    "YOUTUBE TV": ("YOUTUBE",),
    "BIG 12 PLUS": ("ESPN_PLUS",),
}

SKIP_LABELS = {
    "TBD",
    "NONE",
    "N A",
    "NA",
    "LOCAL",
    "REGIONAL",
    "STREAM",
    "STREAMING",
}

# The board is black, so a mark is kept inside the same slot the
# saved logos already use.
_MARK_WIDTH = 40
_MARK_HEIGHT = 14
_LOGO_CACHE_DIR = Path("/tmp/scorecast-broadcast-logos")
_LOGO_RETRY_SECONDS = 600
_logo_memory: dict[str, Image.Image | None] = {}
_logo_failures: dict[str, float] = {}
_logo_lock = threading.Lock()


def _normalize_key(value: str) -> str:
    text = str(value or "").upper().strip()
    text = text.replace("&", " AND ")
    text = text.replace("+", " PLUS ")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize_broadcast_label(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []

    parts = re.split(r"\s*(?:,|/|\||\band\b)\s*", text, flags=re.IGNORECASE)
    tokens = []
    for part in parts:
        cleaned = part.strip()
        if cleaned:
            tokens.append(cleaned)
    if not tokens:
        tokens = [text]
    return tokens


def _is_national_market(value) -> bool:
    if isinstance(value, dict):
        market_type = str(value.get("type") or value.get("id") or "").strip()
        return market_type.lower() == "national"
    text = str(value or "").strip().lower()
    return text == "national"


def _espn_logo_url(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host.endswith("espncdn.com"):
        return ""
    return text


def _entry_logo(entry) -> str:
    """Logo meant for a dark board. ESPN calls that version darkLogo."""
    if not isinstance(entry, dict):
        return ""
    media = entry.get("media")
    if not isinstance(media, dict):
        return ""
    for key in ("darkLogo", "logo"):
        url = _espn_logo_url(media.get(key))
        if url:
            return url
    return ""


def _add_label(bucket, seen, raw, *, national: bool, logo: str = ""):
    for token in _tokenize_broadcast_label(str(raw or "")):
        key = _normalize_key(token)
        if not key or key in SKIP_LABELS:
            continue
        if key.endswith(" APP"):
            continue
        if key in seen:
            index = seen[key]
            label, is_national, existing = bucket[index]
            if logo and not existing:
                bucket[index] = (label, is_national, logo)
            continue
        seen[key] = len(bucket)
        bucket.append((token.strip(), national, logo))


def _collect_from_broadcast_entry(entry, bucket, seen):
    if isinstance(entry, str):
        _add_label(bucket, seen, entry, national=True)
        return

    if not isinstance(entry, dict):
        return

    national = _is_national_market(entry.get("market"))
    logo = _entry_logo(entry)
    names = entry.get("names", [])
    if isinstance(names, str):
        names = [names]
    if isinstance(names, list):
        for name in names:
            _add_label(bucket, seen, name, national=national, logo=logo)

    media = entry.get("media")
    if isinstance(media, dict):
        _add_label(
            bucket,
            seen,
            media.get("shortName") or media.get("name"),
            national=national,
            logo=logo,
        )
    elif isinstance(media, str):
        _add_label(bucket, seen, media, national=national, logo=logo)

    for key in ("shortName", "name", "callLetters"):
        if entry.get(key):
            _add_label(bucket, seen, entry.get(key), national=national, logo=logo)


def _ordered_broadcasts(event=None, competition=None) -> list[tuple[str, str]]:
    bucket: list[tuple[str, bool, str]] = []
    seen: dict[str, int] = {}

    for source in (competition, event):
        if not isinstance(source, dict):
            continue

        if source.get("broadcast"):
            _add_label(
                bucket,
                seen,
                source.get("broadcast"),
                national=True,
            )

        for key in ("broadcasts", "geoBroadcasts"):
            entries = source.get(key, [])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                _collect_from_broadcast_entry(entry, bucket, seen)

    national = [(label, logo) for label, is_national, logo in bucket if is_national]
    regional = [(label, logo) for label, is_national, logo in bucket if not is_national]
    return national + regional


def extract_broadcast_labels(event=None, competition=None) -> list[str]:
    return [label for label, _logo in _ordered_broadcasts(event, competition)]


def format_broadcast(event=None, competition=None) -> str:
    labels = extract_broadcast_labels(event, competition)
    return ", ".join(labels[:3])


def broadcast_logo_url(event=None, competition=None) -> str:
    """ESPN logo for the network shown first, when that network has one."""
    ordered = _ordered_broadcasts(event, competition)
    if not ordered:
        return ""
    return ordered[0][1]


def game_logo_url(game) -> str:
    return str(getattr(game, "broadcast_logo", "") or "").strip()


@lru_cache(maxsize=1)
def available_broadcast_ids() -> frozenset[str]:
    return frozenset(get_teams_with_logos("broadcast"))


def _sanitized_identifier(token: str) -> str:
    text = str(token or "").strip().upper()
    text = text.replace("+", "_PLUS")
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def broadcast_candidates(raw: str) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def add(identifier: str):
        ident = str(identifier or "").strip().upper()
        if not ident or ident in seen:
            return
        seen.add(ident)
        ordered.append(ident)

    for token in _tokenize_broadcast_label(raw):
        key = _normalize_key(token)
        for ident in BROADCAST_ALIASES.get(key, ()):
            add(ident)
        add(_sanitized_identifier(token))
        compact = key.replace(" ", "")
        if compact:
            add(compact)

    return ordered


def resolve_broadcast_identifier(raw: str) -> str | None:
    available = available_broadcast_ids()
    if not raw or not available:
        return None

    for identifier in broadcast_candidates(raw):
        if identifier in available:
            return identifier

    return None


def _fit_broadcast_mark(logo: Image.Image) -> Image.Image | None:
    logo = logo.convert("RGBA")
    bounds = logo.getbbox()
    if not bounds:
        return None
    logo = logo.crop(bounds)

    opaque = [pixel for pixel in logo.getdata() if pixel[3] >= 40]
    if opaque:
        dark = sum(1 for red, green, blue, _alpha in opaque if max(red, green, blue) < 48)
        if dark / len(opaque) > 0.75:
            lifted = []
            for red, green, blue, alpha in logo.getdata():
                if alpha < 20:
                    lifted.append((0, 0, 0, 0))
                elif max(red, green, blue) < 48:
                    lifted.append((255, 255, 255, alpha))
                else:
                    lifted.append((red, green, blue, alpha))
            logo.putdata(lifted)

    scale = min(_MARK_WIDTH / logo.width, _MARK_HEIGHT / logo.height)
    size = (
        max(1, round(logo.width * scale)),
        max(1, round(logo.height * scale)),
    )
    if size != logo.size:
        logo = logo.resize(size, Image.Resampling.LANCZOS)
    return logo


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return _LOGO_CACHE_DIR / f"{digest}.png"


def _read_cached_logo(url: str) -> bytes | None:
    path = _cache_path(url)
    try:
        if path.is_file():
            return path.read_bytes()
    except OSError:
        return None
    return None


def _download_logo(url: str) -> bytes | None:
    try:
        response = session().get(
            url,
            timeout=(3.05, 8),
            verify=CA_BUNDLE,
            headers={"Accept": "image/png,image/*"},
        )
    except OSError:
        return None
    if response.status_code >= 400 or not response.content:
        return None
    try:
        _LOGO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(url).write_bytes(response.content)
    except OSError:
        pass
    return response.content


def _espn_logo(url: str) -> Image.Image | None:
    url = _espn_logo_url(url)
    if not url:
        return None

    with _logo_lock:
        cached = _logo_memory.get(url)
        if url in _logo_memory:
            return None if cached is None else cached.copy()
        failed_at = _logo_failures.get(url)
        if failed_at is not None and time.monotonic() - failed_at < _LOGO_RETRY_SECONDS:
            return None

    raw = _read_cached_logo(url)
    if raw is None:
        raw = _download_logo(url)
    logo = None
    if raw:
        try:
            with Image.open(BytesIO(raw)) as source:
                parsed = source.convert("RGBA")
                parsed.load()
            logo = _fit_broadcast_mark(parsed)
        except (OSError, ValueError):
            logo = None

    with _logo_lock:
        if logo is None:
            _logo_failures[url] = time.monotonic()
            _logo_memory.pop(url, None)
            return None
        _logo_failures.pop(url, None)
        _logo_memory[url] = logo
        return logo.copy()


def broadcast_logo_image(broadcast, settings=None, logo_url: str = ""):
    """ESPN's mark when the game has one, otherwise the saved logo."""
    url = _espn_logo_url(logo_url)
    if url:
        logo = _espn_logo(url)
        if logo is not None:
            return logo

    identifier = resolve_broadcast_identifier(broadcast)
    if not identifier:
        return None

    try:
        variant = get_selected_logo_variant(
            settings or {},
            "broadcast",
            identifier,
        )
        logo = load_logo(
            league="broadcast",
            identifier=identifier,
            variant=variant,
        )
    except (FileNotFoundError, ValueError, OSError, KeyError):
        return None
    return logo.copy()


def draw_broadcast_logo(image, broadcast, x, y, settings, logo_url: str = ""):
    if not broadcast and not logo_url:
        return False

    logo = broadcast_logo_image(broadcast, settings, logo_url)
    if logo is None:
        return False

    image.paste(
        logo,
        (x - logo.width // 2, y - logo.height // 2),
        logo,
    )
    return True
