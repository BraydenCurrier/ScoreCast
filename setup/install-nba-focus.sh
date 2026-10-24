#!/bin/bash
# Copy the NBA focus scoreboard onto the running release and restart it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RELEASE="$(readlink -f /opt/scorecast/current)"
MAIN="$RELEASE/src/main.py"
SETTINGS="$RELEASE/src/common/settings.py"

python3 - "$MAIN" "$SETTINGS" << 'PY'
import pathlib, sys
main_path, settings_path = map(pathlib.Path, sys.argv[1:])
src = main_path.read_text()
replacements = [
(
"from nba.api import get_today_games as get_live_nba\nfrom nba.nba_renderer import render_game_strip_onto as draw_nba_strip\n",
"from nba.api import get_today_games as get_live_nba\nfrom nba.focus_renderer import render_nba_focus\nfrom nba.nba_renderer import render_game_strip_onto as draw_nba_strip\n",
),
(
'''        _id_list("nfl_game_ids")
        + _id_list("cfb_game_ids")
        + _id_list("mlb_game_ids")
''',
'''        _id_list("nfl_game_ids")
        + _id_list("cfb_game_ids")
        + _id_list("mlb_game_ids")
        + _id_list("nba_game_ids")
''',
),
(
'''                is_nfl_game(game)
                or is_cfb_game(game)
                or is_mlb_game(game)
''',
'''                is_nfl_game(game)
                or is_cfb_game(game)
                or is_mlb_game(game)
                or is_nba_game(game)
''',
),
(
'''            elif is_mlb_game(focus_game):
                focus_frame = render_mlb_focus(
                    focus_game,
                    settings,
                )
            else:
''',
'''            elif is_mlb_game(focus_game):
                focus_frame = render_mlb_focus(
                    focus_game,
                    settings,
                )
            elif is_nba_game(focus_game):
                focus_frame = render_nba_focus(
                    focus_game,
                    settings,
                )
            else:
''',
),
]
for old, new in replacements:
    if new in src:
        continue
    if old not in src:
        raise SystemExit(f"Could not patch {main_path}")
    src = src.replace(old, new, 1)
main_path.write_text(src)

settings = settings_path.read_text()
old = '''        "mlb_game_ids": [],
        "rotation_seconds": 30,'''
new = '''        "mlb_game_ids": [],
        "nba_game_ids": [],
        "rotation_seconds": 30,'''
if "nba_game_ids" not in settings:
    if old not in settings:
        raise SystemExit(f"Could not patch {settings_path}")
    settings_path.write_text(settings.replace(old, new, 1))
PY

cp "$ROOT/src/nba/focus_renderer.py" \
   "$ROOT/src/nba/colors.py" \
   "$ROOT/src/nba/models.py" \
   "$ROOT/src/nba/api.py" \
   "$RELEASE/src/nba/"
cp "$ROOT/src/web/app.py" "$RELEASE/src/web/app.py"
systemctl restart scorecast
systemctl is-active scorecast
