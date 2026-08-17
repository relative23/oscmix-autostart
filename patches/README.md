# Patches offered upstream

Changes to [michaelforney/oscmix][oscmix] that this project would like to
see, kept here so the reasoning survives whether or not they are
accepted, and so the measurement that justifies each one is in the
repository rather than in a pull request thread.

Each patch is against the pinned revision
`2411b12d8a13b82829caf3b0b628078980c3d3a4`.

---

## 0001 -- update our view of output stereo on write

**Status:** written, built, and measured. Not yet offered.

### What it changes

`{"stereo", OUTPUT_STEREO, .set=setbool, ...}` becomes
`.set=setoutputstereo`, a 28-line function that updates `outputs[].stereo`
before forwarding the register -- exactly what `setinputstereo()` already
does for inputs.

**Nothing changes on the wire.** `setval()` still forwards the register
unchanged; only oscmix's own view is corrected at the point of the write.
That is what makes this a consistency fix rather than a design change.

### Why it matters here

`setlevel()` reads `out->stereo` to decide whether a `/mix` write
addresses one channel or the pair. Unpatched, that flag only changes when
the *device* echoes the register back over MIDI. A `/mix` arriving in
between takes the unlinked branch, writes `mix[0]` and never touches
`mix[1]` -- the pair's right channel is left alone.

That is this project's most expensive shipped defect: **every even output
silent**. Three constants exist solely to work around it --
`LINK_ECHO_TIMEOUT`, `LINK_SETTLE` and `LINK_SYNC_BLIND_DELAY` -- along
with the two-phase apply and the barrier between the phases
([ADR 0001](../docs/decisions/0001-two-phase-routing-apply.md)).

### The measurement

Two attempts at demonstrating this through audio failed, and both
failures are worth recording because they are why the third approach was
chosen:

1. Played a tone into `oscmix.krk-monitors`, which feeds **playback 5/6**,
   while writing a mix from playback 1. The signal path carried nothing
   and the -56 dB of crosstalk read as a pass.
2. Fixed the sink, but the race was masked: writing `mix[0]` only does
   not *clear* `mix[1]`, so the value left by the preceding control
   measurement kept the right channel audible.

Audio is a consequence of the bug, and consequences can be masked. The
third approach observes the mechanism itself -- `fprintf` of
`out->stereo` inside `setlevel()`, then `/output/5/stereo=1` immediately
followed by `/mix/5/playback/1`, on a Fireface UCX II:

```
unpatched:  PROBE setlevel out=5 stereo=0     <- pair just linked, view stale
patched:    PROBE setlevel out=5 stereo=1
```

The instrumentation is not part of the patch.

### What acceptance would allow here

Not a deletion, and not immediately. [ADR 0008](../docs/decisions/0008-pinned-upstream-revision.md)
fixes the order: **bump the pin, measure on hardware, then** remove
`LINK_ECHO_TIMEOUT`, `LINK_SETTLE` and `LINK_SYNC_BLIND_DELAY`. Doing it
the other way round would delete the workaround for a fix this project
has not yet shipped against.

[oscmix]: https://github.com/michaelforney/oscmix
