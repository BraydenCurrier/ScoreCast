"""Modes page markup."""

from html import escape

from modes.engine import (
    DAY_NAMES,
    SPORT_CHOICES,
    all_modes,
    describe_mode,
    status_line,
)


DAY_ORDER = (6, 0, 1, 2, 3, 4, 5)


def render_modes_page(styles, header, settings, error=""):
    modes = all_modes(settings)
    presets = [mode for mode in modes if mode.get("builtin")]
    custom = [mode for mode in modes if not mode.get("builtin")]
    error_html = (
        f'<div class="error">{escape(error)}</div>'
        if error
        else ""
    )
    cards = "".join(_mode_card(mode, settings) for mode in presets)
    yours = "".join(
        _mode_card(mode, settings, removable=True)
        for mode in custom
    )
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>GameLine Pro Modes</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    {styles}
</head>
<body>
    <div class="page">
        {header}
        <p class="hint">
            Turn a mode on and it adds or removes cards by the clock
            and by what is live. Anything it does not mention stays
            the way you set it on Scores. A night game can take the
            whole screen while it is live. So can the last game a
            mode leaves scrolling, for the NFL, college football,
            MLB, and the NBA.
        </p>
        {error_html}
        {cards}
        <div class="card">
            <div class="card-title">Your modes</div>
            <p class="hint">
                Build a schedule of your own. Leave the days blank
                to use every day. Leave the times blank to use the
                whole day.
            </p>
            {yours}
            {_create_form()}
        </div>
    </div>
</body>
</html>
    """


def _mode_card(mode, settings, removable=False):
    checked = " checked" if mode.get("enabled") else ""
    summary = mode.get("summary") or describe_mode(mode)
    remove = ""
    if removable:
        remove = f"""
        <form method="POST" action="/modes/delete">
            <input type="hidden" name="mode_id" value="{escape(mode["id"], quote=True)}">
            <button class="secondary-button" type="submit">Remove</button>
        </form>
        """
    return f"""
    <div class="card">
        <form method="POST" action="/modes/toggle" data-autosave="1">
            <input type="hidden" name="mode_id" value="{escape(mode["id"], quote=True)}">
            <label class="live-filter">
                <input type="checkbox" name="enabled" value="on"{checked}>
                <span>{escape(mode["name"])}</span>
            </label>
            <p class="hint">{escape(summary)}</p>
            <p class="hint">{escape(status_line(mode, settings))}</p>
        </form>
        {remove}
    </div>
    """


def _create_form():
    days = "".join(
        f"""
        <label class="live-filter">
            <input type="checkbox" name="day" value="{day}">
            <span>{DAY_NAMES[day]}</span>
        </label>
        """
        for day in DAY_ORDER
    )
    sports = "".join(
        f"""
        <label class="live-filter">
            <input type="checkbox" name="sport" value="{escape(key, quote=True)}">
            <span>{escape(label)}</span>
        </label>
        """
        for key, label in SPORT_CHOICES
    )
    return f"""
    <form method="POST" action="/modes/save">
        <label class="field-label" for="mode_name">Name</label>
        <input class="search-input" id="mode_name" name="name" maxlength="40" required>
        <p class="hint">Days</p>
        <div class="filter-row">{days}</div>
        <div class="filter-row">
            <label class="field-label" for="mode_start">From</label>
            <input class="search-input" id="mode_start" name="start" type="time">
            <label class="field-label" for="mode_end">Until</label>
            <input class="search-input" id="mode_end" name="end" type="time">
        </div>
        <p class="hint">Show</p>
        <div class="filter-row">{sports}</div>
        <p class="hint">Keep these stages</p>
        <div class="filter-row">
            <label class="live-filter">
                <input type="checkbox" name="phase" value="pregame" checked>
                <span>Previews</span>
            </label>
            <label class="live-filter">
                <input type="checkbox" name="phase" value="live" checked>
                <span>Live</span>
            </label>
            <label class="live-filter">
                <input type="checkbox" name="phase" value="final">
                <span>Finals</span>
            </label>
        </div>
        <div class="filter-row">
            <label class="field-label" for="mode_live_after">Later games start at</label>
            <input class="search-input" id="mode_live_after" name="live_only_after" type="time">
        </div>
        <p class="hint">
            Games that kick off at that time or later stay off
            until they are live. Leave it blank to show every preview.
        </p>
        <div class="filter-row">
            <label class="field-label" for="mode_focus_after">Fill the screen after</label>
            <input class="search-input" id="mode_focus_after" name="focus_after" type="time">
        </div>
        <p class="hint">
            A live NFL, college, NBA, or MLB game that starts then
            takes the whole board. Leave it blank to keep scrolling.
        </p>
        <label class="live-filter">
            <input type="checkbox" name="favorites_only" value="on">
            <span>Favorite teams only</span>
        </label>
        <label class="live-filter">
            <input type="checkbox" name="hide_outside" value="on">
            <span>Take these off the board outside these hours</span>
        </label>
        <button class="primary-button" type="submit">Add mode</button>
    </form>
    """
