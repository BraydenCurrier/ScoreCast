from __future__ import annotations

from html import escape

from flask import jsonify, redirect, request, session

from common.users import UserError, create_user, has_users
from setup.captive import captive_portal_response, is_captive_probe
from setup.network import NetworkError, classify_security, decorate_network
from setup.runtime import (
    advance_to_homescreen,
    join_home_wifi,
    request_wifi_rescan,
    setup_status_payload,
    stop_setup_hotspot,
)
from setup.state import (
    PHASE_ACCOUNT,
    PHASE_CONNECTING,
    PHASE_HOMESCREEN,
    current_setup_path,
    load_setup_state,
    mark_setup_complete,
    setup_is_complete,
)


def _network_rows(networks, selected: str) -> str:
    rows = []
    ordered = [decorate_network(raw) for raw in networks or [] if raw.get("ssid")]
    ordered.sort(key=lambda item: int(item.get("signal") or 0), reverse=True)
    for item in ordered:
        name = escape(str(item.get("ssid") or ""), quote=True)
        if not name:
            continue
        checked = "checked" if selected == item.get("ssid") else ""
        needs = "1" if item.get("needs_password") else "0"
        security = escape(str(item.get("security") or ""), quote=True)
        label = escape(str(item.get("security_label") or "Open"))
        quality = escape(str(item.get("quality") or "Weak"))
        bars = int(item.get("bars") or 0)
        lock = ""
        if item.get("needs_password") or item.get("key_mgmt") == "enterprise":
            lock = (
                '<span class="wifi-lock" aria-hidden="true">'
                '<svg viewBox="0 0 24 24" width="16" height="16">'
                '<path fill="currentColor" d="M7 10V8a5 5 0 0 1 10 0v2h1a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h1zm2 0h6V8a3 3 0 0 0-6 0v2z"/>'
                "</svg></span>"
            )
        rows.append(
            f"""
            <label class="wifi-choice">
                <input type="radio" name="ssid" value="{name}" {checked}
                    data-needs-password="{needs}" data-security="{security}">
                <span class="wifi-bars" data-bars="{bars}" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
                <span class="wifi-copy">
                    <span class="wifi-name">{name}</span>
                    <span class="wifi-meta">{label} · {quality}</span>
                </span>
                {lock}
            </label>
            """
        )
    return "".join(rows)


def _wifi_page_body(state, error: str, selected: str) -> str:
    networks = state.get("networks") or []
    rows = _network_rows(networks, selected)
    scan_status = str(state.get("scan_status") or "idle")
    scan_error = str(state.get("scan_error") or "")
    hotspot = escape(str(state.get("ssid") or "GameLine"))
    messages = []
    if error:
        messages.append(f"<div class='error' role='alert'>{escape(error)}</div>")
    elif scan_error and scan_status == "failed":
        messages.append(f"<div class='error' role='alert'>{escape(scan_error)}</div>")

    if scan_status == "scanning":
        list_note = '<p class="auth-hint wifi-status" id="wifi-status">Scanning for nearby networks…</p>'
        refresh_meta = '<meta http-equiv="refresh" content="3">'
    elif not rows and scan_status == "failed":
        list_note = '<p class="auth-hint wifi-status" id="wifi-status">The scan did not finish. Tap Refresh Networks.</p>'
        refresh_meta = ""
    elif not rows:
        list_note = (
            '<p class="auth-hint wifi-status" id="wifi-status">'
            "No networks were found. Move the display closer to the router, then tap Refresh Networks. "
            "Hidden networks can be entered below."
            "</p>"
        )
        refresh_meta = ""
    else:
        list_note = '<p class="auth-hint wifi-status" id="wifi-status"></p>'
        refresh_meta = ""

    return f"""
        {refresh_meta}
        <div class="auth-intro">
            <div class="brand-lockup">
                <div class="brand-mark" aria-hidden="true">GL</div>
                <div>
                    <div class="brand-name">GameLine Pro</div>
                    <div class="brand-tag">Connect to home Wi-Fi</div>
                </div>
            </div>
        </div>
        <div class="card login-card">
            <p class="auth-hint">
                You are on <strong>{hotspot}</strong>. Choose the home network
                this display should use. A password is only needed when the
                network is locked.
            </p>
            {''.join(messages)}
            <form method="POST" action="/setup/wifi/scan">
                <button class="wifi-refresh" type="submit">Refresh Networks</button>
            </form>
            {list_note}
            <form method="POST" id="wifi-form">
                <div class="wifi-list">
                    {rows}
                    <label class="wifi-choice">
                        <input type="radio" name="ssid" value="__other__" data-needs-password="1" data-security="">
                        <span class="wifi-copy">
                            <span class="wifi-name">Other network</span>
                            <span class="wifi-meta">Hidden, or not in the list</span>
                        </span>
                    </label>
                </div>
                <div id="other-block" hidden>
                    <label class="field-label" for="other_ssid">Network name</label>
                    <input class="auth-input" id="other_ssid" name="other_ssid" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="Network name">
                    <label class="field-label" for="manual_security">Security</label>
                    <select class="auth-input" id="manual_security" name="manual_security">
                        <option value="wpa-psk" selected>WPA2 / WPA3 (most homes)</option>
                        <option value="sae">WPA3 only</option>
                        <option value="open">Open</option>
                        <option value="owe">Enhanced Open</option>
                        <option value="wep">WEP</option>
                    </select>
                </div>
                <input type="hidden" name="security" id="security-kind" value="">
                <input type="hidden" name="hidden" id="hidden-flag" value="0">
                <div id="password-block">
                    <label class="field-label" for="wifi_password">Password</label>
                    <div class="password-row">
                        <input class="auth-input" id="wifi_password" type="password" name="password" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="Wi-Fi password">
                        <button class="password-toggle" id="toggle-password" type="button" aria-pressed="false" aria-controls="wifi_password">Show</button>
                    </div>
                </div>
                <button class="save-button" id="connect-button" type="submit">Connect</button>
            </form>
        </div>
        <script>
        (function () {{
          var form = document.getElementById("wifi-form");
          var status = document.getElementById("wifi-status");
          var other = document.getElementById("other-block");
          var otherName = document.getElementById("other_ssid");
          var manual = document.getElementById("manual_security");
          var hiddenFlag = document.getElementById("hidden-flag");
          var security = document.getElementById("security-kind");
          var passwordBlock = document.getElementById("password-block");
          var password = document.getElementById("wifi_password");
          var toggle = document.getElementById("toggle-password");
          var button = document.getElementById("connect-button");

          function selected() {{
            return document.querySelector('input[name="ssid"]:checked');
          }}

          function needsPassword(choice) {{
            if (!choice) return true;
            if (choice.value === "__other__") {{
              var kind = manual.value;
              return kind !== "open" && kind !== "owe";
            }}
            return choice.getAttribute("data-needs-password") === "1";
          }}

          function sync() {{
            var choice = selected();
            var otherMode = !!(choice && choice.value === "__other__");
            other.hidden = !otherMode;
            hiddenFlag.value = otherMode ? "1" : "0";
            if (choice && !otherMode) {{
              security.value = choice.getAttribute("data-security") || "";
            }} else if (otherMode) {{
              security.value = manual.value;
            }}
            var needs = needsPassword(choice);
            passwordBlock.hidden = !needs;
            if (!needs) password.value = "";
          }}

          document.querySelectorAll('input[name="ssid"]').forEach(function (input) {{
            input.addEventListener("change", sync);
          }});
          manual.addEventListener("change", sync);
          sync();

          toggle.addEventListener("click", function () {{
            var show = password.type === "password";
            password.type = show ? "text" : "password";
            toggle.textContent = show ? "Hide" : "Show";
            toggle.setAttribute("aria-pressed", show ? "true" : "false");
          }});

          form.addEventListener("submit", function (event) {{
            var choice = selected();
            if (!choice) {{
              event.preventDefault();
              status.textContent = "Choose a Wi-Fi network.";
              return;
            }}
            if (choice.value === "__other__" && !otherName.value.trim()) {{
              event.preventDefault();
              status.textContent = "Enter the network name.";
              return;
            }}
            sync();
            if (!passwordBlock.hidden && !password.value) {{
              event.preventDefault();
              status.textContent = "Enter the Wi-Fi password.";
              return;
            }}
            button.disabled = true;
            button.textContent = "Connecting…";
            status.textContent = "Connecting. This phone will disconnect from the setup network.";
          }});

          var scanning = {str(scan_status == "scanning").lower()};
          function poll() {{
            fetch("/setup/status", {{ credentials: "same-origin" }})
              .then(function (response) {{ return response.json(); }})
              .then(function (data) {{
                if (data.scan_status === "scanning") {{
                  status.textContent = "Scanning for nearby networks. This phone may disconnect for a few seconds. Rejoin the setup network if this page stops loading.";
                  setTimeout(poll, 1000);
                  return;
                }}
                if (scanning) window.location = "/setup/wifi";
              }})
              .catch(function () {{ setTimeout(poll, 1200); }});
          }}
          if (scanning) poll();
        }})();
        </script>
    """


def register_setup_routes(app, *, render_auth_page, establish_session):
    def setup_page(title, body):
        return render_auth_page(title, body)

    @app.before_request
    def gate_first_run_setup():
        if setup_is_complete():
            return None

        path = request.path
        if path.startswith("/static"):
            return None
        if path.startswith("/setup"):
            return None
        if is_captive_probe():
            return captive_portal_response()

        return redirect(current_setup_path())

    @app.route("/setup/status")
    def setup_status():
        return jsonify(setup_status_payload())

    @app.route("/setup")
    def setup_index():
        return redirect(current_setup_path())

    @app.route("/setup/wifi/scan", methods=["POST"])
    def setup_wifi_scan():
        if setup_is_complete():
            return redirect("/games")
        request_wifi_rescan()
        if request.accept_mimetypes.best == "application/json" or request.is_json:
            return jsonify({"scan_status": "scanning"})
        return redirect("/setup/wifi")

    @app.route("/setup/wifi", methods=["GET", "POST"])
    def setup_wifi():
        if setup_is_complete():
            return redirect("/games")

        state = load_setup_state()
        if state.get("phase") in {PHASE_ACCOUNT, PHASE_HOMESCREEN, PHASE_CONNECTING}:
            return redirect(current_setup_path(state))

        error = str(state.get("error") or "")
        selected = request.form.get("ssid") or ""

        if request.method == "POST":
            ssid = (request.form.get("ssid") or "").strip()
            other = (request.form.get("other_ssid") or "").strip()
            hidden = request.form.get("hidden") == "1" or ssid == "__other__"
            if ssid == "__other__":
                ssid = other
            password = request.form.get("password") or ""
            security = (request.form.get("security") or "").strip()
            if hidden:
                security = (request.form.get("manual_security") or security or "wpa-psk").strip()
            elif not security:
                for item in state.get("networks") or []:
                    if str(item.get("ssid") or "") == ssid:
                        security = str(item.get("security") or "")
                        break
            profile = classify_security(security if ssid else "")
            if not ssid:
                error = "Choose a Wi-Fi network."
            elif profile.get("error"):
                error = str(profile["error"])
            elif profile.get("needs_password") and password == "":
                error = "This network needs a password."
            else:
                try:
                    join_home_wifi(ssid, password, security=security, hidden=hidden)
                except NetworkError as exc:
                    error = str(exc)
                else:
                    return redirect("/setup/connecting")

        state = load_setup_state()
        return setup_page("Connect Wi-Fi", _wifi_page_body(state, error, selected))

    @app.route("/setup/connecting")
    def setup_connecting():
        if setup_is_complete():
            return redirect("/games")

        body = """
            <div class="auth-intro">
                <div class="brand-lockup">
                    <div class="brand-mark" aria-hidden="true">GL</div>
                    <div>
                        <div class="brand-name">GameLine Pro</div>
                        <div class="brand-tag">Joining Wi-Fi</div>
                    </div>
                </div>
            </div>
            <div class="card login-card">
                <p class="auth-hint">
                    This display is joining the network. Your phone may drop
                    off the setup hotspot. If it does, rejoin the setup
                    network when something goes wrong, or scan the QR code on
                    the board after it connects.
                </p>
                <p class="auth-hint wifi-status" id="setup-wait">Connecting…</p>
            </div>
            <script>
            (function poll() {
              fetch("/setup/status", { credentials: "same-origin" })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                  var wait = document.getElementById("setup-wait");
                  if (data.phase === "hotspot") {
                    window.location = "/setup/wifi";
                    return;
                  }
                  if (data.phase === "account") {
                    window.location = "/setup/account";
                    return;
                  }
                  if (data.phase === "homescreen") {
                    window.location = "/setup/homescreen";
                    return;
                  }
                  if (data.phase === "starting") {
                    wait.textContent = "Checking the network connection…";
                  } else if (data.error) {
                    wait.textContent = data.error;
                  } else {
                    wait.textContent = "Connecting…";
                  }
                  setTimeout(poll, 1000);
                })
                .catch(function () { setTimeout(poll, 1200); });
            })();
            </script>
        """
        return setup_page("Joining Wi-Fi", body)

    @app.route("/setup/account", methods=["GET", "POST"])
    def setup_account():
        if has_users():
            if not setup_is_complete():
                advance_to_homescreen()
                return redirect("/setup/homescreen")
            return redirect("/games")

        error = ""
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            if password != confirm_password:
                error = "Passwords do not match."
            else:
                try:
                    user = create_user(username, password, role="root")
                except UserError as exc:
                    error = str(exc)
                else:
                    establish_session(user)
                    session.pop("setup_pending", None)
                    advance_to_homescreen()
                    return redirect("/setup/homescreen")

        error_html = f"<div class='error'>{escape(error)}</div>" if error else ""
        body = f"""
            <div class="auth-intro">
                <div class="brand-lockup">
                    <div class="brand-mark" aria-hidden="true">GL</div>
                    <div>
                        <div class="brand-name">GameLine Pro</div>
                        <div class="brand-tag">Create the root profile</div>
                    </div>
                </div>
            </div>
            <div class="card login-card">
                <p class="auth-hint">
                    This first account can add other people later.
                </p>
                {error_html}
                <form method="POST">
                    <label class="field-label" for="root_username">Username</label>
                    <input class="auth-input" id="root_username" type="text" name="username" autocomplete="username" autofocus value="{escape(request.form.get('username', ''), quote=True)}">
                    <label class="field-label" for="root_password">Password</label>
                    <input class="auth-input" id="root_password" type="password" name="password" placeholder="At least 8 characters" autocomplete="new-password">
                    <label class="field-label" for="root_password_confirm">Confirm password</label>
                    <input class="auth-input" id="root_password_confirm" type="password" name="confirm_password" placeholder="Confirm password" autocomplete="new-password">
                    <button class="save-button" type="submit">Create profile</button>
                </form>
            </div>
        """
        return setup_page("Create profile", body)

    @app.route("/setup/homescreen", methods=["GET", "POST"])
    def setup_homescreen():
        if setup_is_complete():
            return redirect("/games")

        if request.method == "POST":
            mark_setup_complete()
            stop_setup_hotspot()
            return redirect("/games")

        body = """
            <div class="auth-intro">
                <div class="brand-lockup">
                    <div class="brand-mark" aria-hidden="true">GL</div>
                    <div>
                        <div class="brand-name">GameLine Pro</div>
                        <div class="brand-tag">Add to your home screen</div>
                    </div>
                </div>
            </div>
            <div class="card login-card">
                <p class="auth-hint">
                    The board is showing a QR code for this dashboard. Keep
                    using that address, then pin it like an app.
                </p>
                <h3 class="setup-step-title">iPhone</h3>
                <ol class="setup-steps">
                    <li>Open this page in Safari (not Chrome).</li>
                    <li>Tap the Share button.</li>
                    <li>Tap <strong>Add to Home Screen</strong>, then Add.</li>
                </ol>
                <h3 class="setup-step-title">Android</h3>
                <ol class="setup-steps">
                    <li>Open this page in Chrome.</li>
                    <li>Tap the menu (three dots).</li>
                    <li>Tap <strong>Add to Home screen</strong> or Install app.</li>
                </ol>
                <form method="POST">
                    <button class="save-button" type="submit">Done — open GameLine</button>
                </form>
            </div>
        """
        return setup_page("Add to Home Screen", body)
