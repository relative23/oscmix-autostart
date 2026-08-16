# 0003 -- A route rewrites only the registers it declares

**Status:** accepted (0.1.2)

## Decision

Applying a routing touches exactly the registers the config names.
Everything else -- mute, EQ, and the output faders unless a route sets
`volume` -- keeps whatever the user left in the mixer, across restarts.

## Why

The shipped example config carried `volume = 0.0` in its commented
monitor block, so copying it pinned the fader. Every backend start forced
the monitor level back to unity and wiped what the user had set. Measured:
a manual -20 dB came back as 0.0 dB two seconds into the next restart.

The docs at the time said GUI changes "stay active until the next backend
start", which reads as though everything is reset. The real rule is
narrower and more useful, and it is now the contract.

`level` is not covered by this: it is the mix-matrix gain, the routing
itself, and is always written.

## What this rules out

Adding a register to the write set "for completeness". Every new option
is opt-in, and its default is a decision, not an oversight. The pin
versus remember distinction is the open design question for 0.3.0's
channel state.

## Enforced by

`tests/test_contracts.py::test_a_route_writes_only_what_it_declares`,
as a property over generated routes.
