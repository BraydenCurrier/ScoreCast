from PIL import Image, ImageDraw

from common.fonts import (
    print_3x5,
    print_4x5,
    print_4x5_centered,
    print_clock,
    print_gfx_5x7,
    gfx_5x7_width,
)

from nfl.colors import (
    BALL_BROWN,
    GREY,
    WHITE,
    YELLOW,
    team_color,
)

from nfl.nfl_renderer import (
    draw_team_logo,
    draw_broadcast_logo,
    draw_possession_football,
    draw_field_tracker,
    ordinal_down,
)


# =========================================================
# Display
# =========================================================

FOCUS_WIDTH = 384
FOCUS_HEIGHT = 32

BLACK = (0, 0, 0)

DIM_WHITE = (155, 155, 155)

CENTER_LINE = (38, 38, 42)


# =========================================================
# Game state helpers
# =========================================================

def _is_scheduled(game):
    status = str(
        getattr(
            game,
            "status",
            "",
        )
    ).strip().upper()

    return status in {
        "STATUS_SCHEDULED",
        "SCHEDULED",
        "STATUS_PREVIEW",
        "PREVIEW",
    }


def _is_final(game):
    status = str(
        getattr(
            game,
            "status",
            "",
        )
    ).strip().upper()

    return (
        "FINAL" in status
        or status == "STATUS_FINAL"
    )


def _is_halftime(game):
    status = str(
        getattr(
            game,
            "status",
            "",
        )
    ).strip().upper()

    return "HALF" in status


def _safe_int(
    value,
    default=0,
):
    try:
        return int(value)

    except (
        TypeError,
        ValueError,
    ):
        return default

# =========================================================
# Text / score helpers
# =========================================================

def _draw_scaled_gfx_text(
    image,
    *,
    text,
    x,
    y,
    color,
    scale=2,
    align="left",
):
    """
    Render the existing 5x7 font and enlarge it
    using nearest-neighbor scaling.

    This gives the scores a proper scoreboard
    appearance without introducing another font.
    """

    text = str(
        text
    )

    if not text:
        return

    text_width = max(
        1,
        gfx_5x7_width(
            text
        ),
    )

    source = Image.new(
        "RGB",
        (
            text_width,
            7,
        ),
        BLACK,
    )

    source_draw = ImageDraw.Draw(
        source
    )

    print_gfx_5x7(
        source_draw,
        text,
        0,
        0,
        color,
    )

    scaled_width = (
        source.width
        * scale
    )

    scaled_height = (
        source.height
        * scale
    )

    enlarged = source.resize(
        (
            scaled_width,
            scaled_height,
        ),
        resample=Image.Resampling.NEAREST,
    )

    if align == "center":
        paste_x = (
            x
            - scaled_width // 2
        )

    elif align == "right":
        paste_x = (
            x
            - scaled_width
        )

    else:
        paste_x = x

    image.paste(
        enlarged,
        (
            paste_x,
            y,
        ),
    )


def _draw_team_name(
    draw,
    *,
    team,
    x,
    y,
    align,
):
    team = str(
        team
    ).upper()

    color = team_color(
        team
    )

    width = gfx_5x7_width(
        team
    )

    if align == "right":
        text_x = (
            x
            - width
        )

    elif align == "center":
        text_x = (
            x
            - width // 2
        )

    else:
        text_x = x

    print_gfx_5x7(
        draw,
        team,
        text_x,
        y,
        color,
    )


# =========================================================
# Exact ticker field tracker — enlarged
# =========================================================

def _draw_large_field_tracker(
    draw,
    x,
    y,
    yardline,
    possession_direction,
    possession,
    home_team,
    home_color,
    distance=None,
):
    GRASS = (0, 180, 30)
    LINE_COLOR = (200, 200, 200)
    SCRIMMAGE_COLOR = (255, 255, 255)
    FIRST_DOWN_COLOR = (255, 255, 255)

    POST_YELLOW = (255, 205, 0)
    BALL_BROWN = (139, 69, 19)
    LACE_WHITE = (255, 255, 255)

    # =====================================================
    # Field dimensions
    # KEEP THESE EXACTLY AS THEY ARE
    # =====================================================

    ez_width = 10
    playable_width = 100
    field_height = 4

    field_left = x
    field_right = (
        x
        + ez_width
        + playable_width
        + ez_width
        - 1
    )

    playable_left = (
        x
        + ez_width
    )

    playable_right = (
        playable_left
        + playable_width
        - 1
    )

    field_bottom = (
        y
        + field_height
        - 1
    )

    # =====================================================
    # End zones / field
    # =====================================================

    # Left end zone
    draw.rectangle(
        [
            field_left,
            y,
            playable_left - 1,
            field_bottom,
        ],
        fill=home_color,
    )

    # Playing field
    draw.rectangle(
        [
            playable_left,
            y,
            playable_right,
            field_bottom,
        ],
        fill=GRASS,
    )

    # Right end zone
    draw.rectangle(
        [
            playable_right + 1,
            y,
            field_right,
            field_bottom,
        ],
        fill=home_color,
    )

    # =====================================================
    # Goal lines
    # =====================================================

    draw.line(
        [
            playable_left,
            y,
            playable_left,
            field_bottom,
        ],
        fill=LINE_COLOR,
    )

    draw.line(
        [
            playable_right,
            y,
            playable_right,
            field_bottom,
        ],
        fill=LINE_COLOR,
    )

    # =====================================================
    # Yard markers
    #
    # Keep these minimal like the ticker field.
    # =====================================================

    # 25-yard line
    draw.line(
        [
            playable_left + 25,
            y,
            playable_left + 25,
            field_bottom,
        ],
        fill=LINE_COLOR,
    )

    # Midfield
    draw.line(
        [
            playable_left + 50,
            y,
            playable_left + 50,
            field_bottom,
        ],
        fill=LINE_COLOR,
    )

    # Opposite 25-yard line
    draw.line(
        [
            playable_left + 75,
            y,
            playable_left + 75,
            field_bottom,
        ],
        fill=LINE_COLOR,
    )

    # Small 10-yard markers
    draw.point(
        (
            playable_left + 10,
            y,
        ),
        fill=LINE_COLOR,
    )

    draw.point(
        (
            playable_right - 10,
            y,
        ),
        fill=LINE_COLOR,
    )

    # =====================================================
    # Determine ball position
    # =====================================================

    is_home_attacking = (
        possession == home_team
    )

    if is_home_attacking:

        if possession_direction == "OWN":
            absolute_yards = (
                100 - yardline
            )

        else:
            absolute_yards = (
                yardline
            )

    else:

        if possession_direction == "OWN":
            absolute_yards = (
                yardline
            )

        else:
            absolute_yards = (
                100 - yardline
            )

    absolute_yards = max(
        0,
        min(
            100,
            absolute_yards,
        ),
    )

    # Preserve your existing field-position scale.
    pixel_offset = int(
        absolute_yards
    )

    scrimmage_x = (
        playable_left
        + pixel_offset
    )

    # =====================================================
    # Optional first-down line
    # =====================================================

    if distance is not None:

        try:
            distance_value = int(
                distance
            )

        except (
            TypeError,
            ValueError,
        ):
            distance_value = 0

        if distance_value > 0:

            # Your existing field position uses
            # 2 football yards per display pixel.
            first_down_pixels = max(
                1,
                int(
                    round(
                        distance_value
                    )
                ),
            )

            if is_home_attacking:
                first_down_x = (
                    scrimmage_x
                    - first_down_pixels
                )

            else:
                first_down_x = (
                    scrimmage_x
                    + first_down_pixels
                )

            first_down_x = max(
                playable_left,
                min(
                    playable_right,
                    first_down_x,
                ),
            )

            draw.line(
                [
                    first_down_x,
                    y,
                    first_down_x,
                    field_bottom,
                ],
                fill=YELLOW,
            )

    # =====================================================
    # Line of scrimmage
    # =====================================================

    draw.line(
        [
            scrimmage_x,
            y,
            scrimmage_x,
            field_bottom,
        ],
        fill=WHITE,
    )

    # =====================================================
    # Football
    #
    # Slightly larger than the tiny ticker football,
    # but keeps the same pixel-art style.
    # =====================================================

    football_y = (
        y - 3
    )

    # Center football on the scrimmage line.
    if possession == home_team:
        football_x = (
            scrimmage_x + 3
        )
    else:
        football_x = (
            scrimmage_x - 3
        )

    # Brown football body
    draw.line(
        [
            (
                football_x - 2,
                football_y,
            ),
            (
                football_x + 2,
                football_y,
            ),
        ],
        fill=BALL_BROWN,
    )

    draw.line(
        [
            (
                football_x - 3,
                football_y + 1,
            ),
            (
                football_x + 3,
                football_y + 1,
            ),
        ],
        fill=BALL_BROWN,
    )

    draw.line(
        [
            (
                football_x - 2,
                football_y + 2,
            ),
            (
                football_x + 2,
                football_y + 2,
            ),
        ],
        fill=BALL_BROWN,
    )

    # White laces
    draw.point(
        (
            football_x,
            football_y + 1,
        ),
        fill=LACE_WHITE,
    )

    draw.point(
        (
            football_x + 1,
            football_y + 1,
        ),
        fill=LACE_WHITE,
    )

    # =====================================================
    # Goalposts
    #
    # Same positioning/proportions as your existing
    # tracker. Do NOT modify y itself.
    # =====================================================

    post_y = (
        y - 4
    )

    # -----------------------------------------------------
    # Left field goal
    # -----------------------------------------------------

    lx = (
        x - 1
    )

    draw.line(
        [
            (
                lx,
                post_y,
            ),
            (
                lx,
                post_y + 2,
            ),
        ],
        fill=POST_YELLOW,
    )

    draw.line(
        [
            (
                lx + 2,
                post_y,
            ),
            (
                lx + 2,
                post_y + 2,
            ),
        ],
        fill=POST_YELLOW,
    )

    draw.line(
        [
            (
                lx,
                post_y + 2,
            ),
            (
                lx + 2,
                post_y + 2,
            ),
        ],
        fill=POST_YELLOW,
    )

    draw.line(
        [
            (
                lx + 1,
                post_y + 3,
            ),
            (
                lx + 1,
                post_y + 5,
            ),
        ],
        fill=POST_YELLOW,
    )

    # -----------------------------------------------------
    # Right field goal
    # -----------------------------------------------------

    rx = (
        field_right - 1
    )

    draw.line(
        [
            (
                rx,
                post_y,
            ),
            (
                rx,
                post_y + 2,
            ),
        ],
        fill=POST_YELLOW,
    )

    draw.line(
        [
            (
                rx + 2,
                post_y,
            ),
            (
                rx + 2,
                post_y + 2,
            ),
        ],
        fill=POST_YELLOW,
    )

    draw.line(
        [
            (
                rx,
                post_y + 2,
            ),
            (
                rx + 2,
                post_y + 2,
            ),
        ],
        fill=POST_YELLOW,
    )

    draw.line(
        [
            (
                rx + 1,
                post_y + 3,
            ),
            (
                rx + 1,
                post_y + 5,
            ),
        ],
        fill=POST_YELLOW,
    )

# =========================================================
# Pregame
# =========================================================

def _draw_scheduled(
    image,
    draw,
    game,
    settings,
):
    away = str(
        getattr(
            game,
            "away",
            "",
        )
    ).upper()

    home = str(
        getattr(
            game,
            "home",
            "",
        )
    ).upper()

    week = getattr(
        game,
        "week",
        "",
    )

    date = str(
        getattr(
            game,
            "date",
            "",
        )
        or ""
    ).strip()

    start_time = str(
        getattr(
            game,
            "start_time",
            "",
        )
        or ""
    ).strip()

    broadcast = str(
        getattr(
            game,
            "broadcast",
            "",
        )
        or ""
    ).strip()

    # =====================================================
    # Team logos
    # =====================================================

    draw_team_logo(
        image,
        away,
        8,
        1,
        settings,
    )

    draw_team_logo(
        image,
        home,
        346,
        1,
        settings,
    )

    # =====================================================
    # Team names
    # =====================================================

    _draw_team_name(
        draw,
        team=away,
        x=45,
        y=11,
        align="left",
    )

    _draw_team_name(
        draw,
        team=home,
        x=339,
        y=11,
        align="right",
    )

    # ---------------------------------------------
    # Week + date
    # ---------------------------------------------

    top_parts = []

    if week:
        top_parts.append(
            f"WEEK {week}"
        )

    if date:
        top_parts.append(
            date
        )

    top_text = "  ".join(
        top_parts
    )

    if top_text:
        print_4x5_centered(
            draw,
            top_text,
            FOCUS_WIDTH // 2,
            1,
            DIM_WHITE,
        )

    # ---------------------------------------------
    # Kickoff time
    # ---------------------------------------------

    if start_time:
        print_4x5_centered(
            draw,
            start_time,
            FOCUS_WIDTH // 2,
            8,
            WHITE,
        )

    # ---------------------------------------------
    # Matchup separator
    # ---------------------------------------------

    print_4x5_centered(
        draw,
        "VS",
        FOCUS_WIDTH // 2,
        15,
        GREY,
    )

    # ---------------------------------------------
    # Broadcast logo
    # ---------------------------------------------

    broadcast_drawn = False

    if broadcast:
        broadcast_drawn = (
            draw_broadcast_logo(
                image,
                broadcast,
                FOCUS_WIDTH // 2,
                26,
                settings,
            )
        )

    # Fall back to text if a broadcast logo does
    # not exist in the logo store.
    if (
        broadcast
        and not broadcast_drawn
    ):
        print_3x5(
            draw,
            broadcast.upper(),
            (
                FOCUS_WIDTH // 2
                - (
                    len(
                        broadcast
                    )
                    * 4
                ) // 2
            ),
            25,
            GREY,
        )


# =========================================================
# Live scoreboard
# =========================================================

def _draw_live_team(
    image,
    draw,
    *,
    team,
    score,
    is_home,
    has_possession,
    settings,
):
    team = str(
        team
    ).upper()

    score = str(
        score
    )

    if is_home:

        # -----------------------------------------
        # Logo
        # -----------------------------------------

        draw_team_logo(
            image,
            team,
            301,
            1,
            settings,
        )

        # -----------------------------------------
        # Team abbreviation
        # -----------------------------------------

        _draw_team_name(
            draw,
            team=team,
            x=294,
            y=2,
            align="right",
        )

        # -----------------------------------------
        # Possession indicator
        # -----------------------------------------

        if has_possession:
            draw_possession_football(
                draw,
                283,
                11,
            )

        # -----------------------------------------
        # Large score
        # -----------------------------------------

        _draw_scaled_gfx_text(
            image,
            text=score,
            x=237,
            y=3,
            color=YELLOW,
            scale=2,
            align="right",
        )

    else:

        # -----------------------------------------
        # Logo
        # -----------------------------------------

        draw_team_logo(
            image,
            team,
            53,
            1,
            settings,
        )

        # -----------------------------------------
        # Team abbreviation
        # -----------------------------------------

        _draw_team_name(
            draw,
            team=team,
            x=90,
            y=2,
            align="left",
        )

        # -----------------------------------------
        # Possession indicator
        # -----------------------------------------

        if has_possession:
            draw_possession_football(
                draw,
                101,
                11,
            )

        # -----------------------------------------
        # Large score
        # -----------------------------------------

        _draw_scaled_gfx_text(
            image,
            text=score,
            x=147,
            y=3,
            color=YELLOW,
            scale=2,
            align="left",
        )


def _draw_live_center(
    draw,
    game,
):
    quarter = _safe_int(
        getattr(
            game,
            "quarter",
            0,
        )
    )

    clock = str(
        getattr(
            game,
            "clock",
            "",
        )
        or ""
    ).strip()

    # =====================================================
    # Quarter / halftime
    # =====================================================

    if _is_halftime(
        game
    ):
        print_4x5_centered(
            draw,
            "HALF",
            FOCUS_WIDTH // 2,
            1,
            WHITE,
        )

    elif quarter > 0:

        quarter_text = (
            "OT"
            if quarter > 4
            else f"Q{quarter}"
        )

        print_4x5_centered(
            draw,
            quarter_text,
            FOCUS_WIDTH // 2,
            1,
            WHITE,
        )

    # =====================================================
    # Clock
    # =====================================================

    if (
        clock
        and not _is_halftime(
            game
        )
    ):
        print_clock(
            draw,
            clock,
            FOCUS_WIDTH // 2,
            7,
            YELLOW,
        )

    # =====================================================
    # Down + distance
    # =====================================================

    down = _safe_int(
        getattr(
            game,
            "down",
            0,
        )
    )

    distance = _safe_int(
        getattr(
            game,
            "distance",
            0,
        )
    )

    if down > 0:

        down_text = (
            f"{ordinal_down(down)}"
            f"&{distance}"
        )

        print_4x5_centered(
            draw,
            down_text,
            FOCUS_WIDTH // 2,
            14,
            WHITE,
        )


def _draw_live(
    image,
    draw,
    game,
    settings,
):
    away = str(
        getattr(
            game,
            "away",
            "",
        )
    ).upper()

    home = str(
        getattr(
            game,
            "home",
            "",
        )
    ).upper()

    away_score = _safe_int(
        getattr(
            game,
            "away_score",
            0,
        )
    )

    home_score = _safe_int(
        getattr(
            game,
            "home_score",
            0,
        )
    )

    possession = str(
        getattr(
            game,
            "possession",
            "",
        )
    ).upper()

    # =====================================================
    # Away team
    # =====================================================

    _draw_live_team(
        image,
        draw,
        team=away,
        score=away_score,
        is_home=False,
        has_possession=(
            possession == away
        ),
        settings=settings,
    )

    # =====================================================
    # Home team
    # =====================================================

    _draw_live_team(
        image,
        draw,
        team=home,
        score=home_score,
        is_home=True,
        has_possession=(
            possession == home
        ),
        settings=settings,
    )

    # =====================================================
    # Quarter / clock / down
    # =====================================================

    _draw_live_center(
        draw,
        game,
    )

    # =====================================================
    # Field
    #
    # This is the regular ticker field tracker,
    # enlarged.
    # =====================================================

    home_color = team_color(game.home)

    if not _is_halftime(game):
        if game.possession == game.yardline_side:
            _draw_large_field_tracker(
                draw,
                132,
                28,
                game.yardline_number,
                "OWN",
                game.possession,
                game.home,
                home_color,
                game.distance,
            )
        else:
            _draw_large_field_tracker(
                draw,
                132,
                28,
                game.yardline_number,
                "OPP",
                game.possession,
                game.home,
                home_color,
                game.distance,
            )


# =========================================================
# Final
# =========================================================

def _draw_final(
    image,
    draw,
    game,
    settings,
):
    away = str(
        getattr(
            game,
            "away",
            "",
        )
    ).upper()

    home = str(
        getattr(
            game,
            "home",
            "",
        )
    ).upper()

    away_score = _safe_int(
        getattr(
            game,
            "away_score",
            0,
        )
    )

    home_score = _safe_int(
        getattr(
            game,
            "home_score",
            0,
        )
    )

    # =====================================================
    # Logos
    # =====================================================

    draw_team_logo(
        image,
        away,
        8,
        1,
        settings,
    )

    draw_team_logo(
        image,
        home,
        346,
        1,
        settings,
    )

    # =====================================================
    # Team names
    # =====================================================

    _draw_team_name(
        draw,
        team=away,
        x=45,
        y=2,
        align="left",
    )

    _draw_team_name(
        draw,
        team=home,
        x=339,
        y=2,
        align="right",
    )

    # =====================================================
    # Scores
    # =====================================================

    _draw_scaled_gfx_text(
        image,
        text=away_score,
        x=82,
        y=10,
        color=YELLOW,
        scale=2,
        align="left",
    )

    _draw_scaled_gfx_text(
        image,
        text=home_score,
        x=302,
        y=10,
        color=YELLOW,
        scale=2,
        align="right",
    )

    print_4x5_centered(
        draw,
        "FINAL",
        FOCUS_WIDTH // 2,
        4,
        WHITE,
    )

    draw.line(
        (
            151,
            13,
            232,
            13,
        ),
        fill=CENTER_LINE,
    )

    print_4x5_centered(
        draw,
        away,
        163,
        20,
        team_color(
            away
        ),
    )

    print_4x5_centered(
        draw,
        home,
        221,
        20,
        team_color(
            home
        ),
    )


# =========================================================
# Main renderer
# =========================================================

def render_nfl_focus(
    game,
    settings,
):
    """
    Render an NFL Focus Mode scoreboard across
    the complete 384x32 ScoreCast display.
    """

    image = Image.new(
        "RGB",
        (
            FOCUS_WIDTH,
            FOCUS_HEIGHT,
        ),
        BLACK,
    )

    away = str(
        getattr(
            game,
            "away",
            "",
        )
    ).upper()

    home = str(
        getattr(
            game,
            "home",
            "",
        )
    ).upper()

    draw = ImageDraw.Draw(
        image
    )

    # =====================================================
    # Pregame
    # =====================================================

    if _is_scheduled(
        game
    ):
        _draw_scheduled(
            image,
            draw,
            game,
            settings,
        )

        return image

    # =====================================================
    # Final
    # =====================================================

    if _is_final(
        game
    ):
        _draw_final(
            image,
            draw,
            game,
            settings,
        )

        return image

    # =====================================================
    # Live
    # =====================================================

    _draw_live(
        image,
        draw,
        game,
        settings,
    )

    return image