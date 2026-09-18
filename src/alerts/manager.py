from collections import deque
from dataclasses import dataclass, field
from threading import RLock
import re
import time
from typing import Optional

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

    last_alert_times: dict = field(default_factory=dict)

    last_seen_at: float = 0.0

    mlb_initialized: bool = False
    saw_live: bool = False
    win_alerted: bool = False
    close_game_alerted: bool = False
    seen_play_ids: set = field(default_factory=set)


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
        homerun_enabled = bool(alerts_settings.get("homerun_enabled", True))
        mlb_win_enabled = bool(alerts_settings.get("mlb_win_enabled", True))
        close_game_enabled = bool(alerts_settings.get("close_game_enabled", True))

        teams_by_league = alerts_settings.get(
            "teams",
            {},
        )

        if not isinstance(
            teams_by_league,
            dict,
        ):
            teams_by_league = {}

        # Backward compatibility with the old
        # NFL-only alert configuration.
        if "nfl" not in teams_by_league:
            teams_by_league["nfl"] = (
                alerts_settings.get(
                    "possession_teams",
                    [],
                )
            )

        confirmations_required = self._safe_int(alerts_settings.get("confirmations_required", 2), default=2, minimum=1, maximum=5)
        cooldown_seconds = self._safe_float(alerts_settings.get("cooldown_seconds", 20), default=20.0, minimum=0.0, maximum=300.0)
        chant_frame_seconds = self._safe_float(alerts_settings.get("chant_frame_seconds", 0.65), default=0.65, minimum=0.2, maximum=3.0)

        details_frame_seconds = self._safe_float(alerts_settings.get("details_frame_seconds", 4.0), default=4.0, minimum=1.0, maximum=15.0)

        created_alerts: list[PossessionAlert] = []

        seen_game_ids: set[str] = set()

        with self._lock:
            for game in games:
                league = self._game_league(
                    game
                )

                if not league:
                    continue

                watched_teams = {
                    str(team).upper()
                    for team in teams_by_league.get(
                        league,
                        [],
                    )
                }

                game_id = self._game_id(game)

                if not game_id:
                    continue

                seen_game_ids.add(game_id)

                state = self._game_states.setdefault(game_id, GamePossessionState())

                state.last_seen_at = now

                if league == "mlb":
                    self._process_mlb_alerts(
                        game=game,
                        state=state,
                        watched_teams=watched_teams,
                        enabled=enabled,
                        homerun_enabled=homerun_enabled,
                        mlb_win_enabled=mlb_win_enabled,
                        close_game_enabled=close_game_enabled,
                        cooldown_seconds=cooldown_seconds,
                        chant_frame_seconds=chant_frame_seconds,
                        details_frame_seconds=details_frame_seconds,
                        now=now,
                        created_alerts=created_alerts,
                    )
                    continue

                status = str(game.status or "").upper()

                if status not in LIVE_STATUSES:
                    self._reset_candidate(state)
                    state.redzone_team = ""

                    self._initialize_or_sync_scores(state, game)
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

                current_team = str(game.possession or "").upper()

                valid_teams = {str(game.away or "").upper(), str(game.home or "").upper()}

                valid_teams.discard("")

                if (not current_team or current_team not in valid_teams):
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

            self._remove_stale_states(seen_game_ids, now)

        return created_alerts

    def _process_mlb_alerts(
        self,
        *,
        game,
        state,
        watched_teams,
        enabled,
        homerun_enabled,
        mlb_win_enabled,
        close_game_enabled,
        cooldown_seconds,
        chant_frame_seconds,
        details_frame_seconds,
        now,
        created_alerts,
    ):
        status = str(game.status or "").upper()
        away = str(game.away or "").upper()
        home = str(game.home or "").upper()
        involved = {away, home}
        involved.discard("")
        watching_game = bool(involved & watched_teams)

        if not state.mlb_initialized:
            state.seen_play_ids = {
                play.play_id
                for play in getattr(game, "scoring_plays", ())
                if getattr(play, "play_id", "")
            }
            state.away_score = self._nonnegative_int(game.away_score)
            state.home_score = self._nonnegative_int(game.home_score)
            state.mlb_initialized = True
            state.saw_live = status in LIVE_STATUSES
            state.win_alerted = status in {"FINAL", "GAME OVER"}

            if status in LIVE_STATUSES:
                self._process_mlb_close_game(
                    game=game,
                    state=state,
                    watched_teams=watched_teams,
                    watching_game=watching_game,
                    enabled=enabled,
                    close_game_enabled=close_game_enabled,
                    cooldown_seconds=cooldown_seconds,
                    chant_frame_seconds=chant_frame_seconds,
                    details_frame_seconds=details_frame_seconds,
                    now=now,
                    created_alerts=created_alerts,
                )

            return

        if status in LIVE_STATUSES:
            state.saw_live = True
            state.win_alerted = False

            self._process_mlb_home_runs(
                game=game,
                state=state,
                watched_teams=watched_teams,
                enabled=enabled,
                homerun_enabled=homerun_enabled,
                cooldown_seconds=cooldown_seconds,
                chant_frame_seconds=chant_frame_seconds,
                details_frame_seconds=details_frame_seconds,
                now=now,
                created_alerts=created_alerts,
            )

            self._process_mlb_close_game(
                game=game,
                state=state,
                watched_teams=watched_teams,
                watching_game=watching_game,
                enabled=enabled,
                close_game_enabled=close_game_enabled,
                cooldown_seconds=cooldown_seconds,
                chant_frame_seconds=chant_frame_seconds,
                details_frame_seconds=details_frame_seconds,
                now=now,
                created_alerts=created_alerts,
            )
            return

        state.close_game_alerted = False

        if status in {"FINAL", "GAME OVER"}:
            self._process_mlb_win(
                game=game,
                state=state,
                watched_teams=watched_teams,
                watching_game=watching_game,
                enabled=enabled,
                mlb_win_enabled=mlb_win_enabled,
                cooldown_seconds=cooldown_seconds,
                chant_frame_seconds=chant_frame_seconds,
                details_frame_seconds=details_frame_seconds,
                now=now,
                created_alerts=created_alerts,
            )

    def _process_mlb_home_runs(
        self,
        *,
        game,
        state,
        watched_teams,
        enabled,
        homerun_enabled,
        cooldown_seconds,
        chant_frame_seconds,
        details_frame_seconds,
        now,
        created_alerts,
    ):
        for play in getattr(game, "scoring_plays", ()):
            play_id = str(getattr(play, "play_id", "") or "")

            if not play_id or play_id in state.seen_play_ids:
                continue

            state.seen_play_ids.add(play_id)

            if not getattr(play, "is_home_run", False):
                continue

            team = str(play.batting_team or "").upper()

            if (
                not enabled
                or not homerun_enabled
                or team not in watched_teams
            ):
                continue

            if self._is_on_cooldown(
                state=state,
                event_type="HOME_RUN",
                team=team,
                now=now,
                cooldown_seconds=cooldown_seconds,
            ):
                continue

            rbi = self._nonnegative_int(play.rbi)
            batter = str(play.batter or team).upper()
            away_score = self._nonnegative_int(game.away_score)
            home_score = self._nonnegative_int(game.home_score)

            if rbi >= 4:
                headline = "GRAND SLAM"
                chant = ("GRAND", "SLAM")
                kind = "GRAND SLAM"
            elif rbi == 1:
                headline = "HOME RUN"
                chant = ("GONE",)
                kind = "SOLO HR"
            else:
                headline = "HOME RUN"
                chant = ("GONE",)
                kind = f"{rbi} RUN HR"

            detail = self._fit_alert_detail(
                f"{batter} {kind} {away_score}-{home_score}"
            )

            alert = self._enqueue_event_alert(
                game=game,
                alert_type="HOME_RUN",
                team=team,
                headline=headline,
                detail=detail,
                chant=chant,
                now=now,
                chant_frame_seconds=chant_frame_seconds,
                details_frame_seconds=details_frame_seconds,
            )

            if alert is not None:
                created_alerts.append(alert)
                self._mark_alert(
                    state=state,
                    event_type="HOME_RUN",
                    team=team,
                    now=now,
                )

    def _process_mlb_close_game(
        self,
        *,
        game,
        state,
        watched_teams,
        watching_game,
        enabled,
        close_game_enabled,
        cooldown_seconds,
        chant_frame_seconds,
        details_frame_seconds,
        now,
        created_alerts,
    ):
        inning = self._nonnegative_int(game.inning)
        away_score = self._nonnegative_int(game.away_score)
        home_score = self._nonnegative_int(game.home_score)
        margin = abs(home_score - away_score)
        is_close = inning >= 7 and margin <= 1

        if not is_close:
            state.close_game_alerted = False
            return

        if state.close_game_alerted:
            return

        if (
            not enabled
            or not close_game_enabled
            or not watching_game
        ):
            return

        away = str(game.away or "").upper()
        home = str(game.home or "").upper()
        team = home if home in watched_teams else away

        if self._is_on_cooldown(
            state=state,
            event_type="CLOSE_GAME",
            team=team,
            now=now,
            cooldown_seconds=cooldown_seconds,
        ):
            return

        half = "TOP" if game.top_inning else "BOT"
        headline = "CLOSE GAME"
        chant = ("CLOSE", "GAME")
        detail = self._fit_alert_detail(
            f"{away} {away_score}-{home_score} {home} {half} {inning}"
        )

        alert = self._enqueue_event_alert(
            game=game,
            alert_type="CLOSE_GAME",
            team=team,
            headline=headline,
            detail=detail,
            chant=chant,
            now=now,
            chant_frame_seconds=chant_frame_seconds,
            details_frame_seconds=details_frame_seconds,
        )

        state.close_game_alerted = True

        if alert is not None:
            created_alerts.append(alert)
            self._mark_alert(
                state=state,
                event_type="CLOSE_GAME",
                team=team,
                now=now,
            )

    def _process_mlb_win(
        self,
        *,
        game,
        state,
        watched_teams,
        watching_game,
        enabled,
        mlb_win_enabled,
        cooldown_seconds,
        chant_frame_seconds,
        details_frame_seconds,
        now,
        created_alerts,
    ):
        if state.win_alerted or not state.saw_live:
            state.win_alerted = True
            return

        state.win_alerted = True

        if not enabled or not mlb_win_enabled or not watching_game:
            return

        away_score = self._nonnegative_int(game.away_score)
        home_score = self._nonnegative_int(game.home_score)

        if away_score == home_score:
            return

        away = str(game.away or "").upper()
        home = str(game.home or "").upper()
        winner = home if home_score > away_score else away

        if winner not in watched_teams:
            return

        if self._is_on_cooldown(
            state=state,
            event_type="WIN",
            team=winner,
            now=now,
            cooldown_seconds=cooldown_seconds,
        ):
            return

        alert = self._enqueue_event_alert(
            game=game,
            alert_type="WIN",
            team=winner,
            headline="WIN",
            detail=self._fit_alert_detail(
                f"{away} {away_score}-{home_score} {home}"
            ),
            chant=(winner, "WIN"),
            now=now,
            chant_frame_seconds=chant_frame_seconds,
            details_frame_seconds=details_frame_seconds,
        )

        if alert is not None:
            created_alerts.append(alert)
            self._mark_alert(
                state=state,
                event_type="WIN",
                team=winner,
                now=now,
            )

    def _process_scoring_alert(self, *, game, state, watched_teams, enabled, touchdown_enabled, field_goal_enabled, cooldown_seconds, chant_frame_seconds, details_frame_seconds, now, created_alerts):
        away_score = self._nonnegative_int(game.away_score)
        home_score = self._nonnegative_int(game.home_score)

        play_id = str(getattr(game, "last_play_id", "") or "").strip()
        play_text = str(getattr(game, "last_play_text", "") or "").strip()

        if (state.away_score is None or state.home_score is None):
            state.away_score = away_score
            state.home_score = home_score
            state.last_play_id = play_id
            state.last_play_text = play_text
            return

        away_delta = (away_score - state.away_score)
        home_delta = (home_score - state.home_score)

        scoring_signature = (play_id if play_id else (f"{away_score}:{home_score}:" f"{play_text.upper()}"))

        score_changed = (away_delta > 0 or home_delta > 0)

        new_scoring_event = (score_changed and scoring_signature != state.last_scoring_signature)

        if (enabled and new_scoring_event):
            scoring_team = ""
            points = 0

            if (away_delta > 0 and home_delta <= 0):
                scoring_team = str(game.away or "").upper()
                points = away_delta

            elif (home_delta > 0 and away_delta <= 0):
                scoring_team = str(game.home or "").upper()
                points = home_delta

            scoring_type = self._scoring_type(play_text, points)

            event_enabled = ((scoring_type == "TOUCHDOWN" and touchdown_enabled) or (scoring_type == "FIELD_GOAL" and field_goal_enabled))

            if (scoring_team and scoring_team in watched_teams and scoring_type and event_enabled and not self._is_on_cooldown(state=state, event_type=scoring_type, team=scoring_team, now=now, cooldown_seconds=(cooldown_seconds))):
                if scoring_type == "TOUCHDOWN":
                    headline = "TOUCHDOWN"
                    chant = ("TOUCH", "DOWN")
                else:
                    headline = "FIELD GOAL"
                    chant = ("FIELD", "GOAL")

                play_detail = self._alert_play_detail(
                    alert_type=scoring_type,
                    game=game,
                    team=scoring_team,
                )

                alert = self._enqueue_event_alert(
                    game=game,
                    alert_type=scoring_type,
                    team=scoring_team,
                    headline=headline,
                    detail=play_detail,
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

                    self._mark_alert(state=state, event_type=scoring_type, team=scoring_team, now=now)

        if new_scoring_event:
            state.last_scoring_signature = (scoring_signature)

        state.away_score = away_score
        state.home_score = home_score
        state.last_play_id = play_id
        state.last_play_text = play_text

    def _process_redzone_alert(self, *, game, state, current_team, watched_teams, enabled, redzone_enabled, cooldown_seconds, chant_frame_seconds, details_frame_seconds, now, created_alerts):
        currently_in_redzone = self._is_redzone(game, current_team)

        if not currently_in_redzone:
            state.redzone_team = ""
            return

        if state.redzone_team == current_team:
            return

        state.redzone_team = current_team

        if (not enabled or not redzone_enabled or current_team not in watched_teams):
            return

        if self._is_on_cooldown(state=state, event_type="REDZONE", team=current_team, now=now, cooldown_seconds=cooldown_seconds):
            return

        field_position = self._field_position_text(game)

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
            current_team,
            league=self._game_league(
                game
            ),
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
            detail=self._alert_play_detail(
                alert_type="POSSESSION",
                game=game,
                team=current_team,
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

    @classmethod
    def _alert_play_detail(
        cls,
        *,
        alert_type: str,
        game: FootballGame,
        team: str,
    ) -> str:
        """Build a short explanation for the alert details frame."""
        alert_type = str(alert_type or "").upper()

        play_text = str(
            getattr(
                game,
                "last_play_text",
                "",
            )
            or ""
        ).strip()

        if not play_text:
            if alert_type == "POSSESSION":
                return "CHANGE OF POSSESSION"

            return cls._field_position_text(
                game
            )

        compact = re.sub(
            r"\s+",
            " ",
            play_text,
        ).strip()

        upper = compact.upper()

        # ---------------------------------------------
        # Change of possession
        # ---------------------------------------------
        if alert_type == "POSSESSION":

            # Interception
            interception = re.search(
                r"INTERCEPTED\s+BY\s+([A-Z][A-Z.'’\-]+)",
                upper,
            )

            if interception:
                return (
                    f"INT BY "
                    f"{interception.group(1)}"
                )

            # Fumble recovery
            recovery = re.search(
                r"RECOVERED\s+BY\s+"
                r"(?:[A-Z]{2,4}-)?"
                r"([A-Z][A-Z.'’\-]+)",
                upper,
            )

            if (
                "FUMBL" in upper
                and recovery
            ):
                return (
                    f"FUMBLE REC BY "
                    f"{recovery.group(1)}"
                )

            if "FUMBL" in upper:
                return "FUMBLE RECOVERY"

            # Missed field goal
            missed_fg = re.search(
                r"(\d{1,2})\s*"
                r"(?:YD|YARD)\s+"
                r"FIELD\s+GOAL",
                upper,
            )

            if (
                "FIELD GOAL" in upper
                and any(
                    marker in upper
                    for marker in (
                        "NO GOOD",
                        "MISSED",
                        "MISSES",
                    )
                )
            ):
                if missed_fg:
                    return (
                        f"MISSED "
                        f"{missed_fg.group(1)} "
                        f"YD FG"
                    )

                return "MISSED FIELD GOAL"

            # Punt
            punt_yards = re.search(
                r"PUNTS?\s+"
                r"(\d{1,3})\s+"
                r"YARDS?",
                upper,
            )

            if punt_yards:
                return (
                    f"PUNT "
                    f"{punt_yards.group(1)} "
                    f"YDS"
                )

            if "PUNT" in upper:
                return "PUNT"

           # Kickoff
            if any(
                marker in upper
                for marker in (
                    "KICKOFF",
                    "KICKS OFF",
                    "KICKED OFF",
                    "ONSIDE KICK",
                    "TOUCHBACK",
                )
            ):
                return "KICKOFF"

            # ESPN commonly formats a kickoff like:
            # "X.X kicks 65 yards from ABC 35..."
            if (
                "KICKS" in upper
                and (
                    " YARDS FROM " in upper
                    or " YDS FROM " in upper
                    or " END ZONE" in upper
                )
            ):
                return "KICKOFF"

            # Turnover on downs should only be shown
            # when ESPN explicitly tells us that is
            # what happened.
            if (
                "TURNOVER ON DOWNS" in upper
                or "TURNED OVER ON DOWNS" in upper
            ):
                return "TURNOVER ON DOWNS"

            # Possession definitely changed, but ESPN's
            # current last-play text does not tell us
            # exactly why. Do not guess that it was a
            # turnover on downs.
            return "CHANGE OF POSSESSION"

        # ---------------------------------------------
        # Field goal
        # ---------------------------------------------
        if alert_type == "FIELD_GOAL":
            distance = re.search(
                r"(\d{1,2})\s*"
                r"(?:YD|YARD)\s+"
                r"FIELD\s+GOAL",
                upper,
            )

            kicker = re.match(
                r"(?:\([^)]*\)\s*)?"
                r"([A-Z][A-Z.'’\-]+)",
                upper,
            )

            if (
                kicker
                and distance
            ):
                return (
                    f"{kicker.group(1)} "
                    f"{distance.group(1)} "
                    f"YD FG"
                )

            if distance:
                return (
                    f"{distance.group(1)} "
                    f"YD FIELD GOAL"
                )

            return "FIELD GOAL GOOD"

        # ---------------------------------------------
        # Touchdown
        # ---------------------------------------------
        if alert_type == "TOUCHDOWN":

            # Pick six
            interception = re.search(
                r"INTERCEPTED\s+BY\s+"
                r"([A-Z][A-Z.'’\-]+)",
                upper,
            )

            return_yards = re.search(
                r"FOR\s+"
                r"(\d{1,3})\s+"
                r"YARDS?",
                upper,
            )

            if interception:
                if return_yards:
                    return (
                        f"{interception.group(1)} "
                        f"{return_yards.group(1)} "
                        f"YD PICK 6"
                    )

                return (
                    f"PICK 6 "
                    f"{interception.group(1)}"
                )

            # Passing touchdown
            pass_td = re.search(
                r"([A-Z][A-Z.'’\-]+)"
                r"\s+PASS.*?\s+TO\s+"
                r"([A-Z][A-Z.'’\-]+)"
                r".*?FOR\s+"
                r"(\d{1,3})\s+YARDS?",
                upper,
            )

            if pass_td:
                return (
                    f"{pass_td.group(1)} "
                    f"TO "
                    f"{pass_td.group(2)} "
                    f"{pass_td.group(3)} "
                    f"YD TD"
                )

            # Rushing touchdown
            rush_td = re.search(
                r"([A-Z][A-Z.'’\-]+)"
                r".*?FOR\s+"
                r"(\d{1,3})\s+YARDS?",
                upper,
            )

            if (
                rush_td
                and "PASS" not in upper
            ):
                return (
                    f"{rush_td.group(1)} "
                    f"{rush_td.group(2)} "
                    f"YD RUSH TD"
                )

            # Unknown TD format:
            # show a shortened version of ESPN's
            # actual play instead of inventing info.
            shortened = re.sub(
                r"^\([^)]*\)\s*",
                "",
                upper,
            )

            shortened = re.sub(
                r"\s+TOUCHDOWN.*$",
                " TD",
                shortened,
            )

            return cls._fit_alert_detail(
                shortened
            )

        return cls._fit_alert_detail(
            upper
        )

    @staticmethod
    def _fit_alert_detail(
        text: str,
        max_chars: int = 55,
    ) -> str:
        """Keep details short enough for the alert frame."""

        text = re.sub(
            r"\s+",
            " ",
            str(text or ""),
        ).strip().upper()

        if len(text) <= max_chars:
            return text

        shortened = (
            text[:max_chars]
            .rsplit(" ", 1)[0]
            .rstrip(" ,.-")
        )

        return (
            shortened
            or text[:max_chars]
        )

    def _enqueue_event_alert(
        self,
        *,
        game,
        alert_type: str,
        team: str,
        headline: str,
        detail: str,
        chant: tuple[str, ...],
        now: float,
        chant_frame_seconds: float,
        details_frame_seconds: float,
    ) -> Optional[PossessionAlert]:
        team = str(
            team
            or ""
        ).upper()

        league = self._game_league(
            game
        )

        team_definition = get_team_alert(
            team,
            league=league,
        )

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
            league=league,
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
                getattr(game, "down", 0)
            ),
            distance=self._nonnegative_int(
                getattr(game, "distance", 0)
            ),
            yardline_side=str(
                getattr(game, "yardline_side", "") or ""
            ).upper(),
            yardline_number=(
                self._nonnegative_int(
                    getattr(game, "yardline_number", 0)
                )
            ),
            quarter=self._nonnegative_int(
                getattr(game, "quarter", None)
                if getattr(game, "quarter", None) is not None
                else getattr(game, "inning", 0)
            ),
            clock=str(
                getattr(game, "clock", "") or ""
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
                league=queued_alert.league,
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
    def _game_league(game) -> str:
        class_name = (
            game.__class__.__name__
        )

        if class_name == "FootballGame":
            return "nfl"

        if class_name == "CollegeFootballGame":
            return "cfb"

        if class_name == "BaseballGame":
            return "mlb"

        return ""

    @classmethod
    def _game_id(
        cls,
        game,
    ) -> str:
        league = cls._game_league(
            game
        )

        if not league:
            return ""

        event_id = str(
            getattr(game, "event_id", "")
            or getattr(game, "game_pk", "")
            or ""
        ).strip()

        if event_id:
            return (
                f"{league}:{event_id}"
            )

        away = str(
            getattr(
                game,
                "away",
                "",
            )
            or ""
        ).upper()

        home = str(
            getattr(
                game,
                "home",
                "",
            )
            or ""
        ).upper()

        if not away or not home:
            return ""

        return (
            f"{league}:"
            f"{away}@{home}"
        )

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