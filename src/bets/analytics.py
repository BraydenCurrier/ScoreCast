from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from bets.catalog import KIND_PARLAY, KIND_SINGLE, MARKETS, STATUS_LOST, STATUS_WON
from bets.odds import result_profit


MIN_LABEL_SAMPLE = 5
MIN_STREAK = 4
MIN_PARLAY_KILLER = 3


def _settled_legs(bets: list[dict[str, Any]]) -> list[tuple[dict, dict]]:
    rows = []
    for bet in bets:
        if bet.get("archived"):
            continue
        for leg in bet.get("legs") or []:
            if leg.get("status") in {STATUS_WON, STATUS_LOST}:
                rows.append((bet, leg))
    return rows


def _record(wins: int, losses: int) -> dict[str, Any]:
    decided = wins + losses
    hit = round(100.0 * wins / decided, 1) if decided else None
    return {
        "wins": wins,
        "losses": losses,
        "decided": decided,
        "record": f"{wins}-{losses}",
        "hit_rate": hit,
    }


def _count_record(items: list[str]) -> dict[str, Any]:
    wins = sum(1 for status in items if status == STATUS_WON)
    losses = sum(1 for status in items if status == STATUS_LOST)
    return _record(wins, losses)


def summarize(bets: list[dict[str, Any]]) -> dict[str, Any]:
    singles = [bet for bet in bets if bet.get("kind") == KIND_SINGLE]
    parlays = [bet for bet in bets if bet.get("kind") == KIND_PARLAY]
    settled = [
        bet for bet in bets
        if bet.get("status") in {STATUS_WON, STATUS_LOST}
    ]
    money_bets = [
        bet for bet in settled
        if bet.get("stake") not in (None, "")
        and (
            bet.get("odds_american") not in (None, "")
            or bet.get("kind") == KIND_PARLAY
        )
    ]

    profits = []
    stakes = []
    for bet in money_bets:
        odds = bet.get("odds_american")
        if odds in (None, "") and bet.get("kind") == KIND_PARLAY:
            continue
        profit = result_profit(bet.get("status"), bet.get("stake"), odds)
        if profit is None:
            continue
        profits.append(profit)
        stakes.append(float(bet["stake"]))

    net = round(sum(profits), 2) if profits else None
    roi = None
    if profits and stakes:
        total_stake = sum(stakes)
        if total_stake:
            roi = round(100.0 * sum(profits) / total_stake, 1)

    overall = _count_record([bet.get("status") for bet in settled])
    live = sum(
        1 for bet in bets
        if bet.get("status") in {"live", "pending"}
    )

    return {
        "overall": overall,
        "singles": _count_record([bet.get("status") for bet in singles if bet.get("status") in {STATUS_WON, STATUS_LOST}]),
        "parlays": _count_record([bet.get("status") for bet in parlays if bet.get("status") in {STATUS_WON, STATUS_LOST}]),
        "net": net,
        "roi": roi,
        "money_sample": len(profits),
        "live": live,
        "recent": _recent_form(settled),
        "streak": _streak(settled),
        "by_league": _group_bets(settled, lambda bet: str(bet.get("legs", [{}])[0].get("league") or "").upper()),
        "by_market": _group_legs(bets, lambda leg: str((MARKETS.get(leg.get("market")) or MARKETS.get("points")).label)),
        "by_player": _group_legs(bets, lambda leg: str(leg.get("player_name") or "")),
        "by_team": _group_legs(bets, lambda leg: str(leg.get("team") or "")),
        "by_direction": _group_legs(
            bets,
            lambda leg: (
                "Over" if "over" in str(leg.get("direction") or "") else
                "Under" if "under" in str(leg.get("direction") or "") else
                "Other"
            ),
        ),
        "labels": build_labels(bets),
    }


def _group_bets(bets, key_fn) -> list[dict[str, Any]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for bet in bets:
        key = key_fn(bet)
        if not key:
            continue
        buckets[key].append(bet.get("status"))
    rows = []
    for key, statuses in buckets.items():
        row = _count_record(statuses)
        row["key"] = key
        rows.append(row)
    rows.sort(key=lambda item: (-item["decided"], item["key"]))
    return rows


def _group_legs(bets, key_fn) -> list[dict[str, Any]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    profits: dict[str, list[float]] = defaultdict(list)
    for bet, leg in _settled_legs(bets):
        key = key_fn(leg)
        if not key:
            continue
        buckets[key].append(leg.get("status"))
        profit = result_profit(bet.get("status"), bet.get("stake"), bet.get("odds_american"))
        if profit is not None and bet.get("kind") == KIND_SINGLE:
            profits[key].append(profit)
    rows = []
    for key, statuses in buckets.items():
        row = _count_record(statuses)
        row["key"] = key
        if profits.get(key):
            row["net"] = round(sum(profits[key]), 2)
        rows.append(row)
    rows.sort(key=lambda item: (-item["decided"], item["key"]))
    return rows


def _recent_form(settled: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(settled, key=lambda bet: str(bet.get("settled_at") or bet.get("updated_at") or ""))
    last = [bet.get("status") for bet in ordered[-10:]]
    return {
        "sample": len(last),
        "results": last,
        **_count_record(last),
    }


def _streak(settled: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        settled,
        key=lambda bet: str(bet.get("settled_at") or bet.get("updated_at") or ""),
        reverse=True,
    )
    if not ordered:
        return {"kind": None, "length": 0}
    kind = ordered[0].get("status")
    length = 0
    for bet in ordered:
        if bet.get("status") != kind:
            break
        length += 1
    return {"kind": kind, "length": length}


def player_breakdown(bets: list[dict[str, Any]], player_name: str) -> dict[str, Any]:
    name = str(player_name or "").strip().lower()
    related = []
    for bet in bets:
        legs = [
            leg for leg in bet.get("legs") or []
            if str(leg.get("player_name") or "").strip().lower() == name
        ]
        if legs:
            related.append((bet, legs))
    statuses = []
    markets: dict[str, list[str]] = defaultdict(list)
    for bet, legs in related:
        for leg in legs:
            if leg.get("status") in {STATUS_WON, STATUS_LOST}:
                statuses.append(leg.get("status"))
                market = str((MARKETS.get(leg.get("market")) or type("M", (), {"label": leg.get("market")})).label)
                markets[market].append(leg.get("status"))
    return {
        "player": player_name,
        "overall": _count_record(statuses),
        "markets": [
            {"key": key, **_count_record(values)}
            for key, values in sorted(markets.items())
        ],
        "bets": [bet for bet, _ in related],
    }


def build_labels(bets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = []
    players = _group_legs(bets, lambda leg: str(leg.get("player_name") or ""))
    markets = _group_legs(
        bets,
        lambda leg: str((MARKETS.get(leg.get("market")) or type("M", (), {"label": "Market"})).label),
    )
    combos = _group_legs(
        bets,
        lambda leg: f"{leg.get('player_name')} — {(MARKETS.get(leg.get('market')) or type('M', (), {'label': ''})).label}".strip(" —"),
    )

    def qualified(rows, predicate):
        return [
            row for row in rows
            if row["decided"] >= MIN_LABEL_SAMPLE and predicate(row)
        ]

    money = [
        row for row in players
        if row.get("net") is not None and row["decided"] >= MIN_LABEL_SAMPLE
    ]
    if money:
        best_money = max(money, key=lambda row: row.get("net") or 0)
        if (best_money.get("net") or 0) > 0:
            labels.append(_label("MONEY PLAYER", "mvp", best_money, "Most profit among tracked players."))

    hot_players = qualified(players, lambda row: (row.get("hit_rate") or 0) >= 65)
    if hot_players:
        labels.append(_label("MONEY PLAYER", "hot-player", hot_players[0], "Your history hits often on this player."))

    cold_players = qualified(players, lambda row: (row.get("hit_rate") or 100) <= 35)
    if cold_players:
        worst = sorted(cold_players, key=lambda row: (row.get("hit_rate") or 0, -row["decided"]))[0]
        labels.append(_label("NO-GO", "nogo", worst, "Unusually poor hit rate in your own history."))

    sweet = qualified(combos, lambda row: (row.get("hit_rate") or 0) >= 70)
    if sweet:
        labels.append(_label("SWEET SPOT", "sweet", sweet[0], "This player/market combo has paid you."))

    hot_markets = qualified(markets, lambda row: (row.get("hit_rate") or 0) >= 65)
    if hot_markets:
        labels.append(_label("HOT MARKET", "hot-market", hot_markets[0], "This market has been kind in your log."))

    cold_markets = qualified(markets, lambda row: (row.get("hit_rate") or 100) <= 35)
    if cold_markets:
        labels.append(_label("COLD MARKET", "cold-market", cold_markets[0], "This market has been rough in your log."))

    streak = _streak([
        bet for bet in bets
        if bet.get("status") in {STATUS_WON, STATUS_LOST}
    ])
    if streak.get("kind") == STATUS_LOST and streak.get("length", 0) >= MIN_STREAK:
        labels.append({
            "code": "cold-streak",
            "title": "COLD STREAK",
            "subject": f"{streak['length']} settled bets",
            "record": streak["length"],
            "detail": "Recent settled bets have missed. This is your history, not a forecast.",
            "sample": streak["length"],
        })

    killer = _parlay_killers(bets)
    if killer:
        labels.append(killer)

    return labels[:8]


def _label(title: str, code: str, row: dict[str, Any], detail: str) -> dict[str, Any]:
    return {
        "code": code,
        "title": title,
        "subject": row.get("key"),
        "record": row.get("record"),
        "hit_rate": row.get("hit_rate"),
        "sample": row.get("decided"),
        "net": row.get("net"),
        "detail": detail,
    }


def _parlay_killers(bets: list[dict[str, Any]]) -> dict[str, Any] | None:
    lost_counts: Counter[str] = Counter()
    samples: Counter[str] = Counter()
    for bet in bets:
        if bet.get("kind") != KIND_PARLAY:
            continue
        for leg in bet.get("legs") or []:
            name = str(leg.get("player_name") or "").strip()
            if not name:
                continue
            samples[name] += 1
            if bet.get("status") == STATUS_LOST and leg.get("status") == STATUS_LOST:
                lost_counts[name] += 1
    if not lost_counts:
        return None
    name, count = lost_counts.most_common(1)[0]
    if count < MIN_PARLAY_KILLER or samples[name] < MIN_LABEL_SAMPLE:
        return None
    return {
        "code": "killer",
        "title": "BET KILLER",
        "subject": name,
        "record": f"{count} parlay-killing legs",
        "sample": samples[name],
        "detail": "This player has been on losing parlay legs often in your log.",
        "hit_rate": None,
    }


def enough_sample(n: int, minimum: int = MIN_LABEL_SAMPLE) -> bool:
    return n >= minimum
