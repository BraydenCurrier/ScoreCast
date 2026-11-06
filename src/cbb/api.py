import json

import requests

from common.http import failure_text, get_body
from common.settings import get_settings
from nba.api import games_from_scoreboard


CBB_CONFERENCES = {
    "50": "Top 25",
    "23": "SEC",
    "7": "Big Ten",
    "2": "ACC",
    "8": "Big 12",
    "4": "Big East",
    "62": "American",
    "0": "All games",
}

DEFAULT_CONFERENCE_GROUPS = ["50"]

SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/"
    "mens-college-basketball/scoreboard"
)

HTTP_TIMEOUT = (3.05, 10)


def get_selected_conference_groups():
    settings = get_settings()
    block = settings.get("cbb", {})
    selected = block.get("selected_conferences", DEFAULT_CONFERENCE_GROUPS)

    if not isinstance(selected, list):
        return DEFAULT_CONFERENCE_GROUPS.copy()

    selected = [
        str(group_id)
        for group_id in selected
        if str(group_id) in CBB_CONFERENCES
    ]

    if not selected:
        return DEFAULT_CONFERENCE_GROUPS.copy()

    if "0" in selected:
        return ["0"]

    return selected


def fetch_scoreboard_group(group_id):
    url = f"{SCOREBOARD_URL}?limit=300"
    if str(group_id) != "0":
        url += f"&groups={group_id}"

    try:
        body = get_body(url, HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise RuntimeError(
            "College basketball request failed: "
            f"{failure_text(exc)[:300]}"
        ) from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "College basketball endpoint returned invalid JSON: "
            f"{body[:300]}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Unexpected college basketball response for group {group_id}"
        )

    return data


def get_today_games():
    seen = set()
    events = []

    for group_id in get_selected_conference_groups():
        payload = fetch_scoreboard_group(group_id)
        for event in payload.get("events") or []:
            event_id = str(event.get("id") or "")
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            events.append(event)

    return games_from_scoreboard({"events": events}, "cbb")
