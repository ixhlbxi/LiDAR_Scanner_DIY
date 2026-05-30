#!/usr/bin/env bash
# Install / refresh rover deployment assets on a Raspberry Pi.
#
# Mirrors the structure of arm-drone-lidar-workflow/base-station/bin/redeploy.sh
# but slimmed down for the rover (no /opt/* binary deploy, fewer services,
# fewer udev rules).
#
# Usage:
#   sudo deploy/install.sh             # install everything
#   sudo deploy/install.sh --dry-run   # show what would change, do nothing
#   sudo deploy/install.sh --no-restart # install but don't restart services
#
# What it does:
#   1. Validates the LD19 + ESP32 udev rules have had their *_SERIAL_PLACEHOLDER
#      values replaced (refuses to install otherwise — placeholder rules would
#      silently never fire, masking the real misconfiguration).
#   2. Copies systemd unit files to /etc/systemd/system/.
#   3. Copies udev rules to /etc/udev/rules.d/.
#   4. Creates /run/rover, /var/log/rover, /etc/rover directory tree.
#   5. Ensures /etc/rover/secret exists with mode 0600 (placeholder if absent).
#   6. systemctl daemon-reload + udevadm control --reload-rules + udevadm trigger.
#   7. Restarts the rover.service if it was already running.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="/etc/systemd/system"
UDEV_DIR="/etc/udev/rules.d"
ETC_DIR="/etc/rover"
RUN_DIR="/run/rover"
LOG_DIR="/var/log/rover"

DRY_RUN=false
RESTART=true

for arg in "$@"; do
    case "$arg" in
        --dry-run)    DRY_RUN=true ;;
        --no-restart) RESTART=false ;;
        -h|--help)
            sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "install.sh: unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

if [[ "$DRY_RUN" == false && $EUID -ne 0 ]]; then
    echo "install.sh: must be run as root (try: sudo $0 $*)" >&2
    exit 1
fi

# --- File lists -----------------------------------------------------------

UNIT_FILES=(
    rover.service
    rover-telemetry.service
)
UDEV_FILES=(
    99-rover-f9p.rules
    99-rover-lidar.rules
    99-rover-esp32.rules
)

# --- Validation -----------------------------------------------------------

echo "=== Validation ==="
fail=0
for rule in 99-rover-lidar.rules 99-rover-esp32.rules; do
    if grep -q "SERIAL_PLACEHOLDER" "$SCRIPT_DIR/udev/$rule"; then
        echo "  REFUSED: $rule still contains *_SERIAL_PLACEHOLDER"
        echo "           Discover the device serial with:"
        echo "             udevadm info -a -n /dev/ttyUSB0 | grep '{serial}' | head -1"
        echo "           Edit deploy/udev/$rule before re-running."
        fail=1
    else
        echo "  OK:      $rule has a configured serial"
    fi
done
if [[ $fail -ne 0 ]]; then
    exit 3
fi

# --- Diff preview ---------------------------------------------------------

echo
echo "=== Changes ==="
changed=0
for f in "${UNIT_FILES[@]}"; do
    if ! diff -q "$SYSTEMD_DIR/$f" "$SCRIPT_DIR/systemd/$f" >/dev/null 2>&1; then
        echo "  DIFFERS: (systemd) $f"
        changed=$((changed + 1))
    fi
done
for f in "${UDEV_FILES[@]}"; do
    if ! diff -q "$UDEV_DIR/$f" "$SCRIPT_DIR/udev/$f" >/dev/null 2>&1; then
        echo "  DIFFERS: (udev) $f"
        changed=$((changed + 1))
    fi
done
if [[ $changed -eq 0 ]]; then
    echo "  No changes detected."
fi

if [[ "$DRY_RUN" == true ]]; then
    echo
    echo "Dry run — no files modified, no services restarted."
    exit 0
fi

# --- Install --------------------------------------------------------------

echo
echo "=== Install ==="
install -d -m 0755 "$ETC_DIR"
install -d -m 0755 "$RUN_DIR"
install -d -m 0755 "$LOG_DIR"

echo "  copying systemd units..."
for f in "${UNIT_FILES[@]}"; do
    install -m 0644 "$SCRIPT_DIR/systemd/$f" "$SYSTEMD_DIR/$f"
done

echo "  copying udev rules..."
for f in "${UDEV_FILES[@]}"; do
    install -m 0644 "$SCRIPT_DIR/udev/$f" "$UDEV_DIR/$f"
done

# Secret file: create as empty placeholder if not present so EnvironmentFile=
# doesn't even need the leading `-` to tolerate absence. Permissions tight
# regardless of whether we just created it.
if [[ ! -f "$ETC_DIR/secret" ]]; then
    echo "  creating empty $ETC_DIR/secret (set ROVER_NTRIP_PASSWORD here)"
    touch "$ETC_DIR/secret"
fi
chmod 0600 "$ETC_DIR/secret"
chown root:root "$ETC_DIR/secret"

# --- Reload + (optional) restart ------------------------------------------

echo
echo "=== Reload ==="
systemctl daemon-reload
udevadm control --reload-rules
udevadm trigger

if [[ "$RESTART" == true ]] && systemctl is-active --quiet rover.service; then
    echo "  restarting rover.service..."
    systemctl restart rover.service
fi

echo
echo "Done. Inspect with:"
echo "  systemctl status rover"
echo "  ls -la /dev/rover-*"
echo "  cat /run/rover/status.json   # once rover has published"
