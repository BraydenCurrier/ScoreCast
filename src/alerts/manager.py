from collections import deque
from dataclasses import dataclass
from threading import RLock
import time
from typing import Deque, Dict, Iterable, Optional

from alerts.models import PossessionAlert
from alerts.teams import get_team_alert
from nfl.models import FootballGame


LIVE_STATUSES = {
    "STATUS_IN_PROGRESS",
    "IN_PROGRESS",
    "LIVE",
}


@dataclass
class GamePossessionState:
    confirmed_team: str = ""
    candidate_team: str = ""
    candidate_count: int = 0
    last_alert_team: str = ""
    last_alert_at: float = 0.0
    last_seen_at: float = 0.0


class PossessionAlertManager:
    def __init__(self) -> None:
        self._lock = RLock()

        self._game_states: Dict[
            str,
            GamePossessionState,
        ] = {}

        self._queue: Deque[PossessionAlert] = deque(
            maxlen=8
        )

        self._active_alert: Optional[
            PossessionAlert
        ] = None

    def process_games(
        self,
        games: Iterable[FootballGame],
        settings: dict,
        now: Optional[float] = None,
    ) -> list[PossessionAlert]:
        if now is None:
            now = time.monotonic()

        alerts_settings = settings.get(
            "alerts",
            {},
        )

        enabled = bool(
            alerts_settings.get(
                "enabled",
                False,
            )
        )

        watched_teams = {
            str(team).upper()
            for team in alerts_settings.get(
                "possession_teams",
                [],
            )
        }

        confirmations_required = self._safe_int(
            alerts_settings.get(
                "confirmations_required",
                2,
            ),
            default=2,
            minimum=1,
            maximum=5,
        )

        cooldown_seconds = self._safe_float(
            alerts_settings.get(
                "cooldown_seconds",
                20,
            ),
            default=20.0,
            minimum=0.0,
            maximum=300.0,
        )

        chant_frame_seconds = self._safe_float(
            alerts_settings.get(
                "chant_frame_seconds",
                0.65,
            ),
            default=0.65,
            minimum=0.2,
            maximum=3.0,
        )

        details_frame_seconds = self._safe_float(
            alerts_settings.get(
                "details_frame_seconds",
                4.0,
            ),
            default=4.0,
            minimum=1.0,
            maximum=15.0,
        )

        created_alerts: list[PossessionAlert] = []
        seen_game_ids: set[str] = set()

        with self._lock:
            for game in games:
                game_id = self._game_id(game)

                if not game_id:
                    continue

                seen_game_ids.add(game_id)

                state = self._game_states.setdefault(
                    game_id,
                    GamePossessionState(),
                )

                state.last_seen_at = now

                status = str(
                    game.status or ""
                ).upper()

                if status not in LIVE_STATUSES:
                    self._reset_candidate(state)
                    continue

                current_team = str(
                    game.possession or ""
                ).upper()

                if not current_team:
                    # Missing possession should not erase
                    # the last confirmed team.
                    self._reset_candidate(state)
                    continue

                if current_team not in {
                    game.away.upper(),
                    game.home.upper(),
                }:
                    # Reject malformed possession values.
                    self._reset_candidate(state)
                    continue

                if not state.confirmed_team:
                    # First observation initializes state.
                    # It must not generate an alert.
                    state.confirmed_team = current_team
                    self._reset_candidate(state)
                    continue

                if current_team == state.confirmed_team:
                    self._reset_candidate(state)
                    continue

                if current_team == state.candidate_team:
                    state.candidate_count += 1
                else:
                    state.candidate_team = current_team
                    state.candidate_count = 1

                if (
                    state.candidate_count
                    < confirmations_required
                ):
                    continue

                previous_team = state.confirmed_team
                state.confirmed_team = current_team
                self._reset_candidate(state)

                if not enabled:
                    continue

                if current_team not in watched_teams:
                    continue

                if (
                    state.last_alert_team
                    == current_team
                    and now - state.last_alert_at
                    < cooldown_seconds
                ):
                    continue

                team_definition = get_team_alert(
                    current_team
                )

                if team_definition is None:
                    continue

                opponent = (
                    game.home
                    if current_team == game.away
                    else game.away
                )

                alert = PossessionAlert(
                    game_id=game_id,
                    team=current_team,
                    opponent=opponent,

                    possession_label=(
                        team_definition.possession_label
                    ),

                    chant=team_definition.chant,
                    primary=team_definition.primary,
                    accent=team_definition.accent,

                    down=max(
                        0,
                        int(game.down or 0),
                    ),

                    distance=max(
                        0,
                        int(game.distance or 0),
                    ),

                    yardline_side=str(
                        game.yardline_side or ""
                    ).upper(),

                    yardline_number=max(
                        0,
                        int(game.yardline_number or 0),
                    ),

                    quarter=max(
                        0,
                        int(game.quarter or 0),
                    ),

                    clock=str(
                        game.clock or ""
                    ),

                    created_at=now,

                    chant_frame_seconds=(
                        chant_frame_seconds
                    ),

                    details_frame_seconds=(
                        details_frame_seconds
                    ),
                )

                self._queue.append(alert)
                created_alerts.append(alert)

                state.last_alert_team = current_team
                state.last_alert_at = now

            self._remove_stale_states(
                seen_game_ids,
                now,
            )

        return created_alerts

    def get_active(
        self,
        now: Optional[float] = None,
    ) -> Optional[PossessionAlert]:
        if now is None:
            now = time.monotonic()

        with self._lock:
            if self._active_alert is not None:
                elapsed = (
                    now
                    - self._active_alert.created_at
                )

                if (
                    elapsed
                    < self._active_alert.total_duration
                ):
                    return self._active_alert

                self._active_alert = None

            if not self._queue:
                return None

            queued_alert = self._queue.popleft()

            # Reset the start time so queued alerts receive
            # their full animation duration.
            self._active_alert = PossessionAlert(
                game_id=queued_alert.game_id,
                team=queued_alert.team,
                opponent=queued_alert.opponent,

                possession_label=(
                    queued_alert.possession_label
                ),

                chant=queued_alert.chant,
                primary=queued_alert.primary,
                accent=queued_alert.accent,

                down=queued_alert.down,
                distance=queued_alert.distance,

                yardline_side=(
                    queued_alert.yardline_side
                ),

                yardline_number=(
                    queued_alert.yardline_number
                ),

                quarter=queued_alert.quarter,
                clock=queued_alert.clock,

                created_at=now,

                chant_frame_seconds=(
                    queued_alert.chant_frame_seconds
                ),

                details_frame_seconds=(
                    queued_alert.details_frame_seconds
                ),
            )

            return self._active_alert

    def enqueue_test_alert(
        self,
        team: str,
        settings: dict,
        now: Optional[float] = None,
    ) -> bool:
        if now is None:
            now = time.monotonic()

        team = str(team).upper()
        team_definition = get_team_alert(team)

        if team_definition is None:
            return False

        alerts_settings = settings.get(
            "alerts",
            {},
        )

        chant_frame_seconds = self._safe_float(
            alerts_settings.get(
                "chant_frame_seconds",
                0.65,
            ),
            default=0.65,
            minimum=0.2,
            maximum=3.0,
        )

        details_frame_seconds = self._safe_float(
            alerts_settings.get(
                "details_frame_seconds",
                4.0,
            ),
            default=4.0,
            minimum=1.0,
            maximum=15.0,
        )

        test_alert = PossessionAlert(
            game_id="test",
            team=team,
            opponent="TEST",

            possession_label=(
                team_definition.possession_label
            ),

            chant=team_definition.chant,
            primary=team_definition.primary,
            accent=team_definition.accent,

            down=1,
            distance=10,

            yardline_side=team,
            yardline_number=37,

            quarter=1,
            clock="12:34",

            created_at=now,

            chant_frame_seconds=(
                chant_frame_seconds
            ),

            details_frame_seconds=(
                details_frame_seconds
            ),
        )

        with self._lock:
            self._queue.append(test_alert)

        return True

    def clear(self) -> None:
        with self._lock:
            self._queue.clear()
            self._active_alert = None
            self._game_states.clear()

    @staticmethod
    def _game_id(game: FootballGame) -> str:
        event_id = str(
            game.event_id or ""
        ).strip()

        if event_id:
            return event_id

        away = str(game.away or "").upper()
        home = str(game.home or "").upper()

        if not away or not home:
            return ""

        return f"{away}@{home}"

    @staticmethod
    def _reset_candidate(
        state: GamePossessionState,
    ) -> None:
        state.candidate_team = ""
        state.candidate_count = 0

    def _remove_stale_states(
        self,
        seen_game_ids: set[str],
        now: float,
    ) -> None:
        stale_cutoff = now - (12 * 60 * 60)

        stale_ids = [
            game_id
            for game_id, state
            in self._game_states.items()
            if (
                game_id not in seen_game_ids
                and state.last_seen_at < stale_cutoff
            )
        ]

        for game_id in stale_ids:
            del self._game_states[game_id]

    @staticmethod
    def _safe_int(
        value,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default

        return max(
            minimum,
            min(maximum, parsed),
        )

    @staticmethod
    def _safe_float(
        value,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default

        return max(
            minimum,
            min(maximum, parsed),
        )


possession_alert_manager = PossessionAlertManager()