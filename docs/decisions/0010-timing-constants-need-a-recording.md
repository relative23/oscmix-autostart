# 0010 -- A timing constant needs a recording, not a recollection

**Status:** accepted (0.2.0)

## Decision

Every constant in `constants.py` that waits for the *device* names the
recording it was derived from, and a test asserts the margin between the
two. Changing such a constant means producing a new recording; it is not
a tuning exercise.

The first one to be held to this is `LINK_SYNC_BLIND_DELAY`, which goes
from **20 s to 5 s**.

## Why

The 20 s was not wrong on purpose. It came from the same session that
produced the "the dump streams for ~15-20 s" line, which this repository
then repeated in `constants.py`, `docs/OSC-PROTOCOL.md`, ADR 0002, ADR
0007 and the roadmap. One unrecorded observation, propagated into five
documents and one default, and nothing anywhere could check it.

Measured properly -- `tests/data/cold-plug-timeline.json`, a real USB
replug with tcpdump on **both** OSC ports so a request can be told apart
from a device push:

| | |
|---|---|
| `/playback/*/stereo` | **0.00 s**, unprompted, before the session sent anything |
| session's `/refresh` | 2.25 s |
| `/output/*/stereo` back | **2.26 s** -- 0.01 s after being asked |
| dump complete | ~4 s |
| anything further | nothing, over the remaining 272 s |

So the wait was nine times the thing it waits for.

## Why 5 and not 3, or 2.5

5 s is not tuned to 2.26 s; it is the smallest round number that keeps
better than a 2× margin. The two errors are not symmetric:

- **Too short** rewrites the mix against a link state that has not
  synchronised -- the defect that silenced every even output, which is
  the most expensive bug this project has shipped.
- **Too long** delays the re-established routing by a few seconds on a
  path that has already applied the mix once.

So the margin is deliberate and the direction of the bias is chosen. It
is not "as low as the measurement allows".

## The upper bound is the new part

`tests/test_recorded_dump.py` asserts the margin is **at least 2× and at
most 10×**. The lower bound is obvious. The upper bound is the one that
would have caught this: a wait an order of magnitude past its evidence is
not caution, it is an unmeasured number wearing caution's clothes.

Without it, "make the timeout generous" is always locally defensible and
the number never comes back down.

## Where this does not apply

Constants that wait for *systemd*, a *subprocess* or a *socket* are not
covered: `CHILD_STOP_GRACE`, `PORT_READY_TIMEOUT`, `VERIFIER_STOP_GRACE`.
They are bounded by `tests/test_unit_file.py` against the unit file
instead, which is the right evidence for them.

`LINK_ECHO_TIMEOUT` and `LINK_SETTLE` (1.5 s) are device waits and do
fall under this rule, but they are *opportunistic* -- a timeout there is
normal, not a failure, because the device reports a register only when it
changes. They are left alone: the recording shows the echo arriving well
inside 1.5 s, and shortening a barrier whose timeout is the expected case
buys nothing.

## What this rules out

- Raising a device wait "to be safe" without a recording that shows the
  device needs it.
- Keeping a constant whose justification is a sentence in a document
  rather than a file in `tests/data/`.
- Bumping the upstream pin without re-recording. ADR 0008 already
  required a fresh hardware measurement for a bump; this adds that the
  timeline is part of it, because a backend that changes how it syncs
  changes what these numbers should be.

## Enforced by

- `tests/test_recorded_dump.py::test_the_blind_delay_is_derived_from_the_timeline_not_from_folklore`
  -- the 2× and 10× bounds.
- `tests/test_recorded_dump.py::test_the_pinned_revision_is_the_one_the_dump_came_from`
  -- the recording has to describe the shipped backend.
