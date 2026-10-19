from __future__ import annotations

from html import escape

from flask import jsonify, redirect, request, session

from common.users import UserError, create_user, has_users
from setup.captive import captive_portal_response, is_captive_probe
from setup.runtime import (
    advance_to_homescreen,
    join_home_wifi,
    setup_status_payload,
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
            if ssid == "__other__":
                ssid = other
            password = request.form.get("password") or ""
            if not ssid:
                error = "Choose a Wi-Fi network."
            else:
                join_home_wifi(ssid, password)
                return redirect("/setup/connecting")

        networks = state.get("networks") or []
        options = []
        for item in networks:
            name = escape(str(item.get("ssid") or ""), quote=True)
            checked = "checked" if selected == item.get("ssid") else ""
            options.append(
                f"""
                <label class="wifi-choice">
                    <input type="radio" name="ssid" value="{name}" {checked}>
                    <span>
                        <span class="wifi-name">{name}</span>
                        <span class="wifi-meta">{escape(str(item.get('security') or 'Open'))}</span>
                    </span>
                </label>
                """
            )

        if not options:
            options.append(
                '<p class="auth-hint">No networks were cached. Type the name below.</p>'
            )

        error_html = f"<div class='error'>{escape(error)}</div>" if error else ""
        hotspot = escape(str(state.get("ssid") or "GameLine"))

        body = f"""
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
                    You are on <strong>{hotspot}</strong>. Pick the house Wi-Fi
                    this display should use. After it joins, look at the board
                    and scan the new QR code.
                </p>
                {error_html}
                <form method="POST">
                    <div class="wifi-list">
                        {''.join(options)}
                        <label class="wifi-choice">
                            <input type="radio" name="ssid" value="__other__">
                            <span>
                                <span class="wifi-name">Other network</span>
                                <span class="wifi-meta">Type the name</span>
                            </span>
                        </label>
                    </div>
                    <label class="field-label" for="other_ssid">Network name</label>
                    <input class="auth-input" id="other_ssid" name="other_ssid" placeholder="Optional">
                    <label class="field-label" for="wifi_password">Password</label>
                    <input class="auth-input" id="wifi_password" type="password" name="password" placeholder="Leave blank if open">
                    <button class="save-button" type="submit">Connect</button>
                </form>
            </div>
        """
        return setup_page("Connect Wi-Fi", body)

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
                    This display is joining your network. Your phone will drop
                    off the setup hotspot. Rejoin home Wi-Fi, then scan the QR
                    on the board.
                </p>
                <p class="auth-hint" id="setup-wait">Connecting…</p>
            </div>
            <script>
            (function poll() {
              fetch("/setup/status", { credentials: "same-origin" })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                  if (data.phase === "hotspot") {
                    window.location = "/setup/wifi";
                    return;
                  }
                  if (data.phase === "account" || data.phase === "homescreen") {
                    document.getElementById("setup-wait").textContent =
                      "Look at the board and scan the QR code.";
                    return;
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
