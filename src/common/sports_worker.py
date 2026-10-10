"""Fetch scores and draw cards outside the display process.

The ticker keeps its own frame clock. This process is started with a
lower priority so parsing and card drawing yield the CPU to it.
"""

import pickle
import sys
import traceback


def main():
    saved_stdout = sys.stdout
    sys.stdout = sys.stderr

    try:
        request = pickle.load(sys.stdin.buffer)
        from main import build_refresh_payload

        payload = build_refresh_payload(
            request["settings"],
            request.get("previous_games") or [],
            request.get("due_sports"),
        )
        pickle.dump(payload, saved_stdout.buffer, protocol=4)
        saved_stdout.flush()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
