from common.football_focus import (
    FootballFocusStyle,
    render_football_focus,
)
from nfl.colors import team_color
from nfl.nfl_renderer import (
    draw_broadcast_logo,
    draw_team_logo,
)


NFL_FOCUS_STYLE = FootballFocusStyle(
    team_color=team_color,
    draw_team_logo=draw_team_logo,
    draw_broadcast_logo=draw_broadcast_logo,
    show_ranks=False,
)


def render_nfl_focus(game, settings):
    return render_football_focus(
        game,
        settings,
        NFL_FOCUS_STYLE,
    )
