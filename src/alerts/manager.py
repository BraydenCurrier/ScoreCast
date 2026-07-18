from collections import deque
from dataclasses import dataclass, field
from threading import RLock
import time
from typing import Deque, Dict, Iterable, Optional

from alerts.models import PossessionAlert
from alerts.teams import get_team_alert
from nfl.models import FootballGame


LIVE_STATUSES = {"STATUS_IN_PROGRESS", "IN_PROGRESS", "LIVE"}


@dataclass
class GamePossessionState:
    confirmed_team: str = ""
    candidate_team: str = ""
    candidate_count: int = 0

    away_score: Optional[int] = None
    home_score: Optional[int] = None

    last_play_id: str = ""
    last_play_text: str = ""
    last_scoring_signature: str = ""

    redzone_team: str = ""

    # Cooldowns are tracked separately by event type and team.
    last_alert_times: dict = field(default_factory=dict)

    last_seen_at: float = 0.0


class PossessionAlertManager:
    def __init__(self):
        self._lock = RLock()

        self._game_states = {}
        self._queue = deque(maxlen=8)

        self._active_alert = None

    def process_games(self, games, settings, now):
        if now is None:
            now = time.monotonic()

        alerts_settings = settings.get("alerts", {})
        enabled = bool(alerts_settings.get("enabled", False))

        possession_enabled = bool(alerts_settings.get("possession_enabled", True))
        redzone_enabled = bool(alerts_settings.get("redzone_enabled", True))
        touchdown_enabled = bool(alerts_settings.get("touchdown_enabled", True))
        field_goal_enabled = bool(alerts_settings.get("field_goal_enabled", True))

        watched_teams = {
            str(team).upper()
            for team in alerts_settings.get(
                "possession_teams",
                [],
            )
        }

        confirmations_required = self._safe_int(alerts_settings.get("confirmations_required", 2), default=2, minimum=1, maximum=5)
        cooldown_seconds = self._safe_float(alerts_settings.get("cooldown_seconds", 20), default=20.0, minimum=0.0, maximum=300.0)
        chant_frame_seconds = self._safe_float(alerts_settings.get("chant_frame_seconds", 0.65), default=0.65, minimum=0.2, maximum=3.0)

        details_frame_seconds = self._safe_float(alerts_settings.get("details_frame_seconds", 4.0), default=4.0, minimum=1.0, maximum=15.0)

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
                    state.redzone_team = ""

                    # Keep scores synchronized so a game that
                    # changes status does not create an old alert.
                    self._initialize_or_sync_scores(
                        state,
                        game,
                    )
                    continue

                self._process_scoring_alert(
                    game=game,
                    state=state,
                    watched_teams=watched_teams,
                    enabled=enabled,
                    touchdown_enabled=(
                        touchdown_enabled
                    ),
                    field_goal_enabled=(
                        field_goal_enabled
                    ),
                    cooldown_seconds=(
                        cooldown_seconds
                    ),
                    chant_frame_seconds=(
                        chant_frame_seconds
                    ),
                    details_frame_seconds=(
                        details_frame_seconds
                    ),
                    now=now,
                    created_alerts=created_alerts,
                )

                current_team = str(
                    game.possession or ""
                ).upper()

                valid_teams = {
                    str(game.away or "").upper(),
                    str(game.home or "").upper(),
                }

                valid_teams.discard("")

                if (
                    not current_team
                    or current_team not in valid_teams
                ):
                    # Missing or malformed possession should
                    # not erase the last confirmed team.
                    self._reset_candidate(state)
                    state.redzone_team = ""
                    continue

                self._process_redzone_alert(
                    game=game,
                    state=state,
                    current_team=current_team,
                    watched_teams=watched_teams,
                    enabled=enabled,
                    redzone_enabled=redzone_enabled,
                    cooldown_seconds=(
                        cooldown_seconds
                    ),
                    chant_frame_seconds=(
                        chant_frame_seconds
                    ),
                    details_frame_seconds=(
                        details_frame_seconds
                    ),
                    now=now,
                    created_alerts=created_alerts,
                )

                self._process_possession_alert(
                    game=game,
                    state=state,
                    current_team=current_team,
                    watched_teams=watched_teams,
                    enabled=enabled,
                    possession_enabled=(
                        possession_enabled
                    ),
                    confirmations_required=(
                        confirmations_required
                    ),
                    cooldown_seconds=(
                        cooldown_seconds
                    ),
                    chant_frame_seconds=(
                        chant_frame_seconds
                    ),
                    details_frame_seconds=(
                        details_frame_seconds
                    ),
                    now=now,
                    created_alerts=created_alerts,
                )

            self._remove_stale_states(
                seen_game_ids,
                now,
            )

        return created_alerts

    def _process_scoring_alert(
        self,
        *,
        game: FootballGame,
        state: GamePossessionState,
        watched_teams: set[str],
        enabled: bool,
        touchdown_enabled: bool,
        field_goal_enabled: bool,
        cooldown_seconds: float,
        chant_frame_seconds: float,
        details_frame_seconds: float,
        now: float,
        created_alerts: list[PossessionAlert],
    ) -> None:
        away_score = self._nonnegative_int(
            game.away_score,
        )

        home_score = self._nonnegative_int(
            game.home_score,
        )

        play_id = str(
            getattr(
                game,
                "last_play_id",
                "",
            )
            or ""
        ).strip()

        play_text = str(
            getattr(
                game,
                "last_play_text",
                "",
            )
            or ""
        ).strip()

        scoring_play = bool(
            getattr(
                game,
                "scoring_play",
                False,
            )
        )

        # The first observation only initializes state.
        # This prevents false alerts when ScoreCast starts
        # during an already-active game.
        if (
            state.away_score is None
            or state.home_score is None
        ):
            state.away_score = away_score
            state.home_score = home_score
            state.last_play_id = play_id
            state.last_play_text = play_text
            return

        away_delta = (
            away_score - state.away_score
        )

        home_delta = (
            home_score - state.home_score
        )

        scoring_signature = (
            play_id
            if play_id
            else (
                f"{away_score}:{home_score}:"
                f"{play_text.upper()}"
            )
        )

        score_changed = (
            away_delta > 0
            or home_delta > 0
        )

        new_scoring_event = (
            score_changed
            and scoring_signature
            != state.last_scoring_signature
        )

        if (
            enabled
            and new_scoring_event
            and (
                scoring_play
                or self._looks_like_scoring_play(
                    play_text
                )
            )
        ):
            scoring_team = ""
            points = 0

            if (
                away_delta > 0
                and home_delta <= 0
            ):
                scoring_team = str(
                    game.away or ""
                ).upper()
                points = away_delta

            elif (
                home_delta > 0
                and away_delta <= 0
            ):
                scoring_team = str(
                    game.home or ""
                ).upper()
                points = home_delta

            scoring_type = self._scoring_type(
                play_text,
                points,
            )

            event_enabled = (
                (
                    scoring_type == "TOUCHDOWN"
                    and touchdown_enabled
                )
                or (
                    scoring_type == "FIELD_GOAL"
                    and field_goal_enabled
                )
            )

            if (
                scoring_team
                and scoring_team in watched_teams
                and scoring_type
                and event_enabled
                and not self._is_on_cooldown(
                    state=state,
                    event_type=scoring_type,
                    team=scoring_team,
                    now=now,
                    cooldown_seconds=(
                        cooldown_seconds
                    ),
                )
            ):
                if scoring_type == "TOUCHDOWN":
                    headline = "TOUCHDOWN"
                    chant = (
                        "TOUCH",
                        "DOWN",
                    )
                else:
                    headline = "FIELD GOAL"
                    chant = (
                        "FIELD",
                        "GOAL",
                    )

                score_detail = (
                    f"{str(game.away).upper()} "
                    f"{away_score}-{home_score} "
                    f"{str(game.home).upper()}"
                )

                alert = self._enqueue_event_alert(
                    game=game,
                    alert_type=scoring_type,
                    team=scoring_team,
                    headline=headline,
                    detail=score_detail,
                    chant=chant,
                    now=now,
                    chant_frame_seconds=(
                        chant_frame_seconds
                    ),
                    details_frame_seconds=(
                        details_frame_seconds
                    ),
                )

                if alert is not None:
                    created_alerts.append(alert)

                    self._mark_alert(
                        state=state,
                        event_type=scoring_type,
                        team=scoring_team,
                        now=now,
                    )

        if new_scoring_event:
            state.last_scoring_signature = (
                scoring_signature
            )

        state.away_score = away_score
        state.home_score = home_score
        state.last_play_id = play_id
        state.last_play_text = play_text

    def _process_redzone_alert(
        self,
        *,
        game: FootballGame,
        state: GamePossessionState,
        current_team: str,
        watched_teams: set[str],
        enabled: bool,
        redzone_enabled: bool,
        cooldown_seconds: float,
        chant_frame_seconds: float,
        details_frame_seconds: float,
        now: float,
        created_alerts: list[PossessionAlert],
    ) -> None:
        currently_in_redzone = self._is_redzone(
            game,
            current_team,
        )

        if not currently_in_redzone:
            # Clearing this value allows another alert if
            # the team leaves and later re-enters.
            state.redzone_team = ""
            return

        # Do not repeatedly alert while the offense remains
        # inside the red zone across multiple polls.
        if state.redzone_team == current_team:
            return

        state.redzone_team = current_team

        if (
            not enabled
            or not redzone_enabled
            or current_team not in watched_teams
        ):
            return

        if self._is_on_cooldown(
            state=state,
            event_type="REDZONE",
            team=current_team,
            now=now,
            cooldown_seconds=cooldown_seconds,
        ):
            return

        field_position = self._field_position_text(
            game,
        )

        alert = self._enqueue_event_alert(
            game=game,
            alert_type="REDZONE",
            team=current_team,
            headline="RED ZONE",
            detail=field_position,
            chant=(
                "RED",
                "ZONE",
            ),
            now=now,
            chant_frame_seconds=(
                chant_frame_seconds
            ),
            details_frame_seconds=(
                details_frame_seconds
            ),
        )

        if alert is not None:
            created_alerts.append(alert)

            self._mark_alert(
                state=state,
                event_type="REDZONE",
                team=current_team,
                now=now,
            )

    def _process_possession_alert(
        self,
        *,
        game: FootballGame,
        state: GamePossessionState,
        current_team: str,
        watched_teams: set[str],
        enabled: bool,
        possession_enabled: bool,
        confirmations_required: int,
        cooldown_seconds: float,
        chant_frame_seconds: float,
        details_frame_seconds: float,
        now: float,
        created_alerts: list[PossessionAlert],
    ) -> None:
        if not state.confirmed_team:
            # First possession observation initializes
            # state and does not generate an alert.
            state.confirmed_team = current_team
            self._reset_candidate(state)
            return

        if current_team == state.confirmed_team:
            self._reset_candidate(state)
            return

        if current_team == state.candidate_team:
            state.candidate_count += 1
        else:
            state.candidate_team = current_team
            state.candidate_count = 1

        if (
            state.candidate_count
            < confirmations_required
        ):
            return

        state.confirmed_team = current_team
        self._reset_candidate(state)

        if (
            not enabled
            or not possession_enabled
            or current_team not in watched_teams
        ):
            return

        if self._is_on_cooldown(
            state=state,
            event_type="POSSESSION",
            team=current_team,
            now=now,
            cooldown_seconds=cooldown_seconds,
        ):
            return

        team_definition = get_team_alert(
            current_team
        )

        if team_definition is None:
            return

        alert = self._enqueue_event_alert(
            game=game,
            alert_type="POSSESSION",
            team=current_team,
            headline=(
                team_definition.possession_label
            ),
            detail=self._field_position_text(
                game
            ),
            chant=team_definition.chant,
            now=now,
            chant_frame_seconds=(
                chant_frame_seconds
            ),
            details_frame_seconds=(
                details_frame_seconds
            ),
        )

        if alert is not None:
            created_alerts.append(alert)

            self._mark_alert(
                state=state,
                event_type="POSSESSION",
                team=current_team,
                now=now,
            )

    def _enqueue_event_alert(
        self,
        *,
        game: FootballGame,
        alert_type: str,
        team: str,
        headline: str,
        detail: str,
        chant: tuple[str, ...],
        now: float,
        chant_frame_seconds: float,
        details_frame_seconds: float,
    ) -> Optional[PossessionAlert]:
        team = str(team or "").upper()

        team_definition = get_team_alert(team)

        if team_definition is None:
            return None

        away = str(
            game.away or ""
        ).upper()

        home = str(
            game.home or ""
        ).upper()

        opponent = (
            home
            if team == away
            else away
        )

        alert = PossessionAlert(
            game_id=self._game_id(game),
            alert_type=str(
                alert_type or "POSSESSION"
            ).upper(),
            team=team,
            opponent=opponent,
            headline=str(
                headline or ""
            ).upper(),
            detail=str(
                detail or ""
            ).upper(),
            possession_label=(
                team_definition.possession_label
            ),
            chant=tuple(chant),
            primary=team_definition.primary,
            accent=team_definition.accent,
            down=self._nonnegative_int(
                game.down
            ),
            distance=self._nonnegative_int(
                game.distance
            ),
            yardline_side=str(
                game.yardline_side or ""
            ).upper(),
            yardline_number=(
                self._nonnegative_int(
                    game.yardline_number
                )
            ),
            quarter=self._nonnegative_int(
                game.quarter
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

        return alert

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
                alert_type=queued_alert.alert_type,
                team=queued_alert.team,
                opponent=queued_alert.opponent,
                headline=queued_alert.headline,
                detail=queued_alert.detail,
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
        alert_type: str = "POSSESSION",
    ) -> bool:
        if now is None:
            now = time.monotonic()

        team = str(team).upper()
        alert_type = str(
            alert_type or "POSSESSION"
        ).upper()

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

        if alert_type == "TOUCHDOWN":
            headline = "TOUCHDOWN"
            detail = f"{team} 7-0 TEST"
            chant = (
                "TOUCH",
                "DOWN",
            )

        elif alert_type == "FIELD_GOAL":
            headline = "FIELD GOAL"
            detail = f"{team} 3-0 TEST"
            chant = (
                "FIELD",
                "GOAL",
            )

        elif alert_type == "REDZONE":
            headline = "RED ZONE"
            detail = "AT TEST 15"
            chant = (
                "RED",
                "ZONE",
            )

        else:
            alert_type = "POSSESSION"
            headline = (
                team_definition.possession_label
            )
            detail = f"AT {team} 37"
            chant = team_definition.chant

        test_alert = PossessionAlert(
            game_id="test",
            alert_type=alert_type,
            team=team,
            opponent="TEST",
            headline=headline,
            detail=detail,
            possession_label=(
                team_definition.possession_label
            ),
            chant=chant,
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
    def _is_redzone(
        game: FootballGame,
        possessing_team: str,
    ) -> bool:
        possessing_team = str(
            possessing_team or ""
        ).upper()

        away = str(
            game.away or ""
        ).upper()

        home = str(
            game.home or ""
        ).upper()

        yardline_side = str(
            game.yardline_side or ""
        ).upper()

        yardline_number = (
            PossessionAlertManager._nonnegative_int(
                game.yardline_number
            )
        )

        if (
            not possessing_team
            or possessing_team not in {away, home}
            or not yardline_side
            or yardline_number < 1
            or yardline_number > 20
        ):
            return False

        opponent = (
            home
            if possessing_team == away
            else away
        )

        # ESPN field position such as "GB 15" means
        # the ball is on Green Bay's 15-yard line.
        return yardline_side == opponent

    @staticmethod
    def _scoring_type(
        play_text: str,
        points: int,
    ) -> str:
        normalized = (
            f" {str(play_text or '').upper()} "
        )

        if (
            "FIELD GOAL" in normalized
            or "FG IS GOOD" in normalized
            or "FG GOOD" in normalized
        ):
            return "FIELD_GOAL"

        if (
            "TOUCHDOWN" in normalized
            or " TD " in normalized
            or points in {6, 7, 8}
        ):
            return "TOUCHDOWN"

        # A three-point score is normally a field goal.
        # Play text remains the preferred signal.
        if points == 3:
            return "FIELD_GOAL"

        return ""

    @staticmethod
    def _looks_like_scoring_play(
        play_text: str,
    ) -> bool:
        normalized = str(
            play_text or ""
        ).upper()

        return any(
            marker in normalized
            for marker in (
                "TOUCHDOWN",
                "FIELD GOAL",
                "FG IS GOOD",
                "FG GOOD",
                "EXTRA POINT",
                "TWO-POINT",
                "2-PT",
                "SAFETY",
            )
        )

    @staticmethod
    def _field_position_text(
        game: FootballGame,
    ) -> str:
        side = str(
            game.yardline_side or ""
        ).upper()

        number = (
            PossessionAlertManager._nonnegative_int(
                game.yardline_number
            )
        )

        if side and number:
            return f"AT {side} {number}"

        if side:
            return f"AT {side}"

        return "BALL IN PLAY"

    @staticmethod
    def _alert_key(
        event_type: str,
        team: str,
    ) -> str:
        return (
            f"{str(event_type).upper()}:"
            f"{str(team).upper()}"
        )

    @classmethod
    def _is_on_cooldown(
        cls,
        *,
        state: GamePossessionState,
        event_type: str,
        team: str,
        now: float,
        cooldown_seconds: float,
    ) -> bool:
        key = cls._alert_key(
            event_type,
            team,
        )

        last_alert_at = state.last_alert_times.get(
            key,
            0.0,
        )

        return (
            last_alert_at > 0.0
            and now - last_alert_at
            < cooldown_seconds
        )

    @classmethod
    def _mark_alert(
        cls,
        *,
        state: GamePossessionState,
        event_type: str,
        team: str,
        now: float,
    ) -> None:
        key = cls._alert_key(
            event_type,
            team,
        )

        state.last_alert_times[key] = now

    @staticmethod
    def _initialize_or_sync_scores(
        state: GamePossessionState,
        game: FootballGame,
    ) -> None:
        state.away_score = (
            PossessionAlertManager._nonnegative_int(
                game.away_score
            )
        )

        state.home_score = (
            PossessionAlertManager._nonnegative_int(
                game.home_score
            )
        )

        state.last_play_id = str(
            getattr(
                game,
                "last_play_id",
                "",
            )
            or ""
        )

        state.last_play_text = str(
            getattr(
                game,
                "last_play_text",
                "",
            )
            or ""
        )

    @staticmethod
    def _game_id(
        game: FootballGame,
    ) -> str:
        event_id = str(
            game.event_id or ""
        ).strip()

        if event_id:
            return event_id

        away = str(
            game.away or ""
        ).upper()

        home = str(
            game.home or ""
        ).upper()

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
        stale_cutoff = now - (
            12 * 60 * 60
        )

        stale_ids = [
            game_id
            for game_id, state
            in self._game_states.items()
            if (
                game_id not in seen_game_ids
                and state.last_seen_at
                < stale_cutoff
            )
        ]

        for game_id in stale_ids:
            del self._game_states[game_id]

    @staticmethod
    def _nonnegative_int(value) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0

        return max(0, parsed)

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


possession_alert_manager = (
    PossessionAlertManager()
)