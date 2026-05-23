"""
Beszel PocketBase API HTTP client.

All methods accept an ``api_url`` parameter that overrides the configured
``BESZEL_API_URL`` from config.json. If not passed, the configured URL is
used. This allows tools to work with any Beszel hub deployment — local
Docker, cloud VPS, behind NPM reverse proxy, etc.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

PLUGIN_DIR = Path(__file__).parent
CONFIG_PATH = PLUGIN_DIR / "config.json"


# ── Config helpers ──────────────────────────────────────────────────────

def _load_config() -> dict:
    """Load plugin config with defaults."""
    defaults: dict[str, Any] = {
        "BESZEL_API_URL": "",
        "BESZEL_API_TOKEN": "",
        "BESZEL_USER_ID": "",
        "WEBHOOK_SECRET": "",
        "GATEWAY_IP": "",
        "GATEWAY_PORT": 8644,
        "WEBHOOK_ROUTE": "beszel",
        "DEFAULT_ALERTS_CONFIGURED": False,
    }
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            defaults.update(data)
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def _save_config(cfg: dict) -> None:
    """Persist plugin config."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def get_api_url(api_url_override: str | None = None) -> str:
    """Return the effective Beszel API URL.

    Priority:
    1. Explicit ``api_url_override`` parameter
    2. ``BESZEL_API_URL`` from config.json
    """
    if api_url_override:
        url = api_url_override.strip().rstrip("/")
        if url:
            return url
    config = _load_config()
    url = config.get("BESZEL_API_URL", "").strip().rstrip("/")
    if not url:
        raise RuntimeError(
            "BESZEL_API_URL not configured. Run 'hermes beszel setup' or call "
            "beszel_setup first to configure the Beszel hub URL."
        )
    return url


def get_token() -> str:
    """Return the stored JWT token (already includes 'Bearer ' prefix)."""
    config = _load_config()
    token = config.get("BESZEL_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Not authenticated with Beszel. Run 'hermes beszel setup' or call "
            "beszel_setup first."
        )
    return token


# ── HTTP helpers ────────────────────────────────────────────────────────

def _build_request(
    method: str,
    path: str,
    api_url: str,
    body: dict | None = None,
    auth: bool = True,
) -> urllib.request.Request:
    """Build a urllib Request for PocketBase API."""
    url = f"{api_url}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    headers: dict[str, str] = {}
    if auth:
        headers["Authorization"] = get_token()
    if body is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return req


def _fetch(req: urllib.request.Request, timeout: int = 30) -> dict:
    """Execute a request and return parsed JSON response."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {"status": resp.status}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {"error": str(e)}
        return {
            "error": True,
            "status": e.code,
            "message": body.get("message", str(e)),
            "data": body.get("data", {}),
        }
    except urllib.error.URLError as e:
        return {"error": True, "status": 0, "message": f"Connection error: {e.reason}"}
    except Exception as e:
        return {"error": True, "status": 0, "message": str(e)}


# ── Auth ────────────────────────────────────────────────────────────────

def auth_with_password(
    email: str,
    password: str,
    api_url: str | None = None,
) -> dict:
    """Authenticate with email + password, return JWT token data.

    Returns dict with keys: token, user_id, record, or error details.
    """
    url = get_api_url(api_url)
    req = _build_request(
        "POST", "/api/collections/users/auth-with-password", url,
        body={"identity": email, "password": password},
        auth=False,
    )
    result = _fetch(req, timeout=15)
    if not result.get("error"):
        # The response from PocketBase has: {token, record: {id, email, ...}}
        result["user_id"] = result.get("record", {}).get("id", "")
        # Store the token as "Bearer xxx" for use in auth headers
        result["bearer_token"] = f"Bearer {result.get('token', '')}"
    return result


def auth_refresh(api_url: str | None = None) -> dict:
    """Refresh the stored JWT token. Returns updated token data."""
    url = get_api_url(api_url)
    req = _build_request(
        "POST", "/api/collections/users/auth-refresh", url, auth=True,
    )
    result = _fetch(req, timeout=15)
    if not result.get("error") and "token" in result:
        config = _load_config()
        config["BESZEL_API_TOKEN"] = f"Bearer {result['token']}"
        _save_config(config)
    return result


# ── Systems ─────────────────────────────────────────────────────────────

def list_systems(
    api_url: str | None = None,
) -> dict:
    """List all monitored systems with live metrics."""
    url = get_api_url(api_url)
    req = _build_request("GET", "/api/collections/systems/records", url)
    return _fetch(req, timeout=15)


def get_system(
    system_id: str,
    api_url: str | None = None,
) -> dict:
    """Get a single system detail by ID."""
    url = get_api_url(api_url)
    req = _build_request("GET", f"/api/collections/systems/records/{system_id}", url)
    return _fetch(req, timeout=15)


# ── SMART ───────────────────────────────────────────────────────────────

def list_smart_devices(
    api_url: str | None = None,
) -> dict:
    """List all SMART disk devices."""
    url = get_api_url(api_url)
    req = _build_request("GET", "/api/collections/smart_devices/records", url)
    return _fetch(req, timeout=15)


# ── Alerts ──────────────────────────────────────────────────────────────

def list_alerts(
    system_id: str | None = None,
    api_url: str | None = None,
) -> dict:
    """List alert rules, optionally filtered by system."""
    url = get_api_url(api_url)
    path = "/api/collections/alerts/records"
    if system_id:
        # PocketBase filter syntax
        filter_val = urllib.parse.quote(f'system="{system_id}"')
        path = f"{path}?filter={filter_val}"
    req = _build_request("GET", path, url)
    return _fetch(req, timeout=15)


def create_alert(
    alert_data: dict,
    api_url: str | None = None,
) -> dict:
    """Create a new alert rule for a system."""
    url = get_api_url(api_url)
    req = _build_request(
        "POST", "/api/collections/alerts/records", url,
        body=alert_data,
    )
    return _fetch(req, timeout=15)


def patch_alert(
    alert_id: str,
    patch_data: dict,
    api_url: str | None = None,
) -> dict:
    """Update an existing alert rule."""
    url = get_api_url(api_url)
    req = _build_request(
        "PATCH", f"/api/collections/alerts/records/{alert_id}", url,
        body=patch_data,
    )
    return _fetch(req, timeout=15)


def list_alerts_history(
    system_id: str | None = None,
    api_url: str | None = None,
) -> dict:
    """List alert history, optionally filtered by system."""
    url = get_api_url(api_url)
    path = "/api/collections/alerts_history/records"
    if system_id:
        filter_val = urllib.parse.quote(f'system="{system_id}"')
        path = f"{path}?filter={filter_val}"
    req = _build_request("GET", path, url)
    return _fetch(req, timeout=15)


# ── User Settings (Shoutrrr webhook management) ─────────────────────────

def get_user_settings(
    api_url: str | None = None,
) -> dict:
    """Get current user settings (includes webhooks array)."""
    url = get_api_url(api_url)
    req = _build_request("GET", "/api/collections/user_settings/records", url)
    return _fetch(req, timeout=15)


def patch_user_settings(
    settings_id: str,
    settings_data: dict,
    api_url: str | None = None,
) -> dict:
    """Patch user settings (e.g. update webhooks array)."""
    url = get_api_url(api_url)
    req = _build_request(
        "PATCH", f"/api/collections/user_settings/records/{settings_id}", url,
        body=settings_data,
    )
    return _fetch(req, timeout=15)


# ── Agent Keys ──────────────────────────────────────────────────────────

def get_agent_key(
    api_url: str | None = None,
) -> dict:
    """Generate a new agent key for adding a system."""
    url = get_api_url(api_url)
    req = _build_request("POST", "/api/beszel/getkey", url)
    return _fetch(req, timeout=15)
