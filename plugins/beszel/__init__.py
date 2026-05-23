"""
Beszel Monitoring Plugin — Hermes Agent Integration

Provides tools to query a Beszel monitoring hub interactively via the
PocketBase API, plus automated webhook push-alert setup via Shoutrrr.

The Beszel hub API endpoint is **fully configurable** — set via
``beszel_setup`` (CLI stdin) and stored as ``BESZEL_API_URL`` in config.json.
Works with local Docker, cloud VPS, reverse-proxied deployments, etc.

Tools:
  beszel_setup          — Interactive CLI setup (hub URL, auth, webhook, alerts)
  beszel_list_systems   — List all monitored systems with live status
  beszel_metrics        — Detailed live metrics for a specific system
  beszel_alerts         — Alert rules listing (optionally filtered by system)
  beszel_smart          — S.M.A.R.T. disk health data

CLI:
  hermes beszel setup   — Run interactive setup wizard
  hermes beszel status  — Show current plugin config (redacted)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import client
from .tools import (
    LIST_SYSTEMS_SCHEMA,
    METRICS_SCHEMA,
    ALERTS_SCHEMA,
    SMART_SCHEMA,
    _handle_list_systems,
    _handle_metrics,
    _handle_alerts,
    _handle_smart,
)
from .setup import SETUP_SCHEMA, _handle_setup, run_setup_interactive

PLUGIN_DIR = Path(__file__).parent


# ── Token refresh check ─────────────────────────────────────────────────

def _check_token() -> bool:
    """Check if the plugin can reach Beszel. Attempts token refresh.

    Returns True if token is valid or was successfully refreshed.
    Returns False if Beszel is unreachable or token is expired.
    """
    config = client._load_config()
    if not config.get("BESZEL_API_URL") or not config.get("BESZEL_API_TOKEN"):
        return False

    try:
        result = client.auth_refresh()
        if result.get("error"):
            return False
        return True
    except Exception:
        return False


# ── CLI: hermes beszel ──────────────────────────────────────────────────

def _cli_setup(args) -> None:
    """CLI handler for 'hermes beszel setup'."""
    if not sys.stdin.isatty():
        print("❌ Setup requires an interactive terminal (TTY).")
        print("   Please run from a terminal session, not from a cron job or Telegram.")
        sys.exit(1)

    result = run_setup_interactive()
    if not result.get("success"):
        print(f"\n❌ Setup failed: {result.get('error')}")
        sys.exit(1)


def _cli_status(args) -> None:
    """CLI handler for 'hermes beszel status'."""
    config = client._load_config()

    print("\n=== Beszel Plugin Status ===\n")
    print(f"  Hub URL: {config.get('BESZEL_API_URL', '(not set)')}")
    print(f"  Auth token: {'✓ set' if config.get('BESZEL_API_TOKEN') else '✗ not set'}")
    print(f"  User ID: {config.get('BESZEL_USER_ID', '(not set)')}")
    print(f"  Webhook route: {config.get('WEBHOOK_ROUTE', 'beszel')}")
    print(f"  Gateway IP: {config.get('GATEWAY_IP', '(not detected)')}")
    print(f"  Gateway port: {config.get('GATEWAY_PORT', 8644)}")
    print(f"  Webhook secret: {'✓ set' if config.get('WEBHOOK_SECRET') else '✗ not set'}")
    print(f"  Default alerts: {'✓ configured' if config.get('DEFAULT_ALERTS_CONFIGURED') else '✗ not configured'}")

    # Test connectivity
    if config.get("BESZEL_API_URL") and config.get("BESZEL_API_TOKEN"):
        try:
            result = client.auth_refresh()
            if result.get("error"):
                print(f"\n  ⚠️  Token refresh failed: {result.get('message')}")
            else:
                print("\n  ✅ Token valid — authenticated with Beszel")
        except Exception as e:
            print(f"\n  ❌ Cannot reach Beszel: {e}")
    else:
        print("\n  ⚠️  Not configured — run 'hermes beszel setup'")


def _register_cli(subparser) -> None:
    """Register the 'beszel' CLI command."""
    subs = subparser.add_subparsers(dest="beszel_command")

    p_setup = subs.add_parser("setup", help="Interactive setup wizard (hub URL, auth, webhook, alerts)")
    p_setup.set_defaults(func=_cli_dispatch)

    p_status = subs.add_parser("status", help="Show plugin configuration and connectivity status")
    p_status.set_defaults(func=_cli_dispatch)

    subparser.set_defaults(func=_cli_dispatch)


def _cli_dispatch(args) -> int:
    """Dispatch CLI subcommands."""
    sub = getattr(args, "beszel_command", None)
    if sub == "setup":
        _cli_setup(args)
    elif sub == "status":
        _cli_status(args)
    else:
        print("usage: hermes beszel {setup,status}")
        return 2
    return 0


# ── Registration ────────────────────────────────────────────────────────

def register(ctx) -> None:
    """Register all Beszel plugin tools with Hermes.

    Called automatically when the plugin is loaded. Tools are registered
    with ``check_fn`` that verifies connectivity — if Beszel is unreachable
    (wrong URL, expired token, hub down), tools remain registered but the
    check function prevents the LLM from attempting calls.
    """
    # ── beszel_setup ────────────────────────────────────────────────
    ctx.register_tool(
        name="beszel_setup",
        toolset="beszel",
        schema=SETUP_SCHEMA,
        handler=_handle_setup,
        description="Interactive CLI setup for Beszel integration (hub URL, auth, webhook, alerts)",
        # Always available — doesn't require prior auth
    )

    # ── beszel_list_systems ─────────────────────────────────────────
    ctx.register_tool(
        name="beszel_list_systems",
        toolset="beszel",
        schema=LIST_SYSTEMS_SCHEMA,
        handler=_handle_list_systems,
        description="List all Beszel-monitored systems with live status and metrics",
        check_fn=_check_token,
    )

    # ── beszel_metrics ──────────────────────────────────────────────
    ctx.register_tool(
        name="beszel_metrics",
        toolset="beszel",
        schema=METRICS_SCHEMA,
        handler=_handle_metrics,
        description="Get detailed live metrics for a specific system (CPU, RAM, disk, network, temps)",
        check_fn=_check_token,
    )

    # ── beszel_alerts ───────────────────────────────────────────────
    ctx.register_tool(
        name="beszel_alerts",
        toolset="beszel",
        schema=ALERTS_SCHEMA,
        handler=_handle_alerts,
        description="List Beszel alert rules with thresholds and trigger status",
        check_fn=_check_token,
    )

    # ── beszel_smart ────────────────────────────────────────────────
    ctx.register_tool(
        name="beszel_smart",
        toolset="beszel",
        schema=SMART_SCHEMA,
        handler=_handle_smart,
        description="Get S.M.A.R.T. disk health data (state, temp, model, raw attributes)",
        check_fn=_check_token,
    )

    # ── CLI command ─────────────────────────────────────────────────
    ctx.register_cli_command(
        name="beszel",
        help="Beszel monitoring hub integration (setup, status)",
        setup_fn=_register_cli,
        handler_fn=_cli_dispatch,
        description="Configure and query Beszel monitoring hub",
    )
