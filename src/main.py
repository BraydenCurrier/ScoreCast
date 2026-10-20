import os
import pickle
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image, ImageDraw

from common.matrix import PANEL_REFRESH_HZ, create_matrix
from common.game_ids import game_id as shared_game_id
from common.game_ids import game_is_shown
from common.settings import get_developer_settings, get_settings
from common.timezone import ensure_network_timezone, start_timezone_refresh, timezone_status
from common.splash import render_idle_splash
from common.ticker_scroll import (
    build_strip,
    column_refreshes,
    load_panel_shift,
    paint_viewport,
    scroll_shift_matches,
)
from updater.status import is_update_in_progress

from fantasy.api import get_today_games as get_live_fantasy, refresh_fantasy_avatars_on_startup
from fantasy.renderer import render_game_strip_onto as draw_fantasy_strip

from alerts.manager import possession_alert_manager
from alerts.renderer import render_possession_alert
from alerts.watcher import possession_watch_loop

from mlb.api import get_today_games as get_live_mlb
from mlb.mlb_renderer import render_game_strip_onto as draw_mlb_strip
from mlb.focus_renderer import render_mlb_focus

from nfl.api import get_today_games as get_live_nfl
from nfl.nfl_renderer import render_game_strip_onto as draw_nfl_strip
from nfl.focus_renderer import render_nfl_focus
from cfb.focus_renderer import render_cfb_focus

from cfb.api import get_today_games as get_live_cfb
from cfb.cfb_renderer import render_game_strip_onto as draw_cfb_strip

from nba.api import get_today_games as get_live_nba
from nba.nba_renderer import render_game_strip_onto as draw_nba_strip

from nhl.api import get_today_games as get_live_nhl
from nhl.nhl_renderer import render_game_strip_onto as draw_nhl_strip

from soccer.api import get_today_games as get_live_soccer
from soccer.soccer_renderer import render_game_strip_onto as draw_soccer_strip

from pga.api import get_today_games as get_live_pga
from pga.pga_renderer import card_width as pga_card_width
from pga.pga_renderer import display_page as pga_display_page
from pga.pga_renderer import render_game_strip_onto as draw_pga_strip

from stocks.api import get_today_games as get_live_stocks
from stocks.renderer import render_game_strip_onto as draw_stocks_strip

from mlb.test_data import TEST_GAMES_MLB
from nfl.test_data import TEST_GAMES_NFL
from cfb.test_data import TEST_GAMES_CFB
from nba.test_data import TEST_GAMES_NBA
from nhl.test_data import TEST_GAMES_NHL
from soccer.test_data import TEST_GAMES_SOCCER
from pga.test_data import TEST_GAMES_PGA
from stocks.test_data import TEST_GAMES_STOCKS
from fantasy.test_data import TEST_GAMES_FANTASY

TEST_GAMES_BY_SPORT = {
    "mlb": TEST_GAMES_MLB,
    "nfl": TEST_GAMES_NFL,
    "cfb": TEST_GAMES_CFB,
    "nba": TEST_GAMES_NBA,
    "nhl": TEST_GAMES_NHL,
    "soccer": TEST_GAMES_SOCCER,
    "pga": TEST_GAMES_PGA,
    "stocks": TEST_GAMES_STOCKS,
    "fantasy": TEST_GAMES_FANTASY,
}

SPORT_DISPLAY_ORDER = (
    "mlb",
    "nfl",
    "cfb",
    "nba",
    "nhl",
    "soccer",
    "pga",
    "stocks",
    "fantasy",
)

from bets.renderer import CARD_WIDTH as BET_CARD_WIDTH
from bets.renderer import render_bet_notice, render_game_strip_onto as draw_bet_strip
from bets.store import init_store as init_bet_store
from bets.tracker import (
    active_notice_frame,
    bets_revision,
    refresh_open_bets,
    ticker_tickets,
)
from web.app import app, set_latest_games
from setup.runtime import start_setup_if_needed
from setup.display import render_setup_display
from setup.state import setup_holds_display


DEFAULT_FPS = 60
MIN_FPS = 10
MAX_FPS = 120

DISPLAY_WIDTH = 384
MATRIX_HEIGHT = 32

CARD_SPACING = 15
DEFAULT_CARD_WIDTH = 129
CFB_CARD_WIDTH = 162
NFL_CARD_WIDTH = 130
NHL_CARD_WIDTH = 156
FANTASY_CARD_WIDTH = 143
STOCK_CARD_WIDTH = 120
BET_TICKER_WIDTH = BET_CARD_WIDTH

SETTINGS_POLL_INTERVAL = 0.5
UPDATE_POLL_INTERVAL = 0.25

_games = []
_games_lock = threading.Lock()
_games_revision = 0
_refresh_in_progress = False

_card_cache = {}
_prerendered_cards = {}
_prerendered_lock = threading.Lock()
_visible_games_cache = []
_cache_signature = None
_built_games_revision = None
_built_settings_signature = None
_ticker_revision = 0

# How often a league is fetched depends on the fastest game it has.
# Visible live games use the settings interval. A live game that is
# hidden still updates every minute. Pregame waits 10 minutes, and a
# league that is only finals (or has nothing today) waits 30.
PREGAME_REFRESH_SECONDS = 10 * 60
HIDDEN_LIVE_REFRESH_SECONDS = 60
QUIET_REFRESH_SECONDS = 30 * 60

_sport_fetched_at = {}
_sport_intervals = {}
_schedule_revision = None
_schedule_mark = None
_bets_fetched_at = 0.0

SPORT_FETCHERS = {
    "mlb": get_live_mlb,
    "nfl": get_live_nfl,
    "cfb": get_live_cfb,
    "nba": get_live_nba,
    "nhl": get_live_nhl,
    "soccer": get_live_soccer,
    "pga": get_live_pga,
    "stocks": get_live_stocks,
    "fantasy": get_live_fantasy,
}

def fetch_all_sports(sports=None):
    results = {}
    errors = {}

    selected = SPORT_FETCHERS
    if sports is not None:
        selected = {
            sport: fetcher
            for sport, fetcher in SPORT_FETCHERS.items()
            if sport in sports
        }

    if not selected:
        return results, errors

    with ThreadPoolExecutor(
        max_workers=len(selected),
        thread_name_prefix="sports-api",
    ) as executor:
        future_to_sport = {
            executor.submit(fetcher): sport
            for sport, fetcher in selected.items()
        }

        for future in as_completed(future_to_sport):
            sport = future_to_sport[future]

            try:
                games = future.result()
                results[sport] = games or []
            except Exception as exc:
                errors[sport] = exc
                results[sport] = []
                print(f"{sport.upper()} refresh failed: {exc}")

    return results, errors


def _live_refresh_seconds(settings):
    try:
        return max(5, int(settings.get("refresh_interval", 30)))
    except (TypeError, ValueError):
        return 30


def _format_refresh_interval(seconds):
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _game_phase(game):
    """live, pregame, or final. Stocks use the market session."""
    if is_stock_quote(game):
        state = str(getattr(game, "market_state", "") or "").upper()
        return "live" if state == "LIVE" else "final"

    status = (
        str(getattr(game, "status", "") or "")
        .upper()
        .replace("_", " ")
        .replace("-", " ")
    )

    if any(
        word in status
        for word in (
            "FINAL",
            "COMPLETE",
            "POSTPONED",
            "CANCELED",
            "CANCELLED",
            "FORFEIT",
        )
    ):
        return "final"

    if (
        "SCHEDULE" in status
        or "PREVIEW" in status
        or status.strip() in {"PRE", "PREGAME"}
    ):
        return "pregame"

    return "live"


def _game_is_shown(game, settings, hidden=None):
    return game_is_shown(game, settings)


def _hidden_game_ids(settings):
    hidden = settings.get("hidden_games") or []
    if isinstance(hidden, str):
        hidden = [hidden]
    return {str(item) for item in hidden}


def sport_refresh_seconds(sport, games, settings):
    """Shortest interval this league needs right now."""
    live_interval = _live_refresh_seconds(settings)
    sport_games = [game for game in games if get_sport(game) == sport]

    if sport == "fantasy":
        fantasy = settings.get("fantasy") or {}
        if not fantasy.get("enabled"):
            return QUIET_REFRESH_SECONDS
        try:
            configured = int(fantasy.get("refresh_interval") or 120)
        except (TypeError, ValueError):
            configured = 120
        return max(60, configured)

    hidden = _hidden_game_ids(settings)

    if sport == "stocks":
        shown = [
            game for game in sport_games
            if _game_is_shown(game, settings, hidden)
        ]
        if not shown:
            return QUIET_REFRESH_SECONDS
        if any(_game_phase(game) == "live" for game in shown):
            return live_interval
        return PREGAME_REFRESH_SECONDS

    if not sport_games:
        return QUIET_REFRESH_SECONDS

    shown_live = False
    hidden_live = False
    any_pregame = False

    for game in sport_games:
        phase = _game_phase(game)
        if phase == "live":
            if _game_is_shown(game, settings, hidden):
                shown_live = True
            else:
                hidden_live = True
        elif phase == "pregame":
            any_pregame = True

    if shown_live:
        return live_interval
    if hidden_live:
        return HIDDEN_LIVE_REFRESH_SECONDS
    if any_pregame:
        return PREGAME_REFRESH_SECONDS
    return QUIET_REFRESH_SECONDS


def _schedule_mark_value(settings):
    fantasy = settings.get("fantasy") or {}
    bets = settings.get("bets") or {}
    try:
        fantasy_interval = int(fantasy.get("refresh_interval") or 120)
    except (TypeError, ValueError):
        fantasy_interval = 120

    return (
        _live_refresh_seconds(settings),
        tuple(sorted(_hidden_game_ids(settings))),
        tuple(sorted(str(item) for item in (settings.get("selected_games") or []))),
        bool(fantasy.get("enabled")),
        fantasy_interval,
        bool(bets.get("ticker_enabled", True)),
        bool(bets.get("notifications_enabled", False)),
    )


def _refresh_schedule(settings):
    global _schedule_revision, _schedule_mark, _sport_intervals

    mark = _schedule_mark_value(settings)
    if _schedule_revision == _games_revision and mark == _schedule_mark:
        return

    with _games_lock:
        revision = _games_revision
        games = list(_games)

    intervals = {
        sport: sport_refresh_seconds(sport, games, settings)
        for sport in SPORT_FETCHERS
    }

    if intervals != _sport_intervals:
        plan = ", ".join(
            f"{sport.upper()} {_format_refresh_interval(intervals[sport])}"
            for sport in SPORT_DISPLAY_ORDER
            if sport in intervals
        )
        print(f"API cadence: {plan}")

    _sport_intervals = intervals
    _schedule_revision = revision
    _schedule_mark = mark


def sports_due(now, settings):
    _refresh_schedule(settings)
    due = []
    for sport, interval in _sport_intervals.items():
        fetched_at = _sport_fetched_at.get(sport)
        if fetched_at is None or now - fetched_at >= interval:
            due.append(sport)
    return due


def bets_refresh_due(now, settings):
    bets = settings.get("bets") or {}
    if not bets.get("ticker_enabled", True) and not bets.get(
        "notifications_enabled",
        False,
    ):
        return False
    return now - _bets_fetched_at >= _live_refresh_seconds(settings)


def mark_sports_fetched(sports, now):
    for sport in sports:
        _sport_fetched_at[sport] = now


def forget_sport_fetch_times():
    _sport_fetched_at.clear()


def _hashable(value):
    if isinstance(value, dict):
        return tuple(
            sorted((key, _hashable(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_hashable(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_hashable(item) for item in value))
    return value


def game_signature(game):
    return (
        game.__class__.__name__,
        tuple(sorted((key, _hashable(item)) for key, item in vars(game).items())),
    )

def logo_variants_signature(settings):
    logo_variants = settings.get(
        "logo_variants",
        {},
    )

    return tuple(
        sorted(
            (
                str(league).lower(),
                str(team).upper(),
                str(variant).lower(),
            )
            for league, teams in logo_variants.items()
            if isinstance(teams, dict)
            for team, variant in teams.items()
        )
    )

def is_bet_ticket(game):
    return game.__class__.__name__ == "BetTicket"


def is_mlb_game(game):
    return game.__class__.__name__ == "BaseballGame"

def is_cfb_game(game):
    return game.__class__.__name__ == "CollegeFootballGame" 

def is_nfl_game(game):
    return game.__class__.__name__ == "FootballGame"

def is_nba_game(game):
    return game.__class__.__name__ == "BasketballGame"

def is_nhl_game(game):
    return game.__class__.__name__ == "HockeyGame"

def is_soccer_game(game):
    return game.__class__.__name__ == "SoccerGame"

def is_pga_tournament(game):
    return game.__class__.__name__ == "GolfTournament"

def is_stock_quote(game):
    return game.__class__.__name__ == "StockQuote"

def is_fantasy_game(game):
    return game.__class__.__name__ == "FantasyMatchup"

def game_id(game):
    return shared_game_id(game)

def get_sport(game):
    if is_cfb_game(game):
        return "cfb"

    if is_nfl_game(game):
        return "nfl"

    if is_nba_game(game):
        return "nba"

    if is_nhl_game(game):
        return "nhl"

    if is_soccer_game(game):
        return "soccer"

    if is_pga_tournament(game):
        return "pga"

    if is_stock_quote(game):
        return "stocks"

    if is_fantasy_game(game):
        return "fantasy"

    if is_bet_ticket(game):
        return "bets"
    
    return "mlb"

def get_game_width(game):
    if is_cfb_game(game):
        return CFB_CARD_WIDTH
    if is_nfl_game(game):
        return NFL_CARD_WIDTH
    if is_nhl_game(game):
        return NHL_CARD_WIDTH
    if is_fantasy_game(game):
        return FANTASY_CARD_WIDTH
    if is_pga_tournament(game):
        return pga_card_width(game)
    if is_stock_quote(game):
        return STOCK_CARD_WIDTH
    if is_bet_ticket(game):
        return int(getattr(game, "width", None) or BET_TICKER_WIDTH)

    return DEFAULT_CARD_WIDTH


def get_game_step(game):
    return get_game_width(game) + CARD_SPACING


def draw_game(image, draw, game, x, settings):
    if is_cfb_game(game):
        draw_cfb_strip(image, draw, game, x, settings)
    elif is_nba_game(game):
        draw_nba_strip(image, draw, game, x, settings)
    elif is_nfl_game(game):
        draw_nfl_strip(image, draw, game, x, settings)
    elif is_nhl_game(game):
        draw_nhl_strip(image, draw, game, x, settings)
    elif is_soccer_game(game):
        draw_soccer_strip(image, draw, game, x, settings)
    elif is_pga_tournament(game):
        draw_pga_strip(image, draw, game, x, settings)
    elif is_stock_quote(game):
        draw_stocks_strip(image, draw, game, x, settings)
    elif is_fantasy_game(game):
        draw_fantasy_strip(image, draw, game, x, settings)
    elif is_bet_ticket(game):
        draw_bet_strip(image, draw, game, x, settings)
    else:
        draw_mlb_strip(image, draw, game, x, settings)

def apply_saved_order(all_games, settings):
    saved_order = settings.get("game_order", [])

    if not saved_order:
        return all_games

    order_index = {gid: idx for idx, gid in enumerate(saved_order)}
    return sorted(all_games, key=lambda g: order_index.get(game_id(g), 999))

def get_target_fps(settings):
    try:
        fps = int(settings.get("fps", DEFAULT_FPS))
    except (TypeError, ValueError):
        fps = DEFAULT_FPS

    return max(
        MIN_FPS,
        min(MAX_FPS, fps),
    )

def get_favorite_teams(
    settings,
    sport
):
    favorites = settings.get(
        "favorite_teams",
        {}
    )

    if not isinstance(
        favorites,
        dict
    ):
        return set()

    values = favorites.get(
        sport,
        []
    )

    if isinstance(values, str):
        values = [values]

    return {
        str(team).strip().upper()
        for team in values
        if str(team).strip()
    }

def is_favorite_game(
    game,
    settings
):
    sport = get_sport(game)

    favorites = get_favorite_teams(
        settings,
        sport
    )

    if not favorites:
        return False

    away = str(
        getattr(
            game,
            "away",
            ""
        )
    ).strip().upper()

    home = str(
        getattr(
            game,
            "home",
            ""
        )
    ).strip().upper()

    return (
        away in favorites
        or home in favorites
    )

def get_focus_settings(settings):
    focus = settings.get(
        "focus_mode",
        {},
    )

    if not isinstance(
        focus,
        dict,
    ):
        focus = {}

    return focus


def get_focus_games(
    all_games,
    settings,
):
    focus = get_focus_settings(
        settings
    )

    if not bool(
        focus.get(
            "enabled",
            False,
        )
    ):
        return []

    def _id_list(key):
        values = focus.get(key, [])
        if not isinstance(values, list):
            return []
        return [str(value) for value in values]

    selected_ids = (
        _id_list("nfl_game_ids")
        + _id_list("cfb_game_ids")
        + _id_list("mlb_game_ids")
    )

    if not selected_ids:
        return []

    selected_set = set(selected_ids)

    matching_games = [
        game
        for game in all_games
        if (
            (
                is_nfl_game(game)
                or is_cfb_game(game)
                or is_mlb_game(game)
            )
            and game_id(game)
            in selected_set
        )
    ]

    order_index = {
        game_identifier: index
        for index, game_identifier
        in enumerate(selected_ids)
    }

    matching_games.sort(
        key=lambda game: order_index.get(
            game_id(game),
            999,
        )
    )

    return matching_games

def get_visible_games(all_games, settings):
    return [
        game
        for game in all_games
        if game_is_shown(game, settings)
    ]

def render_error_card(game, error):
    card_width = get_game_width(game)

    image = Image.new(
        "RGB",
        (card_width, MATRIX_HEIGHT),
        (0, 0, 0),
    )

    draw = ImageDraw.Draw(image)

    draw.text(
        (2, 2),
        "CARD ERROR",
        fill=(255, 0, 0),
    )

    draw.text(
        (2, 14),
        get_sport(game).upper(),
        fill=(255, 255, 255),
    )

    return image

_card_error_keys = set()


def card_cache_key(game, settings, logo_signature=None):
    if logo_signature is None:
        logo_signature = logo_variants_signature(settings)

    page = 0
    if is_pga_tournament(game):
        page = pga_display_page(getattr(game, "players", ()))

    return (
        game_signature(game),
        logo_signature,
        page,
    )


def leaderboard_page_token(games):
    return tuple(
        pga_display_page(getattr(game, "players", ()))
        for game in games
        if is_pga_tournament(game)
    )


def render_card(game, settings):
    key = card_cache_key(game, settings)

    cached = _card_cache.get(key)

    if cached is not None:
        return cached

    card_width = get_game_width(game)

    image = Image.new(
        "RGB",
        (card_width, MATRIX_HEIGHT),
        (0, 0, 0),
    )

    draw = ImageDraw.Draw(image)

    try:
        draw_game(image, draw, game, 0, settings)

    except Exception as error:
        print(
            "Card rendering failed:",
            get_sport(game),
            repr(game),
            error,
        )
        traceback.print_exc()

        image = render_error_card(game, error)
        _card_cache[key] = image
        _card_error_keys.add(key)
        return image

    _card_error_keys.discard(key)
    _card_cache[key] = image
    return image


def card_settings_signature(settings):
    return (
        tuple(settings.get("hidden_games", [])),
        tuple(settings.get("selected_games", [])),
        tuple(settings.get("game_order", [])),
        tuple(
            (league, tuple(teams if isinstance(teams, list) else [teams]))
            for league, teams in sorted(settings.get("favorite_teams", {}).items())
        ),
        logo_variants_signature(settings),
        bool((settings.get("bets") or {}).get("ticker_enabled", True)),
        bets_revision(),
    )


def publish_games(games):
    global _games, _games_revision

    with _games_lock:
        _games = games
        _games_revision += 1
        set_latest_games(games)


def rebuild_visible_games_if_needed(settings):
    global _visible_games_cache, _cache_signature, _card_cache
    global _ticker_revision
    global _built_games_revision, _built_settings_signature

    settings_signature = card_settings_signature(settings)

    with _games_lock:
        games_revision = _games_revision

        if (
            games_revision == _built_games_revision
            and settings_signature == _built_settings_signature
        ):
            return _visible_games_cache

        current_games = _games.copy()

    logo_signature = logo_variants_signature(settings)

    signature = (
        tuple(game_signature(g) for g in current_games),
        settings_signature,
    )

    if signature == _cache_signature:
        # These cards match the ticker already on screen.
        take_prerendered_cards()
        if _card_error_keys:
            _ticker_revision += 1
            _card_cache = {
                key: image
                for key, image in _card_cache.items()
                if key not in _card_error_keys
            }
            _card_error_keys.clear()

        _built_games_revision = games_revision
        _built_settings_signature = settings_signature
        return _visible_games_cache

    ordered_games = apply_saved_order(current_games, settings)
    visible_games = get_visible_games(ordered_games, settings)
    bets_settings = settings.get("bets") or {}
    if bets_settings.get("ticker_enabled", True):
        visible_games = list(ticker_tickets()) + visible_games

    live_keys = {
        card_cache_key(game, settings, logo_signature)
        for game in visible_games
    }

    for key, image in take_prerendered_cards().items():
        if key in live_keys:
            _card_cache[key] = image

    # Keep bitmaps whose game data is unchanged. Retry cards that
    # previously failed, and drop cards that are no longer shown.
    if _card_error_keys:
        _ticker_revision += 1

    _card_cache = {
        key: image
        for key, image in _card_cache.items()
        if key in live_keys and key not in _card_error_keys
    }
    _card_error_keys.clear()

    _visible_games_cache = visible_games
    _cache_signature = signature
    _built_games_revision = games_revision
    _built_settings_signature = settings_signature

    return _visible_games_cache

def combine_sports_results(
    sports_results,
    sports_errors=None,
    previous_games=None,
    use_test_fallback=False,
    fetched_sports=None,
):
    combined_games = []

    sports_errors = sports_errors or {}
    previous_games = previous_games or []

    previous_by_sport = {
        sport: []
        for sport in SPORT_DISPLAY_ORDER
    }

    for game in previous_games:
        sport = get_sport(game)

        if sport in previous_by_sport:
            previous_by_sport[sport].append(game)

    for sport in SPORT_DISPLAY_ORDER:
        if (
            fetched_sports is not None
            and sport not in fetched_sports
            and sport not in sports_errors
        ):
            combined_games.extend(previous_by_sport.get(sport, []))
            continue

        games = sports_results.get(sport, [])

        if sport in sports_errors:
            # API failed: keep the last known good data.
            previous = previous_by_sport.get(sport, [])

            if previous:
                print(
                    f"{sport.upper()} refresh failed; "
                    "keeping previous data."
                )
                combined_games.extend(previous)

            elif use_test_fallback:
                combined_games.extend(
                    TEST_GAMES_BY_SPORT[sport]
                )

            continue

        # Successful request.
        if games:
            combined_games.extend(games)

        elif use_test_fallback:
            # Only use test data during startup.
            combined_games.extend(
                TEST_GAMES_BY_SPORT[sport]
            )

    return combined_games

def sample_games():
    games = []

    for sport in SPORT_DISPLAY_ORDER:
        games.extend(TEST_GAMES_BY_SPORT[sport])

    return games


def build_refresh_payload(settings, previous_games, due_sports=None):
    """Fetch games and draw their cards. Runs in the refresh process."""
    sports_results, sports_errors = fetch_all_sports(due_sports)
    fetched_sports = set(sports_results) | set(sports_errors)
    combined_games = combine_sports_results(
        sports_results,
        sports_errors=sports_errors,
        previous_games=previous_games,
        use_test_fallback=False,
        fetched_sports=fetched_sports,
    )
    ordered_games = apply_saved_order(combined_games, settings)
    visible_games = get_visible_games(ordered_games, settings)
    cards = []

    for game in visible_games:
        if get_sport(game) not in fetched_sports:
            continue
        key = card_cache_key(game, settings)
        image = render_card(game, settings)
        if key in _card_error_keys:
            continue
        cards.append((key, image.mode, image.size, image.tobytes()))

    return {
        "games": combined_games,
        "errors": {
            sport: f"{type(error).__name__}: {error}"
            for sport, error in sports_errors.items()
        },
        "cards": cards,
    }


def _install_prerendered_cards(cards):
    images = {}
    for key, mode, size, data in cards:
        images[key] = Image.frombytes(mode, tuple(size), data)

    with _prerendered_lock:
        _prerendered_cards.update(images)


def take_prerendered_cards():
    global _prerendered_cards

    with _prerendered_lock:
        cards = _prerendered_cards
        _prerendered_cards = {}
        return cards


def run_refresh_subprocess(settings, previous_games, due_sports):
    """Run the sports refresh at a lower priority than the ticker."""
    src_dir = str(Path(__file__).resolve().parent)
    env = os.environ.copy()
    env["PYTHONPATH"] = src_dir
    request = pickle.dumps(
        {
            "settings": settings,
            "previous_games": previous_games,
            "due_sports": list(due_sports),
        },
        protocol=4,
    )
    completed = subprocess.run(
        ["nice", "-n", "10", sys.executable, "-m", "common.sports_worker"],
        cwd=src_dir,
        env=env,
        input=request,
        capture_output=True,
        timeout=90,
    )

    if completed.stderr:
        message = completed.stderr.decode(errors="replace").strip()
        if message:
            print(message)

    if completed.returncode != 0:
        raise RuntimeError(
            "Sports refresh process failed "
            f"({completed.returncode})"
        )

    return pickle.loads(completed.stdout)


def refresh_games_background(due_sports, refresh_bets):
    global _refresh_in_progress, _bets_fetched_at

    try:
        if get_developer_settings().get("test_games"):
            publish_games(sample_games())
            mark_sports_fetched(SPORT_FETCHERS, time.monotonic())
            try:
                refresh_open_bets()
            except Exception as error:
                print("Bet refresh failed:", error)
            _bets_fetched_at = time.monotonic()
            print("Using developer sample games")
            return

        if due_sports:
            with _games_lock:
                previous_games = _games.copy()

            payload = run_refresh_subprocess(
                get_settings(),
                previous_games,
                due_sports,
            )
            _install_prerendered_cards(payload.get("cards") or [])
            publish_games(payload.get("games") or [])
            mark_sports_fetched(due_sports, time.monotonic())

            sports_errors = payload.get("errors") or {}
            refreshed = ", ".join(sport.upper() for sport in due_sports)
            if sports_errors:
                failed_sports = ", ".join(
                    sport.upper()
                    for sport in sports_errors
                )
                print(
                    f"Refreshed {refreshed}. "
                    f"{failed_sports} failed; previous data retained."
                )
            else:
                print(f"Refreshed {refreshed}")

        if refresh_bets:
            try:
                refresh_open_bets()
            except Exception as error:
                print("Bet refresh failed:", error)
            _bets_fetched_at = time.monotonic()

    except Exception as e:
        if due_sports:
            mark_sports_fetched(due_sports, time.monotonic())
        print(
            "Games refresh failed; keeping previous data:",
            e,
        )

    finally:
        _refresh_in_progress = False


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    block_on_close = False


def run_web_server():
    def serve(port):
        try:
            server = make_server(
                "0.0.0.0",
                port,
                app,
                server_class=ThreadingWSGIServer,
            )
            print(f"Web app running on port {port}")
            server.serve_forever()
        except OSError as error:
            print(f"Web app could not bind port {port}: {error}")

    threading.Thread(
        target=serve,
        args=(80,),
        daemon=True,
        name="gameline-http-80",
    ).start()
    serve(8080)


def load_initial_games():
    if get_developer_settings().get("test_games"):
        return sample_games()

    sports_results, sports_errors = fetch_all_sports()

    return combine_sports_results(
        sports_results,
        sports_errors=sports_errors,
        previous_games=[],
        use_test_fallback=True,
    )

if __name__ == "__main__":
    canvas_key, scroll_columns, capture_buffer = load_panel_shift()
    matrix = create_matrix()
    frame_canvas = matrix.CreateFrameCanvas()
    # Which hidden frame still holds a ticker picture, and at what strip offset.
    ticker_canvas_state = {}
    scroll_mode = {"fast": False}

    def present_frame(image):
        # Draw into the hidden buffer, then swap on the panel
        # refresh so a scrolling update is not shown half-copied.
        global frame_canvas
        if canvas_key is not None:
            ticker_canvas_state.pop(canvas_key(frame_canvas), None)
        frame_canvas.SetImage(image)
        frame_canvas = matrix.SwapOnVSync(frame_canvas)

    def present_ticker(origin, period, strip, fraction):
        """Hold this column for an exact number of panel refreshes."""
        global frame_canvas

        token = strip["token"]
        key = canvas_key(frame_canvas) if canvas_key is not None else None
        shown = ticker_canvas_state.get(key) if key is not None else None
        # The hidden frame is the previous picture. Advancing one column
        # means that frame is two columns behind the one we are about to show.
        shifted = False
        if (
            key is not None
            and shown is not None
            and shown[0] == token
            and (origin - shown[1]) % period == 2
        ):
            try:
                shifted = bool(scroll_columns(
                    frame_canvas,
                    2,
                    strip["rgb"],
                    period,
                    strip["height"],
                    origin,
                    DISPLAY_WIDTH,
                ))
            except Exception:
                traceback.print_exc()
                shifted = False

        if not shifted:
            paint_viewport(frame_image, strip["image"], origin, period)
            frame_canvas.SetImage(frame_image)

        if key is not None:
            ticker_canvas_state[key] = (token, origin % period)

        frame_canvas = matrix.SwapOnVSync(frame_canvas, fraction)

    if is_update_in_progress():
        present_frame(
            render_idle_splash(
                DISPLAY_WIDTH,
                MATRIX_HEIGHT,
                "UPDATING",
            )
        )

    start_setup_if_needed()

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    possession_stop_event = threading.Event()

    threading.Thread(
        target=possession_watch_loop,
        args=(possession_stop_event,),
        daemon=True,
        name="possession-watcher",
    ).start()

    start_timezone_refresh()

    if setup_holds_display():
        publish_games([])
    else:
        ensure_network_timezone(block=True, timeout=4)
        zone_status = timezone_status()
        print(
            "Display timezone: "
            f"{zone_status['effective']} ({zone_status['source']})"
        )
        refresh_fantasy_avatars_on_startup()
        try:
            init_bet_store()
            refresh_open_bets()
        except Exception as error:
            print("Bet tracker init deferred:", error)

        publish_games(load_initial_games())
        try:
            refresh_open_bets()
        except Exception as error:
            print("Bet refresh deferred:", error)

    current_game = 0
    scroll_x = 0.0
    scroll_origin_px = 0
    locked_speed = None
    locked_fraction = 1
    next_column_due = None
    scheduled_scroll_speed = None

    # Last ticker frame actually pushed to the panel.
    # Cleared whenever a non-ticker frame is shown.
    presented_scroll_column = None
    presented_game_index = None
    presented_frame_signature = None
    presented_ticker_revision = None
    presented_leaderboard_page = None


    def note_external_frame():
        """Forget the ticker frame so the next ticker loop redraws it."""
        global presented_scroll_column
        global presented_game_index
        global presented_frame_signature
        global presented_ticker_revision
        global presented_leaderboard_page
        global next_column_due

        presented_scroll_column = None
        presented_game_index = None
        presented_frame_signature = None
        presented_ticker_revision = None
        presented_leaderboard_page = None
        next_column_due = None

    focus_game_index = 0
    focus_last_switch = time.monotonic()
    focus_previous_ids = ()

    if not setup_holds_display():
        mark_sports_fetched(SPORT_FETCHERS, time.monotonic())
    _bets_fetched_at = time.monotonic()
    last_settings_poll = 0.0
    last_update_poll = 0.0
    update_in_progress = False

    settings = get_settings()
    last_test_games = get_developer_settings(settings).get("test_games")

    last_brightness = None

    # Tracks whether the physical LED display is sleeping.
    display_sleeping = False

    # Reusable black frame for blanking the matrix.
    black_frame = Image.new(
        "RGB",
        (DISPLAY_WIDTH, MATRIX_HEIGHT),
        (0, 0, 0),
    )

    frame_image = Image.new(
        "RGB",
        (DISPLAY_WIDTH, MATRIX_HEIGHT),
        (0, 0, 0),
    )

    ticker_strip = {
        "token": None,
        "image": None,
        "rgb": None,
        "period": 0,
        "height": MATRIX_HEIGHT,
    }

    def ensure_ticker_strip(visible_games, settings):
        token = (
            _cache_signature,
            _ticker_revision,
            leaderboard_page_token(visible_games),
        )
        if token == ticker_strip["token"] and ticker_strip["rgb"] is not None:
            return ticker_strip

        cards = [
            (render_card(game, settings), get_game_step(game))
            for game in visible_games
        ]
        image, period = build_strip(cards)
        ticker_strip["token"] = token
        ticker_strip["image"] = image
        ticker_strip["period"] = period
        ticker_strip["height"] = image.height if image is not None else MATRIX_HEIGHT
        ticker_strip["rgb"] = image.tobytes() if image is not None else None
        return ticker_strip

    if scroll_columns is not None and capture_buffer is not None:
        try:
            scroll_mode["fast"] = scroll_shift_matches(
                frame_canvas,
                scroll_columns,
                capture_buffer,
            )
        except Exception:
            traceback.print_exc()
            scroll_mode["fast"] = False

        if scroll_mode["fast"]:
            print(
                f"Ticker scroll is locked to the {PANEL_REFRESH_HZ}Hz panel refresh."
            )
        else:
            print(
                "Column shift check failed; "
                "redrawing each ticker column."
            )

    def sleep_ticker_frame():
        # Wake for the next panel frame, or sooner when the next
        # column is due, so each column starts on the same beat.
        remaining = frame_delay - (time.monotonic() - frame_started_at)
        if next_column_due is not None:
            until_column = next_column_due - time.monotonic()
            if until_column < remaining:
                remaining = until_column
        if remaining > 0:
            time.sleep(remaining)

    while True:
        frame_started_at = time.monotonic()
        now = frame_started_at

        if now - last_settings_poll >= SETTINGS_POLL_INTERVAL:
            settings = get_settings()
            last_settings_poll = now

            test_games = get_developer_settings(settings).get("test_games")
            if test_games != last_test_games:
                last_test_games = test_games
                forget_sport_fetch_times()

        if now - last_update_poll >= UPDATE_POLL_INTERVAL:
            update_in_progress = is_update_in_progress()
            last_update_poll = now

        target_fps = get_target_fps(settings)
        frame_delay = 1.0 / target_fps

        scroll_speed = float(settings.get("scroll_speed", 30.0))
        brightness = int(settings.get("brightness", 50))

        if setup_holds_display():
            note_external_frame()
            if brightness != last_brightness:
                matrix.brightness = brightness
                last_brightness = brightness
            present_frame(
                render_setup_display(DISPLAY_WIDTH, MATRIX_HEIGHT)
            )
            frame_elapsed = time.monotonic() - frame_started_at
            sleep_time = frame_delay - frame_elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            continue

        # --------------------------------------------------
        # Display software power / low-energy sleep mode
        # --------------------------------------------------

        display_enabled = bool(
            settings.get(
                "display_enabled",
                True,
            )
        )

        if not display_enabled:
            note_external_frame()

            if not display_sleeping:
                # Blank the physical LED matrix once.
                present_frame(black_frame)

                # Keep brightness within the rgbmatrix
                # supported range while all pixels are black.
                matrix.brightness = 1

                display_sleeping = True
                last_brightness = None

                print("Display sleeping")

            # Do not start API refreshes, render scorecards,
            # or process display alerts while asleep.
            time.sleep(0.2)
            continue

        if display_sleeping:
            # Restore the configured brightness.
            matrix.brightness = brightness

            display_sleeping = False
            last_brightness = brightness
            ticker_canvas_state.clear()

            # Force a fresh sports update after waking.
            forget_sport_fetch_times()

            print("Display awake")

        if update_in_progress:
            note_external_frame()

            if brightness != last_brightness:
                matrix.brightness = brightness
                last_brightness = brightness
                ticker_canvas_state.clear()

            present_frame(
                render_idle_splash(
                    DISPLAY_WIDTH,
                    MATRIX_HEIGHT,
                    "UPDATING",
                )
            )

            frame_elapsed = time.monotonic() - frame_started_at
            sleep_time = frame_delay - frame_elapsed

            if sleep_time > 0:
                time.sleep(sleep_time)

            continue

        # --------------------------------------------------
        # Normal API refreshes — only while display is awake
        # --------------------------------------------------

        if not _refresh_in_progress:
            due_sports = sports_due(now, settings)
            refresh_bets = bets_refresh_due(now, settings)
            if due_sports or refresh_bets:
                _refresh_in_progress = True

                threading.Thread(
                    target=refresh_games_background,
                    args=(due_sports, refresh_bets),
                    daemon=True,
                ).start()

        if brightness != last_brightness:
            matrix.brightness = brightness
            last_brightness = brightness
            ticker_canvas_state.clear()

        active_alert = possession_alert_manager.get_active(
            now
        )

        if active_alert is not None:
            note_external_frame()

            alert_frame = render_possession_alert(
                active_alert,
                now=now,
            )

            present_frame(
                alert_frame
            )

            frame_elapsed = (
                time.monotonic()
                - frame_started_at
            )

            sleep_time = (
                frame_delay
                - frame_elapsed
            )

            if sleep_time > 0:
                time.sleep(
                    sleep_time
                )

            continue

        focus_settings = get_focus_settings(settings)
        if focus_settings.get("enabled"):
            with _games_lock:
                focus_source_games = _games.copy()
            focus_games = get_focus_games(
                focus_source_games,
                settings,
            )
        else:
            focus_games = ()

        if focus_games:
            note_external_frame()

            focus_settings = get_focus_settings(
                settings
            )

            try:
                focus_rotation_seconds = int(
                    focus_settings.get(
                        "rotation_seconds",
                        30,
                    )
                )
            except (TypeError, ValueError):
                focus_rotation_seconds = 30

            focus_rotation_seconds = max(
                5,
                min(
                    300,
                    focus_rotation_seconds,
                ),
            )

            focus_ids = tuple(
                game_id(game)
                for game in focus_games
            )

            # Selected games changed in the web app.
            if focus_ids != focus_previous_ids:
                focus_previous_ids = focus_ids
                focus_game_index = 0
                focus_last_switch = now

            if (
                focus_game_index
                >= len(focus_games)
            ):
                focus_game_index = 0

            # Only rotate if more than one game is selected.
            if (
                len(focus_games) > 1
                and (
                    now - focus_last_switch
                    >= focus_rotation_seconds
                )
            ):
                focus_game_index += 1

                if (
                    focus_game_index
                    >= len(focus_games)
                ):
                    focus_game_index = 0

                focus_last_switch = now

            focus_game = focus_games[
                focus_game_index
            ]

            if is_cfb_game(focus_game):
                focus_frame = render_cfb_focus(
                    focus_game,
                    settings,
                )
            elif is_mlb_game(focus_game):
                focus_frame = render_mlb_focus(
                    focus_game,
                    settings,
                )
            else:
                focus_frame = render_nfl_focus(
                    focus_game,
                    settings,
                )

            present_frame(
                focus_frame
            )

            frame_elapsed = (
                time.monotonic()
                - frame_started_at
            )

            sleep_time = (
                frame_delay
                - frame_elapsed
            )

            if sleep_time > 0:
                time.sleep(
                    sleep_time
                )

            continue

        bets_settings = settings.get("bets") or {}
        notice = active_notice_frame(
            now,
            bool(bets_settings.get("notifications_enabled", True)),
        )
        if notice is not None:
            note_external_frame()
            present_frame(render_bet_notice(notice))
            frame_elapsed = time.monotonic() - frame_started_at
            sleep_time = frame_delay - frame_elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            continue

        try:
            visible_games = rebuild_visible_games_if_needed(
                settings
            )
        except Exception as error:
            print("Ticker rebuild failed:", error)
            traceback.print_exc()
            visible_games = _visible_games_cache or []

        if not visible_games:
            note_external_frame()

            present_frame(
                render_idle_splash(
                    DISPLAY_WIDTH,
                    MATRIX_HEIGHT,
                )
            )

            frame_elapsed = time.monotonic() - frame_started_at
            sleep_time = frame_delay - frame_elapsed

            if sleep_time > 0:
                time.sleep(sleep_time)

            continue

        if scroll_mode["fast"]:
            strip = ensure_ticker_strip(visible_games, settings)
            period = strip["period"]
            if period > 0 and strip["rgb"] is not None:
                if locked_speed != scroll_speed:
                    locked_speed = scroll_speed
                    locked_fraction = column_refreshes(
                        scroll_speed,
                        PANEL_REFRESH_HZ,
                    )
                    actual_speed = PANEL_REFRESH_HZ / locked_fraction
                    print(
                        f"Scroll locked to {actual_speed:.1f} pixels per second "
                        f"({locked_fraction} refreshes per column)."
                    )
                origin = scroll_origin_px % period
                present_ticker(
                    origin,
                    period,
                    strip,
                    locked_fraction,
                )
                scroll_origin_px += 1
                continue

            scroll_mode["fast"] = False

        if current_game >= len(visible_games):
            current_game = 0

        column_interval = 1.0 / max(scroll_speed, 1.0)
        if (
            next_column_due is None
            or scheduled_scroll_speed != scroll_speed
        ):
            scheduled_scroll_speed = scroll_speed
            next_column_due = time.monotonic() + column_interval
        elif time.monotonic() >= next_column_due:
            # One column per update. Time owed beyond that is dropped
            # so a hitch cannot skip several pixels at once.
            scroll_x -= 1.0
            next_column_due += column_interval
            if time.monotonic() >= next_column_due:
                next_column_due = time.monotonic() + column_interval

        active_card_step = get_game_step(
            visible_games[current_game]
        )

        if scroll_x <= -active_card_step:
            scroll_x += active_card_step
            current_game += 1

            if current_game >= len(visible_games):
                current_game = 0

        scroll_column = int(scroll_x)

        # The panel only moves when the integer column changes.
        # Identical columns already on the matrix stay there.
        leaderboard_page = leaderboard_page_token(visible_games)
        if (
            scroll_column == presented_scroll_column
            and current_game == presented_game_index
            and _cache_signature == presented_frame_signature
            and _ticker_revision == presented_ticker_revision
            and leaderboard_page == presented_leaderboard_page
            and presented_frame_signature is not None
        ):
            sleep_ticker_frame()
            continue

        frame_image.paste(
            (0, 0, 0),
            (0, 0, DISPLAY_WIDTH, MATRIX_HEIGHT),
        )

        x = scroll_column
        game_index = current_game

        while x < DISPLAY_WIDTH:
            game = visible_games[game_index]
            frame_image.paste(
                render_card(game, settings),
                (x, 0),
            )
            x += get_game_step(game)
            game_index += 1
            if game_index >= len(visible_games):
                game_index = 0

        present_frame(frame_image)

        presented_scroll_column = scroll_column
        presented_game_index = current_game
        presented_frame_signature = _cache_signature
        presented_ticker_revision = _ticker_revision
        presented_leaderboard_page = leaderboard_page

        sleep_ticker_frame()