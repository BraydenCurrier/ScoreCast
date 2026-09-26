from common.football_focus import (
    FootballFocusStyle,
    render_football_focus,
)
from cfb.colors import team_color
from cfb.cfb_renderer import (
    draw_broadcast_logo,
    draw_team_logo,
)


CFB_FOCUS_STYLE = FootballFocusStyle(
    team_color=team_color,
    draw_team_logo=draw_team_logo,
    draw_broadcast_logo=draw_broadcast_logo,
    show_ranks=True,
)


def render_cfb_focus(game, settings):
    return render_football_focus(
        game,
        settings,
        CFB_FOCUS_STYLE,
    )
