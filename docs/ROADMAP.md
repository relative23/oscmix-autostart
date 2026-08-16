# Roadmap

Where this project is going, and why. Every number in here was measured
against this repository or a Fireface UCX II (24216011), not estimated.

## What this project is

oscmix-autostart is the **state layer** for a Fireface on Linux. Upstream
[oscmix] speaks the device's MIDI SysEx protocol and offers a live mixer
GUI; this project makes the resulting state *declarative, reproducible and
verified* -- applied on every boot and hotplug, checked against what the
device actually reports.

A knob to turn belongs in the GUI. A state that has to survive a reboot
belongs in `routing.conf`.

### Where we can be better than TotalMix FX

Not at DSP, metering or breadth of controls -- that is RME's and
upstream's ground. At **state management**, and at being *provably*
correct:

| | TotalMix FX | oscmix-autostart |
|---|---|---|
| Configuration | GUI, opaque blob | text file, reviewable, diffable |
| Version control | no | yes |
| Reproducible after reboot | manual snapshot recall | automatic, every start |
| Verified against the device | no | read-back with per-register verdicts |
| Desktop audio integration | none | named PipeWire sinks from the same config |
| Scriptable / headless | no | yes |

## Where we are (0.1.3)

Working and verified: playback→output routing for mono and stereo pairs,
stereo linking with the ordering that requires, output faders, PipeWire
named sinks, hotplug autostart, readiness signalling, routing read-back.

Measured state of the code itself:

| | today | note |
|---|---|---|
| `bin/oscmix-session` | 1386 lines, one file | 8 concerns in one module |
| longest function | 106 lines (`run_session`) | 6 functions over 50 lines |
| tests | 118 | 3433 lines total |
| coverage | 65% total, 71% session | subprocess paths unmeasured |
| `mypy --strict` | 12 errors | non-strict is clean |
| mutation testing | none | blocked on module structure |
| performance budget | none | time-to-READY unmeasured |
| hardware evidence | manual, ad hoc | not reproducible by others |

Three release-blocking defects in 0.1.3 were found by measuring output
levels off the wire, not by reading code. Two of them were invisible at
message level. That sets the standard for everything below.

## 0.2.0 -- maturity

No new device features. This release is about making the existing
behaviour **provably** correct and cheap to change, because the feature
work in 0.3.0 multiplies the surface by roughly ten and the current
structure will not carry it.

Each item states what is true today, what has to become true, and how
that is proven rather than asserted.

### 1. Architecture and structure

*Today:* one 1386-line script holding the OSC codec, config parsing,
routing translation, verification, process supervision, PipeWire
generation and the CLI. `run_session` is 106 lines and does device
discovery, process launch, signal handling, readiness and supervision.

*Target:* a package -- `osc`, `config`, `routing`, `verify`, `supervise`,
`pipewire`, `cli` -- with `bin/oscmix-session` as a thin entry point.

*The constraint this must not break:* the runtime uses nothing outside
the standard library and runs from a checkout without an install step.
That property is why the file is monolithic today, and it is worth more
than tidiness -- it is what makes the thing work on a bare system. So the
package ships alongside the executable rather than replacing it, and an
architecture test enforces the guarantee instead of a comment claiming it.

*Proven by:* an architecture test asserting no third-party import in the
runtime package, no import cycles, a declared layering (config must not
import supervise, routing must not import cli), and a function-length
ceiling. Mechanical, so it cannot rot.

### 2. Contracts

*Today:* the invariants exist in comments and in a few tests that happen
to cover them. Nothing states them as contracts.

*Target:* written and machine-checked:

- `route_messages == link_messages + mix_messages` *(already tested)*
- a route writes **exactly** the registers it declares -- the rule the
  `volume` bug taught us -- expressed as: written paths ⊆ declared paths
- exit codes: 0 = device absent or clean stop, 1 = runtime failure
  (restart), 2 = config error (no restart)
- readiness: `READY=1` is sent exactly once on every exit that returns 0
- OSC codec: `decode(encode(x)) == x` for every representable message
- config: parsing is total -- every input either yields a `Config` or a
  `ConfigError` naming the section and option, never a traceback

*Proven by:* property-based tests (hypothesis) for the codec and the
config parser, and a dedicated contract test module. Fuzzing the OSC
decoder against malformed datagrams belongs here too: it parses data off
a socket and currently trusts its own encoder.

### 3. Testability

*Today:* 118 tests, but `run_session`, `supervise` and
`wait_for_seq_client` are exercised only through a subprocess, which
coverage does not follow. The 71% figure for the session is therefore
both understated and unearned in places. `_cleanup_stale_backend` -- which
sends `SIGTERM` to PIDs it selected -- has no direct test at all.

*Target:* subprocess coverage via `COVERAGE_PROCESS_START` so the number
is honest; direct tests for every function that makes a decision;
`_cleanup_stale_backend` and `resolve_binary` covered including their
refusal paths.

*Proven by:* a raised coverage ratchet on real numbers, and a policy test
that every public function in the runtime package is named by at least
one test.

### 4. Provability

*Today:* the only proof that audio actually reaches both channels is that
I measured it by hand with `tcpdump` and a test tone. Nobody else can
reproduce that, and nothing stops it regressing.

*Target:* `make verify-hardware` -- a committed tool that plays a known
signal, reads `/output/<n>/level` back off the wire and asserts the
audible result per output, skipped when no device is attached so CI stays
hardware-free. It emits an evidence artifact (machine-readable plus a
human summary) that can be attached to a release.

The three defects fixed in 0.1.3 become its first regression cases:
even outputs silent, unlinked pair half-dead, unlinked route 6 dB low.

*Proven by:* the artifact itself. A routing change is not done until the
measurement is in the release.

### 5. Stability

*Today:* a flakiness gate runs the suite five times. There is no fault
injection and no soak. Every failure mode found so far -- the link race,
two teardown races, the stub signal race -- was a timing bug.

*Target:* deliberate fault injection (drop, duplicate and reorder UDP
datagrams; kill the backend mid-apply; unplug the device mid-verify;
occupy the receive port halfway through) and a restart soak that applies
the routing N times and asserts the result every time.

*Proven by:* fault-injection tests in the normal suite, soak on `main`.

### 6. Code quality

*Today:* ruff on a curated rule set, `mypy` non-strict, no mutation
testing. `mypy --strict` reports 12 errors -- a small, closable gap.

*Target:* `--strict` clean, an expanded ruff selection, and **mutation
testing** with a ratcheted score on the core modules (routing, config,
osc). Mutation testing was skipped in 0.1.2 because mutmut could not find
code to mutate in an extension-less script; the package from item 1
removes that blocker, which is why these two belong in the same release.

*Proven by:* a mutation baseline policy in CI, in the shape
payload-live-preview uses.

### 7. Performance

*Today:* unmeasured. Time-to-`READY=1` is device wait + port wait + a
1.5 s link barrier; the register dump streams for ~15-20 s in the
background. Nothing is known to be slow, which is not the same as knowing
it is fast.

*Target:* a measured budget with a regression test -- time-to-READY
against the stub backend under a fixed bound, and the dump parser checked
for accidental quadratic behaviour as register counts grow.

*Proven by:* a benchmark test in CI with a hard budget, failing on
regression rather than reporting a number nobody reads.

### 8. Maintainability

*Today:* the prose docs are good, but the expensive knowledge is
scattered through commit messages -- why the apply is two-phase, why
verification and re-apply share one `/refresh`, why `volume` is opt-in.

*Target:* an ADR trail (`docs/decisions/`) for the non-obvious choices.
Each of those took a measurement session to derive; none of them should
have to be rediscovered.

## 0.3.0 -- the whole signal path, declared

The feature depth, on top of a base that can carry it. A finding that
shapes it: **`/mix/<out>/input/<in>` appears in the device dump;
`/mix/<out>/playback/<pb>` does not.** Almost all of the new surface is
therefore verifiable, unlike the playback matrix this project started
with. Confirmed present in a dump: input `48v` (ch 1-2), `hi-z` (3-4),
`reflevel` (3-8), `gain`, `mute`, `phase`, `stereo`; output `mute`, `pan`,
`reflevel`, `phase`, `volume`, `stereo`. Confirmed absent and therefore
write-only: `/input/*/name`, `/output/*/name`, `/output/*/loopback`.

- **Hardware input routing** -- `input = 1/2` as a route source.
  Zero-latency direct monitoring, the reason TotalMix exists on a
  tracking session. Not expressible at all today.
- **Channel state** -- `[input:N]` and `[output:N]` sections: phantom
  power that survives a reboot, gain, reference level, mute, pan, phase.
  Validated against the channels that actually have each option.
- **`--dump-config`** -- read the device and emit a `routing.conf` that
  reproduces it. Build it in the GUI, freeze it with one command. Testable
  as a round trip: dump → apply → dump is a fixed point.
- **Profiles** -- several configs and a way to switch between them;
  TotalMix's eight snapshots, but as text.
- **The pin/remember model** -- today's implicit rule made selectable per
  option. `48v` wants pinning; a monitor fader wants remembering.

## 0.4.0 and later

EQ, dynamics, low cut and room EQ per channel; channel names; reverb and
echo; clock source and optical/SPDIF mode; standalone behaviour; loopback
routing; a `--diff` mode reporting what the device has that the config
does not mention.

## Explicit non-goals

- **A mixer GUI.** That is [oscmix-gtk][oscmix].
- **Metering and DSP.** Upstream's ground.
- **DURec transport control.** Interactive by nature; a config file is the
  wrong shape.
- **Matching TotalMix FX feature for feature.** The aim is to win where
  being declarative and verifiable wins.

## Known constraints and upstream issues

All measured, all things the design has to live with:

- **The playback mix matrix cannot be read back.** A `/mix` write draws no
  reply and the dump omits `/mix/*/playback/*`. It can only be
  re-established from a known link state, never verified. Input routing
  does not share this limitation.
- **oscmix does not sync its register cache on its own.** It learns the
  device's values only from a `/refresh` dump, which streams for ~15-20 s
  on a UCX II.
- **The device reports a register only when it changes.** Writing a value
  it already holds produces no report, so "wait for the echo" cannot be
  the only synchronisation mechanism.
- **Room EQ registers report implausible values** (+30 dB and +40 dB at
  50 Hz, Q=80, on every output). This looks like a register offset in
  upstream's decoding rather than real device state. Worth an upstream
  issue before 0.4.0 builds on them.
- **`unexpected enum value -1`** on every start, from oscmix reading an
  enum it cannot map. Harmless noise; also upstream.
- **Only the UCX II is tested.** The 802 path is untested and always has
  been.

[oscmix]: https://github.com/michaelforney/oscmix
