"""Display timezone for game times.

The Raspberry Pi system timezone is not used. A timezone saved in the
app wins. Automatic mode asks a public IP lookup which zone this
network is in, and remembers the answer. UTC is only a stand-in until
that lookup succeeds.
"""

from __future__ import annotations

import json
import os
import threading
import time
from functools import lru_cache
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from common.http import get_body
from common.settings import SETTINGS_DIR, get_settings


AUTO_TIMEZONE = "auto"
FALLBACK_TIMEZONE = "UTC"
CACHE_FILE_NAME = "timezone.json"
FRESH_SECONDS = 12 * 60 * 60

# First match wins. worldtimeapi is omitted; it resets the connection here.
_DETECT_ENDPOINTS = (
    ("https://ipwho.is/", "ipwho"),
    ("https://ipapi.co/json/", "ipapi"),
    ("https://ipinfo.io/json", "ipinfo"),
)

COMMON_TIMEZONES = (
    ("America/New_York", "Eastern Time (New York)"),
    ("America/Chicago", "Central Time (Chicago)"),
    ("America/Denver", "Mountain Time (Denver)"),
    ("America/Phoenix", "Arizona (no daylight saving)"),
    ("America/Los_Angeles", "Pacific Time (Los Angeles)"),
    ("America/Anchorage", "Alaska"),
    ("Pacific/Honolulu", "Hawaii"),
    ("America/Puerto_Rico", "Atlantic Time (Puerto Rico)"),
    ("UTC", "UTC"),
)

_COMMON_LABELS = dict(COMMON_TIMEZONES)

_lock = threading.RLock()
_detect_lock = threading.Lock()
_memory_cache: dict[str, float | str] = {}
_refresh_started = False
_logged_network_name = ""
_logged_fallback = False


def is_valid_timezone(name: str) -> bool:
    text = str(name or "").strip()
    if not text or text.lower() == AUTO_TIMEZONE:
        return False
    try:
        ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def normalize_timezone_setting(value) -> str:
    """Return 'auto' or a real IANA zone name."""
    text = str(value or "").strip()
    if not text or text.lower() == AUTO_TIMEZONE:
        return AUTO_TIMEZONE
    if is_valid_timezone(text):
        return text
    return AUTO_TIMEZONE


def configured_timezone_name() -> str | None:
    """Manual zone from settings, or None when Automatic is selected."""
    try:
        raw = get_settings().get("timezone", AUTO_TIMEZONE)
    except Exception:
        return None
    text = normalize_timezone_setting(raw)
    if text == AUTO_TIMEZONE:
        return None
    return text


def timezone_label(name: str) -> str:
    return _COMMON_LABELS.get(name, str(name or "").replace("_", " "))


@lru_cache(maxsize=1)
def timezone_choice_groups() -> list[tuple[str, list[tuple[str, str]]]]:
    common_names = {name for name, _label in COMMON_TIMEZONES}
    groups: list[tuple[str, list[tuple[str, str]]]] = [
        ("Common", list(COMMON_TIMEZONES)),
    ]
    regions: dict[str, list[tuple[str, str]]] = {}
    for name in sorted(available_timezones()):
        if name in common_names:
            continue
        if name.startswith(("Etc/", "SystemV/", "posix/", "right/")):
            continue
        if "/" not in name:
            continue
        region = name.split("/", 1)[0]
        regions.setdefault(region, []).append(
            (name, name.replace("_", " "))
        )
    for region in sorted(regions):
        groups.append((region, regions[region]))
    return groups


def get_local_timezone():
    """Zone used for scoreboard dates and kickoff times."""
    manual = configured_timezone_name()
    if manual:
        return ZoneInfo(manual)

    cached = _cached_name()
    if cached:
        return ZoneInfo(cached)

    return ZoneInfo(FALLBACK_TIMEZONE)


def _parse_local_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None

    try:
        utc_dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)

    return utc_dt.astimezone(get_local_timezone())


def format_local_time(value):
    local_dt = _parse_local_datetime(value)
    if local_dt is None:
        return str(value or "")
    return local_dt.strftime("%-I:%M")


def format_local_date(value):
    local_dt = _parse_local_datetime(value)
    if local_dt is None:
        return ""
    return local_dt.strftime("%b %-d")


def timezone_status() -> dict[str, str]:
    manual = configured_timezone_name()
    cached = _cached_name()
    zone = get_local_timezone()
    name = getattr(zone, "key", str(zone))
    clock = datetime.now(zone).strftime("%-I:%M %p")
    label = timezone_label(name)

    if manual:
        source = "setting"
        detail = f"Game times use {label}. It is {clock}."
    elif cached:
        source = "network"
        detail = (
            f"Game times use {label}, detected from the network. "
            f"It is {clock}."
        )
    else:
        source = "fallback"
        detail = (
            "Could not detect a timezone from the network yet. "
            f"Times use UTC ({clock}) until detection works, "
            "or pick a timezone."
        )

    return {
        "setting": manual or AUTO_TIMEZONE,
        "effective": name,
        "source": source,
        "clock": clock,
        "detail": detail,
    }


def ensure_network_timezone(*, block: bool = True, timeout: float = 4.0) -> str | None:
    """Resolve Automatic mode. A saved timezone skips the network."""
    manual = configured_timezone_name()
    if manual:
        return manual

    cached = _load_cache()
    if cached and not _is_stale(cached):
        return str(cached["timezone"])

    if not block:
        return str(cached["timezone"]) if cached else None

    if not _detect_lock.acquire(timeout=max(0.1, timeout)):
        return str(cached["timezone"]) if cached else None

    try:
        cached = _load_cache()
        if cached and not _is_stale(cached):
            return str(cached["timezone"])

        detected = detect_timezone_name(timeout=timeout)
        if detected:
            _write_cache(detected)
            _log_network(detected)
            return detected

        if cached:
            return str(cached["timezone"])

        _log_fallback()
        return None
    finally:
        _detect_lock.release()


def detect_timezone_name(timeout: float = 8.0) -> str | None:
    deadline = time.monotonic() + max(0.5, timeout)
    for url, kind in _DETECT_ENDPOINTS:
        remaining = deadline - time.monotonic()
        if remaining < 0.3:
            break
        connect = min(2.0, remaining)
        read = min(3.0, remaining)
        try:
            body = get_body(url, (connect, read))
        except Exception:
            continue
        name = timezone_from_detection_body(kind, body)
        if name and is_valid_timezone(name):
            return name
    return None


def timezone_from_detection_body(kind: str, body: str) -> str | None:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    if kind == "ipwho":
        if data.get("success") is False:
            return None
        timezone = data.get("timezone")
        if isinstance(timezone, dict):
            return _clean_zone_name(timezone.get("id"))
        return None

    if data.get("error") is True:
        return None
    return _clean_zone_name(data.get("timezone"))


def start_timezone_refresh() -> None:
    """Keep an Automatic timezone fresh without blocking the board."""
    global _refresh_started
    with _lock:
        if _refresh_started:
            return
        _refresh_started = True

    thread = threading.Thread(
        target=_refresh_loop,
        name="timezone-refresh",
        daemon=True,
    )
    thread.start()


def clear_timezone_cache() -> None:
    """Drop the remembered network zone. Used by tests."""
    global _logged_network_name, _logged_fallback
    with _lock:
        _memory_cache.clear()
        _logged_network_name = ""
        _logged_fallback = False
    try:
        _cache_path().unlink(missing_ok=True)
    except OSError:
        pass


def _refresh_loop() -> None:
    while True:
        delay = _next_delay()
        time.sleep(delay)
        try:
            if configured_timezone_name() is not None:
                continue
            cached = _load_cache()
            if cached and not _is_stale(cached):
                continue
            ensure_network_timezone(block=True, timeout=8)
        except Exception as error:
            print(f"Timezone refresh failed: {error}")


def _next_delay() -> float:
    if configured_timezone_name() is not None:
        return 15 * 60
    cached = _load_cache()
    if not cached or _is_stale(cached):
        return 60
    remaining = FRESH_SECONDS - _cache_age(cached)
    return max(60.0, remaining)


def _clean_zone_name(value) -> str | None:
    text = str(value or "").strip()
    if not text or any(character.isspace() for character in text):
        return None
    return text


def _cache_path():
    return SETTINGS_DIR / CACHE_FILE_NAME


def _cached_name() -> str | None:
    cached = _load_cache()
    if not cached:
        return None
    name = str(cached.get("timezone") or "")
    if is_valid_timezone(name):
        return name
    return None


def _load_cache() -> dict | None:
    with _lock:
        memory_name = str(_memory_cache.get("timezone") or "")
        if memory_name:
            return {
                "timezone": memory_name,
                "detected_at": float(_memory_cache.get("detected_at") or 0),
            }

    try:
        loaded = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(loaded, dict):
        return None

    name = str(loaded.get("timezone") or "").strip()
    if not is_valid_timezone(name):
        return None
    try:
        detected_at = float(loaded.get("detected_at") or 0)
    except (TypeError, ValueError):
        detected_at = 0.0

    with _lock:
        _memory_cache["timezone"] = name
        _memory_cache["detected_at"] = detected_at
    return {"timezone": name, "detected_at": detected_at}


def _write_cache(name: str) -> None:
    detected_at = time.time()
    payload = {
        "timezone": name,
        "detected_at": detected_at,
    }
    with _lock:
        _memory_cache["timezone"] = name
        _memory_cache["detected_at"] = detected_at

    path = _cache_path()
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _cache_age(cached: dict) -> float:
    try:
        detected_at = float(cached.get("detected_at") or 0)
    except (TypeError, ValueError):
        return FRESH_SECONDS
    if detected_at <= 0:
        return FRESH_SECONDS
    return max(0.0, time.time() - detected_at)


def _is_stale(cached: dict) -> bool:
    return _cache_age(cached) >= FRESH_SECONDS


def _log_network(name: str) -> None:
    global _logged_network_name, _logged_fallback
    with _lock:
        if _logged_network_name == name:
            return
        _logged_network_name = name
        _logged_fallback = False
    print(f"Display timezone: {name} (network)")


def _log_fallback() -> None:
    global _logged_fallback
    with _lock:
        if _logged_fallback:
            return
        _logged_fallback = True
    print("Display timezone: UTC until a network lookup succeeds")
