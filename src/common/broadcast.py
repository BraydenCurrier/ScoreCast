from __future__ import annotations

import re
from functools import lru_cache

from common.logo_store import (
    draw_logo,
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
    "FOX SPORTS 1": ("FS1",),
    "FOX SPORTS 2": ("FS2",),
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


def _add_label(bucket: list[tuple[str, bool]], seen: set[str], raw, *, national: bool):
    for token in _tokenize_broadcast_label(str(raw or "")):
        key = _normalize_key(token)
        if not key or key in SKIP_LABELS:
            continue
        if key.endswith(" APP"):
            continue
        if key in seen:
            continue
        seen.add(key)
        bucket.append((token.strip(), national))


def _collect_from_broadcast_entry(entry, bucket, seen):
    if isinstance(entry, str):
        _add_label(bucket, seen, entry, national=True)
        return

    if not isinstance(entry, dict):
        return

    national = _is_national_market(entry.get("market"))
    names = entry.get("names", [])
    if isinstance(names, str):
        names = [names]
    if isinstance(names, list):
        for name in names:
            _add_label(bucket, seen, name, national=national)

    media = entry.get("media")
    if isinstance(media, dict):
        _add_label(
            bucket,
            seen,
            media.get("shortName") or media.get("name"),
            national=national,
        )
    elif isinstance(media, str):
        _add_label(bucket, seen, media, national=national)

    for key in ("shortName", "name", "callLetters"):
        if entry.get(key):
            _add_label(bucket, seen, entry.get(key), national=national)


def extract_broadcast_labels(event=None, competition=None) -> list[str]:
    bucket: list[tuple[str, bool]] = []
    seen: set[str] = set()

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

    national = [label for label, is_national in bucket if is_national]
    regional = [label for label, is_national in bucket if not is_national]
    return national + regional


def format_broadcast(event=None, competition=None) -> str:
    labels = extract_broadcast_labels(event, competition)
    return ", ".join(labels[:3])


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


def missing_broadcast_identifiers(raw: str) -> list[str]:
    available = available_broadcast_ids()
    missing = []
    seen = set()
    for identifier in broadcast_candidates(raw):
        if identifier in available or identifier in seen:
            continue
        if identifier in {
            ident
            for aliases in BROADCAST_ALIASES.values()
            for ident in aliases
        } or identifier:
            # Prefer the first alias that is not already on disk.
            aliases = BROADCAST_ALIASES.get(_normalize_key(raw), ())
            preferred = aliases[0] if aliases else identifier
            if preferred not in available and preferred not in seen:
                seen.add(preferred)
                missing.append(preferred)
            break
    return missing


def draw_broadcast_logo(image, broadcast, x, y, settings):
    if not broadcast:
        return False

    identifier = resolve_broadcast_identifier(broadcast)
    if not identifier:
        return False

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
        return draw_logo(
            destination=image,
            league="broadcast",
            identifier=identifier,
            x=x - logo.width // 2,
            y=y - logo.height // 2,
            variant=variant,
        )
    except (FileNotFoundError, ValueError, OSError, KeyError):
        return False
