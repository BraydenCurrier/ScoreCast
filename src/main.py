import threading
import time
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

import traceback

from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image, ImageDraw

from common.matrix import create_matrix
from common.settings import get_settings
from common.splash import render_idle_splash
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

from stocks.api import get_today_games as get_live_stocks
from stocks.renderer import render_game_strip_onto as draw_stocks_strip

from mlb.test_data import TEST_GAMES_MLB
from nfl.test_data import TEST_GAMES_NFL
from cfb.test_data import TEST_GAMES_CFB
from nba.test_data import TEST_GAMES_NBA
from nhl.test_data import TEST_GAMES_NHL
from soccer.test_data import TEST_GAMES_SOCCER
from stocks.test_data import TEST_GAMES_STOCKS
from fantasy.test_data import TEST_GAMES_FANTASY

TEST_GAMES_BY_SPORT = {
    "mlb": TEST_GAMES_MLB,
    "nfl": TEST_GAMES_NFL,
    "cfb": TEST_GAMES_CFB,
    "nba": TEST_GAMES_NBA,
    "nhl": TEST_GAMES_NHL,
    "soccer": TEST_GAMES_SOCCER,
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


DEFAULT_FPS = 60
MIN_FPS = 10
MAX_FPS = 120

DISPLAY_WIDTH = 384
MATRIX_HEIGHT = 32

CARD_SPACING = 15
DEFAULT_CARD_WIDTH = 129
CFB_CARD_WIDTH = 162
NFL_CARD_WIDTH = 130
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
_visible_games_cache = []
_cache_signature = None
_built_games_revision = None
_built_settings_signature = None
_ticker_revision = 0

SPORT_FETCHERS = {
    "mlb": get_live_mlb,
    "nfl": get_live_nfl,
    "cfb": get_live_cfb,
    "nba": get_live_nba,
    "nhl": get_live_nhl,
    "soccer": get_live_soccer,
    "stocks": get_live_stocks,
    "fantasy": get_live_fantasy,
}

def fetch_all_sports():
    results = {}
    errors = {}

    with ThreadPoolExecutor(
        max_workers=len(SPORT_FETCHERS),
        thread_name_prefix="sports-api",
    ) as executor:
        future_to_sport = {
            executor.submit(fetcher): sport
            for sport, fetcher in SPORT_FETCHERS.items()
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

def is_stock_quote(game):
    return game.__class__.__name__ == "StockQuote"

def is_fantasy_game(game):
    return game.__class__.__name__ == "FantasyMatchup"

def game_id(game):
    if is_bet_ticket(game):
        return game.ticket_id

    if is_soccer_game(game) and getattr(game, "event_id", ""):
        return f"soccer:{game.event_id}"

    if is_stock_quote(game):
        return f"stocks:{game.symbol}"

    return f"{get_sport(game)}:{game.away}@{game.home}"

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
    if is_fantasy_game(game):
        return FANTASY_CARD_WIDTH
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
    hidden = set(settings.get("hidden_games", []))
    return [game for game in all_games if game_id(game) not in hidden or is_favorite_game(game, settings)]

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

    return (
        game_signature(game),
        logo_signature,
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

def refresh_games_background():
    global _refresh_in_progress

    try:
        with _games_lock:
            previous_games = _games.copy()

        sports_results, sports_errors = fetch_all_sports()

        combined_games = combine_sports_results(
            sports_results,
            sports_errors=sports_errors,
            previous_games=previous_games,
            use_test_fallback=False,
        )

        publish_games(combined_games)
        try:
            refresh_open_bets()
        except Exception as error:
            print("Bet refresh failed:", error)

        if sports_errors:
            failed_sports = ", ".join(
                sport.upper()
                for sport in sports_errors
            )

            print(
                "Refresh completed with failures for "
                f"{failed_sports}; previous data retained."
            )
        else:
            print("Refreshed live games successfully")

    except Exception as e:
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
    server = make_server(
        "0.0.0.0",
        8080,
        app,
        server_class=ThreadingWSGIServer,
    )
    print("Web app running on port 8080")
    server.serve_forever()


def load_initial_games():
    sports_results, sports_errors = fetch_all_sports()

    return combine_sports_results(
        sports_results,
        sports_errors=sports_errors,
        previous_games=[],
        use_test_fallback=True,
    )

matrix = create_matrix()

if is_update_in_progress():
    matrix.SetImage(
        render_idle_splash(
            DISPLAY_WIDTH,
            MATRIX_HEIGHT,
            "UPDATING",
        )
    )

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

# Last ticker frame actually pushed to the panel.
# Cleared whenever a non-ticker frame is shown.
presented_scroll_column = None
presented_game_index = None
presented_frame_signature = None
presented_ticker_revision = None


def note_external_frame():
    """Forget the ticker frame so the next ticker loop redraws it."""
    global presented_scroll_column
    global presented_game_index
    global presented_frame_signature
    global presented_ticker_revision

    presented_scroll_column = None
    presented_game_index = None
    presented_frame_signature = None
    presented_ticker_revision = None

focus_game_index = 0
focus_last_switch = time.monotonic()
focus_previous_ids = ()

last_refresh = time.monotonic()
last_settings_poll = 0.0
last_update_poll = 0.0
update_in_progress = False

last_frame_time = time.monotonic()

settings = get_settings()

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

while True:
    frame_started_at = time.monotonic()

    delta_seconds = frame_started_at - last_frame_time
    last_frame_time = frame_started_at

    delta_seconds = min(delta_seconds, 0.1)

    now = frame_started_at

    if now - last_settings_poll >= SETTINGS_POLL_INTERVAL:
        settings = get_settings()
        last_settings_poll = now

    if now - last_update_poll >= UPDATE_POLL_INTERVAL:
        update_in_progress = is_update_in_progress()
        last_update_poll = now

    target_fps = get_target_fps(settings)
    frame_delay = 1.0 / target_fps

    scroll_speed = float(settings.get("scroll_speed", 30.0))
    brightness = int(settings.get("brightness", 50))
    refresh_interval = int(settings.get("refresh_interval", 120))

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
            matrix.SetImage(black_frame)

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

        # Avoid a large scroll-time jump after sleeping.
        last_frame_time = time.monotonic()

        # Force a fresh sports update after waking.
        last_refresh = now - refresh_interval

        print("Display awake")

    if update_in_progress:
        note_external_frame()

        if brightness != last_brightness:
            matrix.brightness = brightness
            last_brightness = brightness

        matrix.SetImage(
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

    if now - last_refresh >= refresh_interval and not _refresh_in_progress:
        _refresh_in_progress = True

        threading.Thread(
            target=refresh_games_background,
            daemon=True
        ).start()

        last_refresh = now

    if brightness != last_brightness:
        matrix.brightness = brightness
        last_brightness = brightness

    active_alert = possession_alert_manager.get_active(
        now
    )

    if active_alert is not None:
        note_external_frame()

        alert_frame = render_possession_alert(
            active_alert,
            now=now,
        )

        matrix.SetImage(
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

        last_frame_time = time.monotonic()

        continue

    with _games_lock:
        focus_source_games = _games.copy()

    focus_games = get_focus_games(
        focus_source_games,
        settings,
    )

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

        matrix.SetImage(
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
        matrix.SetImage(render_bet_notice(notice))
        frame_elapsed = time.monotonic() - frame_started_at
        sleep_time = frame_delay - frame_elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)
        last_frame_time = time.monotonic()
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

        matrix.SetImage(
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

    if current_game >= len(visible_games):
        current_game = 0

    scroll_x -= scroll_speed * delta_seconds

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
    if (
        scroll_column == presented_scroll_column
        and current_game == presented_game_index
        and _cache_signature == presented_frame_signature
        and _ticker_revision == presented_ticker_revision
        and presented_frame_signature is not None
    ):
        frame_elapsed = time.monotonic() - frame_started_at
        sleep_time = frame_delay - frame_elapsed

        if sleep_time > 0:
            time.sleep(sleep_time)

        continue

    frame_image.paste(
        (0, 0, 0),
        (0, 0, DISPLAY_WIDTH, MATRIX_HEIGHT),
    )

    x = scroll_column
    game_index = current_game

    while x < DISPLAY_WIDTH:
        game = visible_games[game_index]

        sport = get_sport(game)

        frame_image.paste(
            render_card(
                game,
                settings,
            ),
            (x, 0),
        )

        x += get_game_step(game)

        game_index += 1

        if game_index >= len(visible_games):
            game_index = 0

    matrix.SetImage(frame_image)

    presented_scroll_column = scroll_column
    presented_game_index = current_game
    presented_frame_signature = _cache_signature
    presented_ticker_revision = _ticker_revision

    frame_elapsed = time.monotonic() - frame_started_at
    sleep_time = frame_delay - frame_elapsed

    if sleep_time > 0:
        time.sleep(sleep_time)