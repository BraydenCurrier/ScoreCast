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

def resolve_logo_path(
    league: str,
    identifier: str,
    variant: str = "current",
):
    normalized_league = league.strip().lower()
    normalized_identifier = identifier.strip().upper()
    normalized_variant = variant.strip().lower() or "current"

    league_dir = LOGO_ROOT / normalized_league

    variant_path = (
        league_dir
        / normalized_identifier
        / f"{normalized_variant}.png"
    )

    if variant_path.is_file():
        return variant_path

    current_path = (
        league_dir
        / normalized_identifier
        / "current.png"
    )

    if current_path.is_file():
        return current_path

    legacy_path = league_dir / f"{normalized_identifier}.png"

    if legacy_path.is_file():
        return legacy_path

    return None

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


@lru_cache(maxsize=512)
def load_logo(
    league: str,
    identifier: str,
    variant: str = "current",
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

    normalized_variant = (
        str(variant).strip().lower()
        or "current"
    )

    team_directory = (
        LOGO_ROOT
        / normalized_league
        / normalized_identifier
    )

    variant_path = (
        team_directory
        / f"{normalized_variant}.png"
    )

    current_path = (
        team_directory
        / "current.png"
    )

    legacy_path = (
        LOGO_ROOT
        / normalized_league
        / f"{normalized_identifier}.png"
    )

    if variant_path.is_file():
        path = variant_path
    elif current_path.is_file():
        path = current_path
    elif legacy_path.is_file():
        path = legacy_path
    else:
        raise FileNotFoundError(
            variant_path
        )

    with Image.open(path) as source:
        # load() forces decoding before the file closes.
        logo = source.convert("RGBA")
        logo.load()

    return logo

from pathlib import Path

def get_logo_variants(
    league: str,
    identifier: str,
) -> list[str]:
    """
    Returns the available logo variants for a team.

    Examples:
        ["current"]
        ["current", "classic"]
        ["current", "1994", "throwback"]
    """

    normalized_league = str(league).strip().lower()

    if normalized_league not in SUPPORTED_LEAGUES:
        raise ValueError(
            f"Unsupported league: {league!r}"
        )

    normalized_identifier = normalize_identifier(
        identifier
    )

    team_directory = (
        LOGO_ROOT
        / normalized_league
        / normalized_identifier
    )

    # Legacy layout (TEAM.png)
    if not team_directory.is_dir():
        legacy = (
            LOGO_ROOT
            / normalized_league
            / f"{normalized_identifier}.png"
        )

        return ["current"] if legacy.is_file() else []

    variants = []

    for file in team_directory.glob("*.png"):
        variants.append(file.stem)

    if "current" in variants:
        variants.remove("current")
        variants.insert(0, "current")
    else:
        variants.sort()

    return variants

def get_teams_with_logo_variants(
    league: str,
) -> dict[str, list[str]]:
    """
    Returns every team that has more than one logo variant.

    Example:
    {
        "ARI": ["current", "classic"],
        "LAD": ["current", "city_connect"],
    }
    """

    normalized_league = league.strip().lower()

    if normalized_league not in SUPPORTED_LEAGUES:
        raise ValueError(
            f"Unsupported league: {league!r}"
        )

    league_dir = LOGO_ROOT / normalized_league

    if not league_dir.is_dir():
        return {}

    results: dict[str, list[str]] = {}

    for entry in sorted(
        league_dir.iterdir(),
        key=lambda path: path.name.lower(),
    ):
        if not entry.is_dir():
            continue

        variants = get_logo_variants(
            normalized_league,
            entry.name,
        )

        if len(variants) > 1:
            results[entry.name] = variants

    return results

def get_selected_logo_variant(
    config: dict,
    league: str,
    identifier: str,
) -> str:
    normalized_league = str(league).strip().lower()

    if normalized_league not in SUPPORTED_LEAGUES:
        raise ValueError(
            f"Unsupported league: {league!r}"
        )

    normalized_identifier = normalize_identifier(
        identifier
    )

    selected = (
        config
        .get("logo_variants", {})
        .get(normalized_league, {})
        .get(normalized_identifier, "current")
    )

    selected = str(selected).strip().lower() or "current"

    available = get_logo_variants(
        normalized_league,
        normalized_identifier,
    )

    if selected in available:
        return selected

    return "current"

def get_logo_variant_path(
    league,
    identifier,
    variant="current",
):
    league_name = str(league).strip().lower()
    team_name = str(identifier).strip().upper()
    variant_name = str(variant).strip().lower()

    available_variants = get_logo_variants(
        league_name,
        team_name,
    )

    if variant_name not in available_variants:
        return None

    team_directory = (
        LOGO_ROOT
        / league_name
        / team_name
    )

    variant_path = team_directory / f"{variant_name}.png"

    if variant_path.is_file():
        return variant_path

    # Backward-compatible current logo.
    if variant_name == "current":
        legacy_path = (
            LOGO_ROOT
            / league_name
            / f"{team_name}.png"
        )

        if legacy_path.is_file():
            return legacy_path

    return None

def draw_logo(
    destination: Image.Image,
    league: str,
    identifier: str,
    x: int,
    y: int,
    variant: str = "current",
) -> bool:
    try:
        logo = load_logo(
            league=league,
            identifier=identifier,
            variant=variant,
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
