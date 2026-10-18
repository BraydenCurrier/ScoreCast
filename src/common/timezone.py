from datetime import datetime


def get_local_timezone():
    """
    Return the timezone configured on the operating system.

    datetime.now().astimezone().tzinfo uses the Raspberry Pi's
    configured system timezone and automatically handles DST.
    """
    return datetime.now().astimezone().tzinfo


def _parse_local_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None

    try:
        utc_dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

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