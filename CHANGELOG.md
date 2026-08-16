# Changelog

## Unreleased -- 0.2.0

A maturity release: no new device features. Everything here makes the
existing behaviour provably correct and cheap to change, because 0.3.0
multiplies the register surface by roughly ten.

### Architecture

- The 1386-line `bin/oscmix-session` is now a package in
  `src/oscmix_autostart/` (14 modules) with the executable reduced to a
  52-line shim; `run_session` went from 106 lines to ~40.
- `tests/test_architecture.py` enforces the properties that motivated the
  split rather than asserting them in a comment: stdlib-only runtime,
  declared per-module layering, an acyclic import graph, `__all__`
  matching what is exported, no function over 70 lines, a docstring per
  module, and every public name named by at least one test. It caught
  `run_session` immediately.

### Contracts

- `tests/test_contracts.py`: 14 property-based tests (hypothesis) --
  codec round-trip and alignment, hostile and corrupted datagrams,
  config parsing totality, `a route writes only what it declares`,
  `route == link + mix`, links before mix, and `level` meaning the same
  gain linked or unlinked.
- `tests/test_lifecycle.py`: the exit-code model and the readiness
  protocol as assertions -- 0 for device-absent and clean stops, 1 for
  runtime failures, 2 for config errors, and `READY=1` on every exit that
  returns 0. Previously these lived in a docstring.

### Testability and proof

- Subprocess coverage (`COVERAGE_PROCESS_START` plus a `sitecustomize`
  hook): measured coverage went from 65% to 86% without a single new
  test, because the integration tests always drove the entry point,
  session and CLI -- the measurement just never followed them. Ratchet
  raised 60 → 84.
- `scripts/verify-hardware.py` and `make verify-hardware`: play a tone,
  read `/output/<n>/level` back, assert the audible result, emit an
  evidence artifact including the upstream revision measured. Exits 77
  when there is no device, so CI stays hardware-free.
- Mutation testing now runs at all (the package extraction unblocked it):
  2066 mutants, 1009 killed, score 0.73. `quality/mutation-baseline.json`
  plus `scripts/mutation-policy.py` gate on the **ratio**, not on counts,
  because absolute survivor numbers rise with every line added.
- It found a real weakness: `_register_matches` was tested with an
  expected value of 0.0, where a sign error is invisible.

### Stability

- `tests/test_faults.py`: dropped, duplicated and reordered datagrams; a
  device that never answers; a dead backend port; a flood of unrelated
  registers. Every failure this project has shipped was a timing or
  delivery bug, so that is what the tests attack.
- `tests/test_performance.py` asserts **growth order**, not wall-clock. A
  millisecond budget on a shared runner would mostly measure the runner
  and add a flake source to a project whose bugs are already timing bugs.

### Security and supply chain

- `install.sh` builds a **pinned upstream commit** instead of `master`,
  verifies the checkout landed on exactly it, and records the revision in
  the hardware evidence. Tracking upstream is now an explicit
  `OSCMIX_REF=master`. The component that talks to the hardware being
  unpinned made "verified" hollow, and it is the only path here that
  compiles code from the network.
- Stale-backend cleanup signals through `os.pidfd_open`, so a PID
  recycled between the `/proc` scan and the signal cannot be hit.
- The systemd unit is sandboxed as far as an unprivileged *user* unit
  can be. The hardening that looks obvious but breaks it with
  `218/CAPABILITIES` is listed in `tests/test_unit_file.py` with the
  reason, having been discovered by the service refusing to start.
- `docs/SECURITY-MODEL.md` states what nobody had written down: UDP 7222
  is unauthenticated and any local process can write any mixer register.
  From 0.3.0 that includes phantom power.

### Code quality and maintainability

- `mypy --strict` over the package, clean; the twelve errors it reported
  were bare `dict`/`set`/`Popen` generics, now real types.
- Expanded ruff selection (security, logging format, import hygiene,
  exception handling and correctness rules), with every exclusion
  carrying its reason. One rule was overruled on purpose: the launcher
  must not print a traceback to a desktop user.
- `docs/decisions/`: five ADRs for the choices that each cost a
  measurement session to reach.
- `docs/ROADMAP.md` records where this goes next and, explicitly, that
  four of six known constraints are upstream limits -- with the patches
  and issues to raise there treated as work items rather than weather.

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
