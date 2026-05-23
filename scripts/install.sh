#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# Hermes Beszel Plugin — Install Script
# Copies plugin files to ~/.hermes/plugins/beszel/ and optionally
# enables the plugin in ~/.hermes/config.yaml.
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DIR="${HERMES_HOME}/plugins/beszel"
CONFIG_YAML="${HERMES_HOME}/config.yaml"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo ""
echo "=== Hermes Beszel Plugin Installer ==="
echo ""

# ── Step 1: Copy plugin files ──────────────────────────────────
echo "Step 1/3: Copying plugin files..."

mkdir -p "$PLUGIN_DIR"
cp -v "$REPO_DIR/plugins/beszel/"* "$PLUGIN_DIR/"

echo "  ✓ Plugin files copied to $PLUGIN_DIR"
echo ""

# ── Step 2: Enable in config.yaml (plugins.enabled) ────────────
echo "Step 2/3: Enabling plugin in config.yaml..."

if [ ! -f "$CONFIG_YAML" ]; then
    echo "  ⚠️  $CONFIG_YAML not found. Creating minimal config..."
    mkdir -p "$(dirname "$CONFIG_YAML")"
    cat > "$CONFIG_YAML" << 'EOF'
plugins:
  enabled:
    - beszel
platform_toolsets:
  cli:
    - beszel
  telegram:
    - beszel
EOF
    echo "  ✓ Created $CONFIG_YAML with beszel enabled"
else
    # Check if 'beszel' is already in plugins.enabled
    if grep -q 'beszel' "$CONFIG_YAML" 2>/dev/null; then
        echo "  ℹ️  'beszel' already present in config.yaml"
    else
        # Add 'beszel' under plugins.enabled
        if grep -q '^plugins:' "$CONFIG_YAML" 2>/dev/null; then
            if grep -q 'enabled:' "$CONFIG_YAML" 2>/dev/null; then
                # Add to existing enabled list
                sed -i '/^plugins:/,/^[a-z]/{
                    /enabled:/a\    - beszel
                }' "$CONFIG_YAML" 2>/dev/null || {
                    echo "  ⚠️  Could not auto-edit config.yaml. Please add 'beszel' to plugins.enabled manually."
                }
                echo "  ✓ Added 'beszel' to plugins.enabled"
            else
                echo "  ⚠️  Could not find 'enabled:' under plugins. Please add manually:"
                echo "      plugins:"
                echo "        enabled:"
                echo "          - beszel"
            fi
        else
            echo "  ⚠️  Could not find 'plugins:' section. Please add manually:"
            echo "      plugins:"
            echo "        enabled:"
            echo "          - beszel"
        fi
    fi

    # Add 'beszel' to platform_toolsets if present
    if grep -q 'platform_toolsets:' "$CONFIG_YAML" 2>/dev/null; then
        # Try to add under cli and telegram if they exist
        for platform in cli telegram; do
            if grep -A 5 "^  ${platform}:" "$CONFIG_YAML" 2>/dev/null | grep -q 'beszel'; then
                :  # already present
            elif grep -q "^  ${platform}:" "$CONFIG_YAML" 2>/dev/null; then
                sed -i "/^  ${platform}:/a\\    - beszel" "$CONFIG_YAML" 2>/dev/null || true
                echo "  ✓ Added 'beszel' to platform_toolsets.${platform}"
            fi
        done
    fi
fi
echo ""

# ── Step 3: Final instructions ─────────────────────────────────
echo "Step 3/3: Installation complete!"
echo ""
echo "  Next steps:"
echo "  1. Restart Hermes Gateway:"
echo "     hermes gateway restart"
echo ""
echo "  2. Run the interactive setup:"
echo "     hermes beszel setup"
echo ""
echo "  3. Verify:"
echo "     hermes beszel status"
echo ""
echo "  Plugin installed at: $PLUGIN_DIR"
echo ""

exit 0
