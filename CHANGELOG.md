# Changelog

## 0.1.1 (2026-07-11)

- Verification now classifies every expected register dynamically as
  confirmed, mismatched, or unobserved. Warnings and automatic re-sends
  happen only for real problems (a mismatched value, or a register the
  dump reliably reports that went missing); registers the device is
  known not to report in time are logged as information. Registers
  outside the known-reported set are still compared whenever they do
  appear, so a changed upstream dump format is handled without code
  changes. A later matching report now overrides an earlier stale
  mismatch.
- README: screenshot of the mixer on a UCX II.

## 0.1.0 (2026-07-11)

First release.

- Hotplug autostart: udev rule (add + remove via `ENV{PRODUCT}`) with USB
  autosuspend disabled, systemd user service with `Type=notify` readiness
  ("started" means the backend runs and the routing is applied)
- `oscmix-session`: ALSA sequencer discovery via `/proc/asound/seq/clients`,
  process supervision with SIGTERM→SIGKILL escalation, and a clean exit-code
  model (device absent = 0, runtime failure = 1 with restart, config error =
  2 without restart)
- Declarative hardware mixer routing in `~/.config/oscmix/routing.conf`,
  applied on every backend start and verified by reading the device state
  back over OSC (one automatic re-send on mismatch)
- `--pipewire-sinks`: generates named virtual sinks ("Monitors",
  "Headphones") for the desktop sound settings from the same routing config
- Desktop entry, launcher with device/backend checks and notifications,
  application icon
- `install.sh` builds oscmix from upstream and installs everything
  per-user; root is only used for the udev rule; `uninstall.sh` reverts it
- Test suite (pytest, no hardware required) covering OSC encoding/decoding,
  config parsing, discovery, verification, the installer, and the full
  session lifecycle against a stub backend
