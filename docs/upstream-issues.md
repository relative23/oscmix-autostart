# Upstream issues

One issue filed with [michaelforney/oscmix][oscmix], and the record of a
second that was **not** filed because it did not reproduce.

The roadmap treats upstream limits as work items rather than weather. It
also means those items are held to the same standard as everything else
here: an issue that wastes a maintainer's time on an unreproducible
report is worse than no issue.

All observations below are against the pinned revision
`2411b12d8a13b82829caf3b0b628078980c3d3a4` on a Fireface UCX II
(serial 24216011), Linux 7.0.

---

## 1. Fixed upstream: `unexpected enum value -1` from `/controlroom/mainout`

**Status:** the maintainer added optional value lists for enums and
pushed to master on 2026-08-21, after a branch test from here. The
warning also names the OSC address now.

Two things came out of it that outlast the fix.

**On the report itself:** *"The AI text contains a lot of fluff, and
it's hard to tell what's important and what's irrelevant on the first
read through."* The measurements were right and every number held, but
the write-up was some forty lines for a result that needed five, and the
one paragraph he engaged with was the short observation at the end. The
style this repository uses -- counter-checks, taxonomies, methodology
stated so a claim can be re-derived -- is for readers auditing the work.
A maintainer is deciding whether to apply a patch. Short version first,
and in a human's own words.

**On the design:** he replied that oscmix was built to hold as little
state as possible and use the device as the source of truth, "however,
it seems this isn't always possible, so maybe oscmix needs keep its own
complete mirror state." That is the ground under the stereo-link race,
the three timing constants and `patches/0001`. Recorded as a thing to
watch in the roadmap, not as a plan.

---



**Status:** filed as [michaelforney/oscmix#30][issue30] on 2026-08-17.
Reproducible on every start.

[issue30]: https://github.com/michaelforney/oscmix/issues/30

### Title

`unexpected enum value -1` on every start; diagnostic does not say which register

### Body

Running `oscmix` against a Fireface UCX II prints this to stderr on every
start, and repeatedly during `/refresh` dumps:

```
unexpected enum value -1
```

Measured here: **42 occurrences in 24 hours** of ordinary desktop use.

#### Which register

The message does not say, so I found it by asking the device for
everything and looking for the value:

```
/controlroom/mainout    ,i   -1
```

Every other enum register comes back as `,is` with its name, e.g.
`/reverb/type ,is 2 "Large Room"`. This one takes the fallback branch in
`oscsendenum()` (oscmix.c:1440):

```c
if (val >= 0 && val < nameslen) {
        oscsend(addr, ",is", val, names[val]);
} else {
        fprintf(stderr, "unexpected enum value %d\n", val);
        oscsend(addr, ",i", val);
}
```

`CTLROOM_MAINOUT` is declared with ten names, `"1/2"` through `"19/20"`
(oscmix.c:1269). The device reports `-1`, which is outside that range.

#### What -1 probably means

I do not know for certain, and I would rather ask than assert: on this
interface the Control Room main output appears to be **unassigned**, and
`-1` (raw `0xFFFF`) looks like the device's way of saying "none" rather
than a decoding error — every other value in the same dump is plausible,
and the Control Room section is optional on this model.

If that is right, the fix is to give the unassigned state a name rather
than to treat it as unexpected.

#### The part that is a bug regardless

**`oscsendenum()` does not print the address.** Whatever the value turns
out to mean, a message that says only `unexpected enum value -1` cannot
be acted on: there are dozens of enum registers, and nothing in the
output narrows it down. Finding this took a full state dump and a
comparison of type tags.

One line:

```c
fprintf(stderr, "unexpected enum value %d for %s\n", val, addr);
```

That change is useful on its own, independently of what `-1` means here.

#### Reproducing

Any UCX II with no Control Room main output assigned. `oscmix` prints it
at startup without any client interaction.

---

## 2. Filed: Room EQ registers reporting implausible values

**Status:** filed as [michaelforney/oscmix#32][32] on 2026-08-20, with a
mechanism and a before/after measurement.

**It was withdrawn first, and the withdrawal was right on the evidence
at the time.** What follows is the original reasoning, kept intact,
because the way it was wrong is the useful part -- see the resolution at
the end of this section.

[32]: https://github.com/michaelforney/oscmix/issues/32

**Original status:** withdrawn -- does not reproduce.

`docs/ROADMAP.md` carried this as a known constraint and as an upstream
work item:

> **Room EQ registers report implausible values** (+30 dB and +40 dB at
> 50 Hz, Q=80, on every output). This looks like a register offset in
> upstream's decoding rather than real device state.

It was going to be filed. It should not be, because the current
measurement contradicts it. Every EQ and Room EQ register read back from
the device against the pinned revision:

| | count | min | max |
|---|---|---|---|
| `band*gain` | 220 | **0.0 dB** | **0.0 dB** |
| `band*q` | 200 | 0.7 | 5.0 |
| `band*freq` | 200 | 50 Hz | 5000 Hz |
| `roomeq/delay` | 20 | 0.0 | 0.0 |

Zero values outside a plausible range. Not one gain at +30 or +40 dB, no
Q anywhere near 80.

### Why the original observation might still have been real

Three possibilities, and I cannot distinguish them from here:

1. It predates the pin, and the revision it was seen on decoded these
   registers differently.
2. The device held different state at the time -- a loaded TotalMix
   snapshot with real Room EQ settings, misread as implausible.
3. The observation was mistaken.

What settles it is a recording, not an argument. If it reappears,
capture the dump (`scripts/record-dump.py` records shape; values would
need a variant that keeps them) and file it with numbers attached.

### Resolution (2026-08-20): both readings were half of a double report

`device_ffucxii.c:124` recombines the per-output Room EQ offset with `|`
against the base `0x35D0`, whose low five bits are already `0x10`. For
offsets 16..31 the bit collides, so the upper half of each output's
block decodes as its own lower half: `0x35E3` (`BAND6FREQ`) arrives as
`BAND1GAIN`, `0x35E6` (`BAND7FREQ`) as `BAND2GAIN`.

So one `/refresh` carries **two values for the same OSC path**, and
which one a client keeps is arrival order. That is why the table above
reads *every gain at 0.0 dB* -- the reader kept the first -- and why the
roadmap's original note read *+30 dB and +40 dB at 50 Hz*: those are
band 6 and 7 **frequencies** decoded through the gain scale.

Neither observation was mistaken. The roadmap's original hypothesis --
"a register offset in upstream's decoding rather than real device
state" -- was correct, and the withdrawal disproved a claim nobody had
made ("the device holds implausible values") rather than the one that
mattered.

Measured on the UCX II against the pinned revision, one `/refresh`
before and after the one-line fix: 1932 registers with 260 conflicting
paths becomes 2252 with none, and bands 6 to 9 appear with plausible
values. `patches/0002` carries the change.

### The lesson, which is the point of writing this down

**Revised 2026-08-20, because the first version of this lesson was drawn
on the same incomplete evidence as the withdrawal.** It is kept rather
than replaced, because being wrong twice in opposite directions about
one register block is the instructive part.

It used to read: *this claim sat in the roadmap for two releases and
reached the point of being filed before anybody checked it against the
device; a single query would have caught it at any time.*

A single query **did** check it. That is what produced the table above,
and the table is what withdrew the report -- confidently, with numbers,
and wrong. One query reads one half of a double report, and nothing
about the answer says a second value exists.

So the rule is not "query before you claim". It is: **a measurement that
could have more than one answer has to be shown to have one.** The
`/refresh` was read once and the value taken. Reading the same register
four times in a row -- 0.0 once, 0.7 three times -- is what actually
settled it, and that took seconds.

This project has the same rule for its own zeros elsewhere: a
measurement reporting *nothing happened* must prove its instrument was
alive in the same run. The withdrawal above is that rule applied to
somebody else's bug and skipped.

That is the same failure the `15-20 s` dump figure had, and the same one
`LINK_SYNC_BLIND_DELAY = 20` had -- see
[ADR 0010](decisions/0010-timing-constants-need-a-recording.md). The rule
that ADR states for timing constants applies to claims about upstream
too: **name the recording, or do not make the claim.**

[oscmix]: https://github.com/michaelforney/oscmix
