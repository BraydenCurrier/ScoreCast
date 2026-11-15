"""The clock theme picker. One page, every team, plus Christmas."""

from html import escape

from common.clock_themes import season_cards, team_field_color
from common.team_clock import LEAGUES, favorite_themes, league_label, themes_for_league


def _hex(color):
    red, green, blue = (int(color[0]), int(color[1]), int(color[2]))
    return f"#{red:02x}{green:02x}{blue:02x}"


def _swatch_style(theme):
    scene = theme.get("scene")
    if theme.get("swatch"):
        return theme["swatch"]
    if scene == "off":
        return "background:#0b1120;"
    primary = theme.get("primary") or (20, 32, 56)
    return f"background:{_hex(team_field_color(primary))};"


def cards_for(league, settings):
    """Picker cards for one league, Featured included."""
    league = str(league or "featured").strip().lower()
    if league == "featured":
        cards = [
            {
                "id": "off",
                "name": "Solid background",
                "detail": "No picture behind the clock",
                "search": "solid background none off",
                "scene": "off",
            },
        ]
        cards.extend(season_cards())
        for theme in favorite_themes(settings):
            cards.append(_team_card(theme, settings, favorite=True))
        return cards
    return [
        _team_card(theme, settings)
        for theme in themes_for_league(league)
    ]


def _team_card(theme, settings=None, favorite=False):
    from common.team_clock import logo_source

    source = logo_source(
        theme.get("league"),
        theme.get("abbreviation"),
        settings,
    )
    label = league_label(theme.get("league"))
    abbreviation = theme.get("abbreviation") or ""
    name = theme.get("name") or abbreviation
    detail = label
    if name.upper() != abbreviation and abbreviation:
        detail = f"{label} · {abbreviation}"
    if favorite and detail:
        detail = f"Favorite · {detail}"
    search = f"{name} {abbreviation} {label} {theme.get('league') or ''}".lower()
    card = dict(theme)
    card["detail"] = detail
    card["search"] = search
    if source is not None:
        logo_league, logo_team, variant = source
        card["logo"] = (
            f"/logo-preview/{logo_league}/{logo_team}/{variant}"
        )
    return card


def render_clock_themes_page(styles, header, settings, league, active_id):
    league = str(league or "featured").strip().lower()
    if league not in {key for key, _label in LEAGUES}:
        league = "featured"
    active_id = str(active_id or "off")
    cards = cards_for(league, settings)
    active = next((card for card in cards if card["id"] == active_id), None)
    if active is None:
        from common.clock_themes import theme_by_id

        theme = theme_by_id(active_id)
        if theme is None:
            active = {
                "id": "off",
                "name": "Solid background",
                "detail": "No picture behind the clock",
            }
        else:
            active = _team_card(theme, settings) if theme.get("scene") == "team" else {
                "id": theme["id"],
                "name": theme["name"],
                "detail": theme.get("detail") or "",
                "swatch": theme.get("swatch") or "",
            }

    chips = []
    for key, label in LEAGUES:
        selected = " is-on" if key == league else ""
        pressed = "true" if key == league else "false"
        chips.append(
            f'<a class="theme-chip{selected}" href="/clock-themes?league={escape(key, quote=True)}" '
            f'aria-pressed="{pressed}">{escape(label)}</a>'
        )

    buttons = []
    for card in cards:
        selected = card["id"] == active_id
        classes = "theme-card is-selected" if selected else "theme-card"
        mark = "On the clock" if selected else card.get("detail") or ""
        if card.get("logo"):
            face = (
                f'<img class="theme-swatch-logo" src="{escape(card["logo"], quote=True)}" '
                f'alt="" width="40" height="40" loading="lazy" decoding="async">'
            )
        elif card.get("abbreviation"):
            face = (
                f'<span class="theme-swatch-mark">{escape(card["abbreviation"])}</span>'
            )
        else:
            face = ""
        buttons.append(
            f"""
            <button
                class="{classes}"
                type="submit"
                name="theme_id"
                value="{escape(card["id"], quote=True)}"
                data-search="{escape(card.get("search") or card["name"], quote=True)}"
                aria-pressed="{"true" if selected else "false"}"
            >
                <span class="theme-swatch" style="{_swatch_style(card)}">{face}</span>
                <span class="theme-card-copy">
                    <span class="theme-card-name">{escape(card["name"])}</span>
                    <span class="theme-card-meta">{escape(mark)}</span>
                </span>
            </button>
            """
        )

    if league == "featured":
        intro = "Christmas, a solid background, and your teams. Open a league to see every team."
    else:
        intro = f"{len(cards)} themes"

    preview_id = escape(active["id"], quote=True)
    empty_hidden = "" if not cards else " hidden"

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>GameLine Pro Clock themes</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    {styles}
</head>
<body>
    <div class="page">
        {header}
        <section class="theme-hero" aria-label="Theme on the clock">
            <img
                id="theme-preview"
                class="theme-preview"
                alt=""
                width="384"
                height="32"
                data-src="/clock-themes/preview.png?id={preview_id}"
                src="/clock-themes/preview.png?id={preview_id}&amp;phase=0"
            >
            <div class="theme-hero-name">{escape(active["name"])}</div>
            <div class="theme-hero-meta">{escape(active.get("detail") or "Behind the standby clock")}</div>
        </section>

        <div class="theme-chips" role="tablist">{''.join(chips)}</div>

        <input
            class="search-input theme-search"
            id="theme-search"
            type="search"
            placeholder="Search themes"
            oninput="filterClockThemes()"
        >
        <p class="hint theme-count" id="theme-count">{escape(intro)}</p>

        <form method="POST" action="/clock-themes/use">
            <input type="hidden" name="league" value="{escape(league, quote=True)}">
            <div class="theme-grid" id="theme-grid">
                {''.join(buttons)}
            </div>
            <div class="empty" id="theme-empty"{empty_hidden}>
                No themes match that search.
            </div>
        </form>
    </div>
    <script>
        function filterClockThemes() {{
            var input = document.getElementById("theme-search");
            var query = input ? input.value.toLowerCase().trim() : "";
            var shown = 0;
            document.querySelectorAll(".theme-card").forEach(function (card) {{
                var text = card.dataset.search || "";
                var match = !query || text.indexOf(query) !== -1;
                card.hidden = !match;
                if (match) shown += 1;
            }});
            var empty = document.getElementById("theme-empty");
            if (empty) empty.hidden = shown !== 0;
            var count = document.getElementById("theme-count");
            if (count) {{
                count.textContent = query
                    ? shown + (shown === 1 ? " theme" : " themes")
                    : {escape(intro)!r};
            }}
        }}

        (function () {{
            var frame = 0;
            window.setInterval(function () {{
                var image = document.getElementById("theme-preview");
                if (!image) return;
                frame += 1;
                image.src = image.dataset.src + "&phase=" + (frame * 0.16).toFixed(2);
            }}, 180);
        }})();
    </script>
</body>
</html>
    """
