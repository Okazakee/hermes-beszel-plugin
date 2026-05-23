"""
Beszel setup automation — webhook subscription, alert rules, credential flow.

The ``beszel_setup`` tool runs interactively via CLI stdin. It asks for:
1. The Beszel hub API URL (configurable — NOT hardcoded to localhost)
2. Email + password for authentication
3. Then automates Shoutrrr webhook config + default alert rule creation.

Credentials (email + password) are requested via CLI stdin, NEVER via
Telegram chat. Only the JWT token + API URL are persisted.
"""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import client

PLUGIN_DIR = Path(__file__).parent
CONFIG_PATH = PLUGIN_DIR / "config.json"


# ── Docker gateway detection ────────────────────────────────────────────

def _detect_docker_gateway_ip() -> str:
    """Detect Docker bridge gateway IP for the Beszel container.

    The Shoutrrr webhook URL uses the Docker gateway IP because that's
    how the Beszel container reaches the host (where Hermes listens).
    This is always local to the Docker host, independent of the
    external Beszel hub URL.
    """
    # Try docker inspect on the beszel container
    try:
        result = subprocess.run(
            ["docker", "inspect", "beszel",
             "--format", "{{range $k, $v := .NetworkSettings.Networks}}{{$v.Gateway}}{{end}}"],
            capture_output=True, text=True, timeout=10,
        )
        ip = result.stdout.strip()
        if ip and ip != "<no value>":
            return ip
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: inspect the network
    try:
        result = subprocess.run(
            ["docker", "network", "inspect", "beszel_default",
             "--format", "{{(index .IPAM.Config 0).Gateway}}"],
            capture_output=True, text=True, timeout=10,
        )
        ip = result.stdout.strip()
        if ip:
            return ip
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Last resort default
    return "172.29.0.1"


# ── Webhook secret generation ───────────────────────────────────────────

def _generate_secret() -> str:
    """Generate a random webhook secret for Shoutrrr auth."""
    return secrets.token_hex(24)


# ── Main setup flow ─────────────────────────────────────────────────────

def run_setup_interactive() -> dict:
    """Run the full interactive setup flow via CLI stdin.

    Called by the beszel_setup tool handler. Returns a result dict
    with status details for the LLM to report to the user.
    """
    print("\n=== Beszel ↔ Hermes Setup ===\n")
    print("This will configure the Hermes agent to communicate with your Beszel hub.")
    print("Your email and password are used once to get a JWT token — they are NEVER stored.\n")

    # ── Step 1: Ask for the Beszel hub API URL ──────────────────────────
    print("Step 1/5: Beszel Hub URL")
    print("  Examples: https://beszel.okazakee.dev (behind reverse proxy)")
    print("            http://10.0.0.1:8090 (local network)")
    print("            http://localhost:8090 (same machine)")

    config = client._load_config()
    current_url = config.get("BESZEL_API_URL", "")
    prompt = f"  Hub URL [{current_url}]: " if current_url else "  Hub URL: "
    api_url = input(prompt).strip()
    if not api_url and current_url:
        api_url = current_url
    elif not api_url:
        print("  ❌ Hub URL is required.")
        return {"success": False, "error": "No hub URL provided. Setup aborted."}

    # Validate basic URL format
    api_url = api_url.rstrip("/")
    if not api_url.startswith(("http://", "https://")):
        print("  ⚠️  URL should start with http:// or https://. Adding https://")
        api_url = f"https://{api_url}"

    print(f"  ✓ Using: {api_url}\n")

    # ── Step 2: Email ───────────────────────────────────────────────────
    print("Step 2/5: Beszel Admin Email")
    email = input("  Email: ").strip()
    if not email:
        print("  ❌ Email is required.")
        return {"success": False, "error": "No email provided. Setup aborted."}

    # ── Step 3: Password ────────────────────────────────────────────────
    print("\nStep 3/5: Beszel Password")
    print("  (input is hidden)")
    password = ""
    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch == "\n" or ch == "\r":
                    print()
                    break
                elif ch == "\x03":  # Ctrl+C
                    print("^C")
                    return {"success": False, "error": "Cancelled by user."}
                elif ch == "\x7f" or ch == "\x08":  # Backspace
                    if password:
                        password = password[:-1]
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                else:
                    password += ch
                    sys.stdout.write("*")
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except (ImportError, termios.error):
        # Fallback: plain input (less secure but functional)
        password = input("  Password: ").strip()

    if not password:
        print("  ❌ Password is required.")
        return {"success": False, "error": "No password provided. Setup aborted."}

    # ── Step 4: Authenticate ────────────────────────────────────────────
    print("\n  Authenticating...")
    auth_result = client.auth_with_password(email, password, api_url=api_url)

    # Discard credentials immediately
    del email, password

    if auth_result.get("error"):
        return {
            "success": False,
            "error": f"Authentication failed: {auth_result.get('message', 'Unknown error')}",
        }

    token = auth_result.get("bearer_token", "")
    user_id = auth_result.get("user_id", "")
    if not token:
        return {"success": False, "error": "Authentication succeeded but no token received."}

    print("  ✓ Authenticated successfully")

    # Save token + URL to config (temporarily, for subsequent API calls)
    config["BESZEL_API_URL"] = api_url
    config["BESZEL_API_TOKEN"] = token
    config["BESZEL_USER_ID"] = user_id
    client._save_config(config)

    # ── Step 5: Configure webhook + alerts ──────────────────────────────
    print("\nStep 4/5: Configuring Shoutrrr webhook...")

    # Detect Docker gateway IP
    gateway_ip = _detect_docker_gateway_ip()
    print(f"  Docker gateway IP: {gateway_ip}")

    # Load/create webhook secret
    webhook_secret = config.get("WEBHOOK_SECRET") or _generate_secret()
    gateway_port = config.get("GATEWAY_PORT", 8644)
    webhook_route = config.get("WEBHOOK_ROUTE", "beszel")

    # Build Shoutrrr URL
    shoutrrr_url = (
        f"generic://{gateway_ip}:{gateway_port}/webhooks/{webhook_route}"
        f"?template=json&@X-Gitlab-Token={webhook_secret}"
    )
    print(f"  Shoutrrr URL: {shoutrrr_url}")

    # Get user settings to find the settings record
    settings_resp = client.get_user_settings(api_url=api_url)
    if settings_resp.get("error"):
        return {
            "success": False,
            "error": f"Failed to fetch user settings: {settings_resp.get('message')}",
        }

    settings_items = settings_resp.get("items", [])
    if not settings_items:
        return {"success": False, "error": "No user settings record found. Has the admin user been created in Beszel?"}

    settings_record = settings_items[0]
    settings_id = settings_record.get("id")
    current_settings = settings_record.get("settings", {})

    # Update webhooks array in settings
    existing_webhooks: list[str] = current_settings.get("webhooks", []) or []

    # Add our Shoutrrr URL if not already there
    if shoutrrr_url not in existing_webhooks:
        new_webhooks = existing_webhooks + [shoutrrr_url]
    else:
        new_webhooks = existing_webhooks

    patch_resp = client.patch_user_settings(
        settings_id,
        {"settings": {"webhooks": new_webhooks}},
        api_url=api_url,
    )
    if patch_resp.get("error"):
        return {
            "success": False,
            "error": f"Failed to update webhook settings: {patch_resp.get('message')}",
        }
    print("  ✓ Webhook configured")

    # Create default alert rules if not already done
    alert_results = []
    if not config.get("DEFAULT_ALERTS_CONFIGURED"):
        print("\nStep 5/5: Creating default alert rules...")
        alert_results = _create_default_alerts(config, gateway_ip, gateway_port, webhook_route, webhook_secret)

    # Save final config
    config["WEBHOOK_SECRET"] = webhook_secret
    config["GATEWAY_IP"] = gateway_ip
    config["GATEWAY_PORT"] = gateway_port
    config["WEBHOOK_ROUTE"] = webhook_route
    if alert_results:
        config["DEFAULT_ALERTS_CONFIGURED"] = True
    client._save_config(config)

    # Build response
    result = {
        "success": True,
        "hub_url": api_url,
        "user_id": user_id,
        "webhook": {
            "shoutrrr_url": shoutrrr_url,
            "gateway_ip": gateway_ip,
            "gateway_port": gateway_port,
            "route": webhook_route,
        },
        "alerts_created": alert_results,
    }

    print("\n✅ Setup complete!")
    print(f"  Hub: {api_url}")
    print(f"  Webhook: {shoutrrr_url}")
    print(f"  Config saved to: {CONFIG_PATH}")
    if alert_results:
        created = sum(1 for a in alert_results if a.get("created"))
        failed = sum(1 for a in alert_results if not a.get("created"))
        print(f"  Alert rules: {created} created, {failed} failed")

    # Also print the bash command for quick webhook subscription
    print(f"\n  To subscribe the webhook in Hermes, run:")
    print(f"  hermes webhook subscribe {webhook_route} --deliver telegram --secret \"{webhook_secret}\"")
    print()

    return result


def _create_default_alerts(
    config: dict,
    gateway_ip: str,
    gateway_port: int,
    webhook_route: str,
    webhook_secret: str,
) -> list[dict]:
    """Create default alert rules for all systems in Beszel.

    Default rules: CPU > 90% for 5 min, Memory > 90% for 5 min,
    Disk > 90% for 5 min (for each unique system).

    The alert rules in Beszel don't have a separate notification channel;
    they use whatever is configured in user_settings.webhooks.
    """
    api_url = config.get("BESZEL_API_URL", "")

    # Get all systems
    systems_resp = client.list_systems(api_url=api_url)
    if systems_resp.get("error"):
        return [{"error": f"Failed to list systems: {systems_resp.get('message')}"}]

    systems = systems_resp.get("items", [])
    if not systems:
        return [{"error": "No systems found in Beszel. Add a system first, then re-run setup."}]

    default_rules = [
        {"name": "CPU", "value": 90, "min": 5},
        {"name": "Memory", "value": 90, "min": 5},
        {"name": "Disk", "value": 90, "min": 5},
    ]

    results = []
    for system in systems:
        system_id = system.get("id")
        system_name = system.get("name", system_id)
        for rule in default_rules:
            alert_data = {
                "name": rule["name"],
                "value": rule["value"],
                "min": rule["min"],
                "system": system_id,
                "user": config.get("BESZEL_USER_ID", ""),
            }
            resp = client.create_alert(alert_data, api_url=api_url)
            if resp.get("error"):
                results.append({
                    "system": system_name,
                    "rule": f"{rule['name']} > {rule['value']}% for {rule['min']}min",
                    "created": False,
                    "error": resp.get("message", "Unknown error"),
                })
            else:
                results.append({
                    "system": system_name,
                    "rule": f"{rule['name']} > {rule['value']}% for {rule['min']}min",
                    "created": True,
                    "id": resp.get("id", ""),
                })

    return results


# ── Tool handler ────────────────────────────────────────────────────────

def _handle_setup(params: dict, **kwargs) -> str:
    """Handler for beszel_setup tool.

    This should be called from a CLI session where stdin is available.
    The tool requires interactive input — the LLM can instruct the user
    to run `hermes beszel setup` from the terminal.
    """
    # If called from a non-interactive context (Telegram, cron),
    # return instructions instead
    if not sys.stdin.isatty():
        return json.dumps({
            "success": False,
            "error": (
                "beszel_setup requires interactive CLI input. "
                "Please run `hermes beszel setup` from the terminal "
                "on the machine where Hermes is running. You'll be "
                "prompted for the Beszel hub URL, email, and password."
            ),
            "hint": "Run from terminal: hermes beszel setup",
        })

    result = run_setup_interactive()
    return json.dumps(result)


# ── Schema ──────────────────────────────────────────────────────────────

SETUP_SCHEMA: dict[str, Any] = {
    "name": "beszel_setup",
    "description": (
        "Configure the Beszel-Hermes integration. This is interactive — "
        "it asks for the Beszel hub URL, admin email, and password via CLI stdin "
        "(NEVER via Telegram chat). It authenticates against the PocketBase API, "
        "configures the Shoutrrr webhook for push alerts, and creates default "
        "alert rules for all monitored systems.\n\n"
        "When called from Telegram/cron (non-interactive context), it returns "
        "instructions to run `hermes beszel setup` from the terminal instead.\n\n"
        "The Beszel hub URL is fully configurable — it works with:\n"
        "- Local Docker: http://localhost:8090\n"
        "- Reverse proxy: https://beszel.okazakee.dev\n"
        "- Remote/cloud: http://10.0.0.1:8090"
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}
