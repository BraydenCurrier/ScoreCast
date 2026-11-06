from __future__ import annotations

import threading
import traceback

from common.users import has_users
from setup.network import (
    NetworkError,
    connect_wifi,
    dashboard_url,
    ensure_hotspot,
    ethernet_has_link,
    ethernet_ipv4,
    hotspot_password,
    hotspot_ssid,
    perform_wifi_scan,
    public_error,
    publish_mdns,
    stop_hotspot,
    wait_for_upstream,
)
from setup.state import (
    AP_ADDRESS,
    PHASE_ACCOUNT,
    PHASE_COMPLETE,
    PHASE_CONNECTING,
    PHASE_HOMESCREEN,
    PHASE_HOTSPOT,
    PHASE_STARTING,
    load_setup_state,
    mark_setup_complete,
    resolve_boot_action,
    save_setup_state,
    setup_holds_display,
    setup_is_complete,
    should_run_first_setup,
)


_worker_lock = threading.Lock()
_started = False
_watcher_started = False


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
        _run_boot_sequence()
    except Exception as exc:
        traceback.print_exc()
        _fail_open_hotspot(public_error(str(exc), hotspot_password()))


def _fail_open_hotspot(message: str) -> None:
    state = load_setup_state()
    if state.get("phase") in {PHASE_COMPLETE, PHASE_ACCOUNT, PHASE_HOMESCREEN}:
        save_setup_state({"error": message})
        return
    ssid = hotspot_ssid()
    try:
        ssid = ensure_hotspot()
    except Exception:
        traceback.print_exc()
    save_setup_state({
        "phase": PHASE_HOTSPOT,
        "ssid": ssid,
        "error": message or "Setup could not start. Rejoin the setup network and try again.",
        "dashboard_url": f"http://{AP_ADDRESS}/",
    })


def _run_boot_sequence() -> None:
    if setup_is_complete() or not should_run_first_setup():
        return
    if setup_is_complete():
        return

    link = _safe_ethernet_link()
    phase = load_setup_state().get("phase")
    timeout = 20 if link or phase in {PHASE_ACCOUNT, PHASE_HOMESCREEN, PHASE_CONNECTING} else 8
    ip_address = wait_for_upstream(timeout)
    action = resolve_boot_action(
        load_setup_state(),
        upstream_ip=ip_address,
        ethernet_link=_safe_ethernet_link(),
        user_account=has_users(),
    )
    if action.get("wait"):
        ip_address = wait_for_upstream(25)
        action = resolve_boot_action(
            load_setup_state(),
            upstream_ip=ip_address,
            ethernet_link=_safe_ethernet_link(),
            user_account=has_users(),
            ethernet_grace_exhausted=True,
        )
    _apply_boot_action(action)
    if action.get("watch_ethernet"):
        _start_ethernet_watcher()


def _safe_ethernet_link() -> bool:
    try:
        return ethernet_has_link()
    except Exception:
        return False


def _apply_boot_action(action: dict) -> None:
    phase = action.get("phase") or PHASE_HOTSPOT
    if phase == PHASE_COMPLETE:
        mark_setup_complete()
        if action.get("lan_ip"):
            save_setup_state({
                "lan_ip": action["lan_ip"],
                "dashboard_url": dashboard_url(action["lan_ip"]),
            })
            publish_mdns(action["lan_ip"])
        return

    updates = {
        "phase": phase,
        "error": action.get("error") or "",
    }
    if action.get("lan_ip"):
        updates["lan_ip"] = action["lan_ip"]
        updates["dashboard_url"] = dashboard_url(action["lan_ip"])
    save_setup_state(updates)

    if action.get("start_hotspot"):
        if action.get("scan") and phase == PHASE_HOTSPOT and not action.get("recovery"):
            _scan_and_cache()
        ssid = ensure_hotspot()
        save_setup_state({
            "ssid": ssid,
            "recovery_hotspot": bool(action.get("recovery")),
            "dashboard_url": f"http://{AP_ADDRESS}/",
        })
        return

    if action.get("lan_ip"):
        publish_mdns(action["lan_ip"])
        save_setup_state({"recovery_hotspot": False})
        try:
            stop_hotspot()
        except NetworkError:
            pass


def _scan_and_cache() -> None:
    save_setup_state({"scan_status": "scanning", "scan_error": ""})
    report = perform_wifi_scan(allow_hotspot_pause=True)
    updates = {
        "scan_status": "ready" if report.get("ok") else "failed",
        "scan_error": "" if report.get("ok") else str(report.get("error") or "Could not scan for Wi-Fi networks."),
    }
    if report.get("ok"):
        updates["networks"] = report.get("networks") or []
    save_setup_state(updates)


def _start_ethernet_watcher() -> None:
    global _watcher_started
    with _worker_lock:
        if _watcher_started:
            return
        _watcher_started = True
    threading.Thread(
        target=_ethernet_watch_loop,
        daemon=True,
        name="gameline-ethernet-watch",
    ).start()


def _ethernet_watch_loop() -> None:
    for _ in range(90):
        time_sleep()
        state = load_setup_state()
        phase = state.get("phase")
        if phase == PHASE_COMPLETE:
            return
        if phase == PHASE_CONNECTING:
            continue
        try:
            ip_address = ethernet_ipv4()
        except Exception:
            ip_address = ""
        if not ip_address:
            continue
        action = resolve_boot_action(
            state,
            upstream_ip=ip_address,
            ethernet_link=True,
            user_account=has_users(),
            ethernet_grace_exhausted=True,
        )
        if action.get("phase") == phase and action.get("lan_ip") == state.get("lan_ip"):
            continue
        save_setup_state({
            "phase": action["phase"],
            "error": "",
            "lan_ip": ip_address,
            "dashboard_url": dashboard_url(ip_address),
        })
        if action["phase"] == PHASE_COMPLETE:
            mark_setup_complete()
            save_setup_state({
                "lan_ip": ip_address,
                "dashboard_url": dashboard_url(ip_address),
            })
        publish_mdns(ip_address)
        if action["phase"] != PHASE_HOTSPOT:
            save_setup_state({"recovery_hotspot": False})
            try:
                stop_hotspot()
            except NetworkError:
                pass
        return


def time_sleep() -> None:
    import time
    time.sleep(2)


def advance_with_ethernet(ip_address: str) -> None:
    """Move past Wi-Fi setup when a cable already has an address."""
    if not ip_address or setup_is_complete():
        return
    action = resolve_boot_action(
        load_setup_state(),
        upstream_ip=ip_address,
        ethernet_link=True,
        user_account=has_users(),
        ethernet_grace_exhausted=True,
    )
    _apply_boot_action(action)


def join_home_wifi(
    ssid: str,
    password: str,
    security: str = "",
    hidden: bool = False,
) -> None:
    save_setup_state({
        "phase": PHASE_CONNECTING,
        "error": "",
        "scan_status": load_setup_state().get("scan_status") or "idle",
    })

    def worker():
        try:
            ip_address = connect_wifi(ssid, password, security=security, hidden=hidden)
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
            message = public_error(str(exc), password)
            wired = ""
            try:
                wired = ethernet_ipv4()
            except Exception:
                wired = ""
            if wired:
                try:
                    stop_hotspot()
                except NetworkError:
                    pass
                save_setup_state({
                    "phase": PHASE_ACCOUNT,
                    "error": "",
                    "lan_ip": wired,
                    "dashboard_url": dashboard_url(wired),
                })
                publish_mdns(wired)
                return
            try:
                ensure_hotspot()
            except Exception:
                traceback.print_exc()
            save_setup_state({
                "phase": PHASE_HOTSPOT,
                "ssid": hotspot_ssid(),
                "error": message,
                "dashboard_url": f"http://{AP_ADDRESS}/",
            })

    threading.Thread(target=worker, daemon=True, name="gameline-wifi-join").start()


def request_wifi_rescan() -> str:
    state = load_setup_state()
    if state.get("phase") == PHASE_CONNECTING:
        return "busy"
    if state.get("scan_status") == "scanning":
        return "scanning"
    save_setup_state({"scan_status": "scanning", "scan_error": ""})
    threading.Thread(target=_rescan_worker, daemon=True, name="gameline-wifi-scan").start()
    return "scanning"


def _rescan_worker() -> None:
    phase = load_setup_state().get("phase")
    try:
        report = perform_wifi_scan(allow_hotspot_pause=True)
    except Exception:
        traceback.print_exc()
        report = {
            "ok": False,
            "networks": [],
            "error": "Could not scan for Wi-Fi networks. Try again.",
        }

    updates = {
        "scan_status": "ready" if report.get("ok") else "failed",
        "scan_error": "" if report.get("ok") else str(
            report.get("error") or "Could not scan for Wi-Fi networks. Try again."
        ),
    }
    if report.get("ok"):
        updates["networks"] = report.get("networks") or []
    save_setup_state(updates)

    if phase in {PHASE_HOTSPOT, PHASE_STARTING}:
        try:
            ssid = ensure_hotspot()
        except NetworkError as exc:
            save_setup_state({
                "scan_status": "failed",
                "scan_error": public_error(str(exc), hotspot_password()),
            })
            return
        save_setup_state({
            "phase": PHASE_HOTSPOT,
            "ssid": ssid,
            "dashboard_url": f"http://{AP_ADDRESS}/",
        })


def stop_setup_hotspot() -> None:
    """Stop the setup hotspot after provisioning. Failures stay on the device."""
    try:
        stop_hotspot()
    except NetworkError:
        pass
    except Exception:
        traceback.print_exc()


def advance_to_homescreen() -> None:
    from setup.network import usable_upstream_ip

    ip_address = usable_upstream_ip() or load_setup_state().get("lan_ip") or ""
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
        "networks": state.get("networks") or [],
        "scan_status": state.get("scan_status") or "idle",
        "scan_error": state.get("scan_error") or "",
    }
