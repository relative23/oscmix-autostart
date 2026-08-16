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

### The bar is the stack, not this repository

**Draft, 2026-08-16 -- the matrix is measured, the conclusions are not
yet decided.**

"As complete as TotalMix FX, and better" is a claim about a *stack*. What
a user actually runs is upstream `oscmix` (the protocol), upstream
`oscmix-gtk` (the mixer GUI) and this project (the state). Measuring any
one of the three against a product that is all three at once is how a
feature gap turns into an argument about scope, and this document has an
[explicit non-goals](#explicit-non-goals) section that reads as a refusal
of the goal if the stack is never named.

So the bar is written down once, for the stack. The middle column is
measured: it is what a `/refresh` dump on a UCX II reports, recorded in
`tests/data/refresh-dump.json` (2002 registers, 70 of them streamed
without being asked, against the pinned revision). The third says when
the state becomes *declarable* here.

**There is deliberately no oscmix-gtk column.** Nobody has walked that
GUI against this list, and a column of guesses next to a column of
measurements is the exact failure mode item **L** was about. Filling it
in is a task, not an assumption: for every row below, does upstream's
GUI expose it at all?

| TotalMix FX capability | In the dump | Declarable here |
|---|---|---|
| Submix per output, playback sources | `/mix/<out>/playback/*` **absent** | today (re-established, never verified) |
| Submix per output, input sources | `/mix/<out>/input/*` (100) | 0.3.0 |
| Input strip: gain, `48v`, hi-z, reflevel, mute, phase, stereo | all seven reported | 0.3.0 |
| Output strip: volume, pan, mute, phase, reflevel, stereo | all six reported | today: volume, stereo. 0.3.0: the rest |
| EQ (3 band) and low cut, in and out | `eq/band1..3{freq,gain,q}`, `type` on bands 1 and 3 only, `lowcut/{freq,slope}` | 0.4.0 |
| Dynamics, auto level | `dynamics/{attack,release,comp*,exp*,gain}`, `autolevel/{headroom,maxgain,risetime}` | 0.4.0 |
| Room EQ (outputs) | `roomeq/band1..4{freq,gain,q}`, `band5gain`, `delay` | 0.4.0, and see the constraint below |
| Reverb and echo FX | `/reverb/*` (14), `/echo/*` (7) | 0.4.0 |
| Control room: main out, dim, mono, recall volume | `/controlroom/*` (6) | 0.4.0 |
| Crossfeed | `/output/<n>/crossfeed` | 0.4.0 |
| Clock source, sample rate, word clock | `/clock/*` (5) | 0.4.0, and see the open decision below |
| Optical/SPDIF mode, standalone, key lock | `/hardware/*` (10) | 0.4.0 |
| Loopback, channel names | **absent** -- write-only | 0.4.0, unverifiable by construction |
| Metering | 70 streamed registers | never: a meter is not state |
| Snapshots (8) | -- | 0.3.0 as profiles, plural text files |
| Workspaces, layouts, matrix view | -- | never: GUI, and no device state |
| DURec transport | not in this dump | never: interactive |
| Remote control (MIDI/OSC) | the whole interface is OSC | already better than the original |

Read down the last column and the shape of the answer is: **the device
surface is nearly all reachable and nearly all declarable, and the two
rows that are not** -- the playback matrix and the write-only registers
-- **are exactly the two this project already treats as special cases.**
That is a stronger position than "we win at state management", and it is
worth stating as the goal it is.

What the matrix does *not* answer, and what has to be decided rather than
measured: which rows this project should own at all, and which belong to
a GUI that nobody here maintains. Every row marked 0.4.0 is a row where
the honest answer today is "turn it in the GUI, and hope nothing resets
it" -- which is the same answer TotalMix gives, minus the snapshot.

## Where we are (0.2.0, unreleased)

Working and verified: playback→output routing for mono and stereo pairs,
stereo linking with the ordering that requires, output faders, PipeWire
named sinks, hotplug autostart, readiness signalling, routing read-back.

Three release-blocking defects in 0.1.3 were found by measuring output
levels off the wire, not by reading code. Two of them were invisible at
message level. That set the standard for the release below.

What 0.2.0 moved, measured rather than claimed (2026-08-16):

| | 0.1.3 | 0.2.0 |
|---|---|---|
| runtime layout | 1386 lines, one file | 15 modules, 2119 lines, two shims of 52 and 42 lines |
| longest function | 106 lines | 66 (`verify_and_repair`), under the 70 ceiling |
| tests | 118 | 377 cases from 266 test functions |
| coverage | 65% (subprocess unmeasured) | 94% measured, gate at 94 |
| `mypy --strict` | 12 errors | clean, 15 files |
| mutation score | not runnable | 0.728, floor 0.72 |
| upstream backend | `master`, unpinned | pinned commit, verified at checkout |
| hardware evidence | done by hand, once | two committed tools, a recorded dump, no artifact in a release yet |
| structural guarantees | comments | 60+ assertions, plus `systemd-analyze verify` and an install smoke test |

One number below still does not describe this suite: the mutation floor
was measured before `tests/test_lifecycle.py` and `tests/test_process.py`
existed, which is item **K** in [Still open](#still-open-in-020). The
hardware evidence now has a tool, a dump fixture and a place in
`docs/RELEASE-CHECKLIST.md`; what it does not have is a release to be
attached to.

## 0.2.0 -- maturity

No new device features. This release is about making the existing
behaviour **provably** correct and cheap to change, because the feature
work in 0.3.0 multiplies the surface by roughly ten and the current
structure will not carry it.

Each item states what is true today, what has to become true, and how
that is proven rather than asserted.

### 1. Architecture and structure -- **done**

*Was:* one 1386-line script holding the OSC codec, config parsing,
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

### 2. Contracts -- **done**

*Was:* the invariants exist in comments and in a few tests that happen
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

### 3. Testability -- **done**

*Was:* 118 tests, but `run_session`, `supervise` and
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

*Closed late:* the ratchet sat at 84 while the suite measured 91, and
`bin/oscmix-launch` sat outside the package, the architecture test and
the mutation scope. Both are fixed: the launcher is
`src/oscmix_autostart/launcher.py` at 100%, and the gate is 94 against a
measured 94 -- no margin left to erode unnoticed.

### 4. Provability -- **done**

*Was:* the only proof that audio actually reaches both channels is that
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

### 5. Stability -- **done**

*Was:* a flakiness gate runs the suite five times. There is no fault
injection and no soak. Every failure mode found so far -- the link race,
two teardown races, the stub signal race -- was a timing bug.

*Target:* deliberate fault injection (drop, duplicate and reorder UDP
datagrams; kill the backend mid-apply; unplug the device mid-verify;
occupy the receive port halfway through) and a restart soak that applies
the routing N times and asserts the result every time.

*Done, transport:* `tests/test_faults.py` -- drop, duplicate, reorder, a
flood of unrelated registers, a device that never answers, a dead backend
port.

*Done, state:* the three cases that tear a transaction open -- the
backend killed between the link phase and the mix write, the device
vanishing while `/refresh` is still streaming, and the receive port taken
*between* attempts rather than before the first one. Those are the shape
every defect this project has shipped had, and they are what gave the
verifier a stop contract (ADR 0009) rather than the other way round.

*Done, soak:* `.github/workflows/soak.yml`, daily at 04:17 UTC -- 200
restart cycles, each one a real `bin/oscmix-session` against the stub
backend checked datagram for datagram, plus the fault suite repeated 15
times. A scheduled workflow, not a Makefile target: `Proven by: soak on
main` was in this document long before anything ran one.

### 6. Code quality -- **done**

*Was:* ruff on a curated rule set, `mypy` non-strict, no mutation
testing. `mypy --strict` reports 12 errors -- a small, closable gap.

*Target:* `--strict` clean, an expanded ruff selection, and **mutation
testing** with a ratcheted score on the core modules (routing, config,
osc). Mutation testing was skipped in 0.1.2 because mutmut could not find
code to mutate in an extension-less script; the package from item 1
removes that blocker, which is why these two belong in the same release.

*Proven by:* a mutation baseline policy in CI, in the shape
payload-live-preview uses.

### 7. Performance -- **reframed and done**

The original plan here measured the wrong thing. How fast the Python runs
is not the question: time-to-`READY=1` is dominated by the device wait,
the 1.5 s link barrier and the dump, none of which a benchmark against a
stub would touch. A hard wall-clock budget on a shared runner would
mostly measure the runner -- a new flake source in a project whose bugs
are already timing bugs.

*One premise of that reasoning is now in doubt.* This said "the 15-20 s
dump", and the dump measures 1.9 s (see the finding under [Still
open](#still-open-in-020)). The conclusion survives -- the device wait
and the barrier still dominate, and neither is benchmarkable against a
stub -- but the sentence was carrying a number nobody had checked, in the
one item of the nine that exists because a number was being measured for
its own sake.

*Done instead:* the tests assert **growth order**, not milliseconds.
Doubling the input must not quadruple the time; an absurd absolute bound
catches a hang. That survives a busy machine and still rejects an
accidental quadratic in the dump parser.

*The question with actual value* is not benchmarkable here at all: can
the handful of `/output/<n>/stereo` registers be queried directly instead
of waiting out a full `/refresh`? If upstream cannot, that is a feature
request (see below), not a number.

### 8. Supply chain and blast radius -- **done**

*Today (before this release):* `install.sh` built `OSCMIX_REF=master` --
whatever upstream happened to be that day. The component that actually
talks to the hardware was unpinned, which makes the word "verified"
hollow: a measurement is only evidence about the binary it was taken
against. It is also the only path here that fetches and compiles code
from the network.

*Done:* the ref defaults to a full commit SHA, the checkout is verified
to have landed on exactly it, tracking upstream is an explicit
`OSCMIX_REF=master`, and the built revision is recorded in the hardware
evidence artifact. No signature verification -- upstream publishes no
signed tags, which is why the default is a commit that has been measured
rather than a branch.

*Also done:* `_cleanup_stale_backend` signals through `os.pidfd_open`
instead of a bare PID, so a number recycled between the `/proc` scan and
the signal cannot be hit; the unit gained the sandboxing a user manager
can actually apply; and `docs/SECURITY-MODEL.md` states the thing nobody
had written down -- **UDP 7222 is unauthenticated, and any local process
can write any mixer register.** That is upstream's design and acceptable
on a single-user desktop, but from 0.3.0 it means a local process can put
48 V on a ribbon microphone. It deserved a sentence.

### 9. Maintainability -- **done**

*Was:* the prose docs are good, but the expensive knowledge is
scattered through commit messages -- why the apply is two-phase, why
verification and re-apply share one `/refresh`, why `volume` is opt-in.

*Target:* an ADR trail (`docs/decisions/`) for the non-obvious choices.
Each of those took a measurement session to derive; none of them should
have to be rediscovered.

## Still open in 0.2.0

Twelve items, in the order I would close them. **A** and **C** are
leftovers from the nine above; **B** and **D** to **F** are gaps the
release itself opened; **G** to **L** only became visible once there was
a standard strict enough to measure against.

The first three were the ones that would have embarrassed this release if
someone had looked: a stability item claimed as done, a CI check that
guarded the project's most expensive bug by inspecting the wrong
artifact, and a coverage gate seven points below what the suite earned.

**Eleven of the twelve are closed.** Each item below keeps its original
diagnosis -- that is the reason it existed, and worth more than a tick --
followed by a *Closed:* line naming what proves it. What is left is
**K**, the mutation re-baseline, and the half of **D** that no checklist
can supply: an actual measured artifact, which needs a release to be
attached to.

Two things were found while closing these and are recorded rather than
acted on, because acting would have meant changing behaviour on a
condition nobody measured:

- **The dump is 1.9 s, not 15-20 s.** Measured against the pinned
  revision on a UCX II, twice (cold backend + immediate `/refresh`, and
  passively for 45 s after a restart): 2002 registers, all inside 2 s.
  `/playback/*/stereo` arrives at **0.0 s**, not "near the end of a dump
  that streams for many seconds" as `register_promptly_reported` says.
  The condition *not* measured is a cold **device** -- this was an
  already-enumerated interface with only the backend restarted -- and
  `LINK_SYNC_BLIND_DELAY = 20` exists for the hotplug case. So the
  constant stands and the measurement is in
  `tests/data/refresh-dump.json` with its conditions attached. Settling
  it needs one measurement after a real replug.
- **The discrepancy went unseen because the verify loop hides it.** It
  exits as soon as the *prompt* set matches, so `/playback/*` was never
  looked at -- the classification made itself true.

### A. The fault cases that tear state, not just packets

*Today:* `tests/test_faults.py` disturbs the **transport** -- datagrams
dropped, duplicated, reordered, drowned in noise, and a peer that never
answers. Every one of those leaves the process intact and the state
machine untouched.

*Missing:* the three cases from item 5 that break state while a
transaction is open, which is the shape every defect this project has
actually shipped had:

- the backend killed **between** the link phase and the mix write, i.e.
  during the one window where the routing is knowingly half-applied
- the device unplugged **during** the read-back, while `/refresh` is
  still streaming
- the receive port taken **halfway through** the dump rather than before
  it -- `tests/test_verify.py` only covers "taken from the start", which
  takes the clean early-return path

*Also missing:* the restart soak. Apply the routing N times, assert the
result every time. Nothing in the repository runs one, and no scheduled workflow
exists, although *Proven by* has said "soak on `main`" since the first
draft.

*Proven by:* the three cases in the normal suite; the soak as a scheduled
workflow, not a Makefile target nobody invokes.

*Closed:* the three state-tearing cases are in `tests/test_faults.py`.
The soak is `tests/test_soak.py` driving the real entry point through
start -> `READY=1` -> verify -> SIGTERM -> exit 0, asserting the routing
datagrams byte for byte on *every* cycle, and
`.github/workflows/soak.yml` runs 200 of them nightly plus 15 repeats of
the fault, apply and verify suites. Measured locally: 50 cycles in 61 s,
green. `make soak` exists to reproduce a scheduled failure, not to be
the gate.

### B. What a `routing.conf` promises across versions

*Today:* `config.py` rejects every unknown option and every unknown
section with a `ConfigError` -- exit 2, and `RestartPreventExitStatus=2`
means systemd will not retry. That is correct while the schema is small
and written by hand.

*Why it stops being correct:* 0.3.0 adds `[input:N]`, `[output:N]`,
profiles and `--dump-config`. From then on the file is machine-generated
and travels between machines and versions. A config written by 0.3.0 and
read by a 0.2.0 install produces no routing at all, no restart, and one
line in the journal. For a project whose whole premise is that the text
file is the source of truth, reviewable and diffable, that is a promise
which has never been stated.

*Target:* a compatibility rule, decided in 0.2.0 because this is the last
release in which it is free -- whether the file carries a schema version;
whether an unknown *section* becomes a warning while an unknown *option in
a known section* stays an error; what is promised in each direction.

*Proven by:* a test per direction (a future-shaped config on today's
parser, today's config on a parser that knows more) and an ADR, because
this is a promise rather than an implementation detail.

*Closed:* [ADR 0006](decisions/0006-routing-conf-compatibility.md). An
unknown **section** is a warning and the rest of the file is applied; an
unknown **option in a known section** stays a `ConfigError`. No schema
version field -- the ADR records why, and when to revisit (the first
*incompatible* change to an existing option). A test per direction, plus
one pinning the known option surface so removing a name is a visible
edit. The cost is stated: `[routes:x]`, a typo, is now a dropped route
and a warning rather than an error.

### C. The gate, and the code outside the package

*Today:* three measurement gaps, all small, all pointing the same way:

- `make coverage` measures 91%; `fail_under` in `pyproject.toml` says 84.
  Seven points of erosion the gate would not notice.
- `bin/oscmix-launch` is the least covered file in the repository (63%,
  124 statements). It duplicates ~25 lines of sysfs/procfs helpers on
  purpose, and that decision leaves it outside the package, outside
  `tests/test_architecture.py` and outside the mutation scope. It is now
  the one quiet exception to everything item 1 established.
- `tests/test_contracts.py` calls `pytest.importorskip("hypothesis")`. A
  checkout without the dev requirements runs 271 tests, reports green, and
  has checked no contract at all. CI installs them, so the gate holds
  there -- but a local "all passed" means less than it looks.

*Target:* the ratchet raised to what the suite earns; the launcher either
covered like the rest or declared out of scope *in writing*; a skipped
contract suite that says so loudly.

*Closed:* the ratchet is 94 against a measured 94% (`fail_under` in
`pyproject.toml`, with the reason for the jump written next to it). The
launcher moved into the package -- so it is inside the architecture
test, the mutation scope and the coverage -- and
`tests/test_launcher.py` took it from 61% to **100%**, including every
refusal path a user meets after a desktop double-click. The hypothesis
skip is loud: without it the terminal summary prints what did not run
and why, and `OSCMIX_REQUIRE_CONTRACTS=1` turns the skip into a
collection error. CI sets it on the test and coverage jobs.

### D. Releasing 0.2.0

*Today:* the version and the changelog are in place. What is not: the
three artifacts that this document's *proven by* clauses name -- the
hardware evidence, the built oscmix revision, the mutation score -- have
no defined place in a release. `make verify-hardware` exists and its
verdict arithmetic is under test, but no measured artifact has ever been
attached to anything.

*Target:* a release checklist stating what must exist before a tag,
including the rule from item 4 that a routing change is not done until its
measurement is in the release.

*Also:* two of the nine items above were *decisions*, not tasks, and
neither has a record -- why performance gates measure growth order rather
than wall-clock time, and why the upstream revision is pinned. Both belong
in `docs/decisions/`, for exactly the reason item 9 gives.

*Closed, except the artifact itself:* `docs/RELEASE-CHECKLIST.md` states
what must exist before a tag, in six stages, and names what is
deliberately *not* on it. The two missing decisions are
[ADR 0007](decisions/0007-growth-order-not-wall-clock.md) (growth order,
not wall-clock) and
[ADR 0008](decisions/0008-pinned-upstream-revision.md) (the pin, and the
bump rule).

*Measured (2026-08-16), against pinned revision 2411b12 on a UCX II
(24216011):* `krk-monitors` (outputs 5/6) and `phones` (7/8) pass, each
output responding **119.2 dB** to its own side of the tone and nothing
to the other. `main-out` (1/2) fails.

It fails truthfully: `/output/1/volume` and `/output/2/volume` are at
**-65.0 dB**, the fader shut on a rear output. That is user state -- the
route declares no `volume`, so ADR 0003 leaves the fader alone -- and
the routing itself is applied. But the run also exposed a defect in the
tool: it blamed "other audio on the bus" for a silence it had the
information to explain. `LevelReader.output_state()` now reads volume
and mute for every measured output and the verdict names the cause.

*Still open:* the artifact needs a release to be attached to, and one
decision that is not the tool's to make -- whether `main-out` should
carry a `volume` (pinning the fader open), be removed, or stay as a
route whose output is deliberately off, in which case the checklist's
"every route `ok: true`" needs a way to say so.

### E. When the upstream pin moves

*Today:* the pin is set, verified at checkout, and recorded in the
evidence artifact. What is nowhere written is when it may move.

*Target:* a bump requires a fresh hardware measurement. Otherwise the
artifact describes a binary that is no longer shipped, and three bumps
quietly restore the situation the pin was introduced to end. The same rule
governs the upstream work below: if the cache-synchronisation patch is
accepted, the order is bump, measure, *then* delete `LINK_ECHO_TIMEOUT`,
`LINK_SETTLE` and `LINK_SYNC_BLIND_DELAY`.

*Small, same item:* the pin forces `install.sh` into a full clone, because
`--depth 1 --branch` accepts a branch or a tag but not a commit. `git
init` plus `git fetch --depth 1 origin <sha>` gets the shallow clone back.

*Closed:* the bump rule is [ADR 0008](decisions/0008-pinned-upstream-revision.md),
including the ordering for the upstream patch (bump, measure, *then*
delete the constants). `install.sh` has its shallow clone back via `git
init` + `git fetch --depth 1 origin <sha>`, with a fallback to a full
clone for servers that refuse a bare SHA. Measured against upstream: one
commit and 480K of `.git` instead of the full history at 632K.

### F. "The session writes nothing" has an expiry date

*Today:* the unit runs with `ProtectHome=read-only` and an empty
`ReadWritePaths`, and `docs/SECURITY-MODEL.md` states that the session
writes nothing. Both are true of what the session does today.

*Target:* profiles, `--dump-config` writing to a file and any cached state
all need a writable path. That is a 0.3.0 conversation, but the security
model should record *now* that this is a property of the current feature
set, and where it would have to be renegotiated -- otherwise the first
feature that needs a file will quietly widen the sandbox instead of
arguing for it.

*Closed:* `docs/SECURITY-MODEL.md` now says that "writes nothing" is a
property of today's feature set, names the four questions the first
writable path has to answer (does the *service* need it or only the CLI;
`StateDirectory=` rather than a hand-written path; the config itself
stays read-only; partial writes), and points at the assertion that keeps
the sandbox from widening quietly -- which did not exist and now does
(`test_the_service_declares_no_writable_path`).

### G. The dry run is not the path it claims to check

*Today:* the cheapest end-to-end assertion in CI greps `--dry-run` output
to prove that links go out before the mix matrix -- the guard against the
defect that silenced every even output. It checks the wrong artifact.
`_print_dry_run` walks `route_messages(route)` route by route and prints
links, mix, links, mix. `apply_routing` sends *every* link of *every*
route, waits for the barrier, then sends every mix. With the one-route
example config the two agree by accident. With two routes, measured on
this revision:

```
dry run:    /playback/1/stereo  /output/1/stereo  /mix/1/playback/1
            /playback/3/stereo  /output/7/stereo  /mix/7/playback/3

real order: /playback/1/stereo  /output/1/stereo
            /playback/3/stereo  /output/7/stereo   <- barrier ->
            /mix/1/playback/1   /mix/7/playback/3
```

*Target:* one function produces the order and both the dry run and the
apply consume it, so the printed sequence *is* the sent sequence.

*Proven by:* a contract test asserting that the dry-run lines are exactly
the datagrams `apply_routing` sends, in the same order -- plus a second
route in the config CI uses, because a single route cannot exhibit the bug
class this check exists for.

*Closed:* `routing_plan()` produces the order and both the dry run and
the apply consume it. A contract test asserts the printed lines are
exactly the datagrams `apply_routing` puts on the wire, in the same
order, over three routes; reverting `_print_dry_run` to the old walk
fails it at index 2. CI's dry run moved to `tests/data/two-routes.conf`
and asserts *last* link < *first* mix rather than one link < one mix.

### H. The timing budget has to compose

*Today:* eight waits (`DEFAULT_DEVICE_TIMEOUT` 30 s, `PORT_READY_TIMEOUT`
10 s, `LINK_ECHO_TIMEOUT` and `LINK_SETTLE` 1.5 s, `VERIFY_SETTLE`,
`VERIFY_TIMEOUT` 10 s, `LINK_SYNC_BLIND_DELAY` 20 s, `CHILD_STOP_GRACE`
5 s) and two systemd deadlines (`TimeoutStartSec=75`, `TimeoutStopSec=10`).
The relationship between them lives in a comment in the unit file. The
defaults fit -- device wait plus port wait plus barrier is ~41.5 s of the
75 -- but `--timeout` is a command-line argument, so an edited `ExecStart`
can push the start past the deadline and have the unit killed *during* the
apply. That is item **A**'s torn state, reached by editing a number.

*Target:* the budget as an assertion in the shape `tests/test_unit_file.py`
already uses: parse the unit, read the constants, assert that the
worst-case path to `READY=1` fits inside `TimeoutStartSec` with margin and
that `CHILD_STOP_GRACE` fits inside `TimeoutStopSec`.

*Closed:* `constants.startup_budget()` sums the waits on the path to
`READY=1` -- **42.0 s** against `TimeoutStartSec=75`.
`tests/test_unit_file.py` parses the unit and asserts the budget fits
with at least 10 s of margin, that `ExecStart`'s own `--timeout` fits
(so raising it past ~53 s fails the suite rather than the service), that
`CHILD_STOP_GRACE` plus one poll step fits inside `TimeoutStopSec`, and
that the sum still names every term. Verification's exclusion is
asserted *structurally* rather than arithmetically -- `READY=1` follows
the apply in the same block and `_apply_and_verify` still defers to a
thread -- because with 33 s of margin the arithmetic would pass either
way.

### I. The background verifier has no stated contract

*Today:* `_apply_and_verify` starts `verify_and_repair` on a daemon
thread. It reads `stop_requested` and `child.poll()` exactly once, before
starting. What follows can run for two verification windows plus a blind
delay and issues writes at three points: `send_mix` from the observer,
`send_mix` when the dump never reported the links, and a full
`apply_routing` retry. A `systemctl --user stop` in the first half minute
after a hotplug therefore terminates the backend while the verifier is
still writing routing at it, and the process exits when `supervise`
returns -- cutting the daemon thread wherever it happens to be.

Nothing here is known to break; the writes go to loopback UDP and a dead
port is silent. But *"the mix is never left half-applied"* is the property
the whole two-phase design exists for, and on this path nobody states it.

*Target:* one written rule -- the verifier checks `stop_requested` between
phases and before every write, and the session does not exit until the
verifier has stopped or its deadline passed. Item **A**'s kill-mid-apply
case then has something to assert against.

*Closed:* [ADR 0009](decisions/0009-verifier-stop-contract.md), and the
code to match. The verifier asks `should_stop()` between every phase and
before each of the three writes, and every wait wakes early
(`wait_unless_stopped` replaced the sleeps -- the blind delay is 20 s
against a `TimeoutStopSec` of 10, and it is the path a *user* hits,
because it is taken when the mixer GUI holds the port). `run_session`
joins the verifier for `VERIFIER_STOP_GRACE` (2 s) before exiting; 2 + 5
fits inside 10, asserted against the unit file. A dead backend counts as
a stop.

### J. Nothing proves the unit starts, or that an install works

*Today:* `tests/test_unit_file.py` reads the unit as text. That catches
the directives known to break a user unit; it cannot catch a typo in a
directive name and it starts nothing. `install.sh` is likewise tested for
its shape but never run end to end -- in a release that moved the runtime
from `lib/` to `src/` and rewrote that path in three places.

*Target:* `systemd-analyze verify` on the unit in CI, and an install smoke
test: run `install.sh --no-build --no-udev` into a temporary `HOME`, then
assert the installed file set and that `oscmix-session --dry-run` runs
from it.

*Closed:* `scripts/verify-unit.sh` runs `systemd-analyze verify --user`
and fails on anything it says about this unit -- necessary because the
tool reports an unknown key on stderr and still exits 0, so the exit
status is not a gate. Wired into the quality job, where a missing
`systemd-analyze` is a failure rather than a skip. Three install tests
now run what `install.sh` produced, from a directory that is not the
checkout: the session's `--dry-run`, the launcher's device-absent path
(which would die with `ImportError` if `launcher.py` had not been
installed), and the module set matching `src/` exactly.

### K. The mutation baseline predates half the suite

*Today:* 677 mutants count as `not_covered` because `cli`, `session` and
`process` were reachable only through a subprocess. That was measured
before `tests/test_lifecycle.py` and `tests/test_process.py` existed, and
both drive those modules in process. The floor of 0.72 is set against a
run that no longer describes this suite.

*Target:* re-run and re-baseline. The expectation is that `not_covered`
shrinks rather than that the score moves; if it does not shrink, the
reason is worth knowing before the number is trusted again.

### L. "Promptly reported" is folklore that could be a fixture

*Today:* `register_promptly_reported` encodes which register families the
device dump reports in time, and that decides whether a missing register
is a warning or a note. It is a hand-maintained list, measured once
against a UCX II, checked against nothing.

*Target:* now that the backend revision is pinned, a recorded `/refresh`
dump from exactly that revision belongs in the repository as a fixture,
and the classification becomes a test against it rather than a memory. It
is also what the verification classes in 0.3.0 should be derived from,
instead of being written out a second time by hand.

*Closed:* `scripts/record-dump.py` and `tests/data/refresh-dump.json` --
a real dump from the pinned revision, recorded as register *shape* and
arrival times, never values. It separates the 70 continuously streaming
meter registers from the dump itself, which a first attempt did not:
54970 messages in 60 s, and the dump never went quiet because the meters
never stop.

Confirmed against 2411b12 on a UCX II (24216011), 2002 registers:
`/mix/*/playback/*` absent as the two-phase design assumes;
`/mix/*/input/*` present (400 registers) as 0.3.0 assumes; `48v`,
`hi-z`, `reflevel`, `gain`, `mute`, `phase` all present; `name` and
`loopback` absent, i.e. still write-only. `tests/test_recorded_dump.py`
binds the classification to that measurement in the direction that
matters -- a register the dump never reports may never be called prompt,
or the verifier warns and re-sends on every single run -- and holds the
1.9 s finding above in place with its conditions.

## Decisions that are free now and expensive later

**Draft, 2026-08-16. None of these is decided.** They are here for the
reason item **B** turned out to be right: each one costs a paragraph
today and a migration after 0.3.0. Item B was the only one of the twelve
that was a *promise* rather than a task, and it was the one that would
have been unfixable a release later.

### Two writers, one device

*Today:* this project writes the routing at start, and through the
verifier for up to a minute after. `oscmix-gtk` writes whenever the user
turns something. Neither knows the other exists. The device takes the
last write, and nothing anywhere states who is supposed to win.

That stays invisible for one reason: this project writes at start and
then stops. `routing.conf` is not a *desired state* that is maintained,
it is an *initial state* that is applied. The difference does not show at
six registers wide.

*What makes it visible:* the pin/remember model in 0.3.0. "`48v` wants
pinning" is a statement about what happens **after** start, when
something else has changed it. With a start-only writer, `pin` means "set
once, then hope" -- which is not what the word says, and is not more than
TotalMix already offers.

*Three positions, in increasing cost:*

- **Start-only, stated.** Applied at every start, the GUI always wins
  afterwards. Cheapest and perfectly honest -- but then the option is
  not called `pin`.
- **Reconcile on a signal.** Re-apply on hotplug, on resume, on a sample
  rate change, on `SIGHUP`. Never on a timer. Bounded, explainable, and
  it covers the cases where state is actually lost.
- **Continuously reconcile.** The device snaps back within a second of
  any GUI change. Maximally declarative, and the point where the two
  writers genuinely fight: a user watching a knob undo itself files a
  bug, not a compliment.

*What would settle it, and it is measurable today:* does a GUI-initiated
change show up as a report on the receive port? The device reports on
change, so it should -- but this is one measurement, not an argument.

It cannot be done with `scripts/record-dump.py`, which binds UDP 8222 and
therefore cannot run while the GUI holds it. Sniff the loopback instead,
which is how the three 0.1.3 defects were found in the first place:

    sudo tcpdump -i lo -n -s 0 -U -w gui.pcap 'udp port 8222'
    tshark -r gui.pcap -T fields -e udp.payload -Y udp.dstport==8222

Turn one fader in oscmix-gtk and the answer is in the capture. If the
reports arrive, position two is cheap and position three is possible at
all; if they do not, only position one is honest.

### Sample rate and clock changes destroy state

*Today:* nothing in this repository says what happens to the mixer when
the clock source or the sample rate changes. 0.4.0 lists "clock source"
as a *feature to declare*, which is a different thing from the *event* it
is.

*Why it belongs here:* a sample rate change is the routine way a Fireface
loses mixer state in ordinary use -- more routine than a reboot, which
this project handles, and more routine than a hotplug, which it also
handles. A project whose premise is "the state survives" has an
unexamined hole exactly where the state does not survive.

*Open, and unmeasured:* does the UCX II reset the matrix on a rate
change, and which registers survive it? `/clock/samplerate` is in the
dump, so a session can *see* the change happen. What it should do about
it is the reconciler question above, in its first concrete instance --
which is why these two are one decision, not two.

*A first step that needs no decision:* notice it and log it. A session
that reports `/clock/samplerate` changing costs nothing and turns a
future "the routing was gone after I switched to 96k" into a readable
journal.

### More than one Fireface

*Today:* the udev rule, the unit and `routing.conf` are singletons. Two
interfaces on one host is not supported, and not refused either. It is
undefined, which is the worse of the two.

*Why the timing matters:* the answer is a template unit
(`oscmix@.service`) with the device instance as `%i` and the config path
derived from it. Today that is a rename and a path change. After profiles
land it is a rename, a path change, a config schema change and a
migration for every existing user.

*The decision is not "implement it".* It is whether the single-device
assumption is **stated as a limit** in the README and the config, or
**designed out** while it is still a rename. Both are defensible.
Silence is not, and silence is what ships today.

### The upgrade path is untested, in the release that moves everything

*Today:* 0.2.0 moves the runtime from `lib/` to `src/` and rewrites that
path in three places. `install.sh` is now smoke-tested end to end -- but
into an *empty* `HOME`. Nobody has run it over an existing 0.1.3 install,
which is what every current user will do exactly once.

*The specific risks, none of them confirmed:* a stale `lib/` tree left
behind and still resolving first; a running unit that keeps the old code
until it is restarted rather than reloaded; and a `routing.conf` written
against 0.1.3 now read under ADR 0006's rules.

*Target:* one more case in the install smoke test -- install `v0.1.3`,
install this revision over it, then assert what the empty-`HOME` case
asserts. It is the cheapest test in the release, and it covers the one
path taken by everybody who already has this installed.

## Upstream is part of the quality goal, not the weather

Four of the six constraints below are upstream limits: the playback
matrix cannot be read back, the register cache does not self-synchronise,
a dump is slow enough to have to be waited out, the Room EQ registers are
implausible. The ceiling on "provably correct" is therefore set by code
this project does not own. Treating that as given would cap the whole
effort.

So, as work items rather than complaints:

- **Offer the cache-synchronisation patch.** `setbool` not updating
  oscmix's own view is the single root cause of `LINK_ECHO_TIMEOUT`,
  `LINK_SETTLE` and `LINK_SYNC_BLIND_DELAY`. Upstream accepting a patch
  that syncs link state on write would delete that entire class of
  timing constant from this codebase.
- **File the Room EQ and `unexpected enum value -1` issues** before
  0.4.0 builds on those registers.
- **Ask for a targeted register query.** `/refresh` dumps 2002 registers
  when what this project needs is a handful of `/output/<n>/stereo`.
  That is a feature request, not a benchmark -- see the reframing of
  point 7 above. **Worth less than this document assumed:** the ask was
  sized against a 15-20 s dump, and the measurement says 1.9 s on a warm
  device. Settle the cold-hotplug case first (the finding under Still
  open); if the dump is fast there too, this is a tidiness request rather
  than a fix, and the cache-synchronisation patch above is the one that
  earns its keep.

## Structural work before the surface grows (0.3.0)

Three refactors that are cheap now and expensive after the feature work.
They belong to the same window and largely to the same session.

### A backend seam

The OSC calls should sit behind a narrow interface, so the dependency on
oscmix's behaviour is visible and replaceable rather than spread through
the control flow. Two reasons beyond tidiness: the timing constants above
exist purely because of an upstream implementation detail, and a seam is
what makes the option below cheap to keep open.

**The option worth keeping open** is not a competing mixer. It is an own
*state path*: writing and reading the two dozen registers this project
actually pins directly over SysEx, while oscmix keeps the GUI and
metering. That removes the dual-writer problem, makes read-back possible
where upstream does not dump, and kills the cache race at the root. The
cost is owning register decoding for devices that cannot be tested here,
which is why it is not worth doing today -- and exactly why the seam and
the register model go in while the surface is still small.

### The register model as data

The channel-state work multiplies the register surface by roughly ten.
Which channels have `48v` (1-2), `hi-z` (3-4), `reflevel` (3-8), which
registers the device reports back and which are write-only -- all of that
is currently knowledge in prose, spread across format strings in
`routing.py`, ranges in `constants.py` and the known-not-prompt families
in `verify.py`. It belongs in one data structure that validation,
`--dump-config` and verification all read, introduced *before* ten times
as much of it exists.

**Indexed by device from the first line.** `48v` on 1-2 and `hi-z` on 3-4
are UCX II facts, not Fireface facts. A model without a device dimension
casts this one interface into the data structure and puts the untested 802
permanently out of reach -- in the very refactor that could have brought
it closer.

### Desired state, observed state, plan

What this project *is*, is a reconciler: desired state from the config,
observed state from the dump, the difference applied. What the code does
is four partly overlapping paths over the same data -- `apply_routing`,
`send_mix`, `blind_reapply_mix` and `verify_and_repair`.

Stated as `desired(config)`, `observed(dump)` and `plan(desired,
observed)`, apply and verify become one path -- and two planned features
fall out of it instead of becoming paths five and six: `--dump-config`
(0.3.0) is `observed()` rendered as config, and `--diff` (0.4.0) is
`plan()` printed instead of sent.

This is also what makes the register model pay for itself: a plan is a set
of registers, and everything above -- validation, verification, the pin
and remember rule -- becomes a property of an entry in that table rather
than a branch in the routing code.

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

**Prerequisite:** item **B**. `--dump-config` makes the file
machine-generated and profiles make it plural; both are unshippable until
the compatibility rule for `routing.conf` is decided.

### What a new register family costs

Every item above multiplies the surface, so the bar for adding one is
fixed in advance rather than argued per feature. A register family is done
when:

1. it has a row in the register model -- path template, type tags, value
   domain, valid channels **per device**, verification class;
2. a contract test states what its config section writes, as written paths
   ⊆ declared paths -- the rule the `volume` bug produced;
3. the round trip covers it: `--dump-config` → apply → dump is a fixed
   point;
4. if it is audible, a case in `verify-hardware` and a line in the
   release's evidence artifact;
5. if a decision had to be made, an ADR.

None of that is new machinery invented for 0.3.0. It is the 0.2.0
apparatus, applied by default instead of on request.

### Verification classes, declared per register

The dump splits the surface into three classes, and each register says
which one it is:

- **verifiable** -- reported by the dump, so a value is confirmed,
  mismatched or missing. Most of the new surface, `/mix/<out>/input/<in>`
  included.
- **write-only** -- accepted, never reported (`/input/*/name`,
  `/output/*/name`, `/output/*/loopback`). The verifier reports
  *unverifiable*, never *confirmed*.
- **re-established** -- the playback matrix: unverifiable *and* dependent
  on link state, so it is rewritten from a known-good state rather than
  checked.

Naming the class is what keeps verification from over-claiming as the
surface grows. Today that distinction lives in `register_promptly_reported`
and in prose, which is fine for six registers and not for sixty. It should
be derived from the recorded dump of item **L**, not typed out twice.

### Dangerous registers get their own rule

`48v` is a register like any other to the protocol and nothing like any
other to a ribbon microphone. Before phantom power is settable from a text
file:

- **it is never implied.** No default, no profile fallback, no
  pin-everything mode turns it on; only an explicit `48v = true` on that
  channel does.
- **it is applied last**, after the routing verified, and logged at
  warning level naming the channel.
- **turning it off is never deferred or retried away.** An unapplied
  disable is a louder failure than an unapplied enable.
- **a hardware case proves the channel it names is the channel it hits.**
  An off-by-one here is not a silent output, it is damaged equipment.

Anything else that can hurt equipment or ears belongs in the same class:
`reflevel` changes and volume jumps on an active monitor path, muted
across the change wherever the device clicks.

### Profiles are transactions

A profile switch writes a set of registers to a device somebody is
listening to. A half-applied switch is item **A**'s torn state with a user
holding the trigger, so the switch has to state its outcome: applied and
verified, applied but unverifiable (with the list), or refused before
anything was written because the config did not parse. Never "partly, and
here is a traceback".

That also settles what `--dump-config` does with the registers a config
does not mention -- it is the same question as the pin/remember model, and
the answer belongs in the register table, not in the writer.

### What "supported" means for a device

Today the 802 is "untested", which is honest and unbounded. A
device-indexed register model turns that into a bar: a device is supported
when its register table is declared, its channel capabilities are
recorded, and one hardware evidence artifact exists for it. Below that
line it is "may work", stated in the README -- and no register table is
merged that silently assumes UCX II channel counts.

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
- **Matching TotalMix FX feature for feature *in this repository*.** A
  knob to turn is a GUI's job; this project's job is the state behind it.

  That is a division of labour, **not a ceiling on the stack**. The
  goal for oscmix + oscmix-gtk + this project together is to be at least
  as complete as TotalMix FX and better where being declarative and
  verifiable wins -- see [the bar is the
  stack](#the-bar-is-the-stack-not-this-repository), which puts numbers
  on how much of the device surface is already within reach. Every row
  in that matrix has to land somewhere; a non-goal here is a statement
  about *which component owns it*, and it is only honest as long as some
  component does.

## Known constraints and upstream issues

All measured, all things the design has to live with:

- **The playback mix matrix cannot be read back.** A `/mix` write draws no
  reply and the dump omits `/mix/*/playback/*`. It can only be
  re-established from a known link state, never verified. Input routing
  does not share this limitation.
- **oscmix does not sync its register cache on its own.** It learns the
  device's values only from a `/refresh` dump. How long that takes is
  **measured at 1.9 s** for 2002 registers on a UCX II whose backend was
  restarted (`tests/data/refresh-dump.json`), against the ~15-20 s this
  document asserted from an earlier, unrecorded observation. The
  unmeasured case is a cold device after a replug, which is what
  `LINK_SYNC_BLIND_DELAY = 20` is sized for, so the constant stands until
  somebody measures a real hotplug.
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
