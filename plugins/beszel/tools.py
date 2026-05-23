"""
Tool schemas and handlers for the Beszel plugin.

All tools accept an optional ``api_url`` parameter to override
the configured ``BESZEL_API_URL``. The default is read from config.json.

Each handler returns a Telegram-formatted string with emoji and markdown
(**bold**, `code`) suitable for direct display to users.
"""

from __future__ import annotations

from typing import Any

from . import client


# ── Formatting helpers ──────────────────────────────────────────────────

def _status_emoji(status: str) -> str:
    """Return emoji for system status."""
    s = status.lower() if status else ""
    if s == "up":
        return "✅"
    if s == "down":
        return "❌"
    return "❓"


def _format_uptime(seconds: float | int | None) -> str:
    """Format uptime seconds into human-readable string (e.g. '47d 5h 12m')."""
    if seconds is None:
        return "N/A"
    seconds = int(float(seconds))
    if seconds < 0:
        return "N/A"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _fmt_pct(val: Any) -> str:
    """Format a value as percentage string."""
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.1f}%"
    except (TypeError, ValueError):
        return str(val)


def _fmt_num(val: Any, suffix: str = "") -> str:
    """Format a numeric value with optional suffix."""
    if val is None:
        return "N/A"
    try:
        n = float(val)
        if n == int(n):
            return f"{int(n)}{suffix}"
        return f"{n:.1f}{suffix}"
    except (TypeError, ValueError):
        return f"{val}{suffix}"


def _fmt_load(la: Any) -> str:
    """Format load average array [1m, 5m, 15m]."""
    if not la or not isinstance(la, list) or len(la) < 3:
        return ""
    return f"Load: {la[0]:.2f} / {la[1]:.2f} / {la[2]:.2f}"


def _fmt_bandwidth(bb: Any) -> str:
    """Format bandwidth (network RX/TX) info if available."""
    if not bb:
        return ""
    if isinstance(bb, dict):
        rx = bb.get("rx", 0)
        tx = bb.get("tx", 0)
        return f"↓{_fmt_bytes(rx)}  ↑{_fmt_bytes(tx)}"
    return str(bb)


def _fmt_bytes(b: float | int | None) -> str:
    """Format bytes into human-readable size."""
    if b is None:
        return "0 B"
    b = float(b)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _fmt_timestamp(ts: str) -> str:
    """Trim a PocketBase ISO timestamp to a shorter form."""
    if not ts:
        return ""
    # "2025-01-15 10:30:00.123Z" → "2025-01-15 10:30"
    return ts[:16] if len(ts) >= 16 else ts


# ── beszel_list_systems ─────────────────────────────────────────────────

def _handle_list_systems(params: dict, **kwargs) -> str:
    """List all monitored systems with live status and metrics."""
    api_url = params.get("api_url") or None
    result = client.list_systems(api_url=api_url)

    if result.get("error"):
        return f"❌ **Error:** {result.get('message', 'Unknown error')}"

    items: list[dict] = result.get("items", [])
    if not items:
        return "📊 No systems found in Beszel."

    lines: list[str] = []
    for item in items:
        info: dict = item.get("info", {})
        name: str = item.get("name", "Unknown")
        status: str = item.get("status", "unknown")
        emoji = _status_emoji(status)

        cpu = info.get("cpu")
        mp = info.get("mp")    # memory %
        dp = info.get("dp")    # disk %
        la = info.get("la")    # load average
        u = info.get("u")      # uptime seconds

        # Header
        lines.append(f"━━━ 📊 **{name}** ━━━")

        # Status line: emoji + CPU/RAM/Disk pct
        status_parts = [f"{emoji} {status.title()}"]
        if cpu is not None:
            status_parts.append(f"CPU {_fmt_pct(cpu)}")
        if mp is not None:
            status_parts.append(f"RAM {_fmt_pct(mp)}")
        if dp is not None:
            status_parts.append(f"**Disk {_fmt_pct(dp)}**")
        lines.append(" · ".join(status_parts))

        # Detail line: load + uptime
        detail_parts = []
        load_str = _fmt_load(la)
        if load_str:
            detail_parts.append(load_str)
        if u is not None:
            detail_parts.append(f"Uptime {_format_uptime(u)}")
        if detail_parts:
            lines.append(" · ".join(detail_parts))

        lines.append("")  # blank separator between systems

    return "\n".join(lines).strip()


# ── beszel_metrics ──────────────────────────────────────────────────────

def _handle_metrics(params: dict, **kwargs) -> str:
    """Get detailed live metrics for a specific system."""
    system_name = params.get("system", "").strip()
    system_id = params.get("system_id", "").strip()
    api_url = params.get("api_url") or None

    if system_id:
        result = client.get_system(system_id, api_url=api_url)
    elif system_name:
        all_systems = client.list_systems(api_url=api_url)
        if all_systems.get("error"):
            return f"❌ **Error:** {all_systems.get('message', 'Failed to list systems')}"
        found = None
        for item in all_systems.get("items", []):
            if item.get("name", "").lower() == system_name.lower():
                found = item
                break
        if not found:
            return f"❌ **Error:** System '{system_name}' not found"
        result = found
    else:
        return "❌ **Error:** Provide 'system' (name) or 'system_id' parameter"

    if not isinstance(result, dict):
        return "❌ **Error:** Invalid response from Beszel"

    info: dict = result.get("info", {})
    name: str = result.get("name", "Unknown")
    status: str = result.get("status", "unknown")
    emoji = _status_emoji(status)

    lines: list[str] = [
        f"━━━ 📊 **{name}** ━━━",
        "",
        f"{emoji} **Status:** {status.title()}",
    ]

    # CPU
    cpu = info.get("cpu")
    if cpu is not None:
        lines.append(f"🖥 **CPU:** {_fmt_pct(cpu)}")

    # Memory
    mp = info.get("mp")    # memory %
    mt = info.get("mt")    # memory total GB
    if mp is not None:
        mem_str = f"🧠 **Memory:** {_fmt_pct(mp)}"
        if mt is not None:
            mem_str += f" of {_fmt_num(mt, ' GB')}"
        lines.append(mem_str)

    # Disk
    dp = info.get("dp")    # disk %
    dt = info.get("dt")    # disk total GB
    if dp is not None:
        disk_str = f"💾 **Disk:** {_fmt_pct(dp)}"
        if dt is not None:
            disk_str += f" of {_fmt_num(dt, ' GB')}"
        lines.append(disk_str)

    # Load
    la = info.get("la")
    if la and isinstance(la, list) and len(la) >= 3:
        lines.append(f"📈 **Load:** {la[0]:.2f} / {la[1]:.2f} / {la[2]:.2f}  _(1m / 5m / 15m)_")

    # Uptime
    u = info.get("u")
    if u is not None:
        lines.append(f"⏱ **Uptime:** {_format_uptime(u)}")

    # Bandwidth
    bb = info.get("bb")
    if bb:
        lines.append(f"🌐 **Network:** {_fmt_bandwidth(bb)}")

    # Temperature (t = temperature)
    t = info.get("t")
    if t is not None:
        lines.append(f"🌡 **Temperature:** {_fmt_num(t, '°C')}")

    # Containers
    containers = info.get("containers")
    if containers:
        if isinstance(containers, list):
            lines.append(f"📦 **Containers:** {len(containers)} running")
        else:
            lines.append(f"📦 **Containers:** {containers}")

    # Host
    host = info.get("h") or result.get("host")
    if host:
        lines.append(f"🏠 **Host:** `{host}`")
    port = result.get("port")
    if port:
        lines.append(f"🔌 **Port:** `{port}`")

    # Agent version
    ver = info.get("v")
    if ver:
        lines.append(f"🔖 **Agent:** v{ver}")

    # Last updated
    updated = _fmt_timestamp(result.get("updated", ""))
    if updated:
        lines.append(f"🕐 **Updated:** {updated}")

    return "\n".join(lines)


# ── beszel_alerts ───────────────────────────────────────────────────────

def _handle_alerts(params: dict, **kwargs) -> str:
    """List alert rules, optionally filtered by system name."""
    system_name = params.get("system", "").strip()
    system_id = params.get("system_id", "").strip()
    api_url = params.get("api_url") or None

    # Resolve system name → ID if needed
    resolved_id: str | None = system_id or None
    if system_name and not resolved_id:
        all_systems = client.list_systems(api_url=api_url)
        if not all_systems.get("error"):
            for item in all_systems.get("items", []):
                if item.get("name", "").lower() == system_name.lower():
                    resolved_id = item.get("id")
                    break

    result = client.list_alerts(system_id=resolved_id, api_url=api_url)
    if result.get("error"):
        return f"❌ **Error:** {result.get('message', 'Unknown error')}"

    items: list[dict] = result.get("items", [])
    filter_label = system_name or system_id or "All systems"
    lines: list[str] = [
        "━━━ 🚨 **Alerts** ━━━",
        f"_{filter_label}_",
        "",
    ]

    if not items:
        lines.append("✅ No alert rules configured.")
        return "\n".join(lines)

    for item in items:
        name = item.get("name", "Unnamed")
        value = item.get("value", "?")
        min_val = item.get("min", "?")
        triggered = item.get("triggered", False)
        alert_emoji = "🔴" if triggered else "🟢"

        lines.append(
            f"{alert_emoji} **{name}** — Threshold: `{value}`  "
            f"(window: {min_val}m)"
        )

    return "\n".join(lines)


# ── beszel_smart ────────────────────────────────────────────────────────

def _handle_smart(params: dict, **kwargs) -> str:
    """Get SMART disk health data."""
    api_url = params.get("api_url") or None

    result = client.list_smart_devices(api_url=api_url)
    if result.get("error"):
        return f"❌ **Error:** {result.get('message', 'Unknown error')}"

    items: list[dict] = result.get("items", [])
    lines: list[str] = [
        "━━━ 💿 **SMART Devices** ━━━",
        "",
    ]

    if not items:
        lines.append("📭 No SMART devices found.")
        return "\n".join(lines)

    for item in items:
        name = item.get("name", "Unknown")
        model = item.get("model", "")
        state = item.get("state", "unknown")
        temp = item.get("temp")
        capacity = item.get("capacity", "")

        # State emoji
        s_upper = state.upper() if state else ""
        if s_upper == "PASSED":
            state_emoji = "✅"
        elif s_upper == "FAILED":
            state_emoji = "❌"
        else:
            state_emoji = "⚠️"

        # Header line
        header = f"{state_emoji} **{name}**"
        if model:
            header += f" — `{model}`"
        lines.append(header)

        # Detail line
        detail_parts = [f"State: {state}"]
        if temp is not None:
            detail_parts.append(f"Temp: {_fmt_num(temp, '°C')}")
        if capacity:
            detail_parts.append(f"Capacity: {capacity}")
        lines.append(" · ".join(detail_parts))

        # Associated system
        sys_name = item.get("system", "")
        if sys_name:
            lines.append(f"  ↳ System: {sys_name}")

        lines.append("")

    return "\n".join(lines).strip()


# ── Tool schemas ────────────────────────────────────────────────────────

LIST_SYSTEMS_SCHEMA: dict[str, Any] = {
    "name": "beszel_list_systems",
    "description": (
        "List all systems monitored by Beszel. Returns system name, status (up/down), "
        "CPU usage %, RAM usage %, disk usage %, and last update time for each system. "
        "Call this to get an overview of your infrastructure health."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "api_url": {
                "type": "string",
                "description": (
                    "Override the configured Beszel hub API URL. "
                    "Useful for testing or multi-hub setups. "
                    "Example: 'https://beszel.okazakee.dev'"
                ),
            },
        },
    },
}

METRICS_SCHEMA: dict[str, Any] = {
    "name": "beszel_metrics",
    "description": (
        "Get detailed live metrics for a specific Beszel-monitored system. "
        "Returns CPU, RAM, disk, network RX/TX, uptime, load average, temperatures, "
        "and the full raw info JSON. Provide either the system name (e.g. 'vps') or system ID."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "system": {
                "type": "string",
                "description": "System name as shown in Beszel dashboard (e.g. 'vps', 'rpi')",
            },
            "system_id": {
                "type": "string",
                "description": "System ID (PocketBase record ID). Alternative to 'system' name.",
            },
            "api_url": {
                "type": "string",
                "description": "Override the configured Beszel hub API URL.",
            },
        },
    },
}

ALERTS_SCHEMA: dict[str, Any] = {
    "name": "beszel_alerts",
    "description": (
        "List alert rules configured in Beszel. Returns rule name (CPU/Memory/Disk/...), "
        "threshold value, monitoring window (min), and whether currently triggered. "
        "Optionally filter by system name (e.g. 'vps')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "system": {
                "type": "string",
                "description": "Optional: filter alerts by system name (e.g. 'vps')",
            },
            "system_id": {
                "type": "string",
                "description": "Optional: filter by system PocketBase ID",
            },
            "api_url": {
                "type": "string",
                "description": "Override the configured Beszel hub API URL.",
            },
        },
    },
}

SMART_SCHEMA: dict[str, Any] = {
    "name": "beszel_smart",
    "description": (
        "Get S.M.A.R.T. disk health data from Beszel. Returns device state "
        "(PASSED/FAILED), temperature, model, and raw SMART attributes per disk."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "api_url": {
                "type": "string",
                "description": "Override the configured Beszel hub API URL.",
            },
        },
    },
}
