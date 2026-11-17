"""Message designer. The preview is the 384x32 board."""

from html import escape

from common.message import BOARD_HEIGHT, BOARD_WIDTH, message_token


def _checked(value):
    return "checked" if value else ""


def _item_card(item):
    item_id = escape(item["id"], quote=True)
    x = int(item["x"])
    y = int(item["y"])
    kind = item["kind"]
    shared = f"""
        <input type="hidden" name="item" value="{item_id}">
        <input type="hidden" name="kind_{item_id}" value="{escape(kind, quote=True)}">
        <div class="message-position">
            <label>X
                <input class="number-input" data-axis="x" type="number"
                    name="x_{item_id}" min="0" max="1600" value="{x}">
            </label>
            <label>Y
                <input class="number-input" data-axis="y" type="number"
                    name="y_{item_id}" min="0" max="{BOARD_HEIGHT - 1}" value="{y}">
            </label>
        </div>
        <div class="message-nudge">
            <button type="button" data-nudge="x" data-step="-1">Left</button>
            <button type="button" data-nudge="x" data-step="1">Right</button>
            <button type="button" data-nudge="y" data-step="-1">Up</button>
            <button type="button" data-nudge="y" data-step="1">Down</button>
        </div>
        <button type="button" class="quiet-button quiet-button-danger" data-remove-item>
            Remove
        </button>
    """
    if kind == "image":
        image_id = escape(item["image"], quote=True)
        return f"""
        <div class="card message-item">
            <div class="card-title">Image</div>
            <img class="message-thumb" alt="" src="/messages/image/{image_id}.png">
            <input type="hidden" name="image_{item_id}" value="{image_id}">
            {shared}
        </div>
        """
    text = escape(item.get("text") or "", quote=True)
    color = escape(item.get("color") or "#ffffff", quote=True)
    font = item.get("font") or "5x7"
    large = "selected" if font != "4x5" else ""
    small = "selected" if font == "4x5" else ""
    return f"""
    <div class="card message-item">
        <div class="card-title">Text</div>
        <label class="field-label" for="text_{item_id}">Text</label>
        <input class="search-input" id="text_{item_id}" name="text_{item_id}"
            type="text" maxlength="64" value="{text}" autocomplete="off">
        <div class="message-style">
            <label>Color
                <input type="color" name="color_{item_id}" value="{color}">
            </label>
            <label>Size
                <select class="select-input" name="font_{item_id}">
                    <option value="5x7" {large}>Large</option>
                    <option value="4x5" {small}>Small</option>
                </select>
            </label>
        </div>
        {shared}
    </div>
    """


def render_message_page(styles, header, message, images, error=""):
    token = escape(message_token(message), quote=True)
    speed = int(message["speed"])
    background = escape(message["background"], quote=True)
    scroll = bool(message["scroll"])
    speed_hidden = "" if scroll else " hidden"
    error_html = ""
    if error:
        error_html = f'<p class="message-error">{escape(error)}</p>'
    cards = "".join(_item_card(item) for item in message["items"])
    if not cards:
        cards = '<p class="hint" id="message-empty">Add text or an image. Nothing is on the board yet.</p>'
    library = ""
    for image_id in images:
        safe = escape(image_id, quote=True)
        library += f"""
        <div class="message-library-item">
            <img alt="" src="/messages/image/{safe}.png">
            <button type="button" class="quiet-button" data-place-image="{safe}">Place</button>
            <form method="POST" action="/messages/image/delete">
                <input type="hidden" name="image" value="{safe}">
                <button class="quiet-button quiet-button-danger" type="submit">Delete</button>
            </form>
        </div>
        """
    if not library:
        library = '<p class="hint">Uploaded pictures show up here.</p>'

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>GameLine Pro Messages</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    {styles}
</head>
<body>
    <div class="page">
        {header}
        {error_html}
        <form method="POST" action="/messages" data-autosave="1" id="message-form">
            <p class="hint" data-autosave-error hidden></p>
            <div class="card">
                <div class="message-stage" id="message-stage">
                    <img
                        id="message-play"
                        alt="Message on the board"
                        data-message-preview
                        data-scroll="{"1" if scroll else "0"}"
                        data-speed="{speed}"
                        src="/messages/preview.png?play=1&amp;v={token}"
                    >
                </div>
                <p class="hint">This is the whole board. Letters use the scoreboard capitals.</p>
            </div>

            <div class="card">
                <div class="card-title">Layout</div>
                <div class="message-design">
                    <img
                        alt="Every pixel in the message"
                        data-message-preview
                        src="/messages/preview.png?v={token}"
                    >
                </div>
                <p class="hint">Drag sideways to see a long message. X and Y are board pixels.</p>
            </div>

            <div class="card">
                <label class="game-row">
                    <input type="checkbox" name="enabled" value="1" {_checked(message["enabled"])}>
                    <div class="game-info">
                        <div class="matchup">Show on the board</div>
                        <div class="details">Replaces the scores and focus. Alerts still interrupt it.</div>
                    </div>
                </label>
            </div>

            <div class="card">
                <label class="game-row">
                    <input type="checkbox" name="scroll" value="1" {_checked(scroll)}>
                    <div class="game-info">
                        <div class="matchup">Scroll</div>
                        <div class="details">Off keeps the design still in the board window.</div>
                    </div>
                </label>
                <div class="control" id="message-speed"{speed_hidden}>
                    <div class="control-top">
                        <label for="message_speed">Speed</label>
                        <input class="number-input" type="number" id="message_speed"
                            name="speed" min="5" max="120" step="1" value="{speed}">
                    </div>
                    <input type="range" id="message_speed_slider" min="5" max="120" step="1"
                        value="{speed}"
                        oninput="message_speed.value = this.value">
                    <p class="hint">Pixels per second. 30 matches the score ticker.</p>
                </div>
            </div>

            <div class="card">
                <label class="field-label" for="message_background">Background</label>
                <input type="color" id="message_background" name="background" value="{background}">
            </div>

            <div id="message-items">
                {cards}
            </div>
            <button class="ghost-button" type="button" id="message-add-text">Add text</button>
        </form>

        <div class="card">
            <div class="card-title">Images</div>
            <form method="POST" action="/messages/upload" enctype="multipart/form-data">
                <label class="ghost-button message-upload">
                    Upload image
                    <input type="file" name="image" accept="image/png,image/jpeg,image/webp,image/gif" required onchange="this.form.submit()">
                </label>
            </form>
            <div class="message-library">{library}</div>
        </div>
    </div>
    <script>
    (function () {{
      var form = document.getElementById("message-form");
      var list = document.getElementById("message-items");
      var play = document.getElementById("message-play");
      var speedBox = document.getElementById("message-speed");

      function scrolling() {{
        var box = form.querySelector("[name=scroll]");
        return !!(box && box.checked);
      }}

      function syncSpeed() {{
        if (speedBox) speedBox.hidden = !scrolling();
        if (play) play.dataset.scroll = scrolling() ? "1" : "0";
        var speed = document.getElementById("message_speed");
        if (play && speed) play.dataset.speed = speed.value || "30";
      }}

      function arm(img) {{
        if (!img || img.id !== "message-play") return;
        var speed = Number(img.dataset.speed) || 30;
        if (img.dataset.scroll !== "1" || !img.naturalWidth) {{
          img.style.animation = "none";
          img.style.width = "100%";
          return;
        }}
        img.style.width = (img.naturalWidth / {BOARD_WIDTH} * 100) + "%";
        img.style.animation = "message-marquee " + ((img.naturalWidth / 2) / speed) + "s linear infinite";
      }}

      function refreshPreview() {{
        var stamp = Date.now();
        document.querySelectorAll("[data-message-preview]").forEach(function (img) {{
          img.onload = function () {{ arm(img); }};
          var play = img.id === "message-play" ? "1" : "0";
          img.src = "/messages/preview.png?play=" + play + "&t=" + stamp;
        }});
      }}

      function newId() {{
        var hex = "";
        for (var i = 0; i < 8; i += 1) {{
          hex += Math.floor(Math.random() * 16).toString(16);
        }}
        return hex;
      }}

      function nextX() {{
        var inputs = list.querySelectorAll("[data-axis=x]");
        if (!inputs.length) return 4;
        return Math.min(1600, Number(inputs[inputs.length - 1].value || 0) + 48);
      }}

      function clearEmpty() {{
        var note = document.getElementById("message-empty");
        if (note) note.remove();
      }}

      function addText() {{
        clearEmpty();
        var id = newId();
        var x = nextX();
        var card = document.createElement("div");
        card.className = "card message-item";
        card.innerHTML =
          '<div class="card-title">Text</div>' +
          '<label class="field-label" for="text_' + id + '">Text</label>' +
          '<input class="search-input" id="text_' + id + '" name="text_' + id + '" type="text" maxlength="64" value="" autocomplete="off">' +
          '<div class="message-style">' +
            '<label>Color <input type="color" name="color_' + id + '" value="#ffffff"></label>' +
            '<label>Size <select class="select-input" name="font_' + id + '">' +
              '<option value="5x7" selected>Large</option>' +
              '<option value="4x5">Small</option>' +
            '</select></label>' +
          '</div>' +
          '<input type="hidden" name="item" value="' + id + '">' +
          '<input type="hidden" name="kind_' + id + '" value="text">' +
          '<div class="message-position">' +
            '<label>X <input class="number-input" data-axis="x" type="number" name="x_' + id + '" min="0" max="1600" value="' + x + '"></label>' +
            '<label>Y <input class="number-input" data-axis="y" type="number" name="y_' + id + '" min="0" max="31" value="12"></label>' +
          '</div>' +
          '<div class="message-nudge">' +
            '<button type="button" data-nudge="x" data-step="-1">Left</button>' +
            '<button type="button" data-nudge="x" data-step="1">Right</button>' +
            '<button type="button" data-nudge="y" data-step="-1">Up</button>' +
            '<button type="button" data-nudge="y" data-step="1">Down</button>' +
          '</div>' +
          '<button type="button" class="quiet-button quiet-button-danger" data-remove-item>Remove</button>';
        list.appendChild(card);
        if (window.autosaveForm) window.autosaveForm(form, 0);
        window.setTimeout(refreshPreview, 800);
      }}

      function placeImage(imageId) {{
        clearEmpty();
        var id = newId();
        var x = nextX();
        var card = document.createElement("div");
        card.className = "card message-item";
        card.innerHTML =
          '<div class="card-title">Image</div>' +
          '<img class="message-thumb" alt="" src="/messages/image/' + imageId + '.png">' +
          '<input type="hidden" name="image_' + id + '" value="' + imageId + '">' +
          '<input type="hidden" name="item" value="' + id + '">' +
          '<input type="hidden" name="kind_' + id + '" value="image">' +
          '<div class="message-position">' +
            '<label>X <input class="number-input" data-axis="x" type="number" name="x_' + id + '" min="0" max="1600" value="' + x + '"></label>' +
            '<label>Y <input class="number-input" data-axis="y" type="number" name="y_' + id + '" min="0" max="31" value="0"></label>' +
          '</div>' +
          '<div class="message-nudge">' +
            '<button type="button" data-nudge="x" data-step="-1">Left</button>' +
            '<button type="button" data-nudge="x" data-step="1">Right</button>' +
            '<button type="button" data-nudge="y" data-step="-1">Up</button>' +
            '<button type="button" data-nudge="y" data-step="1">Down</button>' +
          '</div>' +
          '<button type="button" class="quiet-button quiet-button-danger" data-remove-item>Remove</button>';
        list.appendChild(card);
        if (window.autosaveForm) window.autosaveForm(form, 0);
        window.setTimeout(refreshPreview, 800);
      }}

      document.getElementById("message-add-text").addEventListener("click", addText);

      document.addEventListener("click", function (event) {{
        var place = event.target.closest("[data-place-image]");
        if (place) {{
          placeImage(place.getAttribute("data-place-image"));
          return;
        }}
        var nudge = event.target.closest("[data-nudge]");
        if (nudge) {{
          var item = nudge.closest(".message-item");
          var input = item && item.querySelector('[data-axis="' + nudge.getAttribute("data-nudge") + '"]');
          if (!input) return;
          var next = Number(input.value || 0) + Number(nudge.getAttribute("data-step"));
          var min = Number(input.min || 0);
          var max = Number(input.max || 0);
          input.value = String(Math.max(min, Math.min(max, next)));
          input.dispatchEvent(new Event("input", {{ bubbles: true }}));
          window.setTimeout(refreshPreview, 800);
          return;
        }}
        var remove = event.target.closest("[data-remove-item]");
        if (remove && list.contains(remove)) {{
          remove.closest(".message-item").remove();
          if (!list.querySelector(".message-item") && !document.getElementById("message-empty")) {{
            list.insertAdjacentHTML("beforeend", '<p class="hint" id="message-empty">Add text or an image. Nothing is on the board yet.</p>');
          }}
          if (window.autosaveForm) window.autosaveForm(form, 0);
          window.setTimeout(refreshPreview, 800);
        }}
      }});

      form.addEventListener("change", function () {{
        syncSpeed();
        window.setTimeout(refreshPreview, 800);
      }});
      form.addEventListener("input", function (event) {{
        if (event.target && (event.target.id === "message_speed" || event.target.id === "message_speed_slider")) {{
          var speed = document.getElementById("message_speed");
          var slider = document.getElementById("message_speed_slider");
          if (event.target === slider && speed) speed.value = slider.value;
          if (event.target === speed && slider) slider.value = speed.value;
          if (play && speed) play.dataset.speed = speed.value || "30";
          arm(play);
        }}
        window.setTimeout(refreshPreview, 800);
      }});

      document.querySelectorAll("[data-message-preview]").forEach(function (img) {{
        img.addEventListener("load", function () {{ arm(img); }});
      }});
      syncSpeed();
      arm(play);
    }})();
    </script>
</body>
</html>
    """
