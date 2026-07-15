#!/usr/bin/env python3

import argparse
import signal
import sys
import time

from PIL import Image

from alerts.models import PossessionAlert
from alerts.renderer import render_possession_alert
from alerts.teams import NFL_TEAM_ALERTS
from common.config import PANEL_HEIGHT, PANEL_WIDTH
from common.matrix import create_matrix


FPS = 60
FRAME_DELAY = 1.0 / FPS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cycle through every NFL possession alert "
            "on the ScoreCast RGB matrix."
        )
    )

    parser.add_argument(
        "--chant-seconds",
        type=float,
        default=0.65,
        help="Seconds each chant word remains visible.",
    )

    parser.add_argument(
        "--details-seconds",
        type=float,
        default=4.0,
        help="Seconds the possession details remain visible.",
    )

    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=1.0,
        help="Pause between teams.",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Cycle through all teams once, then exit.",
    )

    parser.add_argument(
        "--team",
        type=str,
        default="",
        help="Test only one team, such as GB, MIN, or KC.",
    )

    return parser.parse_args()


def create_test_alert(
    team: str,
    chant_seconds: float,
    details_seconds: float,
) -> PossessionAlert:
    definition = NFL_TEAM_ALERTS[team]

    return PossessionAlert(
        game_id=f"test-{team}",
        team=team,
        opponent="TEST",

        possession_label=definition.possession_label,
        chant=definition.chant,

        primary=definition.primary,
        accent=definition.accent,

        down=1,
        distance=10,

        yardline_side=team,
        yardline_number=37,

        quarter=1,
        clock="12:34",

        created_at=time.monotonic(),

        chant_frame_seconds=chant_seconds,
        details_frame_seconds=details_seconds,
    )


def clear_matrix(matrix) -> None:
    blank = Image.new(
        "RGB",
        (PANEL_WIDTH, PANEL_HEIGHT),
        (0, 0, 0),
    )

    matrix.SetImage(blank)


def display_alert(
    matrix,
    team: str,
    chant_seconds: float,
    details_seconds: float,
) -> None:
    definition = NFL_TEAM_ALERTS[team]

    print(
        f"Testing {team}: {definition.name} "
        f"{definition.chant}",
        flush=True,
    )

    alert = create_test_alert(
        team=team,
        chant_seconds=chant_seconds,
        details_seconds=details_seconds,
    )

    end_time = (
        alert.created_at
        + alert.total_duration
    )

    while True:
        frame_started_at = time.monotonic()

        if frame_started_at >= end_time:
            break

        frame = render_possession_alert(
            alert,
            now=frame_started_at,
        )

        matrix.SetImage(frame)

        frame_elapsed = (
            time.monotonic()
            - frame_started_at
        )

        sleep_time = FRAME_DELAY - frame_elapsed

        if sleep_time > 0:
            time.sleep(sleep_time)


def main() -> int:
    args = parse_args()

    chant_seconds = max(
        0.1,
        args.chant_seconds,
    )

    details_seconds = max(
        0.5,
        args.details_seconds,
    )

    pause_seconds = max(
        0.0,
        args.pause_seconds,
    )

    requested_team = args.team.strip().upper()

    if requested_team:
        if requested_team not in NFL_TEAM_ALERTS:
            valid_teams = ", ".join(
                sorted(NFL_TEAM_ALERTS)
            )

            print(
                f"Unknown team: {requested_team}",
                file=sys.stderr,
            )

            print(
                f"Valid teams: {valid_teams}",
                file=sys.stderr,
            )

            return 2

        teams = [requested_team]
    else:
        teams = sorted(NFL_TEAM_ALERTS)

    matrix = create_matrix()
    should_stop = False

    def request_stop(
        _signum,
        _frame,
    ) -> None:
        nonlocal should_stop
        should_stop = True

    signal.signal(
        signal.SIGINT,
        request_stop,
    )

    signal.signal(
        signal.SIGTERM,
        request_stop,
    )

    try:
        while not should_stop:
            for team in teams:
                if should_stop:
                    break

                display_alert(
                    matrix=matrix,
                    team=team,
                    chant_seconds=chant_seconds,
                    details_seconds=details_seconds,
                )

                if pause_seconds > 0:
                    clear_matrix(matrix)

                    pause_ends_at = (
                        time.monotonic()
                        + pause_seconds
                    )

                    while (
                        not should_stop
                        and time.monotonic()
                        < pause_ends_at
                    ):
                        time.sleep(0.05)

            if args.once or requested_team:
                break

    finally:
        clear_matrix(matrix)

    print("Alert test finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())