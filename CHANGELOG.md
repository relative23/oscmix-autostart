# Changelog

## 0.1.2 (2026-08-16)

### Fixed

- **Every even output stayed silent** (right headphone, right monitor).
  oscmix only updates its own stereo-link state when the *device* reports
  `/output/<n>/stereo` back; the OSC setter just forwards the register.
  The routing sent the link and the mix matrix in one burst, so `/mix`
  was evaluated against the startup link state, took the unlinked branch
  in `setlevel()` and never wrote the pair's right channel. Outputs 1, 5
  and 7 received a mono sum, outputs 2, 6 and 8 digital silence.
  Measured on a UCX II by reading `/output/<n>/level` back off the wire.

  The routing now goes out in two phases -- links first, mix matrix
  second -- and the mix is written again once the device dump has
  reported the real link state. The dump is what teaches oscmix that
  state, so verification and the re-apply now share a single `/refresh`;
  two overlapping dumps confirmed measurably fewer registers.
- `oscmix-launch` no longer dies with a traceback when `os.execv` fails
  (stale binary, bad interpreter). It reports the error and notifies,
  like the other startup failures.
- `--pipewire-sinks` skips sinks that have no `node.name` instead of
  emitting a `None` target.

### Added

- Quality gates in CI, all wired into `make check`: ruff, mypy, vulture,
  coverage with a ratchet, and a flakiness gate that repeats the suite.
  The Python matrix now spans 3.9-3.13, and action versions are pinned
  to commit SHAs.
- `tests/test_apply_routing.py`: device stand-ins that model oscmix's
  stereo-link state machine. Three of its tests fail against the previous
  single-burst routing.

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
