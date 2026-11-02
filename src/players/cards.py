import io
import threading
import time
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image

from common.settings import get_settings


MAX_PLAYER_CARDS = 12
HEAD_DIR = Path("/tmp/scorecast-player-heads")
SEARCH_URL = (
    "https://site.web.api.espn.com/apis/common/v3/search"
    "?query={query}&limit={limit}&type=player"
)
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
STATS_OK_SECONDS = 60
LIVE_REFRESH_SECONDS = 20
COLLEGE_POSITIONS = {"QB", "RB", "WR", "TE", "K"}
FEEDS = {
    "nfl": "nfl",
    "cfb": "college-football",
}
STATS_FAIL_SECONDS = 120
REQUEST_TIMEOUT = (4, 8)

_lock = threading.Lock()
_cache = {}
_revision = 0
_refresh_pending = False
_summary_lock = threading.Lock()
_summaries = {}
_espn_lock = threading.Lock()
_espn_ids = {}


class PlayerCard:
    def __init__(
        self,
        player_id,
        name,
        team="",
        position="",
        stats=(),
        headshot="",
        first="",
        last="",
        espn_id="",
        league="nfl",
        opponent="",
        game_state="",
        on_field="",
    ):
        self.player_id = str(player_id or "")
        self.espn_id = _digits(espn_id)
        self.name = str(name or "")
        self.first = str(first or "")
        self.last = str(last or "")
        self.team = str(team or "").upper()
        self.position = str(position or "").upper()
        self.league = str(league or "nfl")
        self.stats = tuple(
            (str(value), str(label))
            for value, label in (stats or ())
            if str(value or "") != ""
        )
        self.headshot = str(headshot or "")
        self.opponent = str(opponent or "").strip().upper()
        self.game_state = str(game_state or "").strip().lower()
        self.on_field = str(on_field or "").strip().lower()


def player_cards_revision():
    with _lock:
        return _revision


def ticker_player_cards():
    enabled, players = _configured_players()

    if not enabled:
        return []

    with _lock:
        cache = dict(_cache)

    if any(str(player.get("id") or "") not in cache for player in players):
        _schedule_refresh()

    cards = []

    for player in players:
        player_id = str(player.get("id") or "")
        saved = cache.get(player_id) or {}
        cards.append(PlayerCard(
            player_id=player_id,
            name=player.get("name"),
            team=player.get("team"),
            position=player.get("position"),
            first=player.get("first"),
            last=player.get("last"),
            espn_id=saved.get("espn_id") or player.get("espn_id"),
            league=_player_league(player),
            stats=saved.get("stats") or (),
            headshot=saved.get("headshot") or "",
            opponent=saved.get("opponent") or "",
            game_state=saved.get("game_state") or "",
            on_field=saved.get("on_field") or "",
        ))

    return cards


def _schedule_refresh():
    global _refresh_pending

    with _lock:
        if _refresh_pending:
            return
        _refresh_pending = True

    def run():
        global _refresh_pending

        try:
            refresh_player_cards()
        except Exception as error:
            print(f"Player card refresh failed: {error}")
        finally:
            with _lock:
                _refresh_pending = False

    threading.Thread(
        target=run,
        daemon=True,
        name="player-cards",
    ).start()


def refresh_player_cards():
    global _revision

    enabled, players = _configured_players()
    live_ids = {str(player.get("id") or "") for player in players}

    if not enabled:
        with _lock:
            if _cache:
                _cache.clear()
                _revision += 1
        return

    now = time.monotonic()
    due = []

    with _lock:
        for player in players:
            player_id = str(player.get("id") or "")
            saved = _cache.get(player_id)
            if saved is None:
                due.append(player)
                continue
            if saved.get("game_state") == "live" and saved.get("ok"):
                wait = LIVE_REFRESH_SECONDS
            else:
                wait = STATS_OK_SECONDS if saved.get("ok") else STATS_FAIL_SECONDS
            if now - saved.get("fetched_at", 0) >= wait:
                due.append(player)

    loaded = {}

    if due:
        workers = min(4, len(due))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_load_player, player): str(player.get("id") or "")
                for player in due
            }
            for future in as_completed(futures):
                player_id = futures[future]
                try:
                    loaded[player_id] = future.result()
                except Exception as error:
                    print(f"Player card refresh failed ({player_id}): {error}")
                    loaded[player_id] = {
                        "stats": (),
                        "headshot": "",
                        "opponent": "",
                        "game_state": "",
                        "on_field": "",
                        "espn_id": "",
                        "ok": False,
                    }

    with _lock:
        changed = False

        for player_id in list(_cache):
            if player_id not in live_ids:
                del _cache[player_id]
                changed = True

        for player_id, payload in loaded.items():
            previous = _cache.get(player_id) or {}
            stats = payload["stats"]
            headshot = payload["headshot"]
            opponent = payload.get("opponent") or ""
            game_state = payload.get("game_state") or ""
            on_field = payload.get("on_field") or ""
            espn_id = payload.get("espn_id") or ""

            if not payload["ok"]:
                if previous.get("stats"):
                    stats = previous["stats"]
                    opponent = previous.get("opponent") or opponent
                    game_state = previous.get("game_state") or game_state
                    on_field = previous.get("on_field") or on_field
                if not headshot:
                    headshot = previous.get("headshot") or ""
                if not espn_id:
                    espn_id = previous.get("espn_id") or ""

            record = {
                "stats": stats,
                "headshot": headshot,
                "opponent": opponent,
                "game_state": game_state,
                "on_field": on_field,
                "espn_id": espn_id,
                "ok": payload["ok"],
                "fetched_at": time.monotonic(),
            }

            if (
                previous.get("stats") != record["stats"]
                or previous.get("headshot") != record["headshot"]
                or previous.get("opponent") != record["opponent"]
                or previous.get("game_state") != record["game_state"]
                or previous.get("on_field") != record["on_field"]
                or previous.get("espn_id") != record["espn_id"]
            ):
                changed = True

            _cache[player_id] = record

        if changed:
            _revision += 1


def game_context(payload, team="", position="", league="nfl"):
    event = _overview_event(payload)
    state = _event_state(event)
    on_field = ""

    if state == "live":
        on_field = field_status(
            position,
            team,
            _possession(str(event.get("id") or ""), league),
        )

    return state, on_field


def _overview_event(payload):
    events = (
        ((payload or {}).get("nextGame") or {}).get("league") or {}
    ).get("events") or []

    if events and isinstance(events[0], dict):
        return events[0]

    return {}


def _event_state(event):
    full = (event.get("fullStatus") or {}).get("type") or {}

    if not isinstance(full, dict):
        full = {}

    state = str(full.get("state") or event.get("status") or "").lower()

    if state == "in" or full.get("name") == "STATUS_IN_PROGRESS":
        return "live"

    if state == "post" or full.get("completed") is True:
        return "final"

    return ""


def field_status(position, team, possession):
    """Whether an offensive player is on the field for this snap.

    The public feed does not list the eleven on the field. For
    quarterbacks, runners, receivers, and tight ends, the team
    that has the ball is the team whose skill players are out
    there. Kickers stay off that read unless the other team has
    the ball, when they are on the sideline.
    """
    position = str(position or "").upper()
    team = str(team or "").upper()

    if not isinstance(possession, dict) or team not in possession:
        return ""

    has_ball = bool(possession.get(team))

    if position in {"QB", "RB", "WR", "TE"}:
        return "on" if has_ball else "off"

    if position == "K" and not has_ball:
        return "off"

    return ""


def _possession(event_id, league="nfl"):
    return _possession_map(_game_summary(event_id, league))


def _possession_map(summary):
    if not isinstance(summary, dict):
        return None

    competitions = ((summary.get("header") or {}).get("competitions") or [])

    if not competitions or not isinstance(competitions[0], dict):
        return None

    found = {}

    for side in competitions[0].get("competitors") or []:
        if not isinstance(side, dict):
            continue
        abbreviation = str(
            (side.get("team") or {}).get("abbreviation") or ""
        ).upper()
        if abbreviation:
            found[abbreviation] = bool(side.get("possession"))

    return found or None


def _game_summary(event_id, league="nfl"):
    event_id = _digits(event_id)

    if not event_id:
        return None

    now = time.monotonic()
    cache_key = (_feed(league), event_id)

    with _summary_lock:
        cached = _summaries.get(cache_key)
        if cached and now - cached[0] < LIVE_REFRESH_SECONDS:
            return cached[1]

    try:
        response = requests.get(
            _summary_url(event_id, league),
            headers={
                "User-Agent": "GameLine/1.0",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT,
            verify=_verify(),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as error:
        print(f"Player game status failed ({event_id}): {error}")
        return None

    with _summary_lock:
        _summaries[cache_key] = (time.monotonic(), payload)

    return payload


def game_stat_groups(payload, position, team=""):
    payload = payload if isinstance(payload, dict) else {}
    groups, label = _this_game(payload, position, team)

    if groups:
        return groups, label

    return _latest_logged_game(payload, position)


def _this_game(payload, position, team):
    next_game = payload.get("nextGame") or {}
    statistics = next_game.get("statistics") or {}
    names = statistics.get("names") or []
    values = []

    for split in statistics.get("splits") or []:
        if not isinstance(split, dict):
            continue
        if str(split.get("displayName") or "").lower() == "this game":
            values = split.get("stats") or []
            break

    if not values:
        return (), ""

    events = (next_game.get("league") or {}).get("events") or []
    event = events[0] if events and isinstance(events[0], dict) else {}

    return (
        _groups_for_position(position, _zip_stats(names, values)),
        _opponent_label(event, team),
    )


def _latest_logged_game(payload, position):
    log = payload.get("gameLog") or {}
    events = _events_newest_first(log.get("events"))

    for event in events:
        event_id = str(event.get("id") or "")
        by_name = {}

        for category in log.get("statistics") or []:
            if not isinstance(category, dict):
                continue
            names = category.get("names") or []
            for row in category.get("events") or []:
                if not isinstance(row, dict):
                    continue
                if str(row.get("eventId") or "") != event_id:
                    continue
                by_name.update(_zip_stats(names, row.get("stats") or []))

        groups = _groups_for_position(position, by_name)

        if groups:
            return groups, _logged_opponent(event)

    return (), ""


def _events_newest_first(events):
    rows = []

    if isinstance(events, dict):
        rows = [event for event in events.values() if isinstance(event, dict)]
    elif isinstance(events, list):
        rows = [event for event in events if isinstance(event, dict)]

    rows.sort(key=lambda event: str(event.get("gameDate") or ""), reverse=True)
    return rows


def _zip_stats(names, values):
    by_name = {}

    for index, name in enumerate(names):
        if index >= len(values):
            break
        cleaned = _clean_number(values[index])
        if cleaned != "":
            by_name[str(name)] = cleaned

    return by_name


def _opponent_label(event, team):
    team = str(team or "").upper()
    event = event if isinstance(event, dict) else {}
    from_competitors = _label_from_competitors(event.get("competitors"), team)

    if from_competitors:
        return from_competitors

    text = " ".join(str(event.get("shortName") or "").upper().split())
    return _label_from_short_name(text, team)


def _label_from_competitors(competitors, team):
    sides = []

    for side in competitors or []:
        if not isinstance(side, dict):
            continue
        abbreviation = str(side.get("abbreviation") or "").upper()
        where = str(side.get("homeAway") or "").lower()
        if abbreviation:
            sides.append((abbreviation, where))

    if not team or not sides:
        return ""

    player = next((side for side in sides if side[0] == team), None)
    others = [side for side in sides if side[0] != team]

    if player is None or not others:
        return ""

    opponent = others[0][0]

    if player[1] == "away":
        return f"@ {opponent}"

    return f"VS {opponent}"


def _label_from_short_name(text, team):
    if " @ " in text:
        away, home = [part.strip() for part in text.split(" @ ", 1)]
        if team and team == away:
            return f"@ {home}"
        if team and team == home:
            return f"VS {away}"
        return text

    if " VS " in text:
        left, right = [part.strip() for part in text.split(" VS ", 1)]
        if team and team == left:
            return f"VS {right}"
        if team and team == right:
            return f"VS {left}"
        return text

    return text


def _logged_opponent(event):
    opponent = str(
        ((event.get("opponent") or {}).get("abbreviation") or "")
    ).upper()
    side = str(event.get("atVs") or "").strip().lower()

    if opponent and side == "@":
        return f"@ {opponent}"

    if opponent and side == "vs":
        return f"VS {opponent}"

    return opponent


def ensure_headshot(espn_id, league="nfl"):
    espn_id = _digits(espn_id)

    if not espn_id:
        return ""

    path = HEAD_DIR / f"{_feed(league)}-{espn_id}.png"

    if _usable_headshot(path):
        return str(path)

    try:
        response = requests.get(
            _headshot_url(espn_id, league),
            headers={
                "User-Agent": "GameLine/1.0",
                "Accept": "image/png,image/jpeg,image/webp,*/*",
            },
            timeout=REQUEST_TIMEOUT,
            verify=_verify(),
        )
        response.raise_for_status()
        _save_headshot(response.content, path)
    except Exception as error:
        print(f"Player headshot failed ({espn_id}): {error}")
        if path.is_file() and path.stat().st_size > 0:
            return str(path)
        return ""

    if _usable_headshot(path):
        return str(path)

    if path.is_file() and path.stat().st_size > 0:
        return str(path)

    return ""


def _configured_players():
    block = get_settings().get("player_cards") or {}

    if not isinstance(block, dict):
        return False, []

    enabled = bool(block.get("enabled", True))
    players = []

    for raw in block.get("players") or []:
        if not isinstance(raw, dict):
            continue
        player_id = str(raw.get("id") or "").strip()
        if not player_id:
            continue
        players.append(raw)
        if len(players) >= MAX_PLAYER_CARDS:
            break

    return enabled, players


def _load_player(player):
    league = _player_league(player)
    espn_id = _espn_id_for(player)
    headshot = ensure_headshot(espn_id, league) if espn_id else ""
    stats = ()
    opponent = ""
    game_state = ""
    on_field = ""
    ok = bool(espn_id)

    if espn_id:
        try:
            payload = _fetch_overview(espn_id, league)
            stats, opponent = game_stat_groups(
                payload,
                player.get("position"),
                player.get("team"),
            )
            game_state, on_field = game_context(
                payload,
                player.get("team"),
                player.get("position"),
                league,
            )
            if league == "cfb":
                stats, opponent, game_state, on_field = _college_current_game(
                    payload,
                    espn_id,
                    player.get("team"),
                    player.get("position"),
                    stats,
                    opponent,
                    game_state,
                    on_field,
                )
        except Exception as error:
            ok = False
            print(
                "Player card stats failed "
                f"({player.get('id') or espn_id}): {error}"
            )

    return {
        "stats": stats,
        "headshot": headshot,
        "opponent": opponent,
        "game_state": game_state,
        "on_field": on_field,
        "espn_id": espn_id,
        "ok": ok,
    }


def _espn_id_for(player):
    espn_id = _digits(player.get("espn_id"))

    if espn_id:
        return espn_id

    raw_id = str((player or {}).get("id") or "")
    if raw_id.startswith("cfb:"):
        return _digits(raw_id.split(":", 1)[1])

    name = " ".join(str(player.get("name") or "").split())
    team = str(player.get("team") or "").strip().upper()

    if len(name) < 3:
        return ""

    league = _player_league(player)
    key = (league, name.casefold(), team)
    now = time.monotonic()

    with _espn_lock:
        cached = _espn_ids.get(key)
        if cached and now - cached[0] < (
            STATS_OK_SECONDS if cached[1] else STATS_FAIL_SECONDS
        ):
            return cached[1]

    found = _search_espn_id(name, team, league)

    with _espn_lock:
        _espn_ids[key] = (time.monotonic(), found)

    return found


def _search_espn_id(name, team, league="nfl"):
    try:
        response = requests.get(
            SEARCH_URL.format(query=quote(name), limit=5),
            headers={
                "User-Agent": "GameLine/1.0",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT,
            verify=_verify(),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as error:
        print(f"Player ESPN id lookup failed ({name}): {error}")
        return ""

    matches = []

    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("league") or "").lower() != _feed(league):
            continue
        if str(item.get("sport") or "").lower() != "football":
            continue
        if str(item.get("displayName") or "").casefold() != name.casefold():
            continue
        matches.append(item)

    if team:
        matches = [
            item for item in matches
            if _search_team(item) == team
        ]

    if not matches:
        return ""

    return _digits(matches[0].get("id"))


def _search_team(item):
    for relation in item.get("teamRelationships") or []:
        if not isinstance(relation, dict):
            continue
        abbreviation = str(
            (relation.get("core") or {}).get("abbreviation") or ""
        ).upper()
        if abbreviation:
            return abbreviation

    return ""


def _fetch_overview(espn_id, league="nfl"):
    response = requests.get(
        _overview_url(espn_id, league),
        headers={
            "User-Agent": "GameLine/1.0",
            "Accept": "application/json",
        },
        timeout=REQUEST_TIMEOUT,
        verify=_verify(),
    )
    response.raise_for_status()
    return response.json()


def _groups_for_position(position, by_name):
    position = str(position or "").upper()

    def pick(*keys):
        for key in keys:
            value = by_name.get(key)
            if value:
                return value
        return ""

    def pair(left_key, right_key):
        left = pick(left_key)
        right = pick(right_key)
        if left and right:
            return f"{left}-{right}"
        return left or right

    def keep(value, label, drop_zero=False):
        if not value:
            return None
        if drop_zero and value in {"0", "0-0"}:
            return None
        return (value, label)

    if position == "QB":
        chosen = (
            keep(pick("passingYards"), "PASS YD"),
            keep(pair("completions", "passingAttempts"), "CMP"),
            keep(pick("passingTouchdowns"), "TD"),
            keep(pick("interceptions"), "INT"),
            keep(pick("rushingYards"), "RUSH YD", drop_zero=True),
        )
    elif position == "RB":
        chosen = (
            keep(pick("rushingYards"), "RUSH YD"),
            keep(pick("rushingAttempts"), "CAR"),
            keep(pick("rushingTouchdowns"), "TD"),
            keep(pick("receptions"), "REC"),
            keep(pick("receivingYards"), "REC YD", drop_zero=True),
        )
    elif position in {"WR", "TE"}:
        chosen = (
            keep(pick("receivingYards"), "REC YD"),
            keep(pick("receptions"), "REC"),
            keep(pick("receivingTouchdowns"), "TD"),
            keep(pick("receivingTargets"), "TGT"),
        )
    elif position == "K":
        chosen = (
            keep(
                pick("fieldGoalsMade-fieldGoalAttempts")
                or pair("fieldGoalsMade", "fieldGoalAttempts"),
                "FG",
            ),
            keep(
                pick("extraPointsMade-extraPointAttempts")
                or pair("extraPointsMade", "extraPointAttempts"),
                "XP",
                drop_zero=True,
            ),
            keep(pick("longFieldGoalMade"), "LNG", drop_zero=True),
            keep(pick("totalKickingPoints"), "PTS"),
        )
    else:
        chosen = ()

    return tuple(item for item in chosen if item)


def _clean_number(value):
    text = str(value or "").strip().replace(",", "")

    if not text or text in {"--", "-"}:
        return ""

    if text[0].isdigit() and "-" in text[1:]:
        left, right = text.split("-", 1)
        if left.isdigit() and right.isdigit():
            return f"{int(left)}-{int(right)}"

    negative = text.startswith("-")
    body = text[1:] if negative else text

    if "." in body:
        body = body.split(".", 1)[0]

    if not body.isdigit():
        return ""

    number = str(int(body))
    return f"-{number}" if negative else number


def _usable_headshot(path):
    if not path.is_file() or path.stat().st_size <= 0:
        return False

    try:
        with Image.open(path) as image:
            return image.width == image.height and image.width >= 48
    except Exception:
        return False


def _save_headshot(content, path):
    from players.renderer import crop_portrait

    with Image.open(io.BytesIO(content)) as source:
        image = crop_portrait(source)
        image.thumbnail((96, 96), Image.Resampling.LANCZOS)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, "PNG")


def search_college_players(query, limit=8):
    """College skill players from the ESPN search."""
    text = " ".join(str(query or "").split())

    if len(text) < 2:
        return []

    try:
        response = requests.get(
            SEARCH_URL.format(query=quote(text), limit=10),
            headers={
                "User-Agent": "GameLine/1.0",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT,
            verify=_verify(),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as error:
        print(f"College player search failed ({text}): {error}")
        return []

    found = []

    for item in payload.get("items") or []:
        card = _college_search_hit(item)
        if card is None:
            continue
        found.append(card)
        if len(found) >= max(1, int(limit)):
            break

    return found


def stored_card_players(player_ids, posted, previous, limit=MAX_PLAYER_CARDS):
    """Keep NFL roster records and college players posted from search."""
    from nfl.player_directory import get_player, public_player

    previous_by_id = {}

    for record in previous or []:
        card = _public_card(record)
        if card is not None:
            previous_by_id[card["id"]] = card

    players = []
    seen = set()
    posted = list(posted or [])

    for index, raw_id in enumerate(player_ids or []):
        player_id = str(raw_id or "").strip()

        if not player_id or player_id in seen:
            continue

        seen.add(player_id)
        extra = posted[index] if index < len(posted) and isinstance(posted[index], dict) else {}
        earlier = previous_by_id.get(player_id) or {}
        league = _player_league({
            "id": player_id,
            "league": extra.get("league") or earlier.get("league"),
        })

        if league == "nfl":
            directory = public_player(get_player(player_id))
            if directory is not None:
                directory["league"] = "nfl"
                players.append(directory)
                if len(players) >= limit:
                    break
                continue

        card = _public_card({
            "id": player_id,
            "league": league,
            "name": extra.get("name") or earlier.get("name"),
            "first": extra.get("first") or earlier.get("first"),
            "last": extra.get("last") or earlier.get("last"),
            "team": extra.get("team") or earlier.get("team"),
            "position": extra.get("position") or earlier.get("position"),
            "espn_id": extra.get("espn_id") or earlier.get("espn_id"),
        })

        if card is None:
            continue

        players.append(card)

        if len(players) >= limit:
            break

    return players


def _college_current_game(
    payload,
    espn_id,
    team,
    position,
    stats,
    opponent,
    game_state,
    on_field,
):
    """College overviews omit the current game, so use the box score."""
    event = _overview_event(payload)
    summary = _game_summary(event.get("id"), "cfb")
    state = _summary_state(summary)

    if state not in {"live", "final"}:
        return stats, opponent, game_state, on_field

    label = _summary_opponent(summary, team) or opponent
    box = _box_stats(summary, espn_id)
    line = _groups_for_position(position, box) if box else ()
    field = ""

    if state == "live":
        field = field_status(position, team, _possession_map(summary))

    return line, label, state, field


def _summary_state(summary):
    if not isinstance(summary, dict):
        return ""

    competitions = ((summary.get("header") or {}).get("competitions") or [])

    if not competitions or not isinstance(competitions[0], dict):
        return ""

    state = str(
        (
            ((competitions[0].get("status") or {}).get("type") or {}).get("state")
            or ""
        )
    ).lower()

    if state == "in":
        return "live"

    if state == "post":
        return "final"

    if state == "pre":
        return "pre"

    return ""


def _summary_opponent(summary, team):
    competitions = ((summary.get("header") or {}).get("competitions") or [])

    if not competitions or not isinstance(competitions[0], dict):
        return ""

    competitors = []

    for side in competitions[0].get("competitors") or []:
        if not isinstance(side, dict):
            continue
        competitors.append({
            "abbreviation": (side.get("team") or {}).get("abbreviation"),
            "homeAway": side.get("homeAway"),
        })

    return _label_from_competitors(competitors, team)


def _box_stats(summary, espn_id):
    espn_id = _digits(espn_id)
    by_name = {}
    teams = ((summary or {}).get("boxscore") or {}).get("players") or []

    for team in teams:
        if not isinstance(team, dict):
            continue
        for group in team.get("statistics") or []:
            if not isinstance(group, dict):
                continue
            keys = group.get("keys") or []
            for athlete in group.get("athletes") or []:
                if not isinstance(athlete, dict):
                    continue
                if _digits((athlete.get("athlete") or {}).get("id")) != espn_id:
                    continue
                values = athlete.get("stats") or []
                for index, key in enumerate(keys):
                    if index >= len(values):
                        break
                    _put_stat(by_name, key, values[index])

    return by_name


def _put_stat(by_name, key, value):
    key = str(key or "")
    text = str(value or "").strip()

    if "/" in key and "/" in text:
        left_key, right_key = key.split("/", 1)
        left_val, right_val = text.split("/", 1)
        for part_key, part_val in ((left_key, left_val), (right_key, right_val)):
            cleaned = _clean_number(part_val)
            if cleaned != "":
                by_name[str(part_key)] = cleaned
        return

    cleaned = _clean_number(text)

    if cleaned != "":
        by_name[key] = cleaned


def _college_search_hit(item):
    if not isinstance(item, dict):
        return None

    if str(item.get("league") or "").lower() != "college-football":
        return None

    if str(item.get("sport") or "").lower() != "football":
        return None

    if item.get("isRetired") is True or item.get("isActive") is False:
        return None

    position = str(
        ((item.get("position") or {}).get("abbreviation") or "")
    ).upper()
    position = "K" if position == "PK" else position

    if position not in COLLEGE_POSITIONS:
        return None

    espn_id = _digits(item.get("id"))
    name = " ".join(str(item.get("displayName") or "").split())

    if not espn_id or not name:
        return None

    parts = name.split(" ", 1)

    return {
        "id": f"cfb:{espn_id}",
        "name": name,
        "first": parts[0],
        "last": parts[1] if len(parts) > 1 else "",
        "team": _search_team(item),
        "position": position,
        "espn_id": espn_id,
        "league": "cfb",
    }


def _public_card(player):
    if not isinstance(player, dict):
        return None

    player_id = str(player.get("id") or "").strip()
    name = " ".join(str(player.get("name") or "").split())

    if not player_id or not name:
        return None

    league = _player_league(player)
    team = str(player.get("team") or "").strip().upper()

    if league == "nfl":
        from nfl.player_directory import normalize_team
        team = normalize_team(team)

    position = str(player.get("position") or "").upper()
    position = "K" if position == "PK" else position
    espn_id = _digits(player.get("espn_id"))

    if not espn_id and player_id.startswith("cfb:"):
        espn_id = _digits(player_id.split(":", 1)[1])

    return {
        "id": player_id,
        "name": name,
        "first": str(player.get("first") or "").strip(),
        "last": str(player.get("last") or "").strip(),
        "team": team,
        "position": position,
        "espn_id": espn_id,
        "league": league,
    }


def _player_league(player):
    league = str((player or {}).get("league") or "").strip().lower()

    if league in {"cfb", "college", "college-football"}:
        return "cfb"

    if str((player or {}).get("id") or "").startswith("cfb:"):
        return "cfb"

    return "nfl"


def _feed(league):
    return FEEDS.get(_player_league({"league": league}), "nfl")


def _overview_url(espn_id, league):
    return (
        "https://site.web.api.espn.com/apis/common/v3/sports/"
        f"football/{_feed(league)}/athletes/{espn_id}/overview"
    )


def _headshot_url(espn_id, league):
    return (
        "https://a.espncdn.com/i/headshots/"
        f"{_feed(league)}/players/full/{espn_id}.png"
    )


def _summary_url(event_id, league):
    return (
        "https://site.api.espn.com/apis/site/v2/sports/football/"
        f"{_feed(league)}/summary?event={event_id}"
    )


def _digits(value):
    return "".join(char for char in str(value or "") if char.isdigit())


def _verify():
    if Path(CA_BUNDLE).is_file():
        return CA_BUNDLE
    return True
