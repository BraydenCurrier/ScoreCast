from datetime import datetime


def get_local_timezone():
    """
    Return the timezone configured on the operating system.

    datetime.now().astimezone().tzinfo uses the Raspberry Pi's
    configured system timezone and automatically handles DST.
    """
    return datetime.now().astimezone().tzinfo