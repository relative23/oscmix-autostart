# 0014 -- Nested settings go in `[<family>:<channel-family>:<n>]`

## Status

Accepted, 0.4.0. The choice is constrained by a measurement against the
released 0.3.0 parser, not by taste.

## Context

0.3.0 declares six per-channel options, each a single flat word:
`gain`, `hi-z`, `reflevel`, `mute`, `phase`, `volume`. Everything left
in 0.4.0 is nested -- `/input/3/eq/band1freq`,
`/output/5/dynamics/compthres` -- and there are **50 distinct option
names** below `/<family>/<channel>/`, across 1424 registers.

`[input:3]` with `volume = -6.0` does not extend to that. Four shapes
were on the table:

```ini
[input:3]              [input:3.eq]      [input:3:eq]      [eq:input:3]
eq.band1freq = 80      band1freq = 80    band1freq = 80    band1freq = 80
```

[ADR 0006](0006-routing-conf-compatibility.md) is what decides between
them: an unknown **section** warns and the rest of the file is applied,
an unknown **option** in a known section is an error and the file is
refused whole. A refused file means no routing at all, and no restart
(`RestartPreventExitStatus=2`) -- the device keeps whatever the last
boot left.

So the question is which shapes an installed 0.3.0 merely skips.

## The measurement

Every form fed to the released parser, in a config that also carries a
route and an `[input:3] gain` this version does understand:

| written as | 0.3.0 does |
|---|---|
| `[input:3]` + `eq.band1freq` | **refuses the file** -- unknown option |
| `[input:3]` + `eq/band1freq` | **refuses the file** -- unknown option |
| `[input:3.eq]` | **refuses the file** -- `'3.eq' is not a channel number` |
| `[input:3:eq]` | **refuses the file** -- `'3:eq' is not a channel number` |
| `[input:3/eq]` | **refuses the file** -- same |
| `[eq:input:3]` | warns, skips it, applies the route and the gain |
| `[input-eq:3]` | warns, skips it, applies the rest |

**The sub-section forms do not degrade.** That was assumed in the
roadmap's 0.4.0 plan and it is wrong: `config.py` dispatches on
`section.startswith(("input:", "output:"))` *before* it looks at the
rest, so anything beginning `input:` reaches the channel parser and dies
on `int("3.eq")`. That is a property of a released version and cannot be
fixed retroactively.

## Decision

**`[<family>:<channel-family>:<n>]`** -- family first:

```ini
[input:3]                 # unchanged, 0.3.0 understands it
gain = 12.0

[eq:input:3]              # new, 0.3.0 skips it with a warning
band1freq = 80
band1gain = -3.0

[dynamics:output:5]
compthres = -18.0
```

Option names stay the last path segment, exactly as everywhere else in
this project: `/input/3/eq/band1freq` is `band1freq`. Not
`[eq:input:3:band1]` with `freq` -- the device's own vocabulary has one
segment there, and splitting it would triple the sections to spell the
same thing.

The form reads as the existing ones do: `[route:main]` is the route
named main, `[eq:input:3]` is the EQ of input 3. The colon is already
this file format's separator.

## Consequences

- **A 0.3.0 install ignores 0.4.0's new settings and keeps working.**
  That is the whole point, and it is measured rather than assumed.
- **Grouping is by family, not by channel.** A channel strip is spread
  across several sections rather than gathered in one, which is the real
  cost of this choice. `[input:3]`, `[eq:input:3]`, `[dynamics:input:3]`
  are three places to look for one channel. The alternative was a file
  0.3.0 refuses, and a config that will not load is worse than one that
  reads awkwardly.
- **A full dump gets long.** Twenty channels across five families is up
  to a hundred sections. `--dump-config` already emits remembered values
  as comments, so most of that is commented out; if it becomes
  unpleasant, the fix is in the writer, not the format.
- **`[input-eq:3]` also survives** and is shorter. Rejected anyway: it
  invents a second naming convention for the same idea, and the reason
  it survives -- not matching a prefix check in one released version --
  is an accident rather than a design.

## Alternatives considered

**Dotted options inside `[input:3]`.** The most compact, and it keeps a
channel in one place. It is the one form that guarantees an older
install refuses the whole file, which ADR 0006 exists to prevent.

**Wait and change ADR 0006 instead**, making an unknown option a warning
too. Rejected: that rule is what makes `levl = -20` an error rather than
a silently wrong device state, and it has caught real typos. Loosening
it to gain a nicer section name would trade a certain benefit for a
cosmetic one.

**A `[eq]` section with channel-keyed options**, `input.3.band1freq = 80`.
Degrades correctly, and puts 480 EQ registers in one section with
three-part option names -- which moves the nesting problem from the
section into the option and makes every line longer.
