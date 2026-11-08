"""Current conditions for the clock standby screen.

A saved city or ZIP wins. Otherwise the public IP is located with the
same lookup services the timezone detector uses. Open-Meteo supplies
the temperature and condition. The board reads a cached line and never
waits on the network.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from urllib.parse import urlencode

from common.http import get_body
from common.settings import SETTINGS_DIR, get_settings


# Same public IP lookups as common.timezone. Each body is parsed for a
# city and coordinates, which that module does not keep.
_DETECT_ENDPOINTS = (
    ("https://ipwho.is/", "ipwho"),
    ("https://ipapi.co/json/", "ipapi"),
    ("https://ipinfo.io/json", "ipinfo"),
)

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_ZIP_URL = "https://api.zippopotam.us/us/"

CACHE_FILE_NAME = "weather.json"
PLACE_FRESH_SECONDS = 12 * 60 * 60
WEATHER_FRESH_SECONDS = 15 * 60
# Keep the last good reading through a short outage.
SHOW_SECONDS = 2 * 60 * 60
LOOP_SECONDS = 60.0
LOCATION_SETTING_SECONDS = 2.0

_CONDITIONS = {
    0: "CLEAR",
    1: "FAIR",
    2: "CLOUDY",
    3: "OVERCAST",
    45: "FOG",
    48: "FOG",
    51: "DRIZZLE",
    53: "DRIZZLE",
    55: "DRIZZLE",
    56: "FREEZING",
    57: "FREEZING",
    61: "RAIN",
    63: "RAIN",
    65: "RAIN",
    66: "FREEZING",
    67: "FREEZING",
    71: "SNOW",
    73: "SNOW",
    75: "SNOW",
    77: "SNOW",
    80: "SHOWERS",
    81: "SHOWERS",
    82: "SHOWERS",
    85: "SNOW",
    86: "SNOW",
    95: "STORM",
    96: "HAIL",
    99: "HAIL",
}

_lock = threading.RLock()
_refresh_lock = threading.Lock()
_wake = threading.Event()
_started = False
_loaded = False
_logged_line = ""
_location_value = ""
_location_checked_at = 0.0

_state: dict[str, object] = {
    "place_key": "",
    "name": "",
    "region": "",
    "latitude": None,
    "longitude": None,
    "source": "",
    "located_at": 0.0,
    "temperature": None,
    "condition": "",
    "fetched_at": 0.0,
    "error": "",
}


def normalize_weather_location(value) -> str:
    text = " ".join(str(value or "").split())
    text = "".join(char for char in text if char.isprintable())
    return text[:80]


def configured_location(*, fresh: bool = False) -> str:
    """Saved place. Blank means follow the network."""
    global _location_value, _location_checked_at
    now = time.monotonic()
    with _lock:
        if (
            not fresh
            and _location_checked_at
            and now - _location_checked_at < LOCATION_SETTING_SECONDS
        ):
            return _location_value

    value = _read_location_setting()
    with _lock:
        _location_value = value
        _location_checked_at = now
    return value


def standby_weather():
    """(place, temperature, condition) for the idle clock, or None."""
    _ensure_loaded()
    manual = configured_location()
    with _lock:
        snapshot = dict(_state)
    if snapshot.get("place_key") != _wanted_key(manual):
        return None
    if not _readable(snapshot):
        return None
    place = board_place(snapshot.get("name") or "")
    return (
        place,
        str(int(snapshot["temperature"])),
        str(snapshot.get("condition") or ""),
    )


def weather_status() -> dict[str, str]:
    _ensure_loaded()
    manual = configured_location(fresh=True)
    with _lock:
        snapshot = dict(_state)
    return _status_payload(snapshot, manual)


def request_weather_refresh() -> None:
    """Ask the background loop to look up again."""
    global _location_checked_at
    with _lock:
        _location_checked_at = 0.0
    _wake.set()


def start_weather_refresh() -> None:
    """Keep the standby conditions fresh without blocking the board."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    _ensure_loaded()
    thread = threading.Thread(
        target=_refresh_loop,
        name="weather-refresh",
        daemon=True,
    )
    thread.start()


def refresh_weather() -> None:
    """One lookup. Safe to call from tests and from the refresh thread."""
    if not _refresh_lock.acquire(blocking=False):
        return
    try:
        _refresh_unlocked()
    finally:
        _refresh_lock.release()


def clear_weather_cache() -> None:
    """Drop the remembered place and reading. Used by tests."""
    global _loaded, _logged_line, _location_checked_at, _location_value
    with _lock:
        _reset_state()
        _loaded = True
        _logged_line = ""
        _location_value = ""
        _location_checked_at = 0.0
    try:
        _cache_path().unlink(missing_ok=True)
    except OSError:
        pass


def condition_label(code) -> str:
    try:
        number = int(code)
    except (TypeError, ValueError):
        return ""
    return _CONDITIONS.get(number, "")


def board_place(name) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(
        char for char in text if not unicodedata.combining(char)
    )
    cleaned = []
    for char in text.upper():
        if char.isalnum() or char == " ":
            cleaned.append(char)
        else:
            cleaned.append(" ")
    return " ".join("".join(cleaned).split())[:18]


def location_from_detection_body(kind: str, body: str):
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    if kind == "ipwho":
        if data.get("success") is False:
            return None
        return _place(
            data.get("city"),
            data.get("region"),
            data.get("latitude"),
            data.get("longitude"),
            "network",
        )

    if kind == "ipapi":
        if data.get("error") is True:
            return None
        return _place(
            data.get("city"),
            data.get("region"),
            data.get("latitude"),
            data.get("longitude"),
            "network",
        )

    if data.get("error") is True:
        return None
    latitude, longitude = _split_loc(data.get("loc"))
    return _place(
        data.get("city"),
        data.get("region"),
        latitude,
        longitude,
        "network",
    )


def place_from_geocode_body(body: str):
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    if not isinstance(first, dict):
        return None
    return _place(
        first.get("name"),
        first.get("admin1"),
        first.get("latitude"),
        first.get("longitude"),
        "setting",
    )


def place_from_zip_body(body: str):
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    places = data.get("places")
    if not isinstance(places, list) or not places:
        return None
    first = places[0]
    if not isinstance(first, dict):
        return None
    return _place(
        first.get("place name"),
        first.get("state"),
        first.get("latitude"),
        first.get("longitude"),
        "setting",
    )


def reading_from_forecast_body(body: str):
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    current = data.get("current")
    if not isinstance(current, dict):
        return None
    try:
        temperature = int(round(float(current.get("temperature_2m"))))
    except (TypeError, ValueError):
        return None
    if temperature < -80 or temperature > 140:
        return None
    return {
        "temperature": temperature,
        "condition": condition_label(current.get("weather_code")),
    }


def _refresh_loop() -> None:
    while True:
        try:
            refresh_weather()
        except Exception as error:
            print(f"Weather refresh failed: {error}")
        if _wake.wait(LOOP_SECONDS):
            _wake.clear()


def _refresh_unlocked() -> None:
    manual = configured_location(fresh=True)
    wanted = _wanted_key(manual)
    place = _current_place(wanted)
    if place is None or _place_is_stale(place):
        located = _locate(manual)
        if located is None:
            _mark_lookup_failed(wanted, manual)
            return
        place = located

    if not _weather_is_stale(place):
        return

    reading = _fetch_reading(place["latitude"], place["longitude"])
    if reading is None:
        _mark_weather_failed(place, wanted)
        return

    _store_reading(place, wanted, reading)
    _log_line(place, reading)


def _locate(manual: str):
    if manual:
        return _locate_manual(manual)
    return _locate_network()


def _locate_manual(query: str):
    if _is_zip(query):
        body = _get(_ZIP_URL + query[:5])
        if body:
            place = place_from_zip_body(body)
            if place:
                return place
    body = _get(_GEOCODE_URL + "?" + urlencode({
        "name": query,
        "count": "1",
        "language": "en",
        "format": "json",
    }))
    if not body:
        return None
    return place_from_geocode_body(body)


def _locate_network():
    for url, kind in _DETECT_ENDPOINTS:
        body = _get(url)
        if not body:
            continue
        place = location_from_detection_body(kind, body)
        if place:
            return place
    return None


def _fetch_reading(latitude, longitude):
    body = _get(_FORECAST_URL + "?" + urlencode({
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "current": "temperature_2m,weather_code",
        "temperature_unit": "fahrenheit",
        "forecast_days": "1",
    }))
    if not body:
        return None
    return reading_from_forecast_body(body)


def _get(url: str) -> str | None:
    try:
        return get_body(url, (2.0, 4.0))
    except Exception:
        return None


def _current_place(wanted: str):
    with _lock:
        if _state.get("place_key") != wanted:
            return None
        latitude = _state.get("latitude")
        longitude = _state.get("longitude")
        if latitude is None or longitude is None:
            return None
        return {
            "name": _state.get("name") or "",
            "region": _state.get("region") or "",
            "latitude": latitude,
            "longitude": longitude,
            "source": _state.get("source") or "",
            "located_at": float(_state.get("located_at") or 0),
            "fetched_at": float(_state.get("fetched_at") or 0),
            "temperature": _state.get("temperature"),
        }


def _place_is_stale(place: dict) -> bool:
    return _age(place.get("located_at")) >= PLACE_FRESH_SECONDS


def _weather_is_stale(place: dict) -> bool:
    if place.get("temperature") is None:
        return True
    return _age(place.get("fetched_at")) >= WEATHER_FRESH_SECONDS


def _mark_lookup_failed(wanted: str, manual: str) -> None:
    with _lock:
        if _state.get("place_key") == wanted and _readable(_state):
            _state["error"] = ""
            _write_cache()
            return
        _state["place_key"] = wanted
        _state["name"] = ""
        _state["region"] = ""
        _state["latitude"] = None
        _state["longitude"] = None
        _state["source"] = "setting" if manual else "network"
        _state["temperature"] = None
        _state["condition"] = ""
        _state["fetched_at"] = 0.0
        _state["error"] = "not_found" if manual else "network"
        _write_cache()


def _mark_weather_failed(place: dict, wanted: str) -> None:
    with _lock:
        if _state.get("place_key") == wanted and _readable(_state):
            return
        _state["place_key"] = wanted
        _state["name"] = place.get("name") or ""
        _state["region"] = place.get("region") or ""
        _state["latitude"] = place["latitude"]
        _state["longitude"] = place["longitude"]
        _state["source"] = place.get("source") or ""
        _state["located_at"] = float(place.get("located_at") or 0) or time.time()
        _state["temperature"] = None
        _state["condition"] = ""
        _state["fetched_at"] = 0.0
        _state["error"] = "weather"
        _write_cache()


def _store_reading(place: dict, wanted: str, reading: dict) -> None:
    now = time.time()
    with _lock:
        _state["place_key"] = wanted
        _state["name"] = place.get("name") or ""
        _state["region"] = place.get("region") or ""
        _state["latitude"] = place["latitude"]
        _state["longitude"] = place["longitude"]
        _state["source"] = place.get("source") or ""
        _state["located_at"] = float(place.get("located_at") or 0) or now
        _state["temperature"] = reading["temperature"]
        _state["condition"] = reading["condition"]
        _state["fetched_at"] = now
        _state["error"] = ""
        _write_cache()


def _log_line(place: dict, reading: dict) -> None:
    global _logged_line
    condition = reading["condition"] or "UNKNOWN"
    line = (
        f"{place.get('name') or 'there'} "
        f"{reading['temperature']}F {condition.lower()} "
        f"({place.get('source') or 'network'})"
    )
    with _lock:
        if _logged_line == line:
            return
        _logged_line = line
    print(f"Weather: {line}")


def _status_payload(snapshot: dict, manual: str) -> dict[str, str]:
    matched = snapshot.get("place_key") == _wanted_key(manual)
    place = _place_label(snapshot) if matched else ""
    readable = matched and _readable(snapshot)
    temperature = ""
    condition = ""
    if readable:
        temperature = str(int(snapshot["temperature"]))
        condition = str(snapshot.get("condition") or "")
    source = "setting" if manual else "network"
    if matched and snapshot.get("source"):
        source = str(snapshot.get("source"))
    return {
        "setting": manual,
        "source": source,
        "place": place,
        "temperature": temperature,
        "condition": condition,
        "detail": _detail(snapshot, manual, place, readable),
    }


def _detail(snapshot, manual, place, readable) -> str:
    if manual and snapshot.get("place_key") == _wanted_key(manual):
        if snapshot.get("error") == "not_found":
            return (
                "That place did not match a city or ZIP. "
                "The clock standby is waiting for a location it can read."
            )
        if snapshot.get("error") == "weather":
            return (
                f"Found {place or manual}. "
                "Conditions have not come back yet."
            )
    if readable and place:
        reading = f"{int(snapshot['temperature'])}°"
        condition = str(snapshot.get("condition") or "").lower()
        if condition:
            reading = f"{reading} and {condition}"
        if manual:
            return f"Standby shows {place}, {reading}."
        return (
            f"Standby shows {place}, {reading}, from this network."
        )
    if manual:
        return "Looking up that place for the clock standby."
    if snapshot.get("error") == "network":
        return (
            "This network has not returned a location yet. "
            "Enter a city or ZIP to set one."
        )
    return (
        "Weather follows this network's location and shows "
        "on the clock standby."
    )


def _place_label(snapshot: dict) -> str:
    name = str(snapshot.get("name") or "").strip()
    region = str(snapshot.get("region") or "").strip()
    if name and region and region.casefold() not in name.casefold():
        return f"{name}, {region}"
    return name


def _readable(snapshot: dict) -> bool:
    if snapshot.get("temperature") is None:
        return False
    return _age(snapshot.get("fetched_at")) <= SHOW_SECONDS


def _wanted_key(manual: str) -> str:
    if manual:
        return "setting:" + manual.casefold()
    return "network"


def _read_location_setting() -> str:
    try:
        weather = get_settings().get("weather") or {}
    except Exception:
        return ""
    if not isinstance(weather, dict):
        return ""
    return normalize_weather_location(weather.get("location"))


def _is_zip(query: str) -> bool:
    return re.fullmatch(r"\d{5}(?:-\d{4})?", query) is not None


def _place(name, region, latitude, longitude, source):
    point = _coordinates(latitude, longitude)
    if point is None:
        return None
    city = " ".join(str(name or "").split())
    area = " ".join(str(region or "").split())
    return {
        "name": city,
        "region": area,
        "latitude": point[0],
        "longitude": point[1],
        "source": source,
    }


def _coordinates(latitude, longitude):
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _split_loc(value):
    text = str(value or "")
    if "," not in text:
        return None, None
    latitude, longitude = text.split(",", 1)
    return latitude.strip(), longitude.strip()


def _age(stamp) -> float:
    try:
        fetched_at = float(stamp or 0)
    except (TypeError, ValueError):
        return SHOW_SECONDS + 1
    if fetched_at <= 0:
        return SHOW_SECONDS + 1
    return max(0.0, time.time() - fetched_at)


def _ensure_loaded() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        _read_cache()


def _cache_path():
    return SETTINGS_DIR / CACHE_FILE_NAME


def _reset_state() -> None:
    _state.update({
        "place_key": "",
        "name": "",
        "region": "",
        "latitude": None,
        "longitude": None,
        "source": "",
        "located_at": 0.0,
        "temperature": None,
        "condition": "",
        "fetched_at": 0.0,
        "error": "",
    })


def _read_cache() -> None:
    try:
        loaded = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return
    if not isinstance(loaded, dict):
        return
    latitude = loaded.get("latitude")
    longitude = loaded.get("longitude")
    point = None
    if latitude is not None and longitude is not None:
        point = _coordinates(latitude, longitude)
    _state["place_key"] = str(loaded.get("place_key") or "")
    _state["name"] = str(loaded.get("name") or "")
    _state["region"] = str(loaded.get("region") or "")
    _state["latitude"] = None if point is None else point[0]
    _state["longitude"] = None if point is None else point[1]
    _state["source"] = str(loaded.get("source") or "")
    _state["located_at"] = _float_or_zero(loaded.get("located_at"))
    temperature = loaded.get("temperature")
    if temperature is None:
        _state["temperature"] = None
    else:
        try:
            _state["temperature"] = int(temperature)
        except (TypeError, ValueError):
            _state["temperature"] = None
    _state["condition"] = str(loaded.get("condition") or "")
    _state["fetched_at"] = _float_or_zero(loaded.get("fetched_at"))
    _state["error"] = str(loaded.get("error") or "")


def _write_cache() -> None:
    payload = {
        "place_key": _state.get("place_key") or "",
        "name": _state.get("name") or "",
        "region": _state.get("region") or "",
        "latitude": _state.get("latitude"),
        "longitude": _state.get("longitude"),
        "source": _state.get("source") or "",
        "located_at": _state.get("located_at") or 0,
        "temperature": _state.get("temperature"),
        "condition": _state.get("condition") or "",
        "fetched_at": _state.get("fetched_at") or 0,
        "error": _state.get("error") or "",
    }
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


def _float_or_zero(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
