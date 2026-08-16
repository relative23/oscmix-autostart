# Changelog

## 0.1.3 (2026-08-16)

### Fixed

- **`stereo = false` routes silenced half the pair.** The option only
  emitted the hard-panned mix messages and never sent
  `/output/<n>/stereo 0`, so it assumed the pair was already unlinked.
  Against a linked pair -- the device default -- both messages address
  the same pair register, the second overwrites the first, and one output
  goes dead. Measured on a UCX II: output 7 fully silent while output 8
  played. The unlink is now stated rather than assumed, and the link
  barrier matches on the expected value instead of only on `1`.
- **`level` meant something different on unlinked routes.** oscmix halves
  the gain on that path (`setlevel()`: `ll = vol / 2`), so `level = 0.0`
  landed 6 dB below the linked equivalent -- measured as exactly 6.1 dB
  before, and identical to the linked routes after. Positive levels
  saturate at unity, because oscmix clamps the gain it derives.
- Routes that disagree on whether an output pair is stereo-linked are now
  a configuration error. The link belongs to the hardware pair, not to a
  route; previously the last link message won while both routes still
  wrote their own mix shape, and the mismatched one silently lost an
  output.
- `find_stale_backends()` skipped its ownership check when `stat()`
  failed and then still matched on argv0, so a process whose owner could
  not be verified could reach the kill list.
- A test stub installed its signal handler only after announcing its
  port, which the tests treat as "up"; a SIGTERM landing in between
  killed it with the default disposition and the SIGTERM->SIGKILL
  escalation went unexercised.

### Documentation

- The README and the example config state that a route rewrites exactly
  the registers it declares. `volume` is opt-in and pins the output
  fader on every start; it is gone from the monitors example so the
  footgun is not the default thing to copy.

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
- The udev rule keeps ASMedia ASM4242 host controllers (`1b21:2426`)
  out of runtime suspend, which could otherwise leave their ports unable
  to enumerate a powered Fireface after a replug.

### Documentation

- ARCHITECTURE and TROUBLESHOOTING describe the two-phase routing;
  the removed `OSCMIX_VERIFY_DELAY` and the never-shipped
  `OSCMIX_LINK_SYNC_TIMEOUT` are gone from the docs, so no override
  documents a setting that does nothing.
- OSC-PROTOCOL carries the ordering constraint itself, since it is a
  property of oscmix's interface rather than of this project: the device
  has to report `/output/<n>/stereo` back before a `/mix` write is
  evaluated, sending the messages back to back is not enough, and the
  failure is silent because `/mix` can never be read back.

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
