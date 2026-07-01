import threading
import time
from wsgiref.simple_server import make_server

from PIL import Image, ImageDraw

from common.matrix import create_matrix
from common.settings import get_settings

from mlb.api import get_today_games as get_live_mlb
from mlb.mlb_renderer import render_game_strip_onto as draw_mlb_strip

from nfl.api import get_today_games as get_live_nfl
from nfl.nfl_renderer import render_game_strip_onto as draw_nfl_strip

from soccer.api import get_today_games as get_live_soccer
from soccer.soccer_renderer import render_game_strip_onto as draw_soccer_strip

from cfb.api import get_today_games as get_live_cfb
from cfb.cfb_renderer import render_game_strip_onto as draw_cfb_strip

from mlb.test_data import TEST_GAMES_MLB
from nfl.test_data import TEST_GAMES_NFL
from soccer.test_data import TEST_GAMES_SOCCER
from cfb.test_data import TEST_GAMES_CFB

from web.app import app, set_latest_games


FRAME_DELAY = 1 / 60

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


def game_id(game):
    return f"{game.away}@{game.home}"


def game_signature(game):
    return (game.__class__.__name__, tuple(sorted(vars(game).items())))


def is_cfb_game(game):
    return game.__class__.__name__ == "CollegeFootballGame" or hasattr(game, "home_rank")


def is_nfl_game(game):
    return (
        game.__class__.__name__ == "FootballGame"
        or hasattr(game, "quarter")
    ) and not is_cfb_game(game)


def is_soccer_game(game):
    return game.__class__.__name__ == "SoccerGame" or hasattr(game, "minute")


def get_game_width(game):
    if is_cfb_game(game):
        return CFB_CARD_WIDTH

    return DEFAULT_CARD_WIDTH


def get_game_step(game):
    return get_game_width(game) + CARD_SPACING


def draw_game(draw, game, x):
    if is_cfb_game(game):
        draw_cfb_strip(draw, game, x)
    elif is_nfl_game(game):
        draw_nfl_strip(draw, game, x)
    elif is_soccer_game(game):
        draw_soccer_strip(draw, game, x)
    else:
        draw_mlb_strip(draw, game, x)


def apply_saved_order(all_games, settings):
    saved_order = settings.get("game_order", [])

    if not saved_order:
        return all_games

    order_index = {gid: idx for idx, gid in enumerate(saved_order)}
    return sorted(all_games, key=lambda g: order_index.get(game_id(g), 999))


def get_visible_games(all_games, settings):
    hidden = set(settings.get("hidden_games", []))
    return [game for game in all_games if game_id(game) not in hidden]


def render_card(game):
    key = game_signature(game)

    cached = _card_cache.get(key)
    if cached is not None:
        return cached

    card_width = get_game_width(game)

    image = Image.new("RGB", (card_width, MATRIX_HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw_game(draw, game, 0)

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
        )

    _visible_games_cache = visible_games
    _cache_signature = signature
    _card_cache = {}

    return _visible_games_cache


def refresh_games_background():
    global _games, _refresh_in_progress, _cache_signature

    try:
        live_mlb = get_live_mlb()
        live_nfl = get_live_nfl()
        live_soccer = get_live_soccer()
        live_cfb = get_live_cfb()

        current_mlb = live_mlb if live_mlb else TEST_GAMES_MLB
        current_nfl = live_nfl if live_nfl else TEST_GAMES_NFL
        current_soccer = live_soccer if live_soccer else TEST_GAMES_SOCCER
        current_cfb = live_cfb if live_cfb else TEST_GAMES_CFB

        combined_games = (
            current_mlb
            + current_nfl
            + current_soccer
            + current_cfb
        )

        with _games_lock:
            _games = combined_games
            set_latest_games(combined_games)

        _cache_signature = None

        print("Refreshed mixed live games background successfully")

    except Exception as e:
        print("Games refresh failed:", e)

    finally:
        _refresh_in_progress = False


def run_web_server():
    server = make_server("0.0.0.0", 8080, app)
    print("Web app running on port 8080")
    server.serve_forever()


def load_initial_games():
    try:
        initial_mlb = get_live_mlb() or TEST_GAMES_MLB
    except Exception:
        initial_mlb = TEST_GAMES_MLB

    try:
        initial_nfl = get_live_nfl() or TEST_GAMES_NFL
    except Exception:
        initial_nfl = TEST_GAMES_NFL

    try:
        initial_soccer = get_live_soccer() or TEST_GAMES_SOCCER
    except Exception:
        initial_soccer = TEST_GAMES_SOCCER

    try:
        initial_cfb = get_live_cfb() or TEST_GAMES_CFB
    except Exception:
        initial_cfb = TEST_GAMES_CFB

    return initial_mlb + initial_nfl + initial_soccer + initial_cfb


matrix = create_matrix()

threading.Thread(
    target=run_web_server,
    daemon=True
).start()

_games = load_initial_games()
set_latest_games(_games)

current_game = 0
scroll_x = 0.0
last_refresh = time.time()

last_settings_poll = 0.0
settings = get_settings()
last_brightness = None


while True:
    now = time.time()

    if now - last_settings_poll >= SETTINGS_POLL_INTERVAL:
        settings = get_settings()
        last_settings_poll = now

    scroll_speed = float(settings.get("scroll_speed", 0.4))
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

    visible_games = rebuild_visible_games_if_needed(settings)

    if not visible_games:
        time.sleep(FRAME_DELAY)
        continue

    if current_game >= len(visible_games):
        current_game = 0

    scroll_x -= scroll_speed

    active_card_step = get_game_step(visible_games[current_game])

    if scroll_x <= -active_card_step:
        scroll_x += active_card_step
        current_game += 1

        if current_game >= len(visible_games):
            current_game = 0

    frame_image = Image.new(
        "RGB",
        (DISPLAY_WIDTH, MATRIX_HEIGHT),
        (0, 0, 0)
    )

    x = int(scroll_x)
    game_index = current_game

    while x < DISPLAY_WIDTH:
        game = visible_games[game_index]
        card = render_card(game)

        frame_image.paste(card, (x, 0))

        x += get_game_step(game)
        game_index += 1

        if game_index >= len(visible_games):
            game_index = 0

    matrix.SetImage(frame_image)

    time.sleep(FRAME_DELAY)