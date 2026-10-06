from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from bets.catalog import (
    OPEN_STATUSES,
    SCOPE_GAME,
    SCOPE_PLAYER,
    STATUS_LIVE,
    STATUS_LOST,
    STATUS_PENDING,
    STATUS_REVIEW,
    STATUS_WON,
    market_for,
)
from bets.odds import combine_american_odds
from bets.probability import combine_independent, estimate_hit_chance
from bets.providers import get_provider
from bets.settlement import grade_game_market, grade_player_market, settle_parlay
from bets.store import (
    add_notice,
    list_open_bets,
    update_bet_fields,
    update_leg_progress,
    utc_now,
)


_ticket_cache: list["BetTicket"] = []
_notice_started_at: float | None = None
_active_notice: dict[str, Any] | None = None
_bets_revision = 0
NOTICE_SECONDS = 4.5


def bets_revision() -> int:
    return _bets_revision


@dataclass
class BetTicket:
    ticket_id: str
    title: str
    detail: str
    status: str
    progress: float | None
    under: bool
    page: int = 0
    pages: tuple = ()
    team: str = ""
    league: str = ""
    need: str = ""
    clock: str = ""
    kind: str = "single"
    legs: tuple = ()
    width: int = 132
    chance: float | None = None


def ticker_tickets() -> list[BetTicket]:
    return list(_ticket_cache)


def refresh_open_bets() -> None:
    """Batch-update open bets from league providers. Safe to call on refresh."""
    global _ticket_cache, _bets_revision

    try:
        bets = list_open_bets()
    except Exception as error:
        print("Bet store unavailable:", error)
        return

    snapshots: dict[tuple[str, str], Any] = {}
    tickets: list[BetTicket] = []

    events = {
        (str(leg.get("league")), str(leg.get("event_id")))
        for bet in bets
        for leg in bet.get("legs") or []
        if leg.get("league") and leg.get("event_id")
        and leg.get("status") in OPEN_STATUSES
    }

    for league, event_id in events:
        try:
            snapshots[(league, event_id)] = get_provider(league).snapshot(event_id)
        except Exception as error:
            print(f"Bet snapshot failed for {league} {event_id}: {error}")
            snapshots[(league, event_id)] = None

    for bet in bets:
        changed_legs = []
        for leg in bet.get("legs") or []:
            if leg.get("status") not in OPEN_STATUSES and not bet.get("manual_result"):
                continue
            snapshot = snapshots.get((str(leg.get("league")), str(leg.get("event_id"))))
            previous = dict(leg)
            updated = _apply_snapshot(leg, snapshot)
            if updated != previous:
                update_leg_progress(leg["id"], {
                    key: updated.get(key)
                    for key in (
                        "status", "current_value", "final_value", "game_status",
                        "period", "clock", "stale", "settle_source", "last_error",
                    )
                })
                _maybe_notice(bet, previous, updated)
            changed_legs.append(updated)
            leg.update(updated)

        if not bet.get("manual_result"):
            new_status = settle_parlay([leg.get("status") for leg in bet.get("legs") or []])
            if bet.get("kind") == "single" and bet.get("legs"):
                new_status = bet["legs"][0].get("status") or STATUS_PENDING
            if new_status != bet.get("status"):
                fields = {"status": new_status}
                if new_status not in OPEN_STATUSES:
                    fields["settled_at"] = utc_now()
                update_bet_fields(bet["id"], None, fields)
                _maybe_bet_notice(bet, bet.get("status"), new_status)
                bet["status"] = new_status

        tickets.extend(_tickets_for(bet))

    _ticket_cache = tickets
    _bets_revision += 1


def _apply_snapshot(leg: dict[str, Any], snapshot) -> dict[str, Any]:
    updated = dict(leg)
    if snapshot is None:
        updated["stale"] = 1
        return updated

    updated["stale"] = 0
    updated["game_status"] = snapshot.status
    updated["period"] = snapshot.period
    updated["clock"] = snapshot.clock
    if snapshot.away and snapshot.home:
        updated["away_team"] = snapshot.away
        updated["home_team"] = snapshot.home
        picked = _picked_team(updated)
        if picked:
            updated["team"] = picked
    updated["remaining_fraction"] = snapshot.remaining_fraction

    final = str(snapshot.status).lower() == "final"
    live = str(snapshot.status).lower() in {"live", "overtime", "intermission"}
    try:
        market = market_for(leg.get("market"))
    except ValueError:
        updated["status"] = STATUS_REVIEW
        updated["last_error"] = "Unknown market"
        return updated

    value = None
    if market.scope == SCOPE_PLAYER:
        stats = snapshot.player_stats.get(str(leg.get("player_id") or "")) or {}
        value = stats.get(market.key)
        if value is None and final:
            updated["status"] = STATUS_REVIEW
            updated["last_error"] = "Player stat missing"
            return updated
        if value is not None:
            updated["current_value"] = float(value)
            if final:
                updated["final_value"] = float(value)
        result = grade_player_market(
            market=market.key,
            direction=str(leg.get("direction")),
            line=leg.get("line"),
            value=None if value is None else float(value),
            final=final,
        )
    else:
        result = grade_game_market(
            market=market.key,
            direction=str(leg.get("direction")),
            line=leg.get("line"),
            away_score=int(snapshot.away_score or 0),
            home_score=int(snapshot.home_score or 0),
            final=final,
        )
        if market.key == "total":
            value = float(snapshot.away_score + snapshot.home_score)
        elif market.key == "team_total" and "away" in str(leg.get("direction")):
            value = float(snapshot.away_score)
        elif market.key == "team_total":
            value = float(snapshot.home_score)
        elif market.key in {"moneyline", "spread"}:
            value = float(snapshot.away_score + snapshot.home_score)
        if value is not None:
            updated["current_value"] = value
            if final:
                updated["final_value"] = value

    if result:
        updated["status"] = result
        updated["settle_source"] = "auto"
        if result not in OPEN_STATUSES:
            updated["last_error"] = None
    elif live:
        updated["status"] = STATUS_LIVE
    elif final:
        updated["status"] = STATUS_REVIEW
    else:
        updated["status"] = STATUS_PENDING
    return updated


def _win_notice_detail(bet: dict[str, Any]) -> str:
    from bets.odds import format_money, result_profit

    odds = combined_odds(bet)
    profit = result_profit(STATUS_WON, bet.get("stake"), odds)
    if profit is None:
        return ""
    return f"WON {format_money(profit, signed=True).replace(',', '')}"


def _maybe_notice(bet, previous, updated) -> None:
    old = previous.get("status")
    new = updated.get("status")
    if old == new:
        return
    name = updated.get("player_name") or updated.get("event_label") or "LEG"
    if new == STATUS_WON:
        add_notice(
            bet["user_id"],
            "leg_won",
            "LEG HIT" if bet.get("kind") == "parlay" else "PROP HIT",
            str(name)[:28],
            bet_id=bet["id"],
            leg_id=updated.get("id"),
        )
    elif new == STATUS_LOST and bet.get("kind") == "single":
        add_notice(
            bet["user_id"],
            "leg_lost",
            "BET LOST",
            str(name)[:28],
            bet_id=bet["id"],
            leg_id=updated.get("id"),
        )


def _maybe_bet_notice(bet, old, new) -> None:
    if old == new:
        return
    if new == STATUS_WON:
        title = "PARLAY WON" if bet.get("kind") == "parlay" else "BET WON"
        add_notice(
            bet["user_id"],
            "bet_won",
            title,
            _win_notice_detail(bet),
            bet_id=bet["id"],
        )
    elif new == STATUS_LOST and bet.get("kind") == "parlay":
        add_notice(bet["user_id"], "bet_lost", "PARLAY LOST", "", bet_id=bet["id"])


def _tickets_for(bet: dict[str, Any]) -> list[BetTicket]:
    if bet.get("status") not in OPEN_STATUSES:
        return []
    legs = bet.get("legs") or []
    if bet.get("kind") == "single" and legs:
        return [_single_ticket(bet, legs[0])]
    return _parlay_tickets(bet)


def _single_ticket(bet, leg) -> BetTicket:
    market = market_for(leg.get("market"))
    current = leg.get("current_value")
    line = leg.get("line")
    direction = str(leg.get("direction"))
    under = "under" in direction
    progress = None
    need = ""
    accumulating = market.scope == SCOPE_PLAYER or market.key in {
        "total",
        "team_total",
    }
    if accumulating and current is not None and line is not None:
        if under:
            progress = max(0.0, min(1.0, float(current) / max(float(line), 0.01)))
            room = float(line) - float(current)
            need = f"ROOM {room:g}"
        else:
            progress = max(0.0, min(1.0, float(current) / max(float(line), 0.01)))
            remain = float(line) - float(current)
            need = "HIT" if remain < 0 else f"NEED {remain:g}"
    title = str(leg.get("player_name") or "").strip()
    if title:
        title = title.split()[-1]
    else:
        away, home = _parse_event_teams(leg)
        title = _matchup_text(away, home) or str(leg.get("event_label") or "BET")
    prefix = "U" if under else "O"
    line_text = "" if line is None else f"{prefix}{line:g}"
    if market.key == "moneyline":
        detail = f"{_picked_team(leg) or 'ML'} ML".strip()
    elif market.key == "spread" and line is not None:
        detail = f"{_picked_team(leg) or 'SPR'} {_signed_line(line)}"
    else:
            detail = f"{line_text} {_led_unit(market)}".strip()
    odds = bet.get("odds_american")
    odds_text = ""
    try:
        if odds is not None and str(odds).strip() != "":
            odds_text = f"{int(odds):+d}"
    except (TypeError, ValueError):
        odds_text = ""
    if odds_text:
        detail = f"{detail}  {odds_text}".strip()
    clock = " ".join(
        part for part in (
            _period_label(leg),
            str(leg.get("clock") or ""),
        ) if part
    )
    current_text = "" if current is None else f"{current:g} {market.unit}".strip()
    estimate = _leg_estimate(leg)
    return BetTicket(
        ticket_id=f"bets:{bet['id']}",
        title=title.upper(),
        detail=detail,
        status=str(leg.get("status") or bet.get("status")),
        progress=progress,
        under=under,
        team=str(_picked_team(leg) or leg.get("team") or ""),
        league=str(leg.get("league") or ""),
        need=need or current_text,
        clock=clock,
        pages=(current_text,),
        kind="single",
        width=148,
        chance=estimate.get("chance"),
    )


def _parse_event_teams(leg) -> tuple[str, str]:
    away = str(leg.get("away_team") or "").strip().upper()
    home = str(leg.get("home_team") or "").strip().upper()
    if away and home:
        return away, home
    label = str(leg.get("event_label") or "")
    for sep in (" @ ", "@", " VS ", " vs "):
        if sep in label:
            left, right = label.split(sep, 1)
            away = away or left.strip().upper()
            home = home or right.strip().upper()
            break
    return away, home


def _picked_team(leg) -> str:
    direction = str(leg.get("direction") or "")
    away, home = _parse_event_teams(leg)
    if "away" in direction:
        return away
    if "home" in direction:
        return home
    return str(leg.get("team") or "").strip().upper()


def _abbr(value: str, size: int = 3) -> str:
    text = "".join(ch for ch in str(value or "").upper() if ch.isalnum() or ch in "-")
    return text[:size]


def _matchup_text(away: str, home: str) -> str:
    a = _abbr(away, 3)
    h = _abbr(home, 3)
    if a and h:
        return f"{a} @ {h}"
    return a or h


def _signed_line(line) -> str:
    value = float(line)
    if value > 0:
        return f"+{value:g}"
    return f"{value:g}"


def _led_unit(market) -> str:
    if market is None:
        return ""
    return {
        "pass_yds": "PASS YDS",
        "pass_td": "PASS TD",
        "pass_comp": "PASS COMP",
        "pass_att": "PASS ATT",
        "pass_int": "PASS INT",
        "rush_yds": "RUSH YDS",
        "rush_att": "RUSH ATT",
        "rush_td": "RUSH TD",
        "rec_yds": "REC YDS",
        "receptions": "REC",
        "rec_td": "REC TD",
        "rush_rec_yds": "R+R YDS",
        "anytime_td": "ANY TD",
    }.get(market.key, str(market.short_label or ""))


def _ou_prefix(direction: str) -> str:
    if "under" in direction:
        return "U"
    if "over" in direction:
        return "O"
    return ""


def _leg_card_text(leg) -> str:
    try:
        market = market_for(leg.get("market"))
    except ValueError:
        market = None
    direction = str(leg.get("direction") or "")
    line = leg.get("line")
    current = leg.get("current_value")
    player = str(leg.get("player_name") or "").strip()
    last = player.split()[-1].upper() if player else ""
    away, home = _parse_event_teams(leg)
    team = _picked_team(leg)
    short = _led_unit(market)
    side = _abbr(team, 4) or _abbr(away, 3) or _abbr(home, 3)

    if market and market.scope == SCOPE_PLAYER:
        who = last or side or "PLAYER"
        if current is not None and line is not None:
            return f"{who} {float(current):g}-{float(line):g} {short}".strip()
        prefix = _ou_prefix(direction) or "O"
        line_text = "" if line is None else f"{prefix}{float(line):g}"
        return f"{who} {line_text} {short}".strip()

    key = market.key if market else ""
    matchup = _matchup_text(away, home)
    if key == "moneyline":
        return f"{side or 'ML'} ML"
    if key == "spread" and line is not None:
        return f"{side or 'SPR'} {_signed_line(line)}"
    if key == "total" and line is not None:
        prefix = _ou_prefix(direction) or "O"
        matchup = _matchup_text(away, home) or side or "TOT"
        return f"{matchup} {prefix}{float(line):g}"
    if key == "team_total" and line is not None:
        prefix = _ou_prefix(direction) or "O"
        return f"{side or 'TEAM'} {prefix}{float(line):g} TT"
    if line is not None:
        prefix = _ou_prefix(direction)
        extra = f"{prefix}{float(line):g}" if prefix else _signed_line(line)
        return f"{side or 'GAME'} {extra} {short}".strip()
    label = str(leg.get("event_label") or "").upper()
    return f"{side} {short}".strip() or label or "LEG"


def _is_player_prop(leg: dict[str, Any]) -> bool:
    try:
        return market_for(leg.get("market")).scope == SCOPE_PLAYER
    except ValueError:
        return False


def _empty_pace(note: str = "") -> dict[str, Any]:
    return {
        "chance": None,
        "label": "—",
        "note": note,
        "source": "Live pace",
    }


def _leg_estimate(leg: dict[str, Any]) -> dict[str, Any]:
    if not _is_player_prop(leg):
        return _empty_pace()
    status = str(leg.get("status") or "")
    if status == STATUS_WON:
        return {
            "chance": 100.0,
            "label": "100%",
            "note": "Already hit.",
            "source": "Live pace",
        }
    if status == STATUS_LOST:
        return {
            "chance": 0.0,
            "label": "0%",
            "note": "Already dead.",
            "source": "Live pace",
        }
    return estimate_hit_chance(
        current=leg.get("current_value"),
        line=leg.get("line"),
        direction=str(leg.get("direction") or ""),
        remaining_fraction=leg.get("remaining_fraction"),
        final=str(leg.get("game_status") or "").lower() == "final",
    )


def _leg_parts(leg) -> tuple[str, str, str, str, str, str]:
    status = str(leg.get("status") or STATUS_PENDING)
    estimate = _leg_estimate(leg)
    chance = ""
    if estimate.get("chance") is not None:
        chance = str(estimate.get("label") or "")
    league = str(leg.get("league") or "")
    team = _picked_team(leg)
    try:
        market = market_for(leg.get("market"))
    except ValueError:
        market = None
    direction = str(leg.get("direction") or "")
    line = leg.get("line")
    current = leg.get("current_value")
    player = str(leg.get("player_name") or "").strip()
    last = player.split()[-1].upper() if player else ""
    away, home = _parse_event_teams(leg)
    side = _abbr(team, 4) or _abbr(away, 3) or _abbr(home, 3)
    unit = _led_unit(market)

    if market and market.scope == SCOPE_PLAYER:
        name = last or side or "PLAYER"
        if current is not None and line is not None:
            stat = f"{float(current):g}-{float(line):g}"
        elif line is not None:
            prefix = _ou_prefix(direction) or "O"
            stat = f"{prefix}{float(line):g}"
        else:
            stat = ""
        return status, name[:10], stat[:10], chance, league, team[:4], unit

    key = market.key if market else ""
    if key == "moneyline":
        return status, (side or "ML")[:6], "ML", "", league, team[:4], ""
    if key == "spread" and line is not None:
        return (
            status,
            (side or "SPR")[:6],
            _signed_line(line)[:8],
            "",
            league,
            team[:4],
            "",
        )
    if key == "total" and line is not None:
        prefix = _ou_prefix(direction) or "O"
        name = _matchup_text(away, home) or side or "TOT"
        return status, name[:10], f"{prefix}{float(line):g}", "", league, team[:4], ""
    if key == "team_total" and line is not None:
        prefix = _ou_prefix(direction) or "O"
        return (
            status,
            (side or "TEAM")[:6],
            f"{prefix}{float(line):g}",
            "",
            league,
            team[:4],
            "",
        )
    text = _leg_card_text(leg)
    return status, text[:10], "", chance, league, team[:4], unit


def _leg_summary(leg) -> tuple[str, str, str, str, str, str]:
    return _leg_parts(leg)


def _parlay_grid(leg_count: int) -> tuple[int, int]:
    count = max(1, int(leg_count))
    if count <= 3:
        return 1, 188
    if count <= 6:
        return 2, 280
    return 3, min(330, 16 + 3 * 104)


def _parlay_tickets(bet) -> list[BetTicket]:
    legs = bet.get("legs") or []
    summaries = tuple(_leg_summary(leg) for leg in legs)
    won = sum(1 for item in summaries if item[0] == STATUS_WON)
    count = len(summaries)
    _cols, width = _parlay_grid(count)
    odds = bet.get("odds_american")
    odds_text = ""
    try:
        if odds is not None and str(odds).strip() != "":
            odds_text = f"{int(odds):+d}"
    except (TypeError, ValueError):
        odds_text = ""
    first = legs[0] if legs else {}
    joint = _empty_pace()
    if legs and all(_is_player_prop(leg) for leg in legs):
        joint = combine_independent([_leg_estimate(leg).get("chance") for leg in legs])
    chance_text = str(joint.get("label") or "") if joint.get("chance") is not None else ""
    return [
        BetTicket(
            ticket_id=f"bets:{bet['id']}",
            title="PARLAY",
            detail=" ".join(
                part
                for part in (f"{won} OF {count} HIT", odds_text, chance_text)
                if part
            ),
            status=str(bet.get("status")),
            progress=won / max(1, count),
            under=False,
            team=str(first.get("team") or ""),
            league=str(first.get("league") or ""),
            need=f"{won} OF {count}",
            clock=odds_text,
            kind="parlay",
            legs=summaries,
            width=width,
            chance=joint.get("chance"),
        )
    ]


def _period_label(leg) -> str:
    league = str(leg.get("league") or "")
    period = str(leg.get("period") or "")
    if not period or period == "0":
        return str(leg.get("game_status") or "")
    if league == "mlb":
        clock = str(leg.get("clock") or "")
        return f"{clock} {period}".strip()
    if league == "nhl":
        return f"P{period}"
    return f"Q{period}"


def enrich_leg(leg: dict[str, Any]) -> dict[str, Any]:
    """Attach live pace fields for the dashboard. Never blocks rendering."""
    payload = dict(leg)
    remaining = payload.get("remaining_fraction")
    if payload.get("league") and payload.get("event_id"):
        try:
            snapshot = get_provider(str(payload["league"])).snapshot(
                str(payload["event_id"])
            )
        except Exception:
            snapshot = None
        if snapshot is not None:
            remaining = snapshot.remaining_fraction
            payload["remaining_fraction"] = remaining
            if snapshot.away and snapshot.home:
                payload["away_team"] = snapshot.away
                payload["home_team"] = snapshot.home
    payload["remaining_fraction"] = remaining
    payload["estimate"] = _leg_estimate(payload)
    return payload


def parlay_estimate(legs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not legs or not all(_is_player_prop(leg) for leg in legs):
        return _empty_pace()
    return combine_independent([
        (leg.get("estimate") or {}).get("chance")
        for leg in legs
    ])


def combined_odds(bet: dict[str, Any]) -> int | None:
    if bet.get("odds_american") not in (None, ""):
        try:
            return int(bet["odds_american"])
        except (TypeError, ValueError):
            return None
    legs = []
    for leg in bet.get("legs") or []:
        if leg.get("odds_american") in (None, ""):
            return None
        legs.append(int(leg["odds_american"]))
    if not legs:
        return None
    try:
        return combine_american_odds(legs)
    except ValueError:
        return None


def active_notice_frame(now: float, enabled: bool):
    """Return a notice dict if one should occupy the matrix briefly."""
    global _notice_started_at, _active_notice
    from bets.store import mark_notice_shown, next_notice

    if not enabled:
        return None
    if _active_notice is not None and _notice_started_at is not None:
        if now - _notice_started_at < NOTICE_SECONDS:
            return _active_notice
        mark_notice_shown(_active_notice["id"])
        _active_notice = None
        _notice_started_at = None
    notice = next_notice()
    if notice is None:
        return None
    _active_notice = notice
    _notice_started_at = now
    return notice
