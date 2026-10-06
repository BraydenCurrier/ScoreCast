from __future__ import annotations

from html import escape
from typing import Any

from flask import abort, jsonify, redirect, request

from bets.analytics import player_breakdown, summarize
from bets.catalog import (
    KIND_PARLAY,
    KIND_SINGLE,
    LEAGUE_LABELS,
    LEAGUES,
    SETTLED_STATUSES,
    STATUS_LOST,
    STATUS_PUSH,
    STATUS_VOID,
    STATUS_WON,
    directions_for,
    market_for,
    markets_for_league,
    positions_for_market,
)
from bets.odds import parse_american_odds, parse_stake, payout_from_american, profit_from_american
from bets.providers import get_provider, supported_leagues
from bets.store import (
    create_bet,
    delete_bet,
    get_bet,
    list_bets,
    update_bet_fields,
    update_leg_progress,
    utc_now,
)
from bets.tracker import combined_odds, enrich_leg, parlay_estimate
from common.settings import get_settings, update_settings


def _user(app_current_user):
    user = app_current_user()
    if user is None:
        abort(401)
    return user


def _money(value) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}${value:,.2f}"


def _pct(value) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}%"


def _status_class(status: str) -> str:
    return "st-" + str(status or "pending")


def _leg_line(leg: dict[str, Any]) -> str:
    try:
        market = market_for(leg.get("market"))
        label = market.label
    except ValueError:
        label = str(leg.get("market") or "")
    direction = str(leg.get("direction") or "")
    line = leg.get("line")
    if "over" in direction:
        prefix = "O"
    elif "under" in direction:
        prefix = "U"
    elif direction.startswith("ml_"):
        prefix = "ML"
    elif "spread" in direction:
        prefix = ""
    else:
        prefix = ""
    line_text = "" if line is None else f"{prefix} {line:g}".strip()
    who = leg.get("player_name") or f"{leg.get('away_team')} @ {leg.get('home_team')}"
    current = "" if leg.get("current_value") is None else f" · {leg['current_value']:g}"
    return f"{who} {line_text} {label}{current}".strip()


def _bet_card(bet: dict[str, Any]) -> str:
    legs = bet.get("legs") or []
    odds = combined_odds(bet)
    stake = bet.get("stake")
    profit = None
    if bet.get("status") in SETTLED_STATUSES and stake is not None and odds is not None:
        from bets.odds import result_profit
        profit = result_profit(bet["status"], stake, odds)
    title = "Parlay" if bet.get("kind") == KIND_PARLAY else (
        (legs[0].get("player_name") if legs else None) or "Single"
    )
    league = ""
    if legs:
        league = LEAGUE_LABELS.get(str(legs[0].get("league")), str(legs[0].get("league") or "").upper())
    legs_html = "".join(
        f"""<li class="bet-leg {_status_class(leg.get('status'))}">
            <span class="bet-leg-mark"></span>
            <span>{escape(_leg_line(leg))}</span>
            <span class="muted">{escape(str(leg.get('status') or ''))}</span>
        </li>"""
        for leg in legs
    )
    meta = []
    if league:
        meta.append(escape(league))
    if odds is not None:
        meta.append(("+" if odds > 0 else "") + str(odds))
    if stake is not None:
        meta.append(f"${stake:.2f}")
    if profit is not None:
        meta.append(_money(profit))
    return f"""
    <article class="card bet-card {_status_class(bet.get('status'))}">
      <a class="bet-card-link" href="/bets/{escape(bet['id'])}">
        <div class="bet-card-top">
          <div>
            <div class="card-title">{escape(str(title))}</div>
            <div class="muted">{' · '.join(meta)}</div>
          </div>
          <span class="bet-status">{escape(str(bet.get('status') or '').upper())}</span>
        </div>
        <ul class="bet-legs">{legs_html}</ul>
      </a>
    </article>
    """


def _summary_strip(stats: dict[str, Any]) -> str:
    overall = stats.get("overall") or {}
    return f"""
    <div class="bet-stats">
      <div class="card bet-stat"><div class="muted">Record</div><div class="bet-stat-value">{escape(overall.get('record') or '0-0')}</div></div>
      <div class="card bet-stat"><div class="muted">Hit Rate</div><div class="bet-stat-value">{_pct(overall.get('hit_rate'))}</div></div>
      <div class="card bet-stat"><div class="muted">Live</div><div class="bet-stat-value">{int(stats.get('live') or 0)}</div></div>
    </div>
    """


def _subnav(active: str) -> str:
    items = [
        ("bets", "/bets", "Bets"),
        ("live", "/bets/live", "Live"),
        ("history", "/bets/history", "History"),
        ("analytics", "/bets/analytics", "Analytics"),
        ("new", "/bets/new", "Add"),
    ]
    links = []
    for key, href, label in items:
        cls = "tab active" if key == active else "tab"
        links.append(f'<a class="{cls}" href="{href}">{label}</a>')
    return f'<nav class="bet-subnav" aria-label="Bets sections">{"".join(links)}</nav>'


def _page(page_header, page_styles, title, active, body: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta
    name="viewport"
    content="width=device-width, initial-scale=1, viewport-fit=cover"
  >
  <title>{escape(title)}</title>
  {page_styles()}
</head>
<body>
  <div class="page">
    {page_header("bets")}
    {_subnav(active)}
    {body}
  </div>
</body>
</html>
"""


def register_bet_routes(app, *, login_required, current_user, page_header, page_styles):
    @app.route("/bets")
    @login_required
    def bets_home():
        user = _user(current_user)
        bets = list_bets(user["id"], limit=80)
        stats = summarize(bets)
        open_bets = [bet for bet in bets if bet.get("status") in {"pending", "live", "review"}]
        cards = "".join(_bet_card(bet) for bet in open_bets) or '<div class="card"><div class="muted">No open bets. Add a single or parlay to start tracking.</div></div>'
        body = _summary_strip(stats) + cards
        return _page(page_header, page_styles, "ScoreCast Bets", "bets", body)

    @app.route("/bets/live")
    @login_required
    def bets_live():
        user = _user(current_user)
        bets = list_bets(user["id"], status="open")
        enriched = []
        for bet in bets:
            bet = dict(bet)
            bet["legs"] = [enrich_leg(leg) for leg in bet.get("legs") or []]
            if bet.get("kind") == KIND_PARLAY:
                bet["estimate"] = parlay_estimate(bet["legs"])
            enriched.append(bet)
        cards = []
        for bet in enriched:
            if bet.get("kind") == KIND_PARLAY:
                pest = bet.get("estimate") or {}
                if pest.get("chance") is not None:
                    cards.append(f"""
                <article class="card">
                  <div class="card-title">Parlay live pace</div>
                  <div>{escape(str(pest.get('label') or '—'))}</div>
                  <div class="hint">{escape(str(pest.get('note') or ''))}</div>
                </article>
                """)
            for leg in bet.get("legs") or []:
                estimate = leg.get("estimate") or {}
                chance = estimate.get("label") or "—"
                under = "under" in str(leg.get("direction"))
                bar_cls = "under" if under else "over"
                current = leg.get("current_value")
                line = leg.get("line")
                pct = 0
                if current is not None and line:
                    pct = max(0, min(100, int(round(100 * float(current) / float(line)))))
                current_text = "" if current is None else f"{current:g}"
                line_text = "" if line is None else f"{line:g}"
                combo = current_text if not line_text else (
                    current_text + " / " + line_text if current_text else line_text
                )
                pace = ""
                if estimate.get("chance") is not None:
                    pace = (
                        f'<div class="hint">Live pace · {escape(str(chance))} · '
                        f'{escape(str(estimate.get("note") or ""))}</div>'
                    )
                cards.append(f"""
                <article class="card bet-live {_status_class(leg.get('status'))}">
                  <div class="card-title">{escape(str(leg.get('player_name') or leg.get('event_label') or 'Leg'))}</div>
                  <div class="muted">{escape(_leg_line(leg))}</div>
                  <div class="bet-progress {bar_cls}"><span style="width:{pct}%"></span></div>
                  <div class="bet-live-meta">
                    <span>{escape(combo)}</span>
                    <span>{escape(str(leg.get('game_status') or ''))} {escape(str(leg.get('period') or ''))} {escape(str(leg.get('clock') or ''))}</span>
                  </div>
                  {pace}
                </article>
                """)
        if not cards:
            cards.append('<div class="card"><div class="muted">Nothing is live. Open bets appear here once the game starts.</div></div>')
        return _page(page_header, page_styles, "Live Bets", "live", "".join(cards))

    @app.route("/bets/history")
    @login_required
    def bets_history():
        user = _user(current_user)
        bets = list_bets(user["id"], status="settled")
        cards = "".join(_bet_card(bet) for bet in bets) or '<div class="card"><div class="muted">Settled bets will live here.</div></div>'
        return _page(page_header, page_styles, "Bet History", "history", cards)

    @app.route("/bets/analytics")
    @login_required
    def bets_analytics():
        user = _user(current_user)
        bets = list_bets(user["id"], limit=1000)
        stats = summarize(bets)
        labels = "".join(
            f"""<article class="card bet-label">
              <div class="bet-label-kicker">{escape(item.get('title') or '')}</div>
              <div class="card-title">{escape(str(item.get('subject') or ''))}</div>
              <div>{escape(str(item.get('record') or ''))} · { _pct(item.get('hit_rate')) } · {int(item.get('sample') or 0)} bets</div>
              <div class="hint">{escape(str(item.get('detail') or ''))} Labels describe your tracking history only.</div>
            </article>"""
            for item in stats.get("labels") or []
        ) or '<div class="card"><div class="muted">Labels appear after a handful of settled bets in the same bucket. One result is never enough.</div></div>'

        def table(title, rows):
            if not rows:
                return f'<div class="card"><div class="card-title">{escape(title)}</div><div class="muted">No sample yet.</div></div>'
            items = "".join(
                f"<li><span>{escape(str(row.get('key')))}</span><span>{escape(row.get('record'))} · {_pct(row.get('hit_rate'))} · {int(row.get('decided') or 0)}</span></li>"
                for row in rows[:12]
            )
            return f'<div class="card"><div class="card-title">{escape(title)}</div><ul class="bet-split">{items}</ul></div>'

        player = request.args.get("player", "").strip()
        drill = ""
        if player:
            breakdown = player_breakdown(bets, player)
            markets = "".join(
                f"<li>{escape(row['key'])} · {escape(row['record'])} · {_pct(row.get('hit_rate'))} · {int(row['decided'])}</li>"
                for row in breakdown.get("markets") or []
            )
            drill = f"""
            <div class="card">
              <div class="card-title">{escape(player)}</div>
              <div>Your record {escape(breakdown['overall']['record'])} · {_pct(breakdown['overall'].get('hit_rate'))} · {int(breakdown['overall']['decided'])} legs</div>
              <ul class="bet-split">{markets}</ul>
            </div>
            """

        body = (
            _summary_strip(stats)
            + labels
            + drill
            + table("By sport", stats.get("by_league") or [])
            + table("By market", stats.get("by_market") or [])
            + table("By player", stats.get("by_player") or [])
            + table("By team", stats.get("by_team") or [])
            + table("Over vs Under / other", stats.get("by_direction") or [])
        )
        return _page(page_header, page_styles, "Bet Analytics", "analytics", body)

    @app.route("/bets/new")
    @login_required
    def bets_new():
        settings = get_settings()
        bets_settings = settings.get("bets") or {}
        ticker = "checked" if bets_settings.get("ticker_enabled", True) else ""
        notices = "checked" if bets_settings.get("notifications_enabled", True) else ""
        body = f"""
        <div class="card">
          <div class="card-title">Add a tracked bet</div>
          <p class="hint">Enter a bet you already placed. Use the win % DraftKings shows; ScoreCast converts it to American odds. ScoreCast does not take wagers, hold a balance, or send bets to a sportsbook.</p>
          <form id="bet-form" class="bet-form">
            <label>Bet type
              <select name="kind" id="bet-kind">
                <option value="single">Single</option>
                <option value="parlay">Parlay</option>
              </select>
            </label>
            <div class="bet-row">
              <label>Sportsbook <input name="sportsbook" maxlength="40" placeholder="Optional"></label>
              <label>Stake <input id="bet-stake" name="stake" inputmode="decimal" placeholder="100"></label>
              <label id="parlay-odds-field">Parlay DK % <input id="parlay-odds" name="odds_american" inputmode="decimal" placeholder="From legs"><span class="hint" id="parlay-odds-converted"></span></label>
            </div>
            <div id="bet-payout" class="bet-payout" hidden>
              <div><span class="muted">Odds</span> <strong id="bet-odds-out">—</strong></div>
              <div><span class="muted">To win</span> <strong id="bet-profit-out">—</strong></div>
              <div><span class="muted">Payout</span> <strong id="bet-payout-out">—</strong></div>
            </div>
            <p class="hint" id="bet-payout-hint"></p>
            <label>Notes <input name="notes" maxlength="280" placeholder="Optional"></label>
            <div id="bet-legs"></div>
            <button type="button" class="secondary-button" id="add-leg">Add leg</button>
            <button type="submit" class="primary-button">Save bet</button>
            <div class="hint" id="bet-form-error"></div>
          </form>
        </div>
        <div class="card">
          <div class="card-title">Board</div>
          <form method="POST" action="/bets/settings" class="bet-form">
            <label class="check"><input type="checkbox" name="ticker_enabled" {ticker}> Show open bets on the LED ticker</label>
            <label class="check"><input type="checkbox" name="notifications_enabled" {notices}> Brief HIT / WON board notices</label>
            <button type="submit" class="secondary-button">Save display settings</button>
          </form>
        </div>
        <script src="/static/bets.js?v=6"></script>
        """
        return _page(page_header, page_styles, "Add Bet", "new", body)

    @app.route("/bets/settings", methods=["POST"])
    @login_required
    def bets_settings():
        update_settings({
            "bets": {
                "ticker_enabled": request.form.get("ticker_enabled") == "on",
                "notifications_enabled": request.form.get("notifications_enabled") == "on",
            }
        })
        return redirect("/bets/new")

    @app.route("/bets/<bet_id>")
    @login_required
    def bets_detail(bet_id):
        user = _user(current_user)
        bet = get_bet(bet_id, user["id"])
        if bet is None:
            abort(404)
        bet["legs"] = [enrich_leg(leg) for leg in bet.get("legs") or []]
        actions = ""
        if bet.get("status") not in SETTLED_STATUSES or True:
            actions = """
            <form method="POST" class="bet-actions" onsubmit="return confirm('Update this bet result?');">
              <input type="hidden" name="bet_id" value="">
              <button formaction="/bets/{id}/settle" name="result" value="won">Mark won</button>
              <button formaction="/bets/{id}/settle" name="result" value="lost">Mark lost</button>
              <button formaction="/bets/{id}/settle" name="result" value="push">Mark push</button>
              <button formaction="/bets/{id}/settle" name="result" value="void">Mark void</button>
              <button formaction="/bets/{id}/settle" name="result" value="auto">Reset automatic</button>
            </form>
            <form method="POST" action="/bets/{id}/delete" onsubmit="return confirm('Delete this bet permanently?');">
              <button class="danger-button" type="submit">Delete</button>
            </form>
            """.format(id=escape(bet["id"]))
        legs = "".join(
            f"""<li class="bet-leg {_status_class(leg.get('status'))}">
              <div>{escape(_leg_line(leg))}</div>
              {'' if (leg.get('estimate') or {}).get('chance') is None else (
                '<div class="hint">Live pace: '
                + escape(str((leg.get('estimate') or {}).get('label') or '—'))
                + ' · '
                + escape(str((leg.get('estimate') or {}).get('note') or ''))
                + '</div>'
              )}
              <form method="POST" action="/bets/leg/{escape(leg['id'])}/settle" class="bet-mini-actions">
                <button name="result" value="won">Won</button>
                <button name="result" value="lost">Lost</button>
                <button name="result" value="push">Push</button>
                <button name="result" value="void">Void</button>
              </form>
            </li>"""
            for leg in bet.get("legs") or []
        )
        body = f"""
        <article class="card">
          <div class="card-title">{'Parlay' if bet.get('kind')==KIND_PARLAY else 'Single'}</div>
          <div class="bet-status">{escape(str(bet.get('status') or '').upper())}</div>
          <div class="muted">{escape(str(bet.get('sportsbook') or ''))} {escape(str(bet.get('notes') or ''))}</div>
          <ul class="bet-legs">{legs}</ul>
          {actions}
        </article>
        """
        return _page(page_header, page_styles, "Bet", "bets", body)

    @app.route("/bets/<bet_id>/settle", methods=["POST"])
    @login_required
    def bets_settle(bet_id):
        user = _user(current_user)
        bet = get_bet(bet_id, user["id"])
        if bet is None:
            abort(404)
        result = str(request.form.get("result") or "")
        if result == "auto":
            update_bet_fields(bet_id, user["id"], {"manual_result": 0, "status": "pending"})
            for leg in bet.get("legs") or []:
                update_leg_progress(leg["id"], {"status": "pending", "settle_source": "auto"})
            return redirect(f"/bets/{bet_id}")
        if result not in {STATUS_WON, STATUS_LOST, STATUS_PUSH, STATUS_VOID}:
            abort(400)
        update_bet_fields(bet_id, user["id"], {
            "status": result,
            "manual_result": 1,
            "settled_at": utc_now(),
        })
        mapped = result
        for leg in bet.get("legs") or []:
            update_leg_progress(leg["id"], {"status": mapped, "settle_source": "manual"})
        return redirect(f"/bets/{bet_id}")

    @app.route("/bets/leg/<leg_id>/settle", methods=["POST"])
    @login_required
    def bets_settle_leg(leg_id):
        user = _user(current_user)
        result = str(request.form.get("result") or "")
        if result not in {STATUS_WON, STATUS_LOST, STATUS_PUSH, STATUS_VOID}:
            abort(400)
        bets = list_bets(user["id"], limit=1000)
        owner = None
        for bet in bets:
            for leg in bet.get("legs") or []:
                if leg.get("id") == leg_id:
                    owner = bet
                    break
        if owner is None:
            abort(404)
        update_leg_progress(leg_id, {"status": result, "settle_source": "manual"})
        return redirect(f"/bets/{owner['id']}")

    @app.route("/bets/<bet_id>/delete", methods=["POST"])
    @login_required
    def bets_delete(bet_id):
        user = _user(current_user)
        if not delete_bet(bet_id, user["id"]):
            abort(404)
        return redirect("/bets")

    @app.route("/api/bets", methods=["POST"])
    @login_required
    def api_create_bet():
        user = _user(current_user)
        payload = request.get_json(silent=True) or {}
        try:
            bet = create_bet(user["id"], payload)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        return jsonify({"ok": True, "id": bet["id"]})

    @app.route("/api/bets/events")
    @login_required
    def api_bet_events():
        league = str(request.args.get("league") or "").lower()
        if league not in supported_leagues():
            return jsonify({"events": []})
        try:
            events = get_provider(league).list_events()
        except Exception:
            return jsonify({"events": [], "error": "unavailable"}), 502
        return jsonify({
            "events": [
                {
                    "id": event.event_id,
                    "label": event.label,
                    "away": event.away,
                    "home": event.home,
                    "status": event.status,
                    "start_time": event.start_time,
                }
                for event in events
            ]
        })

    @app.route("/api/bets/players")
    @login_required
    def api_bet_players():
        league = str(request.args.get("league") or "").lower()
        event_id = str(request.args.get("event_id") or "").strip()
        if league not in supported_leagues() or not event_id:
            return jsonify({"players": []})
        try:
            players = get_provider(league).list_players(event_id)
        except Exception:
            return jsonify({"players": [], "error": "unavailable"}), 502
        return jsonify({
            "players": [
                {
                    "id": player.player_id,
                    "name": player.name,
                    "team": player.team,
                    "position": player.position,
                }
                for player in players
            ]
        })

    @app.route("/api/bets/markets")
    @login_required
    def api_bet_markets():
        league = str(request.args.get("league") or "").lower()
        scope = request.args.get("scope") or None
        markets = markets_for_league(league, scope)
        payload = []
        for market in markets:
            payload.append({
                "key": market.key,
                "label": market.label,
                "scope": market.scope,
                "positions": list(positions_for_market(league, market.key) or []),
                "directions": [
                    {"key": key, "label": label}
                    for key, label in directions_for(market.key)
                ],
            })
        return jsonify({"markets": payload, "leagues": [
            {"key": key, "label": LEAGUE_LABELS[key]} for key in LEAGUES
        ]})

    @app.route("/api/bets/payout")
    @login_required
    def api_bet_payout():
        try:
            stake = parse_stake(request.args.get("stake"))
            odds = parse_american_odds(request.args.get("odds"))
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        if stake is None or odds is None:
            return jsonify({"ok": True, "profit": None, "payout": None})
        return jsonify({
            "ok": True,
            "profit": profit_from_american(stake, odds),
            "payout": payout_from_american(stake, odds),
        })
