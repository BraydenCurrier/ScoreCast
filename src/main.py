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

from nba.api import get_today_games as get_live_nba
from nba.nba_renderer import render_game_strip_onto as draw_nba_strip

from nhl.api import get_today_games as get_live_nhl
from nhl.nhl_renderer import render_game_strip_onto as draw_nhl_strip

from notifications.models import NotificationCard
from notifications.renderer import render_notification_onto as draw_notification_card
from notifications.manager import NotificationManager

from mlb.test_data import TEST_GAMES_MLB
from nfl.test_data import TEST_GAMES_NFL
from soccer.test_data import TEST_GAMES_SOCCER
from cfb.test_data import TEST_GAMES_CFB
from nba.test_data import TEST_GAMES_NBA
from nhl.test_data import TEST_GAMES_NHL

from web.app import app, set_latest_games

from odds.manager import OddsManager

odds_manager = OddsManager()

FRAME_DELAY = 1 / 60

DISPLAY_WIDTH = 384
MATRIX_HEIGHT = 32

CARD_SPACING = 15
DEFAULT_CARD_WIDTH = 129
CFB_CARD_WIDTH = 136
NOTIFICATION_CARD_WIDTH = 273

SETTINGS_POLL_INTERVAL = 0.5

_games = []
_games_lock = threading.Lock()
_refresh_in_progress = False

_card_cache = {}
_visible_games_cache = []
_cache_signature = None

_odds_refresh_in_progress = False

notification_manager = NotificationManager()
_notification_refresh_in_progress = False

def game_signature(game):
    return (game.__class__.__name__, tuple(sorted(vars(game).items())))

def odds_signature(odds):
    if odds is None:
        return None

    return (
        odds.moneyline_away,
        odds.moneyline_home,
        odds.spread,
        odds.spread_price,
        odds.total,
        odds.over_price,
        odds.under_price,
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

def is_notification_card(game):
    return game.__class__.__name__ == "NotificationCard"

def game_id(game):
    if is_notification_card(game):
        return f"notification:{game.source}:{game.title}:{game.created_at}"

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
    
    if is_notification_card(game):
        return "notification"

    return "mlb"

def refresh_odds_background():
    global _odds_refresh_in_progress

    try:
        odds_manager.refresh_all()
    except Exception as e:
        print("Odds refresh failed:", e)
    finally:
        _odds_refresh_in_progress = False

def get_game_width(game):
    if is_cfb_game(game):
        return CFB_CARD_WIDTH

    if is_notification_card(game):
        return NOTIFICATION_CARD_WIDTH

    return DEFAULT_CARD_WIDTH


def get_game_step(game):
    return get_game_width(game) + CARD_SPACING


def draw_game(draw, game, odds, x):
    if is_cfb_game(game):
        draw_cfb_strip(draw, game, odds, x)
    elif is_nba_game(game):
        draw_nba_strip(draw, game, odds, x)
    elif is_nfl_game(game):
        draw_nfl_strip(draw, game, odds, x)
    elif is_soccer_game(game):
        draw_soccer_strip(draw, game, odds, x)
    elif is_nhl_game(game):
        draw_nhl_strip(draw, game, odds, x)
    elif is_notification_card(game):
        draw_notification_card(draw, game, x)
    else:
        draw_mlb_strip(draw, game, odds, x)


def get_limited_notification_cards(settings):
    raw_notifications = notification_manager.get_cards()
    max_cards_setting = settings.get("notifications", {}).get("max_cards") or settings.get("max_cards", 3)
    max_cards = int(max_cards_setting)
    return raw_notifications[:max_cards]


def replace_notifications_in_games(notification_cards):
    global _games, _cache_signature

    with _games_lock:
        non_notification_games = [g for g in _games if not is_notification_card(g)]
        _games = notification_cards + non_notification_games
        set_latest_games(_games)

    _cache_signature = None


def apply_saved_order(all_games, settings):
    saved_order = settings.get("game_order", [])

    if not saved_order:
        return all_games

    order_index = {gid: idx for idx, gid in enumerate(saved_order)}
    return sorted(all_games, key=lambda g: order_index.get(game_id(g), 999))


def get_visible_games(all_games, settings):
    hidden = set(settings.get("hidden_games", []))
    return [game for game in all_games if game_id(game) not in hidden]


def render_card(game, odds):
    key = (
        game_signature(game),
        odds_signature(odds),
    )

    cached = _card_cache.get(key)
    if cached is not None:
        return cached

    card_width = get_game_width(game)

    image = Image.new("RGB", (card_width, MATRIX_HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw_game(draw, game, odds, 0)

    _card_cache[key] = image
    return image


def rebuild_visible_games_if_needed(settings):
    global _visible_games_cache, _cache_signature, _card_cache

    with _games_lock:
        current_games = _games.copy()

    # The signature naturally tracks notifications now because they live inside current_games!
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
            + TEST_GAMES_NBA
            + TEST_GAMES_NHL
        )

    _visible_games_cache = visible_games
    _cache_signature = signature
    _card_cache = {}

    return _visible_games_cache


def refresh_games_background():
    global _games, _refresh_in_progress, _cache_signature

    try:
        # 1. Fetch live sports data
        live_mlb = get_live_mlb()
        live_nfl = get_live_nfl()
        live_soccer = get_live_soccer()
        live_cfb = get_live_cfb()
        live_nba = get_live_nba()
        live_nhl = get_live_nhl()

        current_mlb = live_mlb if live_mlb else TEST_GAMES_MLB
        current_nfl = live_nfl if live_nfl else TEST_GAMES_NFL
        current_soccer = live_soccer if live_soccer else TEST_GAMES_SOCCER
        current_cfb = live_cfb if live_cfb else TEST_GAMES_CFB
        current_nba = live_nba if live_nba else TEST_GAMES_NBA
        current_nhl = live_nhl if live_nhl else TEST_GAMES_NHL

        settings = get_settings()

        # 2. Fetch notifications and treat them exactly like game data
        # try:
        #     notification_manager.refresh()
        #     raw_notifications = notification_manager.get_cards()
        # except Exception as e:
        #     print("Notification refresh failed during game pull:", e)
        #     raw_notifications = []

        # 3. Apply the max_cards limit strictly here
        # notification_cards = get_limited_notification_cards(settings)

        # 4. Combine them into one unified card roster
        combined_games = (
            current_mlb
            + current_nfl
            + current_soccer
            + current_cfb
            + current_nba
            + current_nhl
        )

        with _games_lock:
            _games = combined_games
            set_latest_games(combined_games)

        _cache_signature = None
        print("Refreshed mixed live games and notifications successfully")

    except Exception as e:
        print("Games refresh failed:", e)

    finally:
        _refresh_in_progress = False


def run_web_server():
    server = make_server("0.0.0.0", 8080, app)
    print("Web app running on port 8080")
    server.serve_forever()


def load_initial_games():
    settings = get_settings()
    
    #  Load initial notifications
    # try:
    #     notification_manager.refresh()
    #     raw_notifications = notification_manager.get_cards()
    # except Exception:
    #     raw_notifications = []
        
    #notification_cards = get_limited_notification_cards(settings)

    # Load initial sports
    initial_mlb = get_live_mlb() or TEST_GAMES_MLB
    initial_nfl = get_live_nfl() or TEST_GAMES_NFL
    initial_soccer = get_live_soccer() or TEST_GAMES_SOCCER
    initial_cfb = get_live_cfb() or TEST_GAMES_CFB
    initial_nba = get_live_nba() or TEST_GAMES_NBA
    initial_nhl = get_live_nhl() or TEST_GAMES_NHL

    return initial_mlb + initial_nfl + initial_soccer + initial_cfb + initial_nba + initial_nhl

def refresh_notifications_background():
    global _notification_refresh_in_progress

    try:
        settings = get_settings()
        notification_manager.refresh()
        notification_cards = get_limited_notification_cards(settings)
        replace_notifications_in_games(notification_cards)
    except Exception as e:
        print("Notification refresh failed:", e)
    finally:
        _notification_refresh_in_progress = False

matrix = create_matrix()

threading.Thread(
    target=run_web_server,
    daemon=True
).start()

_games = load_initial_games()
set_latest_games(_games)

threading.Thread(
    target=refresh_notifications_background,
    daemon=True,
).start()

threading.Thread(
    target=odds_manager.refresh_all,
    daemon=True,
).start()

current_game = 0
scroll_x = 0.0
last_refresh = time.time()
last_notification_refresh = time.time()

last_odds_refresh = time.time()

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

    # odds_refresh_interval = (
    #     settings
    #     .get("odds", {})
    #     .get("refresh_interval", 900)
    # )

    # if (
    #     now - last_odds_refresh >= odds_refresh_interval
    #     and not _odds_refresh_in_progress
    # ):
    #     _odds_refresh_in_progress = True

    #     threading.Thread(
    #         target=refresh_odds_background,
    #         daemon=True,
    #     ).start()

    #     last_odds_refresh = now

    # notification_refresh_interval = int(
    #     settings.get("notifications", {}).get("refresh_interval", 60)
    # )

    # if (
    #     now - last_notification_refresh >= notification_refresh_interval
    #     and not _notification_refresh_in_progress
    # ):
    #     _notification_refresh_in_progress = True

    #     threading.Thread(
    #         target=refresh_notifications_background,
    #         daemon=True,
    #     ).start()

    #     last_notification_refresh = now

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

    active_card_step = get_game_step(
        visible_games[current_game]
    )

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

        sport = get_sport(game)

        odds = None

        if not is_notification_card(game):
            odds = odds_manager.get(
                sport,
                game.away,
                game.home,
            )

        frame_image.paste(
            render_card(
                game,
                odds,
            ),
            (x, 0),
        )

        x += get_game_step(game)

        game_index += 1

        if game_index >= len(visible_games):
            game_index = 0

    matrix.SetImage(frame_image)

    time.sleep(FRAME_DELAY)