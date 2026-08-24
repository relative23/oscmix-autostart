# Register addresses, measured

The register model in `registers.py` carries oscmix's OSC **paths**. The
device knows only **register addresses**, and every defect this project
has found in the last two releases lived in the gap between the two:
Room EQ folded onto itself, `/output/N/phase` never written at all, a
`,f` sent to a register that reads integers.

This file closes that gap for the families where it has cost something.
It is not a copy of upstream's source: the arithmetic is read from
`device_ffucxii.c`, and then **each address is confirmed on the wire**
by writing the register its own current value and reading the SysEx off
the MIDI pipe. Writing back what is already there emits the write and
changes nothing, so the desk is untouched by the measurement.

## The arithmetic

    channel families   idx << 6 | reg
                       idx = input index, or 20 + output index
    input matrix       0x2000 | out << 6 | in
    room EQ            0x35D0 + reg + (out << 5)

## The wire format

`setreg()` in oscmix.c:

    regval = (reg & 0x7fff) << 16 | val
    bit 31 = even parity over the whole word

then `base128enc` packs the four little-endian bytes into five septets.

## Confirmed on a UCX II at 55802a6

Written on 2026-08-24, traced on the pipe `alsaseqio` forwards (fd 7).

| path | address | |
|---|---|---|
| `/input/3/phase` | `0x0087` | confirmed |
| `/input/3/gain` | `0x0088` | confirmed |
| `/output/5/volume` | `0x0600` | confirmed |
| `/output/5/stereo` | `0x0604` | confirmed |
| `/output/5/crossfeed` | `0x060A` | confirmed |
| `/output/5/lowcut/freq` | `0x060D` | confirmed |
| `/output/5/eq/band1gain` | `0x0611` | confirmed |
| `/output/5/dynamics/gain` | `0x061C` | confirmed |
| `/output/5/autolevel/maxgain` | `0x0624` | confirmed |
| `/mix/5/input/1` | `0x2100` | confirmed |
| `/output/5/roomeq/band1gain` | `0x3653` | **see below** |

Ten of eleven appeared verbatim. `/output/1/eq/band1gain` at `0x0511`
and `/input/1/phase` at `0x0007` were confirmed separately, in the runs
that produced upstream issues #33 and #34.

## The one that is not confirmed, and why

Room EQ decoded as `0x6653` where the arithmetic gives `0x3653`, a
difference of exactly `0x3000`. The same offset appears between `0x3F00`
and `0x6F00` in the polling traffic, which upstream writes as one
register.

**That points at the decoder used to read the trace, not at the
device.** A systematic offset that appears on two unrelated high
addresses and on none of the ten below `0x3000` is a reconstruction
fault in the septet unpacking, and the honest thing is to say so rather
than to record an address that has not been established.

What would settle it: decode one known high write byte by byte against
`base128enc`, rather than through the ad-hoc unpacker used here. Not
done.

## What this is for

If oscmix stopped being maintained tomorrow, the OSC paths would be
worth nothing and this table would still be true. That is the point of
writing it down.
