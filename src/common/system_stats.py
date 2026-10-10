from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


_cpu_lock = threading.Lock()
_prev_idle = 0
_prev_total = 0
_cpu_primed = False

_THROTTLE_FLAGS = (
    (1 << 0, "Under-voltage now"),
    (1 << 1, "ARM frequency capped"),
    (1 << 2, "Throttled now"),
    (1 << 3, "Soft temperature limit"),
    (1 << 16, "Under-voltage occurred"),
    (1 << 17, "ARM frequency cap occurred"),
    (1 << 18, "Throttling occurred"),
    (1 << 19, "Soft temperature limit occurred"),
)


def _read_cpu_times() -> tuple[int, int]:
    with Path("/proc/stat").open("r", encoding="utf-8") as file:
        fields = file.readline().split()

    values = [int(part) for part in fields[1:8]]
    idle = values[3] + values[4]
    total = sum(values)
    return idle, total


def _cpu_percent() -> float | None:
    global _prev_idle, _prev_total, _cpu_primed

    try:
        idle, total = _read_cpu_times()
    except (OSError, ValueError, IndexError):
        return None

    with _cpu_lock:
        if not _cpu_primed or total <= _prev_total:
            _prev_idle = idle
            _prev_total = total
            _cpu_primed = True
            time.sleep(0.12)
            try:
                idle, total = _read_cpu_times()
            except (OSError, ValueError, IndexError):
                return None

        idle_delta = idle - _prev_idle
        total_delta = total - _prev_total
        _prev_idle = idle
        _prev_total = total

    if total_delta <= 0:
        return 0.0

    busy = 1.0 - (idle_delta / total_delta)
    return max(0.0, min(100.0, busy * 100.0))


def _cpu_temp_c() -> float | None:
    candidates = (
        Path("/sys/class/thermal/thermal_zone0/temp"),
        Path("/sys/class/hwmon/hwmon0/temp1_input"),
    )

    for path in candidates:
        try:
            raw = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue

        if raw > 1000:
            return raw / 1000.0
        return float(raw)

    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    text = (result.stdout or "").strip()
    if "temp=" not in text:
        return None

    try:
        return float(text.split("temp=", 1)[1].split("'")[0])
    except (IndexError, ValueError):
        return None


def _memory_stats() -> tuple[int | None, int | None, float | None]:
    info: dict[str, int] = {}

    try:
        with Path("/proc/meminfo").open("r", encoding="utf-8") as file:
            for line in file:
                key, _, rest = line.partition(":")
                parts = rest.strip().split()
                if parts:
                    info[key] = int(parts[0])
    except (OSError, ValueError):
        return None, None, None

    total_kb = info.get("MemTotal")
    available_kb = info.get("MemAvailable", info.get("MemFree"))

    if not total_kb:
        return None, None, None

    total = total_kb * 1024
    available = (available_kb or 0) * 1024
    used = max(0, total - available)
    percent = (used / total) * 100.0 if total else 0.0
    return used, total, percent


def _uptime_seconds() -> float | None:
    try:
        text = Path("/proc/uptime").read_text(encoding="utf-8")
        return float(text.split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _throttled_flags() -> list[str]:
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    text = (result.stdout or "").strip().lower()
    if "throttled=" not in text:
        return []

    raw = text.split("throttled=", 1)[1].strip()
    try:
        value = int(raw, 0)
    except ValueError:
        return []

    if value == 0:
        return []

    return [
        label
        for bit, label in _THROTTLE_FLAGS
        if value & bit
    ]


def format_bytes(value: int | None) -> str:
    if value is None:
        return "—"

    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    unit = units[0]

    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024

    if unit in {"B", "KB"}:
        return f"{int(size)} {unit}"
    return f"{size:.1f} {unit}"


def format_uptime(seconds: float | None) -> str:
    if seconds is None:
        return "—"

    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def collect_system_stats() -> dict[str, Any]:
    used, total, ram_percent = _memory_stats()
    cpu = _cpu_percent()
    temp = _cpu_temp_c()
    uptime = _uptime_seconds()
    load1, load5, load15 = os.getloadavg()
    flags = _throttled_flags()

    return {
        "cpu_percent": None if cpu is None else round(cpu, 1),
        "cpu_temp_c": None if temp is None else round(temp, 1),
        "ram_used": used,
        "ram_total": total,
        "ram_percent": None if ram_percent is None else round(ram_percent, 1),
        "ram_used_label": format_bytes(used),
        "ram_total_label": format_bytes(total),
        "uptime_seconds": uptime,
        "uptime_label": format_uptime(uptime),
        "load_avg": [round(load1, 2), round(load5, 2), round(load15, 2)],
        "throttled": flags,
    }
