#!/usr/bin/env python3

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageChops


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "assets" / "logos"

ESPN_BASE_URL = (
    "https://site.api.espn.com/apis/site/v2/sports"
)
ESPN_WEB_BASE_URL = (
    "https://site.web.api.espn.com/apis/site/v2/sports"
)

LEAGUES: dict[str, tuple[str, str]] = {
    "nfl": ("football", "nfl"),
    "nba": ("basketball", "nba"),
    "mlb": ("baseball", "mlb"),
    "nhl": ("hockey", "nhl"),
    "cfb": ("football", "college-football"),
}

SOCCER_LEAGUES: dict[str, str] = {
    "eng.1": "Premier League",
    "uefa.champions": "Champions League",
    "usa.1": "MLS",
    "esp.1": "La Liga",
    "ger.1": "Bundesliga",
    "ita.1": "Serie A",
    "mex.1": "Liga MX",
}

REQUEST_TIMEOUT = (3.05, 15)
LOGO_SIZE = (30, 30)

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux aarch64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,image/png,image/*",
    }
)


def normalize_abbreviation(value: Any) -> str:
    abbreviation = str(value or "").strip().upper()

    safe_characters = {
        character
        for character in abbreviation
        if character.isalnum() or character in {"-", "_"}
    }

    normalized = "".join(
        character
        for character in abbreviation
        if character in safe_characters
    )

    if not normalized:
        raise ValueError(
            f"Invalid team abbreviation: {value!r}"
        )

    return normalized


def extract_team_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract ESPN team dictionaries from the nested teams response.
    """
    sports = data.get("sports", [])

    if not sports:
        return []

    leagues = sports[0].get("leagues", [])

    if not leagues:
        return []

    entries = leagues[0].get("teams", [])
    teams: list[dict[str, Any]] = []

    for entry in entries:
        team = entry.get("team", entry)

        if isinstance(team, dict):
            teams.append(team)

    return teams


def get_logo_url(team: dict[str, Any]) -> str | None:
    """
    ESPN responses may expose either `logo` or a `logos` collection.
    """
    direct_logo = team.get("logo")

    if isinstance(direct_logo, str) and direct_logo:
        return direct_logo

    logos = team.get("logos", [])

    if not isinstance(logos, list):
        return None

    # Prefer the first PNG-looking image when available.
    for logo in logos:
        if not isinstance(logo, dict):
            continue

        href = logo.get("href")

        if isinstance(href, str) and ".png" in href.lower():
            return href

    for logo in logos:
        if not isinstance(logo, dict):
            continue

        href = logo.get("href")

        if isinstance(href, str) and href:
            return href

    return None


def remove_flat_background(image: Image.Image) -> Image.Image:
    """
    Preserve existing alpha. If the source has no useful transparency,
    remove a solid corner-colored background.

    This is conservative and is not intended to erase complex backgrounds.
    """
    image = image.convert("RGBA")
    alpha = image.getchannel("A")

    alpha_range = alpha.getextrema()

    if alpha_range != (255, 255):
        return image

    corner_color = image.getpixel((0, 0))[:3]

    background = Image.new(
        "RGBA",
        image.size,
        (*corner_color, 255),
    )

    difference = ImageChops.difference(
        image,
        background,
    ).convert("L")

    # Pixels close to the corner color become transparent.
    mask = difference.point(
        lambda value: 0 if value < 12 else 255
    )

    image.putalpha(mask)
    return image


def fit_for_matrix(
    image: Image.Image,
    size: tuple[int, int] = LOGO_SIZE,
) -> Image.Image:
    """
    Resize without distortion and center on a transparent 30x30 canvas.
    """
    image = remove_flat_background(image)

    # LANCZOS is good for preparation on a development machine.
    # The output itself is still a fixed 30x30 PNG.
    image.thumbnail(
        size,
        Image.Resampling.LANCZOS,
    )

    canvas = Image.new(
        "RGBA",
        size,
        (0, 0, 0, 0),
    )

    x = (size[0] - image.width) // 2
    y = (size[1] - image.height) // 2

    canvas.alpha_composite(
        image,
        (x, y),
    )

    return canvas


def download_image(url: str) -> Image.Image:
    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    with Image.open(BytesIO(response.content)) as source:
        return source.convert("RGBA")


def download_league(
    local_league: str,
    sport: str,
    espn_league: str,
    base_url: str = ESPN_BASE_URL,
) -> None:
    url = (
        f"{base_url}/{sport}/"
        f"{espn_league}/teams"
        "?limit=1000"
    )

    print(f"Fetching {local_league}: {url}")

    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    teams = extract_team_entries(response.json())

    output_directory = OUTPUT_ROOT / local_league
    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    downloaded = 0
    skipped = 0

    for team in teams:
        abbreviation = normalize_abbreviation(
            team.get("abbreviation")
            or team.get("shortDisplayName")
            or team.get("id")
        )

        logo_url = get_logo_url(team)

        if not logo_url:
            print(
                f"  Skipping {abbreviation}: "
                "no logo URL"
            )
            skipped += 1
            continue

        output_path = (
            output_directory
            / f"{abbreviation}.png"
        )

        if output_path.is_file():
            skipped += 1
            continue

        try:
            source_image = download_image(
                logo_url
            )
            matrix_image = fit_for_matrix(
                source_image
            )

            matrix_image.save(
                output_path,
                format="PNG",
                optimize=True,
            )

            downloaded += 1

            print(
                f"  Saved {abbreviation}: "
                f"{output_path.relative_to(PROJECT_ROOT)}"
            )

        except (
            requests.RequestException,
            OSError,
            ValueError,
        ) as error:
            print(
                f"  Failed {abbreviation}: {error}"
            )
            skipped += 1

    print(
        f"{local_league}: "
        f"{downloaded} downloaded, "
        f"{skipped} skipped"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download ESPN team logos and prepare "
            "30x30 transparent PNG assets."
        )
    )

    parser.add_argument(
        "leagues",
        nargs="*",
        choices=sorted(list(LEAGUES) + ["soccer"]),
        help=(
            "Leagues to download. "
            "Defaults to all supported leagues."
        ),
    )

    arguments = parser.parse_args()

    selected_leagues = (
        arguments.leagues
        if arguments.leagues
        else list(LEAGUES) + ["soccer"]
    )

    for local_league in selected_leagues:
        if local_league == "soccer":
            for espn_league in SOCCER_LEAGUES:
                download_league(
                    "soccer",
                    "soccer",
                    espn_league,
                    base_url=ESPN_WEB_BASE_URL,
                )
            continue

        sport, espn_league = LEAGUES[
            local_league
        ]

        download_league(
            local_league,
            sport,
            espn_league,
        )


if __name__ == "__main__":
    main()
