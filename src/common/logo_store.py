from __future__ import annotations

import io
import re
from collections import Counter, deque
from functools import lru_cache
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from common.settings import SETTINGS_DIR


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGO_ROOT = PROJECT_ROOT / "assets" / "logos"
CUSTOM_LOGO_ROOT = SETTINGS_DIR / "logos"

LOGO_SIZE = 30
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_SOURCE_PIXELS = 4000

SUPPORTED_LEAGUES = frozenset(
    {
        "nfl",
        "nba",
        "mlb",
        "nhl",
        "cfb",
        "soccer",
        "broadcast",
        "pitchers",
        "stocks",
    }
)

EDITABLE_LOGO_LEAGUES = (
    "mlb",
    "nfl",
    "cfb",
    "nba",
    "nhl",
    "soccer",
)

RESERVED_VARIANTS = frozenset({"current"})


class LogoError(ValueError):
    """Raised when a custom logo cannot be saved or removed."""


def normalize_identifier(value: str) -> str:
    identifier = str(value).strip().upper()
    # ESPN CFB abbreviations can include "&" (W&M, TA&M).
    identifier = identifier.replace("&", "")
    identifier = re.sub(r"[^A-Z0-9_-]+", "", identifier)

    if not identifier:
        raise ValueError(
            "Logo identifier cannot be empty"
        )

    return identifier


def normalize_league(value: str) -> str:
    league = str(value or "").strip().lower()
    if league not in SUPPORTED_LEAGUES:
        raise ValueError(f"Unsupported league: {value!r}")
    return league


def normalize_variant_name(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise LogoError("Enter a name for this logo.")
    if len(text) > 40:
        text = text[:40].rstrip("_")
    if text in RESERVED_VARIANTS:
        raise LogoError(
            "Choose a name other than Current."
        )
    return text


def variant_label(variant: str) -> str:
    text = str(variant or "current").replace("_", " ").replace("-", " ")
    return text.title() if text else "Current"


def _bundled_team_dir(league: str, identifier: str) -> Path:
    return LOGO_ROOT / league / identifier


def _custom_team_dir(league: str, identifier: str) -> Path:
    return CUSTOM_LOGO_ROOT / league / identifier


def _is_png(path: Path) -> bool:
    try:
        return path.is_file() and path.suffix.lower() == ".png"
    except OSError:
        return False


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _variant_stems(directory: Path) -> list[str]:
    if not _is_dir(directory):
        return []
    try:
        files = sorted(directory.glob("*.png"))
    except OSError:
        return []
    return [
        path.stem
        for path in files
        if _is_png(path)
    ]


def bundled_logo_path(
    league: str,
    identifier: str,
    variant: str = "current",
) -> Path | None:
    team_directory = _bundled_team_dir(league, identifier)
    variant_path = team_directory / f"{variant}.png"
    if _is_png(variant_path):
        return variant_path

    if variant == "current":
        current_path = team_directory / "current.png"
        if _is_png(current_path):
            return current_path
        legacy_path = LOGO_ROOT / league / f"{identifier}.png"
        if _is_png(legacy_path):
            return legacy_path

    return None


def custom_logo_path(
    league: str,
    identifier: str,
    variant: str,
) -> Path | None:
    path = _custom_team_dir(league, identifier) / f"{variant}.png"
    return path if _is_png(path) else None


def clear_logo_cache() -> None:
    load_logo.cache_clear()
    _custom_league_catalog.cache_clear()


def _logo_file(
    league: str,
    identifier: str,
    variant: str,
) -> Path | None:
    custom = custom_logo_path(league, identifier, variant)
    if custom is not None:
        return custom
    return bundled_logo_path(league, identifier, variant)


@lru_cache(maxsize=512)
def load_logo(
    league: str,
    identifier: str,
    variant: str = "current",
) -> Image.Image:
    normalized_league = normalize_league(league)
    normalized_identifier = normalize_identifier(identifier)
    normalized_variant = (
        str(variant).strip().lower() or "current"
    )

    path = _logo_file(
        normalized_league,
        normalized_identifier,
        normalized_variant,
    )
    if path is None and normalized_variant != "current":
        path = _logo_file(
            normalized_league,
            normalized_identifier,
            "current",
        )
    if path is None:
        raise FileNotFoundError(
            _bundled_team_dir(normalized_league, normalized_identifier)
            / f"{normalized_variant}.png"
        )

    with Image.open(path) as source:
        logo = source.convert("RGBA")
        logo.load()

    return logo


def _order_variants(bundled, custom) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if not name or name in seen:
            return
        seen.add(name)
        ordered.append(name)

    bundled = list(bundled or ())
    custom = list(custom or ())
    if "current" in bundled:
        add("current")
    for name in bundled:
        add(name)
    for name in custom:
        add(name)
    return tuple(ordered)


@lru_cache(maxsize=16)
def _bundled_league_catalog(league: str) -> dict[str, tuple[str, ...]]:
    league_dir = LOGO_ROOT / league
    catalog: dict[str, tuple[str, ...]] = {}
    if not _is_dir(league_dir):
        return catalog
    try:
        entries = list(league_dir.iterdir())
    except OSError:
        return catalog

    for entry in entries:
        try:
            is_directory = entry.is_dir()
        except OSError:
            continue
        team = entry.stem.upper() if not is_directory else entry.name.upper()
        if not team:
            continue
        if is_directory:
            stems = _variant_stems(entry)
            if stems:
                catalog[team] = _order_variants(stems, ())
        elif _is_png(entry):
            catalog.setdefault(team, ("current",))
    return catalog


@lru_cache(maxsize=16)
def _custom_league_catalog(league: str) -> dict[str, tuple[str, ...]]:
    league_dir = CUSTOM_LOGO_ROOT / league
    catalog: dict[str, tuple[str, ...]] = {}
    if not _is_dir(league_dir):
        return catalog
    try:
        entries = list(league_dir.iterdir())
    except OSError:
        return catalog

    for entry in entries:
        try:
            is_directory = entry.is_dir()
        except OSError:
            continue
        if not is_directory:
            continue
        team = entry.name.upper()
        stems = _variant_stems(entry)
        if team and stems:
            catalog[team] = tuple(stems)
    return catalog


def get_logo_variants(
    league: str,
    identifier: str,
) -> list[str]:
    normalized_league = normalize_league(league)
    normalized_identifier = normalize_identifier(identifier)
    bundled = _bundled_league_catalog(normalized_league).get(
        normalized_identifier,
        (),
    )
    custom = _custom_league_catalog(normalized_league).get(
        normalized_identifier,
        (),
    )
    return list(_order_variants(bundled, custom))


def custom_logo_variants(
    league: str,
    identifier: str,
) -> list[str]:
    try:
        normalized_league = normalize_league(league)
        normalized_identifier = normalize_identifier(identifier)
    except ValueError:
        return []
    return list(
        _custom_league_catalog(normalized_league).get(
            normalized_identifier,
            (),
        )
    )


def get_custom_variants_by_team(league: str) -> dict[str, set[str]]:
    normalized_league = normalize_league(league)
    return {
        team: set(variants)
        for team, variants in _custom_league_catalog(normalized_league).items()
    }


def get_teams_with_logos(league: str) -> list[str]:
    """Return every team identifier with an available logo for a league."""
    return sorted(get_team_logo_catalog(league))


def get_team_logo_catalog(league: str) -> dict[str, list[str]]:
    normalized_league = normalize_league(league)
    catalog = dict(_bundled_league_catalog(normalized_league))
    for team, custom in _custom_league_catalog(normalized_league).items():
        catalog[team] = _order_variants(catalog.get(team, ()), custom)
    return {
        team: list(variants)
        for team, variants in sorted(catalog.items())
        if variants
    }


def get_teams_with_logo_variants(
    league: str,
) -> dict[str, list[str]]:
    """
    Returns every team that has more than one logo variant.
    """

    return {
        team: variants
        for team, variants in get_team_logo_catalog(league).items()
        if len(variants) > 1
    }


def get_selected_logo_variant(
    config: dict,
    league: str,
    identifier: str,
    available: list[str] | None = None,
) -> str:
    normalized_league = normalize_league(league)

    try:
        normalized_identifier = normalize_identifier(
            identifier
        )
    except ValueError:
        return "current"

    selected = (
        config
        .get("logo_variants", {})
        .get(normalized_league, {})
        .get(normalized_identifier, "current")
    )

    selected = str(selected).strip().lower() or "current"

    if available is None:
        available = get_logo_variants(
            normalized_league,
            normalized_identifier,
        )

    if selected in available:
        return selected

    return "current" if "current" in available else (
        available[0] if available else "current"
    )


def get_logo_variant_path(
    league,
    identifier,
    variant="current",
):
    try:
        league_name = normalize_league(league)
        team_name = normalize_identifier(identifier)
    except ValueError:
        return None

    variant_name = str(variant).strip().lower() or "current"
    return _logo_file(league_name, team_name, variant_name)


def _color_distance(left, right) -> int:
    return (
        abs(left[0] - right[0])
        + abs(left[1] - right[1])
        + abs(left[2] - right[2])
    )


def _edge_background_color(pixels, width: int, height: int):
    buckets: Counter[tuple[int, int, int]] = Counter()
    edge_count = 0

    def consider(x: int, y: int) -> None:
        nonlocal edge_count
        red, green, blue, alpha = pixels[x, y]
        edge_count += 1
        if alpha < 24:
            return
        buckets[(red >> 4, green >> 4, blue >> 4)] += 1

    for x in range(width):
        consider(x, 0)
        if height > 1:
            consider(x, height - 1)
    for y in range(1, height - 1):
        consider(0, y)
        if width > 1:
            consider(width - 1, y)

    if not buckets:
        return None

    quantized, count = buckets.most_common(1)[0]
    if count < max(8, int(edge_count * 0.32)):
        return None
    return (
        quantized[0] * 16 + 8,
        quantized[1] * 16 + 8,
        quantized[2] * 16 + 8,
    )


def _knockout_background(image: Image.Image) -> Image.Image:
    source = image.convert("RGBA")
    width, height = source.size
    if width < 4 or height < 4:
        return source

    pixels = source.load()
    background = _edge_background_color(pixels, width, height)
    if background is None:
        return source

    match_limit = 48
    feather = 28
    visited = bytearray(width * height)
    queue = deque()

    def index(x: int, y: int) -> int:
        return y * width + x

    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(1, height - 1):
        queue.append((0, y))
        queue.append((width - 1, y))

    cleared = 0
    while queue:
        x, y = queue.popleft()
        slot = index(x, y)
        if visited[slot]:
            continue
        visited[slot] = 1
        red, green, blue, alpha = pixels[x, y]
        if alpha < 8:
            continue
        distance = _color_distance((red, green, blue), background)
        if distance <= match_limit:
            pixels[x, y] = (red, green, blue, 0)
            cleared += 1
        elif distance <= match_limit + feather:
            fade = (distance - match_limit) / feather
            pixels[x, y] = (
                red,
                green,
                blue,
                max(0, min(255, int(alpha * fade))),
            )
            continue
        else:
            continue

        if x > 0:
            queue.append((x - 1, y))
        if x + 1 < width:
            queue.append((x + 1, y))
        if y > 0:
            queue.append((x, y - 1))
        if y + 1 < height:
            queue.append((x, y + 1))

    remaining = 0
    for y in range(height):
        for x in range(width):
            if pixels[x, y][3] > 16:
                remaining += 1
    if remaining < max(16, int(width * height * 0.04)):
        return image.convert("RGBA")
    return source


def _fit_board_logo(image: Image.Image) -> Image.Image:
    source = image.convert("RGBA")
    source.thumbnail(
        (LOGO_SIZE, LOGO_SIZE),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (LOGO_SIZE, LOGO_SIZE), (0, 0, 0, 0))
    canvas.paste(
        source,
        (
            (LOGO_SIZE - source.width) // 2,
            (LOGO_SIZE - source.height) // 2,
        ),
        source,
    )
    return canvas


def save_custom_logo(
    league: str,
    identifier: str,
    name: str,
    payload: bytes,
) -> str:
    if not payload:
        raise LogoError("Choose an image file to upload.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise LogoError("That image is too large. Use a file under 2 MB.")

    normalized_league = normalize_league(league)
    if normalized_league not in EDITABLE_LOGO_LEAGUES:
        raise LogoError("This league does not accept custom logos.")

    normalized_identifier = normalize_identifier(identifier)
    variant = normalize_variant_name(name)

    if bundled_logo_path(
        normalized_league,
        normalized_identifier,
        variant,
    ) is not None:
        raise LogoError(
            "That name is already used by a built-in logo. Pick another."
        )

    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            width, height = source.size
            if width < 1 or height < 1:
                raise LogoError("That image could not be read.")
            if width > MAX_SOURCE_PIXELS or height > MAX_SOURCE_PIXELS:
                raise LogoError("That image is too large.")
            prepared = source.convert("RGBA")
            prepared.thumbnail((256, 256), Image.Resampling.LANCZOS)
            prepared = _knockout_background(prepared)
            fitted = _fit_board_logo(prepared)
    except UnidentifiedImageError as error:
        raise LogoError(
            "Use a PNG, JPEG, WebP, or GIF image."
        ) from error
    except OSError as error:
        raise LogoError("That image could not be read.") from error

    destination_dir = _custom_team_dir(
        normalized_league,
        normalized_identifier,
    )
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{variant}.png"
    fitted.save(destination, format="PNG")
    clear_logo_cache()
    return variant


def delete_custom_logo(
    league: str,
    identifier: str,
    variant: str,
) -> None:
    normalized_league = normalize_league(league)
    normalized_identifier = normalize_identifier(identifier)
    variant_name = str(variant).strip().lower()
    if not variant_name or variant_name in RESERVED_VARIANTS:
        raise LogoError("That logo cannot be removed.")

    path = custom_logo_path(
        normalized_league,
        normalized_identifier,
        variant_name,
    )
    if path is None:
        raise LogoError("That custom logo was not found.")

    resolved = path.resolve()
    root = CUSTOM_LOGO_ROOT.resolve()
    if not resolved.is_relative_to(root):
        raise LogoError("That logo cannot be removed.")

    resolved.unlink()
    parent = resolved.parent
    try:
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass
    clear_logo_cache()


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
