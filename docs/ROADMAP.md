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
| runtime layout | 1386 lines, one file | 14 modules, 1726 lines, 52-line shim |
| longest function | 106 lines | 70 (`verify_and_repair`), exactly at the ceiling |
| tests | 118 | 283 cases from 194 test functions |
| coverage | 65% (subprocess unmeasured) | 91% measured, gate still set to 84 |
| `mypy --strict` | 12 errors | clean, 14 files |
| mutation score | not runnable | 0.728, floor 0.72 |
| upstream backend | `master`, unpinned | pinned commit, verified at checkout |
| hardware evidence | done by hand, once | committed tool, no artifact in a release yet |
| structural guarantees | comments | 60+ assertions |

Two of those numbers do not yet match a claim made below -- the coverage
gate and the missing evidence artifact. They are items **C** and **D** in
[Still open](#still-open-in-020).

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

*Left over:* the ratchet was never actually raised. It still says 84
while the suite measures 91 -- see **C** below.

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

### 5. Stability -- **half done**

*Was:* a flakiness gate runs the suite five times. There is no fault
injection and no soak. Every failure mode found so far -- the link race,
two teardown races, the stub signal race -- was a timing bug.

*Target:* deliberate fault injection (drop, duplicate and reorder UDP
datagrams; kill the backend mid-apply; unplug the device mid-verify;
occupy the receive port halfway through) and a restart soak that applies
the routing N times and asserts the result every time.

*Done:* `tests/test_faults.py` -- drop, duplicate, reorder, a flood of
unrelated registers, a device that never answers, a dead backend port.

*Not done:* every case in that list that breaks **state** rather than
**transport**, plus the soak. See **A** below; this is the one item of the
nine that 0.2.0 should not claim.

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
the 1.5 s link barrier and the 15-20 s dump, none of which a benchmark
against a stub would touch. A hard wall-clock budget on a shared runner
would mostly measure the runner -- a new flake source in a project whose
bugs are already timing bugs.

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

The first three are the ones that would embarrass this release if someone
looked: a stability item claimed as done, a CI check that guards the
project's most expensive bug by inspecting the wrong artifact, and a
coverage gate seven points below what the suite earns.

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

## Upstream is part of the quality goal, not the weather

Four of the six constraints below are upstream limits: the playback
matrix cannot be read back, the register cache does not self-synchronise,
a dump takes 15-20 s, the Room EQ registers are implausible. The ceiling
on "provably correct" is therefore set by code this project does not own.
Treating that as given would cap the whole effort.

So, as work items rather than complaints:

- **Offer the cache-synchronisation patch.** `setbool` not updating
  oscmix's own view is the single root cause of `LINK_ECHO_TIMEOUT`,
  `LINK_SETTLE` and `LINK_SYNC_BLIND_DELAY`. Upstream accepting a patch
  that syncs link state on write would delete that entire class of
  timing constant from this codebase.
- **File the Room EQ and `unexpected enum value -1` issues** before
  0.4.0 builds on those registers.
- **Ask for a targeted register query.** `/refresh` dumps everything for
  15-20 s when what this project needs is a handful of
  `/output/<n>/stereo`. That is a feature request, not a benchmark --
  see the reframing of point 7 above.

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
