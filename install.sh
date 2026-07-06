#!/usr/bin/env bash
# oscmix-autostart installer.
#
# Everything is installed per-user (~/.local, ~/.config); root is only
# needed for the udev hotplug rule. Existing files are backed up before
# being replaced, an existing routing.conf is never touched.
set -euo pipefail

OSCMIX_REPO="${OSCMIX_REPO:-https://github.com/michaelforney/oscmix}"
OSCMIX_REF="${OSCMIX_REF:-master}"
USB_VENDOR="2a39"
USB_PRODUCT="3fd9"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$PROJECT_DIR/build/oscmix"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/oscmix"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UDEV_RULE="/etc/udev/rules.d/90-rme-fireface.rules"

DO_BUILD=1
DO_UDEV=1

usage() {
    cat <<'EOF'
usage: ./install.sh [options]

options:
  --no-build   skip building oscmix (use already installed binaries)
  --no-udev    skip the udev rule (no root needed; no hotplug autostart)
  -h, --help   show this help

environment:
  OSCMIX_REPO  oscmix git repository (default: upstream on GitHub)
  OSCMIX_REF   git ref to build (default: master)
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --no-build) DO_BUILD=0 ;;
        --no-udev) DO_UDEV=0 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "install.sh: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

info() { printf '\033[1;34m::\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# Install a file, keeping a timestamped backup if the target differs.
install_file() {
    local mode="$1" src="$2" dst="$3"
    if [ -e "$dst" ] && ! cmp -s "$src" "$dst"; then
        local backup
        backup="$dst.bak.$(date +%Y%m%d-%H%M%S)"
        cp -p "$dst" "$backup"
        info "backed up $dst -> $backup"
    fi
    install -D -m "$mode" "$src" "$dst"
}

require() {
    command -v "$1" >/dev/null 2>&1 || fail "missing dependency: $1 ($2)"
}

# --------------------------------------------------------------------------
# Preflight checks
# --------------------------------------------------------------------------

require python3 "needed by oscmix-session"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || fail "python3 >= 3.9 required"

if ! systemctl --user show-environment >/dev/null 2>&1; then
    fail "cannot talk to the systemd user instance (is this a desktop session?)"
fi

# --------------------------------------------------------------------------
# Build oscmix (backend, alsaseqio bridge, GTK mixer)
# --------------------------------------------------------------------------

GTK_BUILT=0
if [ "$DO_BUILD" = 1 ]; then
    require git "to fetch oscmix"
    require make "to build oscmix"
    require cc "to build oscmix (install gcc or clang)"
    require pkg-config "to build oscmix"
    pkg-config --exists alsa \
        || fail "ALSA development files missing (Debian/Ubuntu: libasound2-dev, Fedora: alsa-lib-devel, Arch: alsa-lib)"

    GTK_FLAG="GTK=n"
    if pkg-config --exists 'gtk+-3.0'; then
        GTK_FLAG="GTK=y"
        require glib-compile-resources "to build oscmix-gtk (libglib2.0-dev-bin)"
        require glib-compile-schemas "to build oscmix-gtk"
    else
        warn "GTK 3 development files not found; building without the GUI"
        warn "(Debian/Ubuntu: libgtk-3-dev, Fedora: gtk3-devel, Arch: gtk3)"
    fi

    if [ -d "$BUILD_DIR/.git" ]; then
        info "updating oscmix source in $BUILD_DIR"
        git -C "$BUILD_DIR" fetch --quiet origin "$OSCMIX_REF"
        git -C "$BUILD_DIR" checkout --quiet FETCH_HEAD
    else
        info "cloning $OSCMIX_REPO ($OSCMIX_REF)"
        mkdir -p "$(dirname "$BUILD_DIR")"
        git clone --quiet --depth 1 --branch "$OSCMIX_REF" \
            "$OSCMIX_REPO" "$BUILD_DIR" 2>/dev/null \
            || git clone --quiet "$OSCMIX_REPO" "$BUILD_DIR"
    fi

    info "building oscmix ($GTK_FLAG)"
    make -C "$BUILD_DIR" "$GTK_FLAG" >/dev/null

    install_file 755 "$BUILD_DIR/oscmix" "$BIN_DIR/oscmix"
    install_file 755 "$BUILD_DIR/alsaseqio" "$BIN_DIR/alsaseqio"
    if [ -x "$BUILD_DIR/gtk/oscmix-gtk" ]; then
        GTK_BUILT=1
        install_file 755 "$BUILD_DIR/gtk/oscmix-gtk" "$BIN_DIR/oscmix-gtk"
        # oscmix-gtk aborts without its GSettings schema.
        install_file 644 "$BUILD_DIR/gtk/oscmix.gschema.xml" \
            "$DATA_DIR/glib-2.0/schemas/oscmix.gschema.xml"
        glib-compile-schemas "$DATA_DIR/glib-2.0/schemas"
    fi
else
    info "skipping build (--no-build); checking for existing binaries"
    for tool in oscmix alsaseqio; do
        found=0
        for dir in "$BIN_DIR" /usr/local/bin /usr/bin; do
            [ -x "$dir/$tool" ] && found=1 && break
        done
        [ "$found" = 1 ] || fail "$tool not found; run without --no-build"
    done
fi

# --------------------------------------------------------------------------
# Install oscmix-autostart components
# --------------------------------------------------------------------------

info "installing scripts to $BIN_DIR"
install_file 755 "$PROJECT_DIR/bin/oscmix-session" "$BIN_DIR/oscmix-session"
install_file 755 "$PROJECT_DIR/bin/oscmix-launch" "$BIN_DIR/oscmix-launch"

if [ ! -e "$CONFIG_DIR/routing.conf" ]; then
    info "installing default config to $CONFIG_DIR/routing.conf"
    install -D -m 644 "$PROJECT_DIR/config/routing.conf.example" \
        "$CONFIG_DIR/routing.conf"
else
    info "keeping existing $CONFIG_DIR/routing.conf"
fi
install -D -m 644 "$PROJECT_DIR/config/routing.conf.example" \
    "$CONFIG_DIR/routing.conf.example"

info "installing systemd user service"
install_file 644 "$PROJECT_DIR/systemd/oscmix.service" "$UNIT_DIR/oscmix.service"
systemctl --user daemon-reload
systemctl --user enable --quiet oscmix.service

info "installing desktop entry and icon"
install_file 644 "$PROJECT_DIR/desktop/oscmix.svg" \
    "$DATA_DIR/icons/hicolor/scalable/apps/oscmix.svg"
# Desktop files cannot rely on PATH containing ~/.local/bin.
DESKTOP_TMP="$(mktemp)"
sed "s|^Exec=.*|Exec=$BIN_DIR/oscmix-launch|" \
    "$PROJECT_DIR/desktop/oscmix-gtk.desktop" > "$DESKTOP_TMP"
install_file 644 "$DESKTOP_TMP" "$DATA_DIR/applications/oscmix-gtk.desktop"
rm -f "$DESKTOP_TMP"
command -v update-desktop-database >/dev/null 2>&1 \
    && update-desktop-database "$DATA_DIR/applications" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 \
    && gtk-update-icon-cache -q -t "$DATA_DIR/icons/hicolor" 2>/dev/null || true

# --------------------------------------------------------------------------
# udev rule (the only step that needs root)
# --------------------------------------------------------------------------

if [ "$DO_UDEV" = 1 ]; then
    info "installing udev rule (needs root)"
    if SUDO=""; [ "$(id -u)" != 0 ]; then SUDO="sudo"; fi
    if $SUDO install -m 644 "$PROJECT_DIR/udev/90-rme-fireface.rules" "$UDEV_RULE" \
        && $SUDO udevadm control --reload-rules; then
        $SUDO udevadm trigger --subsystem-match=usb \
            --attr-match="idVendor=$USB_VENDOR" \
            --attr-match="idProduct=$USB_PRODUCT" --action=add 2>/dev/null || true
    else
        warn "could not install $UDEV_RULE -- hotplug autostart is disabled."
        warn "To finish manually:"
        warn "  sudo install -m 644 udev/90-rme-fireface.rules $UDEV_RULE"
        warn "  sudo udevadm control --reload-rules"
    fi
else
    info "skipping udev rule (--no-udev)"
fi

# --------------------------------------------------------------------------
# Start now if the device is already connected
# --------------------------------------------------------------------------

device_present() {
    local dev
    for dev in /sys/bus/usb/devices/*; do
        [ -f "$dev/idVendor" ] || continue
        [ "$(cat "$dev/idVendor")" = "$USB_VENDOR" ] \
            && [ "$(cat "$dev/idProduct")" = "$USB_PRODUCT" ] && return 0
    done
    return 1
}

if device_present; then
    info "Fireface detected; (re)starting backend"
    systemctl --user restart oscmix.service
    sleep 2
    if systemctl --user is-active --quiet oscmix.service; then
        info "backend is running"
    else
        warn "backend did not start; check: journalctl --user -u oscmix.service"
    fi
else
    info "Fireface not connected; the backend will start automatically on plug-in"
fi

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not in your PATH (the desktop entry works anyway)" ;;
esac

if [ "$DO_BUILD" = 1 ] && [ "$GTK_BUILT" = 0 ]; then
    warn "the GTK mixer was not built; only the headless backend is installed"
fi

info "done. Open 'RME Fireface Mixer' from your app menu."
info "Routing config: $CONFIG_DIR/routing.conf"
