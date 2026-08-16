# 0009 -- The background verifier stops between phases, and the session waits for it

**Status:** accepted (0.2.0)

## Decision

Two rules, one on each side of the thread boundary:

1. **The verifier asks `should_stop()` between every phase and before
   every write.** It never starts a write it was told not to start, and
   every wait it performs wakes early on a stop rather than running out.
2. **The session does not exit until the verifier has stopped or
   `VERIFIER_STOP_GRACE` (2 s) has passed.** Exiting while the verifier
   may still be writing is what the rule above exists to prevent, and a
   daemon thread does not stop the process from exiting on its own.

A dead backend counts as a stop. Its port is gone, so a write from that
point lands nowhere while the log claims a re-apply.

## Why

`_apply_and_verify` starts `verify_and_repair` on a daemon thread. It
read `stop_requested` and `child.poll()` **exactly once, before
starting.** What follows can run for two verification windows
(`VERIFY_TIMEOUT` 10 s each) plus `LINK_SYNC_BLIND_DELAY` (20 s), and it
issues writes at three points:

- `send_mix` from the dump observer, the moment every
  `/output/<n>/stereo` has been reported,
- `send_mix` when the dump never reported the links at all,
- a full `apply_routing` retry when registers came back unconfirmed.

So a `systemctl --user stop` in the first half minute after a hotplug
terminated the backend while the verifier was still writing routing at
it, and the process exited when `supervise` returned -- cutting the
thread wherever it happened to be, which can be between two mix writes
of the same route.

Nothing here was known to break. The writes go to loopback UDP and a
dead port is silent, so the observable damage was zero. That is exactly
why it needed writing down rather than fixing quietly: **"the mix is
never left half-applied" is the property the whole two-phase design
exists for**, and on this path nobody stated it. A property that holds
by accident is one refactor away from not holding, and this project's
three shipped defects were all invisible at message level.

The blind delay is the case that mattered most in practice. It is taken
when the receive port is held -- which means the mixer GUI is open, the
*normal* desktop situation -- and at 20 s it is twice `TimeoutStopSec`.
A `time.sleep` there guaranteed the session was still parked in it when
systemd gave up.

## The numbers have to compose

`CHILD_STOP_GRACE` (5 s) + `VERIFIER_STOP_GRACE` (2 s) = 7 s, inside
`TimeoutStopSec` (10 s). Without that, systemd would kill the session
during the very wait that exists to keep it from being killed
mid-write. `tests/test_unit_file.py` asserts it against the unit file
rather than against memory.

2 s is a bound on being wrong, not an expected duration. Once a stop is
requested the verifier returns within one socket timeout (0.25 s): the
dump window checks at the top of its loop, and every sleep became
`wait_unless_stopped`.

## What this rules out

- A `time.sleep` anywhere on the verifier's path. Use
  `wait_unless_stopped`.
- Adding a fourth write point without a check in front of it. The three
  are numbered in the source for that reason.
- Making the verifier non-daemon to "fix" the exit. That would trade a
  cut thread for a hung shutdown, which systemd resolves with SIGKILL at
  `TimeoutStopSec` -- the same cut, 10 seconds later.

## What it deliberately does not do

It does not make the verifier's work transactional. A stop mid-verify
still leaves the routing exactly as `apply_routing` left it in the
foreground, which is a complete application of every route -- the mix
matrix is unverifiable anyway (ADR 0002) and is re-established rather
than checked. The contract is about not *starting* work during a
shutdown, not about undoing it.

## Enforced by

`tests/test_faults.py`:

- `test_a_stop_between_the_phases_prevents_every_further_write` -- all
  three write points, none of them reached.
- `test_the_verifier_runs_normally_when_nothing_asks_it_to_stop` -- the
  check is not so eager that it breaks the repair it guards.
- `test_the_blind_delay_is_abandoned_on_a_stop`
- `test_the_dump_window_ends_when_a_stop_arrives`
- `test_the_session_waits_for_the_verifier_before_exiting` -- including
  that the grace fits beside `CHILD_STOP_GRACE`.
