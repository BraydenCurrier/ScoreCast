import datetime
from email.utils import parsedate_to_datetime
import hashlib
import re
import time
import xml.etree.ElementTree as ET

import requests

from notifications.models import NotificationCard

CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
DEFAULT_MAX_AGE_SECONDS = 120 * 60


def clean_text(text):
    return " ".join(str(text or "").split())

def normalize_title(title):
    title = clean_text(title).lower()
    title = re.sub(r"[^\w\s]", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()

def utc_timestamp_from_pub_date(pub_date_text):
    if not pub_date_text:
        return None

    tzinfos = {
        "UT": 0,
        "UTC": 0,
        "GMT": 0,
        "EST": -4 * 3600,
        "EDT": -4 * 3600,
        "CST": -6 * 3600,
        "CDT": -5 * 3600,
        "MST": -7 * 3600,
        "MDT": -6 * 3600,
        "PST": -8 * 3600,
        "PDT": -7 * 3600,
    }

    dt = parsedate_to_datetime(pub_date_text)

    # Some feeds use timezone names like EST incorrectly.
    # Force Python to respect the explicit abbreviation.
    parts = pub_date_text.strip().split()
    tz_name = parts[-1].upper() if parts else ""

    if tz_name in tzinfos:
        dt = dt.replace(
            tzinfo=datetime.timezone(
                datetime.timedelta(seconds=tzinfos[tz_name])
            )
        )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    return dt.astimezone(datetime.timezone.utc).timestamp()


def fetch_rss_notifications(
    source_name,
    url,
    seen_ids,
    max_age_seconds=DEFAULT_MAX_AGE_SECONDS,
    now=None,
):
    if not url:
        return []

    if now is None:
        now = time.time()

    try:
        response = requests.get(
            url,
            timeout=10,
            verify=CA_BUNDLE,
            headers={"User-Agent": "Mozilla/5.0 ScoreCast/1.0"},
        )
        response.raise_for_status()
    except Exception as e:
        print(f"RSS request failed ({source_name}): {e}")
        return []

    text = response.text.strip()

    if "verify that you're not a robot" in text.lower():
        print(f"RSS blocked by bot protection: {source_name}")
        return []

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        print(f"Invalid RSS XML ({source_name}): {e}")
        return []

    cards = []

    for item in root.findall("./channel/item")[:10]:
        title = clean_text(item.findtext("title"))

        print(f"[RSS] Found: {title}")

        if not title:
            continue

        link = clean_text(item.findtext("link"))
        description = clean_text(item.findtext("description"))
        guid = clean_text(item.findtext("guid"))
        pub_date_text = item.findtext("pubDate")

        try:
            pub_timestamp = utc_timestamp_from_pub_date(pub_date_text)
            print(f"[RSS] Published timestamp: {pub_timestamp}")
        except Exception as e:
            print(f"Failed to parse RSS pubDate '{pub_date_text}':", e)
            continue

        if pub_timestamp is None:
            continue

        age_seconds = now - pub_timestamp

        print(f"[RSS] Age: {age_seconds:.1f} seconds")

        if age_seconds < 0:
            print(f"[RSS] SKIPPED future timestamp: {title} ({age_seconds:.0f}s)")
            continue

        if age_seconds > DEFAULT_MAX_AGE_SECONDS:
            print(f"[RSS] SKIPPED too old: {title} ({age_seconds:.0f}s)")
            continue

        normalized_title = normalize_title(title)

        item_id = guid or hashlib.sha1(
            f"{normalized_title}|{pub_timestamp}".encode("utf-8")
        ).hexdigest()

        if not item_id or item_id in seen_ids:
            continue

        seen_ids.add(item_id)

        cards.append(
            NotificationCard(
                provider="rss",
                source=source_name,
                title=title,
                body=description,
                created_at=pub_timestamp,
            )
        )

    return cards