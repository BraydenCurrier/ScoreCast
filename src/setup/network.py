from __future__ import annotations

import hashlib
import re
import subprocess
import threading
import time
from pathlib import Path

from setup.state import AP_ADDRESS, AP_CIDR, AP_CONNECTION, HOME_CONNECTION


class NetworkError(RuntimeError):
    """Raised when Wi-Fi setup cannot talk to NetworkManager."""


DNSMASQ_SHARED_DIR = Path("/etc/NetworkManager/dnsmasq-shared.d")
DNSMASQ_SHARED_FILE = DNSMASQ_SHARED_DIR / "gameline-captive.conf"

_nm_lock = threading.RLock()


def _nmcli(*args: str, timeout: int = 20) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["nmcli", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise NetworkError("NetworkManager (nmcli) is not installed.") from exc
    except subprocess.TimeoutExpired as exc:
        raise NetworkError("NetworkManager timed out.") from exc


def _split_terse(line: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == ":":
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _signal_value(value: object) -> int:
    try:
        number = int(str(value or "0").strip() or "0")
    except ValueError:
        return 0
    return max(0, min(100, number))


def signal_bars(value: object) -> int:
    strength = _signal_value(value)
    if strength >= 75:
        return 4
    if strength >= 50:
        return 3
    if strength >= 25:
        return 2
    if strength > 0:
        return 1
    return 0


def signal_quality(value: object) -> str:
    strength = _signal_value(value)
    if strength >= 75:
        return "Strong"
    if strength >= 50:
        return "Good"
    if strength >= 25:
        return "Fair"
    return "Weak"


def classify_security(security: str) -> dict[str, str | bool]:
    """Map a scan result or manual choice onto a NetworkManager key-mgmt."""
    raw = str(security or "").strip()
    compact = " ".join(raw.upper().replace("_", "-").replace("/", " ").split())

    def described(
        method: str,
        label: str,
        needs_password: bool,
        pmf: str = "",
        error: str = "",
    ) -> dict[str, str | bool]:
        return {
            "method": method,
            "label": label,
            "needs_password": needs_password,
            "pmf": pmf,
            "error": error,
        }

    if not raw or compact in {"--", "NONE", "OPEN"}:
        return described("open", "Open", False)

    if any(token in compact for token in ("802.1X", "ENTERPRISE", "WPA-EAP")):
        return described(
            "enterprise",
            "Enterprise login",
            False,
            error=(
                "This network uses a company login. Choose a home network "
                "with a normal Wi-Fi password."
            ),
        )

    wpa3 = "WPA3" in compact or "SAE" in compact.split()
    wpa2 = any(token in compact for token in ("WPA2", "WPA1", "WPA-PSK", "PSK"))
    owes = "OWE" in compact or "ENHANCED OPEN" in compact
    wep = "WEP" in compact and "WPA" not in compact

    if owes and not wpa2 and not wpa3 and not wep:
        return described("owe", "Enhanced Open", False)
    if wep:
        return described("wep", "WEP", True)
    if wpa3 and wpa2:
        return described("wpa-psk", "WPA2/WPA3", True, pmf="2")
    if wpa3:
        return described("sae", "WPA3", True, pmf="3")
    if wpa2:
        return described("wpa-psk", "WPA2", True, pmf="2")
    return described("wpa-psk", "Secured", True, pmf="2")


def decorate_network(item: dict) -> dict[str, str | bool | int]:
    security = str(item.get("security") or "")
    info = classify_security(security)
    signal = item.get("signal") or ""
    needs_password = bool(info["needs_password"])
    return {
        "ssid": str(item.get("ssid") or ""),
        "signal": str(_signal_value(signal)),
        "security": security,
        "security_label": str(info["label"]),
        "key_mgmt": str(info["method"]),
        "open": str(info["method"]) in {"open", "owe"},
        "needs_password": needs_password,
        "bars": signal_bars(signal),
        "quality": signal_quality(signal),
    }


def parse_wifi_list(text: str) -> list[dict]:
    found: dict[str, dict] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = _split_terse(line)
        ssid = (parts[0] if parts else "").replace("\x00", "").strip()
        if not ssid:
            continue
        signal = parts[1] if len(parts) > 1 else ""
        security = parts[2] if len(parts) > 2 else ""
        candidate = decorate_network({
            "ssid": ssid,
            "signal": signal,
            "security": security,
        })
        previous = found.get(ssid)
        if previous is None or _signal_value(candidate["signal"]) > _signal_value(previous["signal"]):
            found[ssid] = candidate

    networks = list(found.values())
    networks.sort(key=lambda item: _signal_value(item["signal"]), reverse=True)
    return networks


def connection_security_args(profile: dict, password: str) -> list[str]:
    """nmcli property pairs for a home network. Open networks omit wifi-sec."""
    method = str(profile.get("method") or "open")
    if method == "open":
        return []
    if method == "owe":
        return ["wifi-sec.key-mgmt", "owe"]
    if method == "wep":
        return [
            "wifi-sec.key-mgmt",
            "none",
            "wifi-sec.wep-key-type",
            "passphrase",
            "wifi-sec.wep-key0",
            password,
        ]
    if method == "sae":
        return [
            "wifi-sec.key-mgmt",
            "sae",
            "wifi-sec.psk",
            password,
            "wifi-sec.pmf",
            "3",
        ]
    args = [
        "wifi-sec.key-mgmt",
        "wpa-psk",
        "wifi-sec.psk",
        password,
    ]
    pmf = str(profile.get("pmf") or "")
    if pmf:
        args.extend(["wifi-sec.pmf", pmf])
    return args


def build_home_add_args(
    ssid: str,
    password: str,
    security: str,
    *,
    interface: str,
    hidden: bool = False,
) -> list[str]:
    profile = classify_security(security)
    if profile.get("error"):
        raise NetworkError(str(profile["error"]))
    if profile["needs_password"] and password == "":
        raise NetworkError("This network needs a password.")
    secret = password if profile["needs_password"] else ""
    args = [
        "connection",
        "add",
        "type",
        "wifi",
        "ifname",
        interface,
        "con-name",
        HOME_CONNECTION,
        "ssid",
        ssid,
        "autoconnect",
        "yes",
        "wifi.mode",
        "infrastructure",
        "wifi.hidden",
        "yes" if hidden else "no",
        "ipv4.method",
        "auto",
        "ipv6.method",
        "auto",
        "connection.autoconnect-priority",
        "100",
    ]
    args.extend(connection_security_args(profile, secret))
    return args


def public_error(message: str, secret: str = "") -> str:
    text = " ".join(str(message or "").split())
    if secret:
        text = text.replace(secret, "********")
    text = re.sub(r"(psk[:=]\s*)\S+", r"\1********", text, flags=re.IGNORECASE)
    text = re.sub(r"(password[:=]\s*)\S+", r"\1********", text, flags=re.IGNORECASE)
    return text[:300]


def friendly_wifi_error(detail: str, secret: str = "") -> str:
    cleaned = public_error(detail, secret)
    lower = cleaned.lower()
    if "key-mgmt" in lower or "property is missing" in lower:
        return "Wi-Fi security could not be saved for that network. Try it again."
    if any(word in lower for word in (
        "secret",
        "password",
        "psk",
        "authentication",
        "invalid key",
        "no secrets",
    )):
        return "That password was not accepted. Check it and try again."
    if any(word in lower for word in ("not found", "no network", "no suitable", "no ap")):
        return "That network was not found. Refresh the list or move the display closer."
    if "timed out" in lower or "timeout" in lower:
        return "Joining that network took too long. Move the display closer and try again."
    if "ip address" in lower or "dhcp" in lower:
        return "The display joined the network but did not receive an IP address. Check the router and try again."
    return "Could not join that Wi-Fi network. Try again."


def _friendly_scan_error(detail: str) -> str:
    lower = str(detail or "").lower()
    if "ap mode" in lower or ("not allowed" in lower and "scan" in lower):
        return (
            "The Wi-Fi radio could not scan while the setup hotspot was on. "
            "Tap Refresh Networks and rejoin the setup network if this phone disconnects."
        )
    if "no wi-fi" in lower or "no wifi" in lower:
        return "No Wi-Fi radio was found on this display."
    if "timed out" in lower or "timeout" in lower:
        return "Looking for networks timed out. Tap Refresh Networks."
    return "Could not scan for Wi-Fi networks. Tap Refresh Networks."


def wifi_interface() -> str:
    result = _nmcli("-t", "-f", "DEVICE,TYPE,STATE", "device", "status")
    if result.returncode != 0:
        raise NetworkError(result.stderr.strip() or "Could not list network devices.")

    fallback = ""
    for line in result.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 2:
            continue
        device, kind = parts[0], parts[1]
        if kind != "wifi":
            continue
        if device.startswith("p2p"):
            continue
        fallback = fallback or device
        state = parts[2] if len(parts) > 2 else ""
        if state != "unmanaged":
            return device
    if fallback:
        return fallback
    raise NetworkError("No Wi-Fi radio was found.")


def _device_serial() -> str:
    serial = ""
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("serial"):
                serial = line.split(":", 1)[-1].strip()
                break
    except OSError:
        serial = ""

    if not serial:
        try:
            serial = Path("/etc/machine-id").read_text(encoding="utf-8").strip()
        except OSError:
            serial = "0000"

    return serial or "0000"


def hotspot_ssid() -> str:
    suffix = re.sub(r"[^A-Fa-f0-9]", "", _device_serial())[-4:].upper().zfill(4)
    return f"GameLine-{suffix}"


def hotspot_password() -> str:
    """WPA passphrase for the setup hotspot.

    Derived from the board serial so the QR code and NetworkManager
    always agree. The SSID only shows the last four characters, so
    seeing the network name is not enough to join.
    """
    digest = hashlib.sha256(
        f"gameline-setup:{_device_serial()}".encode("utf-8")
    ).hexdigest()
    return digest[:8].upper()


def _interface_ipv4(device: str) -> str:
    if not device:
        return ""
    try:
        result = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "dev", device],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

    for match in re.finditer(r"\binet\s+(\d+\.\d+\.\d+\.\d+)", result.stdout):
        ip_address = match.group(1)
        if ip_address.startswith(("127.", "169.254.", "192.168.4.")):
            continue
        return ip_address
    return ""


def _sysfs_carrier(device: str) -> bool:
    try:
        value = Path(f"/sys/class/net/{device}/carrier").read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return value == "1"


def ethernet_device_names() -> list[str]:
    names: list[str] = []
    try:
        result = _nmcli("-t", "-f", "DEVICE,TYPE", "device", "status")
    except NetworkError:
        result = None
    if result is not None and result.returncode == 0:
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1] == "ethernet" and parts[0]:
                names.append(parts[0])

    net = Path("/sys/class/net")
    if net.is_dir():
        for entry in sorted(net.iterdir()):
            name = entry.name
            if name in names or name == "lo" or name.startswith(("wlan", "p2p", "docker", "veth", "br-", "tailscale")):
                continue
            if (entry / "wireless").exists() or (entry / "phy80211").exists():
                continue
            if (entry / "carrier").exists():
                names.append(name)
    return names


def ethernet_has_link() -> bool:
    return any(_sysfs_carrier(device) for device in ethernet_device_names())


def ethernet_ipv4() -> str:
    for device in ethernet_device_names():
        if not _sysfs_carrier(device):
            continue
        ip_address = _interface_ipv4(device)
        if ip_address:
            return ip_address
    return ""


def default_route_ip() -> str:
    try:
        result = subprocess.run(
            ["ip", "-4", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

    match = re.search(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)", result.stdout)
    if match:
        ip_address = match.group(1)
        if ip_address.startswith("192.168.4."):
            return ""
        return ip_address

    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

    for token in result.stdout.split():
        if token.startswith("192.168.4.") or token.startswith("127."):
            continue
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", token):
            return token
    return ""


def _hotspot_is_active() -> bool:
    try:
        iface = wifi_interface()
    except NetworkError:
        return False
    result = _nmcli("-g", "GENERAL.CONNECTION", "device", "show", iface)
    if result.returncode != 0:
        return False
    name = (result.stdout or "").strip().splitlines()
    return bool(name) and name[0].strip() == AP_CONNECTION


def usable_upstream_ip() -> str:
    wired = ethernet_ipv4()
    if wired:
        return wired
    if _hotspot_is_active():
        return ""
    try:
        client_ip = _interface_ipv4(wifi_interface())
    except NetworkError:
        client_ip = ""
    if client_ip:
        return client_ip
    return default_route_ip()


def has_upstream_ip() -> bool:
    return bool(usable_upstream_ip())


def wait_for_upstream(timeout: float = 20) -> str:
    """Poll until Ethernet or home Wi-Fi has an address, or the grace period ends."""
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        ip_address = usable_upstream_ip()
        if ip_address:
            return ip_address
        if time.monotonic() >= deadline:
            return ""
        time.sleep(0.5)


def _prepare_radio() -> str:
    _nmcli("radio", "wifi", "on", timeout=10)
    iface = wifi_interface()
    _nmcli("device", "set", iface, "managed", "yes", timeout=10)
    return iface


def _scan_station(exclude_ssid: str) -> list[dict]:
    iface = _prepare_radio()
    last_error = ""
    empty_successes = 0
    for attempt in range(4):
        rescan = "yes" if attempt < 3 else "auto"
        result = _nmcli(
            "-t",
            "-f",
            "SSID,SIGNAL,SECURITY",
            "device",
            "wifi",
            "list",
            "ifname",
            iface,
            "--rescan",
            rescan,
            timeout=25,
        )
        if result.returncode != 0:
            last_error = (result.stderr or result.stdout or "").strip()
            lowered = last_error.lower()
            if "not allowed immediately" in lowered or "busy" in lowered:
                time.sleep(1.2)
                continue
            if "ap mode" in lowered or "not allowed" in lowered:
                raise NetworkError(_friendly_scan_error(last_error))
            time.sleep(1.0)
            continue

        found = [
            item for item in parse_wifi_list(result.stdout)
            if item["ssid"] != exclude_ssid
        ]
        if found:
            return found
        empty_successes += 1
        if empty_successes >= 2:
            return []
        time.sleep(1.2)

    if empty_successes:
        return []
    raise NetworkError(_friendly_scan_error(last_error))


def _wait_for_station_mode(timeout: float = 8) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _hotspot_is_active():
            time.sleep(0.4)
            return
        time.sleep(0.3)
    raise NetworkError(
        "The setup hotspot did not stop, so nearby networks could not be scanned."
    )


def perform_wifi_scan(*, allow_hotspot_pause: bool = True) -> dict:
    """Scan from station mode.

    The Raspberry Pi radio cannot reliably scan while it is hosting the
    setup hotspot. When a scan is requested during setup, the hotspot is
    paused and brought back afterward. A failed scan is reported as a
    failure instead of an empty successful list.
    """
    with _nm_lock:
        paused = False
        try:
            if _hotspot_is_active():
                if not allow_hotspot_pause:
                    raise NetworkError(_friendly_scan_error(
                        "Scanning not allowed while in AP mode"
                    ))
                paused = True
                _stop_hotspot_locked()
                _wait_for_station_mode()
            networks = _scan_station(hotspot_ssid())
            return {"ok": True, "networks": networks, "error": ""}
        except NetworkError as exc:
            return {"ok": False, "networks": [], "error": str(exc)}
        finally:
            if paused:
                try:
                    _ensure_hotspot_locked()
                except NetworkError:
                    pass


def scan_wifi() -> list[dict]:
    report = perform_wifi_scan(allow_hotspot_pause=True)
    if not report.get("ok"):
        raise NetworkError(str(report.get("error") or "Could not scan for Wi-Fi networks."))
    return list(report.get("networks") or [])


def _write_captive_dns() -> None:
    try:
        DNSMASQ_SHARED_DIR.mkdir(parents=True, exist_ok=True)
        DNSMASQ_SHARED_FILE.write_text(
            "# GameLine first-boot captive DNS\n"
            f"address=/#/{AP_ADDRESS}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _connection_field(name: str, field: str) -> str:
    result = _nmcli("-g", field, "connection", "show", name)
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _hotspot_profile_ready(ssid: str, iface: str) -> bool:
    if _connection_field(AP_CONNECTION, "802-11-wireless.ssid") != ssid:
        return False
    if _connection_field(AP_CONNECTION, "802-11-wireless.mode") != "ap":
        return False
    if _connection_field(AP_CONNECTION, "802-11-wireless-security.key-mgmt") != "wpa-psk":
        return False
    bound = _connection_field(AP_CONNECTION, "connection.interface-name")
    if bound not in {"", iface}:
        return False
    secret = _nmcli("-s", "-g", "802-11-wireless-security.psk", "connection", "show", AP_CONNECTION)
    if secret.returncode != 0:
        return False
    return (secret.stdout or "").strip() == hotspot_password()


def _create_hotspot_profile(ssid: str, iface: str) -> None:
    created = _nmcli(
        "connection",
        "add",
        "type",
        "wifi",
        "ifname",
        iface,
        "con-name",
        AP_CONNECTION,
        "ssid",
        ssid,
        "autoconnect",
        "no",
        "wifi.mode",
        "ap",
        "wifi.band",
        "bg",
        "ipv4.method",
        "shared",
        "ipv4.addresses",
        AP_CIDR,
        "ipv6.method",
        "disabled",
        "wifi-sec.key-mgmt",
        "wpa-psk",
        "wifi-sec.psk",
        hotspot_password(),
        timeout=20,
    )
    if created.returncode != 0:
        detail = public_error(created.stderr or created.stdout, hotspot_password())
        raise NetworkError(detail or "Could not create the setup hotspot.")
    priority = _nmcli(
        "connection",
        "modify",
        AP_CONNECTION,
        "connection.autoconnect",
        "no",
        "connection.autoconnect-priority",
        "-100",
        timeout=15,
    )
    if priority.returncode != 0:
        detail = public_error(priority.stderr or priority.stdout, hotspot_password())
        raise NetworkError(detail or "Could not configure the setup hotspot.")
    if _connection_field(AP_CONNECTION, "802-11-wireless-security.key-mgmt") != "wpa-psk":
        raise NetworkError("The setup hotspot was saved without Wi-Fi security.")


def _rewrite_hotspot_profile(ssid: str, iface: str) -> None:
    """Repair an existing setup profile that is missing Wi-Fi security."""
    modified = _nmcli(
        "connection",
        "modify",
        AP_CONNECTION,
        "connection.interface-name",
        iface,
        "connection.autoconnect",
        "no",
        "connection.autoconnect-priority",
        "-100",
        "wifi.ssid",
        ssid,
        "wifi.mode",
        "ap",
        "wifi.band",
        "bg",
        "ipv4.method",
        "shared",
        "ipv4.addresses",
        AP_CIDR,
        "ipv6.method",
        "disabled",
        "wifi-sec.key-mgmt",
        "wpa-psk",
        "wifi-sec.psk",
        hotspot_password(),
        timeout=20,
    )
    if modified.returncode != 0:
        detail = public_error(modified.stderr or modified.stdout, hotspot_password())
        raise NetworkError(detail or "Could not repair the setup hotspot.")


def _ensure_hotspot_locked() -> str:
    ssid = hotspot_ssid()
    iface = wifi_interface()
    _write_captive_dns()
    if not _hotspot_profile_ready(ssid, iface):
        _nmcli("connection", "delete", AP_CONNECTION, timeout=15)
        try:
            _create_hotspot_profile(ssid, iface)
        except NetworkError:
            _rewrite_hotspot_profile(ssid, iface)
            if not _hotspot_profile_ready(ssid, iface):
                raise

    up = _nmcli("connection", "up", AP_CONNECTION, "ifname", iface, timeout=30)
    if up.returncode != 0:
        detail = public_error(up.stderr or up.stdout, hotspot_password())
        raise NetworkError(detail or "Could not start the setup hotspot.")
    return ssid


def ensure_hotspot() -> str:
    with _nm_lock:
        return _ensure_hotspot_locked()


def _stop_hotspot_locked() -> None:
    if not _hotspot_is_active():
        _nmcli("connection", "down", AP_CONNECTION, timeout=15)
        return
    result = _nmcli("connection", "down", AP_CONNECTION, timeout=20)
    if result.returncode != 0 and _hotspot_is_active():
        detail = (result.stderr or result.stdout or "").strip()
        raise NetworkError(detail or "Could not pause the setup hotspot.")


def stop_hotspot() -> None:
    with _nm_lock:
        _stop_hotspot_locked()


def _iter_wifi_connections() -> list[dict[str, str]]:
    result = _nmcli("-t", "-f", "NAME,UUID,TYPE", "connection", "show")
    if result.returncode != 0:
        return []
    items = []
    for line in result.stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) < 3:
            continue
        if parts[2] not in {"802-11-wireless", "wifi"}:
            continue
        items.append({"name": parts[0], "uuid": parts[1], "type": parts[2]})
    return items


def _connection_snapshot(name: str) -> dict[str, str | bool]:
    result = _nmcli("-t", "connection", "show", name)
    snapshot: dict[str, str | bool] = {
        "ssid": "",
        "mode": "",
        "key_mgmt": "",
        "security": False,
    }
    if result.returncode != 0:
        return snapshot
    for line in result.stdout.splitlines():
        parts = _split_terse(line)
        if not parts:
            continue
        key = parts[0]
        value = ":".join(parts[1:]) if len(parts) > 1 else ""
        if key == "802-11-wireless.ssid":
            snapshot["ssid"] = value
        elif key == "802-11-wireless.mode":
            snapshot["mode"] = value
        elif key == "802-11-wireless-security.key-mgmt":
            snapshot["key_mgmt"] = value.strip()
            snapshot["security"] = True
        elif key.startswith("802-11-wireless-security."):
            snapshot["security"] = True
    return snapshot


def _delete_uuid(uuid: str) -> None:
    if uuid:
        _nmcli("connection", "delete", uuid, timeout=15)


def _prepare_home_profiles(ssid: str) -> None:
    """Replace the ScoreCast home profile and drop broken profiles for this SSID.

    Healthy connections for other networks are left alone. A profile is
    broken when it has Wi-Fi security settings but no key-mgmt, which is
    the NetworkManager error customers see after a failed join.
    """
    for item in _iter_wifi_connections():
        name = item["name"]
        if name == AP_CONNECTION:
            continue
        if name == HOME_CONNECTION:
            _delete_uuid(item["uuid"])
            continue
        snapshot = _connection_snapshot(name)
        same_network = snapshot.get("ssid") == ssid and snapshot.get("mode") != "ap"
        broken = bool(snapshot.get("security")) and not str(snapshot.get("key_mgmt") or "").strip()
        if same_network and broken:
            _delete_uuid(item["uuid"])


def _active_wifi_ssid() -> str:
    try:
        iface = wifi_interface()
    except NetworkError:
        return ""
    result = _nmcli("-g", "GENERAL.CONNECTION", "device", "show", iface)
    if result.returncode != 0:
        return ""
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if not lines or lines[0] in {AP_CONNECTION, "--"}:
        return ""
    snapshot = _connection_snapshot(lines[0])
    return str(snapshot.get("ssid") or "")


def _wait_for_wifi_ipv4(ssid: str, timeout: float = 25) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _active_wifi_ssid() == ssid:
            try:
                ip_address = _interface_ipv4(wifi_interface())
            except NetworkError:
                ip_address = ""
            if ip_address:
                return ip_address
        time.sleep(0.5)
    return ""


def _should_retry_sae(detail: str) -> bool:
    text = public_error(detail).lower()
    if any(word in text for word in ("secret", "password", "psk", "invalid key")):
        return False
    return any(word in text for word in ("sae", "wpa3", "pmf", "key-mgmt", "key management"))


def _connect_wifi_locked(ssid: str, password: str, security: str, hidden: bool) -> str:
    iface = wifi_interface()
    try:
        add_args = build_home_add_args(
            ssid,
            password,
            security,
            interface=iface,
            hidden=hidden,
        )
    except NetworkError:
        raise

    _stop_hotspot_locked()
    try:
        _wait_for_station_mode()
    except NetworkError:
        pass

    _prepare_home_profiles(ssid)
    created = _nmcli(*add_args, timeout=20)
    if created.returncode != 0:
        _prepare_home_profiles(ssid)
        created = _nmcli(*add_args, timeout=20)
    if created.returncode != 0:
        raise NetworkError(friendly_wifi_error(created.stderr or created.stdout, password))

    profile = classify_security(security)
    expected = {
        "sae": "sae",
        "wpa-psk": "wpa-psk",
        "wep": "none",
        "owe": "owe",
    }.get(str(profile["method"]), "")
    if expected:
        actual = _connection_field(HOME_CONNECTION, "802-11-wireless-security.key-mgmt")
        if actual != expected:
            raise NetworkError("Wi-Fi security could not be saved for that network. Try it again.")

    activated = _nmcli("connection", "up", HOME_CONNECTION, "ifname", iface, timeout=45)
    if activated.returncode != 0:
        raw = (activated.stderr or activated.stdout or "").strip()
        if hidden and profile["method"] == "wpa-psk" and _should_retry_sae(raw):
            _prepare_home_profiles(ssid)
            sae_args = build_home_add_args(
                ssid,
                password,
                "sae",
                interface=iface,
                hidden=True,
            )
            rebuilt = _nmcli(*sae_args, timeout=20)
            if rebuilt.returncode != 0:
                raise NetworkError(friendly_wifi_error(rebuilt.stderr or rebuilt.stdout, password))
            activated = _nmcli("connection", "up", HOME_CONNECTION, "ifname", iface, timeout=45)
            if activated.returncode != 0:
                raw = (activated.stderr or activated.stdout or "").strip()
                raise NetworkError(friendly_wifi_error(raw, password))
        else:
            raise NetworkError(friendly_wifi_error(raw, password))

    ip_address = _wait_for_wifi_ipv4(ssid)
    if not ip_address:
        raise NetworkError(
            "The display joined the network but did not receive an IP address. Check the router and try again."
        )
    return ip_address


def connect_wifi(
    ssid: str,
    password: str = "",
    security: str = "",
    hidden: bool = False,
) -> str:
    ssid = str(ssid or "").strip()
    if not ssid:
        raise NetworkError("Choose a Wi-Fi network.")
    password = str(password or "")
    try:
        with _nm_lock:
            try:
                return _connect_wifi_locked(ssid, password, security, hidden)
            except NetworkError:
                try:
                    _ensure_hotspot_locked()
                except NetworkError:
                    pass
                raise
    except NetworkError as exc:
        raise NetworkError(public_error(str(exc), password)) from None


def forget_saved_wifi() -> None:
    """Delete every Wi-Fi profile. Used only by an explicit factory reset."""
    try:
        stop_hotspot()
    except NetworkError:
        pass

    for item in _iter_wifi_connections():
        _delete_uuid(item["uuid"])


def dashboard_url(ip_address: str = "", port: int = 80) -> str:
    host = str(ip_address or "").strip() or usable_upstream_ip() or default_route_ip()
    if not host:
        host = "gameline.local"
    if port in (80, 0):
        return f"http://{host}/"
    return f"http://{host}:{port}/"


def publish_mdns(ip_address: str) -> None:
    if not ip_address:
        return
    try:
        subprocess.Popen(
            ["avahi-publish", "-a", "-R", "gameline.local", ip_address],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass
