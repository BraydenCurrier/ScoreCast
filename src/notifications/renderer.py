import time  # Import time to compute the elapsed duration
from common.fonts import print_4x5

WHITE = (255, 255, 255)
GRAY = (150, 150, 150)
DARK = (45, 45, 45)

BLUE = (0, 140, 255)
GREEN = (0, 220, 90)
YELLOW = (255, 215, 0)
PURPLE = (180, 90, 255)
RED = (255, 80, 80)

PROVIDER_COLORS = {
    "twitter": BLUE,
    "x": WHITE,
    "spotify": GREEN,
    "rss": YELLOW,
    "espn": RED,
    "discord": PURPLE,
    "calendar": BLUE,
    "generic": GRAY,
}


def truncate(text, length):
    text = str(text or "")

    if len(text) <= length:
        return text

    return text[:length - 3] + "..."


def render_notification_onto(draw, card, x):

    provider = getattr(card, "provider", "generic").lower()

    color = PROVIDER_COLORS.get(
        provider,
        GRAY
    )

    source = truncate(
        getattr(card, "source", "").upper(),
        24
    )

    title = truncate(
        getattr(card, "title", ""),
        54
    )

    body = truncate(
        getattr(card, "body", ""),
        54
    )

    import datetime
    created_at = getattr(card, "created_at", None)
    
    if created_at is None:
        time_text = "NOW"
    else:
        # Get true UTC current time in seconds since epoch
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        now_utc_seconds = (now_dt - epoch).total_seconds()
        
        # Simple integer/float subtraction avoids all datetime parsing bugs
        diff_seconds = max(0, now_utc_seconds - created_at)
        diff_minutes = int(diff_seconds // 60)

        if diff_minutes < 1:
            time_text = "NOW"
        else:
            time_text = f"{diff_minutes}M"

    #
    # Background
    #

    draw.rectangle(
        (x, 0, x + 272, 31),
        fill=(0, 0, 0)
    )

    #
    # Left accent
    #

    draw.rectangle(
        (x, 0, x + 2, 31),
        fill=color
    )

    #
    # Divider
    #

    draw.line(
        (x + 4, 8, x + 268, 8),
        fill=DARK
    )

    #
    # Source
    #

    print_4x5(
        draw,
        source,
        x + 6,
        1,
        color
    )

    #
    # Time Elapsed (Placed at x + 195, just to the left of the Provider name)
    #

    print_4x5(
        draw,
        time_text,
        x + 195,
        1,
        GRAY
    )

    #
    # Provider
    #

    print_4x5(
        draw,
        provider.upper(),
        x + 225,
        1,
        GRAY
    )

    #
    # Title
    #

    print_4x5(
        draw,
        title,
        x + 6,
        11,
        WHITE
    )

    #
    # Body
    #

    print_4x5(
        draw,
        body,
        x + 6,
        21,
        GRAY
    )