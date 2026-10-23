from __future__ import annotations

import hashlib
import re
import subprocess
import time
from pathlib import Path

from setup.state import AP_ADDRESS, AP_CIDR, AP_CONNECTION


class NetworkError(RuntimeError):
    """Raised when Wi-Fi setup cannot talk to NetworkManager."""


DNSMASQ_SHARED_DIR = Path("/etc/NetworkManager/dnsmasq-shared.d")
DNSMASQ_SHARED_FILE = DNSMASQ_SHARED_DIR / "gameline-captive.conf"

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


def parse_wifi_list(text: str) -> list[dict[str, str]]:
    networks = []
    seen = set()

    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = []
        current = []
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

        ssid = (parts[0] if parts else "").strip()
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        signal = parts[1] if len(parts) > 1 else ""
        security = parts[2] if len(parts) > 2 else ""
        networks.append({
            "ssid": ssid,
            "signal": signal,
            "security": security,
            "open": not str(security).strip() or str(security).upper() in {"", "--", "NONE"},
        })

    networks.sort(key=lambda item: int(item["signal"] or 0), reverse=True)
    return networks


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


def has_upstream_ip() -> bool:
    return bool(default_route_ip())


def scan_wifi() -> list[dict[str, str]]:
    _nmcli("device", "wifi", "rescan", timeout=10)
    time.sleep(1.2)
    result = _nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list")
    if result.returncode != 0:
        return []
    return parse_wifi_list(result.stdout)


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


def ensure_hotspot() -> str:
    ssid = hotspot_ssid()
    iface = wifi_interface()
    _write_captive_dns()

    existing = _nmcli("-t", "-f", "NAME", "connection", "show")
    names = {line.strip() for line in existing.stdout.splitlines()}

    if AP_CONNECTION not in names:
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
        )
        if created.returncode != 0:
            raise NetworkError(created.stderr.strip() or "Could not create the setup hotspot.")

    modified = _nmcli(
        "connection",
        "modify",
        AP_CONNECTION,
        "connection.interface-name",
        iface,
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
        "connection.autoconnect",
        "no",
        "wifi-sec.key-mgmt",
        "wpa-psk",
        "wifi-sec.psk",
        hotspot_password(),
    )
    if modified.returncode != 0:
        raise NetworkError(modified.stderr.strip() or "Could not configure the setup hotspot.")

    up = _nmcli("connection", "up", AP_CONNECTION, timeout=30)
    if up.returncode != 0:
        raise NetworkError(up.stderr.strip() or "Could not start the setup hotspot.")
    return ssid


def stop_hotspot() -> None:
    _nmcli("connection", "down", AP_CONNECTION, timeout=20)


def forget_saved_wifi() -> None:
    try:
        stop_hotspot()
    except NetworkError:
        pass

    listed = _nmcli("-t", "-f", "UUID,TYPE", "connection", "show")
    if listed.returncode != 0:
        return

    for line in listed.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 2:
            continue
        uuid, kind = parts[0], parts[1]
        if kind not in {"802-11-wireless", "wifi"}:
            continue
        _nmcli("connection", "delete", uuid, timeout=15)


def connect_wifi(ssid: str, password: str = "") -> str:
    ssid = str(ssid or "").strip()
    if not ssid:
        raise NetworkError("Choose a Wi-Fi network.")

    try:
        stop_hotspot()
    except NetworkError:
        pass

    args = ["device", "wifi", "connect", ssid]
    if str(password or "").strip():
        args.extend(["password", str(password).strip()])

    result = _nmcli(*args, timeout=45)
    if result.returncode != 0:
        try:
            ensure_hotspot()
        except NetworkError:
            pass
        detail = (result.stderr or result.stdout or "Wi-Fi join failed.").strip()
        raise NetworkError(detail)

    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        ip_address = default_route_ip()
        if ip_address:
            return ip_address
        time.sleep(0.5)

    try:
        ensure_hotspot()
    except NetworkError:
        pass
    raise NetworkError("Joined Wi-Fi, but this display did not get an IP address.")


def dashboard_url(ip_address: str = "", port: int = 80) -> str:
    host = str(ip_address or "").strip() or default_route_ip()
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
