# Changelog

## 0.3.0 (2026-08-20)

The whole signal path, declared. 0.2.0 made the existing behaviour
provable; this release spends that on surface -- and the notable thing
about it is how much was decided by measuring the device rather than by
planning against it. Four measurements changed what got built, and one
of them removed a feature.

### The config can describe the signal path

- **Hardware input routing.** `input = 1/2` as a route source: direct
  monitoring inside the device, no round trip through the computer.
  Unlike the playback matrix, `/mix/<out>/input/<in>` *is* reported, so
  an input route is verified after every start rather than only
  re-applied.
- **Per-channel state**, as `[input:N]` and `[output:N]`: `gain`,
  `reflevel`, `hi-z`, `mute`, `phase`, `volume`. Every channel range is
  read from a recorded device dump and independently confirmed against
  upstream's device table, so a config naming a channel the interface
  does not have is a parse error rather than a silent no-op.
- **Phantom power is deliberately not settable.** `48v` is in the
  register model and has no value domain, so no config can reach it. It
  stays that way until a hardware case proves the channel it names is
  the channel it powers.
- **Profiles.** A profile is a whole `routing.conf` in `profiles/`
  beside the main one -- not a new section type, so it is parsed by the
  same code and `--dump-config > profiles/tracking.conf` composes.
  `--profile NAME` switches, `--list-profiles` lists. A switch states one
  of three outcomes and never half-applies; a config that does not parse
  is refused before the first datagram. Measured: 0 datagrams for a
  refusal, 5 for a good profile, through the same counter seconds apart.
- **`--dump-config`** reads the device and writes a `routing.conf` from
  it -- 124 channel settings on a UCX II, plus any input routes. It
  refuses when the mixer GUI holds the read-back port, because half an
  answer rendered as a config reads as authoritative.

### Pin and remember

Which settings the config keeps insisting on, and which the mixer wins,
is now a column in the register model, overridable per option by a
`[pin]` section.

The design was forced by a measurement. Of every register a config can
set, exactly **one** is pushed to listeners when it changes:
`/output/{ch}/stereo`. `volume`, `mute`, `hi-z`, `gain`, `reflevel` and
`/playback/{ch}/stereo` all change silently. So "pin" cannot mean "snaps
back when you touch the mixer" at any sensible price, and this release
does not pretend otherwise: it means the config wins while the session
is still looking.

What it replaced was an accident. A fader turned 0.5 s after a restart
came back at the config's value; the same turn at 1.5, 3 and 6 seconds
survived -- and the 0.5 s case was overwritten by the ordinary start-up
apply, not by the verifier. The line between "the config wins" and "the
user wins" was how long the apply happened to take.

`--dump-config` uses the same column: pinned values are emitted as
config, remembered ones as comments carrying the value, because a dump
cannot tell "I meant this" from "this is where I left it".

### Reconcile on events, never on a clock

`systemctl --user reload oscmix.service` re-reads the config, reads the
device back, re-applies what is pinned and leaves what is remembered.
A system-sleep hook asks for the same thing after resume.

Two of the three planned triggers were not built, and both times the
measurement is the reason:

- **Hotplug was already covered.** udev pulls the unit in on `add` and
  `StopWhenUnneeded` drops it on `remove`, so a replug is a full restart
  with a full apply. Both halves are now asserted by test instead.
- **A sample rate change destroys nothing on this device.** Across
  48 kHz -> 44.1 kHz, 1931 of 1932 reported registers were identical;
  the one that differed was `/clock/samplerate`. The playback matrix
  survived too -- shown by signal, since it is never reported. The
  trigger would have been the cheapest of the three, and there is
  nothing measured for it to repair.

### Defects found in the path every boot already ran

None of these were caught by a failing gate. All three were found by
writing a contract as tests before the code existed, or by reading
mutation survivors instead of accepting the score.

- **Channel state was written to the device and then left out of the
  read-back.** Runs logged "routing verified" without having looked at a
  single `[input:N]` or `[output:N]` register. A structural test now
  fails on any function that rebuilds a `Config` from a subset of its
  fields -- the shape both this and its write-path twin had.
- **`/playback/*` was classified as never-reported.** The recorded dump
  carries 42 registers there, and a cold plug returns all 20
  `/playback/<n>/stereo` at t=0.00 s. A lost input-side link write was
  therefore never counted as a problem and never re-sent, on the one
  register family the two-phase apply exists for.
- **The read-back window closed before channel state could arrive.** The
  stereo flags always come first and always match, so `/output/1/volume`
  came back unconfirmed while sitting correct on the device.
- **`DUMP_LISTEN_SETTLE`.** Upstream writes to a *connected* UDP socket
  and ignores `ECONNREFUSED`, so while nothing is bound the meter stream
  queues an ICMP error and the next write dies of it -- silently. Bind
  and ask for a dump in the same breath and the casualty is the one
  bundle `setrefresh()` flushes by hand: every `/playback/<n>/stereo`.
  Measured 4/12 deliveries at no delay, 12/12 at 0.1 s.

### Quality

- 663 tests from 470 functions (392/281 in 0.2.0); coverage 95%.
- Mutation score 0.687, floor 0.67, `not_covered` unchanged at 82 while
  the mutant count grew from 2726 to 4184. Reading the survivors in the
  new code found three more real defects, including one where the
  register model was never consulted, so pinning worked only through an
  explicit `[pin]` override.
- ADR 0011-0013 record the profile-switch contract, the pin/remember
  model and the trigger set, each with its measurements and the
  alternatives that were rejected.
- Every CI job now carries a timeout. One had none, hung in
  `apt-get update` and burned GitHub's 360-minute default -- on a job
  whose measured maximum is 6.7 minutes.

### Compatibility

`routing.conf` files from 0.2.x are read unchanged. The new settings are
all new *sections*, which older versions warn about and skip (ADR 0006);
an older install therefore ignores `[pin]` and channel sections rather
than refusing the file. A profile inherits `[osc]` and `[device]` from
the main config unless it states them itself.

## 0.2.0 (2026-08-17)

A maturity release: no new device features. Everything here makes the
existing behaviour provably correct and cheap to change, because 0.3.0
multiplies the register surface by roughly ten.

### Architecture

- The 1386-line `bin/oscmix-session` is now a package in
  `src/oscmix_autostart/` (15 modules, 2119 lines) with both executables
  reduced to shims of 52 and 42 lines; `run_session` went from 106 lines
  to ~40, and the longest function left is 66.
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
  2501 mutants, 1551 killed, 861 survived, 81 not covered -- score
  **0.643**, floor 0.63. `quality/mutation-baseline.json` plus
  `scripts/mutation-policy.py` gate on the **ratio**, not on counts,
  because absolute survivor numbers rise with every line added.
- That score is lower than the 0.728 recorded mid-release, and the suite
  got better, not worse: `not_covered` fell from 677 to 81 as
  `tests/test_lifecycle.py`, `tests/test_process.py` and
  `tests/test_launcher.py` brought four modules in process, and every
  mutant that stops being uncovered starts being judged. 0.728 described
  the third of the runtime that was under evaluation at the time.
- It found a real weakness: `_register_matches` was tested with an
  expected value of 0.0, where a sign error is invisible.
- The coverage ratchet is 94 against a measured 94%. It had sat at 84
  while the suite earned 91 -- seven points of erosion nothing would have
  noticed. `bin/oscmix-launch` moved into the package, taking it from the
  least covered file in the repository (61%) to 100% and inside the
  architecture test, the mutation scope and the coverage.
- A skipped contract suite no longer looks like a green run. Without
  hypothesis the terminal summary prints what did not run and why, and
  `OSCMIX_REQUIRE_CONTRACTS=1` makes the skip a collection error. CI sets
  it.
- `scripts/record-dump.py` and `tests/data/refresh-dump.json`: a real
  `/refresh` from the pinned revision, recorded as register shape and
  arrival times rather than values, with the continuously streaming level
  meters separated out. `register_promptly_reported` is now tested
  against a measurement instead of a memory.
- `systemd-analyze verify` on the unit in CI, via
  `scripts/verify-unit.sh` -- the tool reports an unknown directive name
  on stderr and still exits 0, so the script reads the output. And
  `install.sh` is now run end to end: three tests install into a
  throwaway `HOME` and run what came out of it.

### Stability

- `tests/test_faults.py`: dropped, duplicated and reordered datagrams; a
  device that never answers; a dead backend port; a flood of unrelated
  registers. Every failure this project has shipped was a timing or
  delivery bug, so that is what the tests attack.
- `tests/test_performance.py` asserts **growth order**, not wall-clock. A
  millisecond budget on a shared runner would mostly measure the runner
  and add a flake source to a project whose bugs are already timing bugs.
- Three fault cases that tear **state** rather than transport: the
  backend killed between the link phase and the mix write, the device
  vanishing while `/refresh` is still streaming, and the receive port
  taken halfway through the dump rather than before it.
- A restart soak that runs. `tests/test_soak.py` drives the real entry
  point through start → `READY=1` → verify → SIGTERM → exit 0 and
  asserts the routing datagrams byte for byte on every cycle;
  `.github/workflows/soak.yml` runs 200 nightly. "Proven by: soak on
  main" had been in the roadmap since the first draft with nothing
  running one.
- The background verifier has a stated contract: it checks for a stop
  between every phase and before each of its three writes, every wait
  wakes early rather than running out, and the session waits for it
  before exiting. It previously read the stop flag once, before starting,
  and then ran for up to two verification windows plus a 20 s blind
  delay.
- The timing budget composes. `constants.startup_budget()` sums the waits
  on the path to `READY=1` (42.0 s against `TimeoutStartSec=75`) and the
  unit is parsed and asserted against it, including `ExecStart`'s own
  `--timeout`.

### Fixed

- `--dry-run` printed an order the apply never uses. It walked route by
  route and printed link, mix, link, mix; `apply_routing` sends every
  link of every route, waits for the barrier, then every mix. With one
  route the two agree by accident -- and the one-route example config was
  exactly what CI grepped to guard the defect that silenced every even
  output, so the cheapest end-to-end check in the pipeline was inspecting
  an artifact nothing sends. One function (`routing_plan`) now produces
  the order and both consume it.

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
- ... and that "the session writes nothing" is a property of today's
  feature set rather than a principle, with the four questions the first
  writable path has to answer, so the sandbox cannot widen as an
  implementation detail. The empty `ReadWritePaths` is now asserted.
- `install.sh` gets its shallow clone back: `git clone --depth 1
  --branch` takes a branch or a tag but not a commit, which is what the
  pin is, so it uses `git init` + `git fetch --depth 1 origin <sha>`,
  falling back to a full clone if the server refuses a bare SHA.

### Code quality and maintainability

- `mypy --strict` over the package, clean; the twelve errors it reported
  were bare `dict`/`set`/`Popen` generics, now real types.
- Expanded ruff selection (security, logging format, import hygiene,
  exception handling and correctness rules), with every exclusion
  carrying its reason. One rule was overruled on purpose: the launcher
  must not print a traceback to a desktop user.
- `docs/decisions/`: nine ADRs for the choices that each cost a
  measurement session to reach. The four added here are the ones a later
  release cannot cheaply revisit: what `routing.conf` promises across
  versions (unknown section warns, unknown option fails, no schema
  field), why performance gates measure growth order, why upstream is
  pinned and when the pin may move, and the verifier's stop contract.
- `docs/RELEASE-CHECKLIST.md`: what must exist before a tag, including
  the rule that a routing change is not done until its measurement is in
  the release, and what is deliberately *not* on the list.
- Compatibility: an unknown **section** in `routing.conf` is now a
  warning and the rest of the file is applied. An unknown **option in a
  known section** is still an error -- that is what a typo looks like,
  and a silently ignored `levl = -20` is a wrong device state nobody is
  told about.
- `docs/ROADMAP.md` records where this goes next and, explicitly, that
  four of six known constraints are upstream limits -- with the patches
  and issues to raise there treated as work items rather than weather.
- The roadmap also states the goal it had only implied. "Better than
  TotalMix FX" is a claim about the **stack** -- oscmix, oscmix-gtk and
  this project -- so the bar is written down once for all three, as a
  matrix of TotalMix capabilities against what the recorded dump proves
  is reachable. The non-goal that used to read as a refusal of that goal
  now says what it meant: a division of labour, not a ceiling.
- Four decisions are drafted rather than deferred, because each costs a
  paragraph now and a migration after 0.3.0: who wins when the GUI and
  the config both write; what a sample rate change does to state that is
  supposed to survive; whether one device per host is a stated limit or
  a design to undo; and the upgrade path, which is untested in the one
  release that moves every path.
- The 15-20 s dump figure is annotated everywhere it appears rather than
  quietly corrected -- including in the item whose reasoning rested on
  it -- because the measurement that contradicts it was taken under one
  condition and the constant it sized exists for another.

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
