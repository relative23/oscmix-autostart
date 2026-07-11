#!/usr/bin/env bash
# oscmix-autostart uninstaller. Removes everything install.sh created.
# The routing config is kept unless --purge is given.
set -euo pipefail

BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/oscmix"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UDEV_RULE="/etc/udev/rules.d/90-rme-fireface.rules"

PURGE=0
case "${1:-}" in
    --purge) PURGE=1 ;;
    -h|--help) echo "usage: ./uninstall.sh [--purge]"; exit 0 ;;
    "") ;;
    *) echo "uninstall.sh: unknown option: $1" >&2; exit 2 ;;
esac

info() { printf '\033[1;34m::\033[0m %s\n' "$*"; }

info "stopping and disabling oscmix.service"
systemctl --user stop oscmix.service 2>/dev/null || true
systemctl --user disable --quiet oscmix.service 2>/dev/null || true

info "removing installed files"
rm -f "$UNIT_DIR/oscmix.service" \
      "$BIN_DIR/oscmix-session" \
      "$BIN_DIR/oscmix-launch" \
      "$BIN_DIR/oscmix" \
      "$BIN_DIR/oscmix-gtk" \
      "$BIN_DIR/alsaseqio" \
      "$DATA_DIR/applications/oscmix-gtk.desktop" \
      "$DATA_DIR/icons/hicolor/scalable/apps/oscmix.svg" \
      "$DATA_DIR/glib-2.0/schemas/oscmix.gschema.xml"
if [ -d "$DATA_DIR/glib-2.0/schemas" ]; then
    glib-compile-schemas "$DATA_DIR/glib-2.0/schemas" 2>/dev/null || true
fi
systemctl --user daemon-reload

if [ -e "$UDEV_RULE" ]; then
    info "removing udev rule (needs root)"
    if SUDO=""; [ "$(id -u)" != 0 ]; then SUDO="sudo"; fi
    $SUDO rm -f "$UDEV_RULE" && $SUDO udevadm control --reload-rules \
        || echo "warning: remove $UDEV_RULE manually" >&2
fi

if [ "$PURGE" = 1 ]; then
    info "removing configuration ($CONFIG_DIR)"
    rm -rf "$CONFIG_DIR"
else
    info "keeping configuration in $CONFIG_DIR (use --purge to remove)"
fi

info "done"
