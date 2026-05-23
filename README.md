# Hermes Beszel Plugin

**Beszel monitoring hub integration for Hermes Agent.** Query systems, metrics, alerts, and SMART disk data via the PocketBase API. Push webhook alerts through Shoutrrr with a configurable hub URL.

- **Author:** okazakee
- **Version:** 1.0.0
- **Kind:** backend plugin
- **License:** MIT

## Features

- **5 query tools** registered with Hermes:
  - `beszel_setup` - Interactive CLI setup wizard for hub URL, auth, webhook, and alerts
  - `beszel_list_systems` - List all monitored systems with live status
  - `beszel_metrics` - Detailed live metrics for a specific system (CPU, RAM, disk, network, temps)
  - `beszel_alerts` - Alert rules with threshold and trigger status
  - `beszel_smart` - S.M.A.R.T. disk health data (state, temp, model, raw attributes)
- **Interactive CLI setup** (`hermes beszel setup`) that configures everything in one pass
- **JWT authentication** via PocketBase API. Email and password are used once, never stored
- **Shoutrrr webhook auto-configuration** for push alerts from Beszel to Hermes via Docker bridge
- **Docker gateway auto-detection** that automatically finds the correct Docker bridge IP
- **Configurable hub URL** that works with local Docker, cloud VPS, or reverse proxy (NPM)
- **Zero external dependencies** - uses only Python stdlib (`urllib`, `json`, `subprocess`)
- **Graceful degradation** - tools remain registered even when Beszel is unreachable
- **CLI status command** (`hermes beszel status`) for current configuration and connectivity

## Setup

### Prerequisites

- Hermes Agent with gateway running
- Beszel Hub accessible from the Hermes machine
- At least one Beszel agent connected and visible in the dashboard
- Telegram configured as a delivery platform in Hermes Gateway (for webhook alerts)

### Installation

**Option 1: Install script (recommended)**

```bash
git clone https://github.com/okazakee/hermes-beszel-plugin.git
cd hermes-beszel-plugin
./scripts/install.sh
```

The install script will:
1. Copy plugin files to `~/.hermes/plugins/beszel/`
2. Add `beszel` to `plugins.enabled` in `~/.hermes/config.yaml`
3. Add `beszel` to `platform_toolsets` in `~/.hermes/config.yaml`

**Option 2: Manual installation**

```bash
# Copy plugin files
cp -r plugins/beszel ~/.hermes/plugins/

# Enable in ~/.hermes/config.yaml
# Add 'beszel' to plugins.enabled list
# Add 'beszel' to platform_toolsets under each platform section

# Restart Hermes
hermes gateway restart
```

### Configuration

After installing, run the interactive setup wizard:

```bash
hermes beszel setup
```

The wizard will ask for:

1. **Beszel Hub URL** - e.g., `https://beszel.okazakee.dev` (reverse proxy), `http://10.0.0.1:8090` (local network), `http://localhost:8090` (same machine)
2. **Admin Email** - your Beszel admin email
3. **Admin Password** - your Beszel admin password (input hidden, never stored)

Then it automatically:
- Authenticates and stores a JWT token
- Detects the Docker gateway IP for Shoutrrr
- Configures the Shoutrrr webhook in Beszel settings
- Creates default alert rules (CPU > 90%, Memory > 90%, Disk > 90% for 5 min)
- Saves all configuration to `~/.hermes/plugins/beszel/config.json`

## Usage

### Via Telegram (Agent Tools)

Once the plugin is enabled and configured, you can ask Hermes on Telegram:

- "Show me all my Beszel systems"
- "What are the metrics for the VPS?"
- "Are there any triggered alerts?"
- "Show me SMART disk health"

The agent will call the appropriate tools automatically.

### CLI Commands

```bash
# Run interactive setup
hermes beszel setup

# Show current configuration and connectivity
hermes beszel status
```

## Configuration Reference

Configuration is stored in `~/.hermes/plugins/beszel/config.json`:

- **`BESZEL_API_URL`** - The Beszel hub API URL (configurable during setup)
- **`BESZEL_API_TOKEN`** - JWT auth token (Bearer token, auto-refreshed)
- **`BESZEL_USER_ID`** - PocketBase user record ID
- **`WEBHOOK_SECRET`** - Auto-generated HMAC secret for Shoutrrr auth
- **`GATEWAY_IP`** - Docker bridge gateway IP (auto-detected)
- **`GATEWAY_PORT`** - Hermes Gateway port (default 8644)
- **`WEBHOOK_ROUTE`** - Webhook route name (default `beszel`)
- **`DEFAULT_ALERTS_CONFIGURED`** - Whether default alert rules were created

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Your Machine                       │
│                                                       │
│  ┌──────────┐    Shoutrrr webhook     ┌──────────┐   │
│  │  Beszel  │ ──────────────────────▶ │ Hermes   │   │
│  │  Hub     │   POST /webhooks/beszel │ Gateway  │   │
│  │ :8090    │                        │  :8644   │   │
│  └────┬─────┘                        └────┬─────┘   │
│       │ REST API (PocketBase)             │ Telegram │
│       │ BESZEL_API_URL                    ▼          │
│       │                              ┌──────────┐   │
│       └──────────────────────────────▶ │  Agent   │   │
│                                  query │ (plugin) │   │
│                                  tool  └──────────┘   │
└─────────────────────────────────────────────────────┘
```

- **Push (alerts):** Beszel to Shoutrrr to Hermes webhook to Agent interprets to Telegram
- **Pull (queries):** User asks, Agent calls tool, Beszel API responds via Telegram

## Security

- **Credentials never stored on disk.** Email and password are requested via CLI stdin during setup, used once to obtain a JWT token, then immediately discarded.
- **JWT-only authentication:** only the Bearer token and API URL are persisted in `config.json`.
- **Easily revocable:** changing the admin password on Beszel invalidates the stored token.
- **HMAC webhook authentication:** Shoutrrr webhook uses a random 48-character hex secret.
- **Local-only webhook traffic:** Shoutrrr URL uses the Docker bridge gateway IP; traffic never leaves the machine.
- **No external dependencies:** uses only Python stdlib, minimizing supply-chain risk.
- **Interactive-only credential input:** `beszel_setup` rejects non-TTY calls (e.g., from Telegram/cron), redirecting users to the CLI.

## Files

```
hermes-beszel-plugin/
├── plugins/
│   └── beszel/
│       ├── plugin.yaml         # Manifest (name, version, description, author)
│       ├── __init__.py         # register(ctx): tool + CLI registration
│       ├── client.py           # PocketBase API HTTP client (auth, systems, alerts, SMART)
│       ├── tools.py            # Tool schemas + handlers (Telegram-formatted output)
│       └── setup.py            # Interactive setup wizard (auth, webhook, alert rules)
├── scripts/
│   └── install.sh              # Install script (copies files, enables in config.yaml)
├── README.md
├── LICENSE
└── .gitignore
```

## Contributing

Contributions are welcome! Please open an issue or PR on GitHub.

## License

MIT. See [LICENSE](./LICENSE) for full text.
