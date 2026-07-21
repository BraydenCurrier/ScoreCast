from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGO_ROOT = PROJECT_ROOT / "assets" / "logos"

SUPPORTED_LEAGUES = frozenset(
    {
        "nfl",
        "nba",
        "mlb",
        "nhl",
        "cfb",
        "soccer",
        "broadcast",
    }
)


def normalize_identifier(value: str) -> str:
    identifier = str(value).strip().upper()

    if not identifier:
        raise ValueError(
            "Logo identifier cannot be empty"
        )

    if not all(
        character.isalnum()
        or character in {"-", "_"}
        for character in identifier
    ):
        raise ValueError(
            f"Invalid logo identifier: {value!r}"
        )

    return identifier


@lru_cache(maxsize=64)
def load_logo(
    league: str,
    identifier: str,
) -> Image.Image:
    normalized_league = (
        str(league).strip().lower()
    )

    if normalized_league not in SUPPORTED_LEAGUES:
        raise ValueError(
            f"Unsupported league: {league!r}"
        )

    normalized_identifier = (
        normalize_identifier(identifier)
    )

    path = (
        LOGO_ROOT
        / normalized_league
        / f"{normalized_identifier}.png"
    )

    if not path.is_file():
        raise FileNotFoundError(path)

    with Image.open(path) as source:
        # load() forces decoding before the file closes.
        logo = source.convert("RGBA")
        logo.load()

    return logo


def draw_logo(
    destination: Image.Image,
    league: str,
    identifier: str,
    x: int,
    y: int,
) -> bool:
    try:
        logo = load_logo(
            league,
            identifier,
        )
    except (
        FileNotFoundError,
        ValueError,
        OSError,
    ):
        return False

    destination.paste(
        logo,
        (x, y),
        logo,
    )

    return True


def preload_logo(
    league: str,
    identifier: str,
) -> bool:
    try:
        load_logo(
            league,
            identifier,
        )
        return True
    except (
        FileNotFoundError,
        ValueError,
        OSError,
    ):
        return False


def clear_logo_cache() -> None:
    load_logo.cache_clear()
