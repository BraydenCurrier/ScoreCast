import threading
import time
from wsgiref.simple_server import make_server

import traceback

from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image, ImageDraw

from common.matrix import create_matrix
from common.settings import get_settings

from fantasy.api import get_today_games as get_live_fantasy

from alerts.manager import possession_alert_manager
from alerts.renderer import render_possession_alert
from alerts.watcher import possession_watch_loop

from mlb.api import get_today_games as get_live_mlb
from mlb.mlb_renderer import render_game_strip_onto as draw_mlb_strip

from nfl.api import get_today_games as get_live_nfl
from nfl.nfl_renderer import render_game_strip_onto as draw_nfl_strip

from soccer.api import get_today_games as get_live_soccer
from soccer.soccer_renderer import render_game_strip_onto as draw_soccer_strip

from cfb.api import get_today_games as get_live_cfb
from cfb.cfb_renderer import render_game_strip_onto as draw_cfb_strip

from nba.api import get_today_games as get_live_nba
from nba.nba_renderer import render_game_strip_onto as draw_nba_strip

from nhl.api import get_today_games as get_live_nhl
from nhl.nhl_renderer import render_game_strip_onto as draw_nhl_strip

from mlb.test_data import TEST_GAMES_MLB
from nfl.test_data import TEST_GAMES_NFL
from soccer.test_data import TEST_GAMES_SOCCER
from cfb.test_data import TEST_GAMES_CFB
from nba.test_data import TEST_GAMES_NBA
from nhl.test_data import TEST_GAMES_NHL

TEST_GAMES_BY_SPORT = {
    "mlb": TEST_GAMES_MLB,
    "nfl": TEST_GAMES_NFL,
    "soccer": TEST_GAMES_SOCCER,
    "cfb": TEST_GAMES_CFB,
    "nba": TEST_GAMES_NBA,
    "nhl": TEST_GAMES_NHL,
    "fantasy": [],
}

SPORT_DISPLAY_ORDER = (
    "mlb",
    "nfl",
    "soccer",
    "cfb",
    "nba",
    "nhl",
    "fantasy",
)

from web.app import app, set_latest_games

DEFAULT_FPS = 60
MIN_FPS = 10
MAX_FPS = 120

DISPLAY_WIDTH = 384
MATRIX_HEIGHT = 32

CARD_SPACING = 15
DEFAULT_CARD_WIDTH = 129
CFB_CARD_WIDTH = 136

SETTINGS_POLL_INTERVAL = 0.5

_games = []
_games_lock = threading.Lock()
_refresh_in_progress = False

_card_cache = {}
_visible_games_cache = []
_cache_signature = None

SPORT_FETCHERS = {
    "mlb": get_live_mlb,
    "nfl": get_live_nfl,
    "soccer": get_live_soccer,
    "cfb": get_live_cfb,
    "nba": get_live_nba,
    "nhl": get_live_nhl,
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

def game_signature(game):
    return (game.__class__.__name__, tuple(sorted(vars(game).items())))

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

def is_cfb_game(game):
    return game.__class__.__name__ == "CollegeFootballGame" 

def is_nfl_game(game):
    return game.__class__.__name__ == "FootballGame"

def is_soccer_game(game):
    return game.__class__.__name__ == "SoccerGame"

def is_nba_game(game):
    return game.__class__.__name__ == "BasketballGame"

def is_nhl_game(game):
    return game.__class__.__name__ == "HockeyGame"

def is_fantasy_game(game):
    return game.__class__.__name__ == "FantasyMatchup"

def game_id(game):
    return f"{get_sport(game)}:{game.away}@{game.home}"

def get_sport(game):
    if is_cfb_game(game):
        return "cfb"

    if is_nfl_game(game):
        return "nfl"

    if is_soccer_game(game):
        return "soccer"

    if is_nba_game(game):
        return "nba"

    if is_nhl_game(game):
        return "nhl"

    if is_fantasy_game(game):
        return "fantasy"
    
    return "mlb"

def get_game_width(game):
    if is_cfb_game(game):
        return CFB_CARD_WIDTH

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
    elif is_soccer_game(game):
        draw_soccer_strip(draw, game, x)
    elif is_nhl_game(game):
        draw_nhl_strip(image, draw, game, x, settings)
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

def get_visible_games(all_games, settings):
    hidden = set(settings.get("hidden_games", []))
    return [game for game in all_games if game_id(game) not in hidden]

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

def render_card(game, settings):
    key = (
        game_signature(game),
        logo_variants_signature(settings),
    )

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
    return image


def rebuild_visible_games_if_needed(settings):
    global _visible_games_cache, _cache_signature, _card_cache

    with _games_lock:
        current_games = _games.copy()

    signature = (
        tuple(game_signature(g) for g in current_games),
        tuple(settings.get("hidden_games", [])),
        tuple(settings.get("game_order", [])),
        logo_variants_signature(settings),
    )

    if signature == _cache_signature:
        return _visible_games_cache

    ordered_games = apply_saved_order(current_games, settings)
    visible_games = get_visible_games(ordered_games, settings)

    if not visible_games:
        visible_games = (
            TEST_GAMES_MLB
            + TEST_GAMES_NFL
            + TEST_GAMES_SOCCER
            + TEST_GAMES_CFB
            + TEST_GAMES_NBA
            + TEST_GAMES_NHL
        )

    _visible_games_cache = visible_games
    _cache_signature = signature
    _card_cache = {}

    return _visible_games_cache

def combine_sports_results(sports_results):
    combined_games = []

    for sport in SPORT_DISPLAY_ORDER:
        games = sports_results.get(sport)

        if games:
            combined_games.extend(games)
        else:
            combined_games.extend(
                TEST_GAMES_BY_SPORT[sport]
            )

    return combined_games

def refresh_games_background():
    global _games, _refresh_in_progress, _cache_signature

    try:
        sports_results, sports_errors = fetch_all_sports()
        combined_games = combine_sports_results(sports_results)

        with _games_lock:
            _games = combined_games
            set_latest_games(combined_games)

        _cache_signature = None
        print("Refreshed live games successfully")

    except Exception as e:
        print("Games refresh failed:", e)

    finally:
        _refresh_in_progress = False


def run_web_server():
    server = make_server("0.0.0.0", 8080, app)
    print("Web app running on port 8080")
    server.serve_forever()


def load_initial_games():
    sports_results, _ = fetch_all_sports()
    return combine_sports_results(sports_results)

matrix = create_matrix()

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

_games = load_initial_games()
set_latest_games(_games)

current_game = 0
scroll_x = 0.0

last_refresh = time.monotonic()
last_settings_poll = 0.0

last_frame_time = time.monotonic()

settings = get_settings()

last_brightness = None

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

    target_fps = get_target_fps(settings)
    frame_delay = 1.0 / target_fps

    scroll_speed = float(settings.get("scroll_speed", 30.0))
    brightness = int(settings.get("brightness", 50))
    refresh_interval = int(settings.get("refresh_interval", 120))

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

    visible_games = rebuild_visible_games_if_needed(
        settings
    )

    if not visible_games:
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

    frame_image.paste(
        (0, 0, 0),
        (0, 0, DISPLAY_WIDTH, MATRIX_HEIGHT),
    )

    x = int(scroll_x)
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

    frame_elapsed = time.monotonic() - frame_started_at
    sleep_time = frame_delay - frame_elapsed

    if sleep_time > 0:
        time.sleep(sleep_time)