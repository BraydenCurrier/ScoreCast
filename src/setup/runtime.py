from __future__ import annotations

import threading
import traceback

from setup.display import render_setup_display
from setup.network import (
    NetworkError,
    connect_wifi,
    dashboard_url,
    default_route_ip,
    ensure_hotspot,
    has_upstream_ip,
    hotspot_ssid,
    publish_mdns,
    scan_wifi,
)
from setup.state import (
    PHASE_ACCOUNT,
    PHASE_CONNECTING,
    PHASE_HOMESCREEN,
    PHASE_HOTSPOT,
    PHASE_STARTING,
    load_setup_state,
    save_setup_state,
    setup_holds_display,
    setup_is_complete,
    should_run_first_setup,
)


_worker_lock = threading.Lock()
_started = False


def start_setup_if_needed() -> None:
    global _started

    with _worker_lock:
        if _started:
            return
        _started = True

    if not should_run_first_setup():
        return

    threading.Thread(
        target=_setup_boot_worker,
        daemon=True,
        name="gameline-setup",
    ).start()


def _setup_boot_worker() -> None:
    try:
        if has_upstream_ip():
            ip_address = default_route_ip()
            save_setup_state({
                "phase": PHASE_ACCOUNT,
                "error": "",
                "lan_ip": ip_address,
                "dashboard_url": dashboard_url(ip_address),
                "ssid": "",
            })
            publish_mdns(ip_address)
            return

        save_setup_state({"phase": PHASE_STARTING, "error": ""})
        networks = []
        try:
            networks = scan_wifi()
        except NetworkError:
            networks = []

        ssid = ensure_hotspot()
        save_setup_state({
            "phase": PHASE_HOTSPOT,
            "ssid": ssid,
            "error": "",
            "networks": networks,
            "lan_ip": "",
            "dashboard_url": f"http://192.168.4.1/",
        })
    except Exception as exc:
        traceback.print_exc()
        save_setup_state({
            "phase": PHASE_HOTSPOT,
            "ssid": hotspot_ssid(),
            "error": str(exc),
        })


def join_home_wifi(ssid: str, password: str) -> None:
    save_setup_state({
        "phase": PHASE_CONNECTING,
        "error": "",
    })

    def worker():
        try:
            ip_address = connect_wifi(ssid, password)
            save_setup_state({
                "phase": PHASE_ACCOUNT,
                "error": "",
                "lan_ip": ip_address,
                "dashboard_url": dashboard_url(ip_address),
                "ssid": hotspot_ssid(),
            })
            publish_mdns(ip_address)
        except Exception as exc:
            traceback.print_exc()
            try:
                ensure_hotspot()
            except Exception:
                traceback.print_exc()
            save_setup_state({
                "phase": PHASE_HOTSPOT,
                "ssid": hotspot_ssid(),
                "error": str(exc),
            })

    threading.Thread(target=worker, daemon=True, name="gameline-wifi-join").start()


def advance_to_homescreen() -> None:
    ip_address = default_route_ip() or load_setup_state().get("lan_ip") or ""
    save_setup_state({
        "phase": PHASE_HOMESCREEN,
        "error": "",
        "lan_ip": ip_address,
        "dashboard_url": dashboard_url(ip_address),
    })
    if ip_address:
        publish_mdns(ip_address)


def setup_status_payload() -> dict:
    state = load_setup_state()
    return {
        "phase": state.get("phase"),
        "ssid": state.get("ssid") or "",
        "error": state.get("error") or "",
        "lan_ip": state.get("lan_ip") or "",
        "dashboard_url": state.get("dashboard_url") or "",
        "complete": setup_is_complete(),
        "holds_display": setup_holds_display(),
    }
