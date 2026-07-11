# The oscmix OSC interface

[oscmix](https://github.com/michaelforney/oscmix) exposes the Fireface's
hardware mixer via OSC 1.0 over UDP. This is what `oscmix-session` uses to
apply routing.conf, and what you can use to script the mixer yourself.

- oscmix **listens** on `udp://127.0.0.1:7222` (commands in)
- oscmix **sends** state changes to `udp://127.0.0.1:8222` (where
  oscmix-gtk listens)

## The mix matrix

`/mix/<output>/playback/<channel>` controls how much of a software
playback channel reaches a hardware output -- the routing matrix from
TotalMix FX. Arguments: `,fi` = level (float, dB) + pan (int).

- level: `0.0` = unity gain, `-65.0` = mute
- pan: `-100` (left) … `100` (right), `0` = center
- all indices are 1-based

**Stereo-linked pairs fold onto the odd channel:** a `/mix` message
addressed to either half of a linked pair writes the *same* pair
register, and pan acts as the pair's balance. Do NOT send per-channel
messages panned hard left/right for linked pairs (the TotalMix pattern
for unlinked channels) -- they overwrite each other and the last pan
wins, leaving the whole mix panned hard to one side.

A plain stereo pass-through of playback 1/2 to output pair 5/6 is one
matrix entry, with both pairs linked:

```
/playback/1/stereo  ,i   1
/output/5/stereo    ,i   1
/mix/5/playback/1   ,fi  0.0 0
```

This is exactly what a `[route:...]` section with `playback = 1/2` and
`output = 5/6` generates.

## Other useful addresses

| Address | Args | Meaning |
|---|---|---|
| `/output/<n>/volume` | `,f` dB | hardware output volume |
| `/output/<n>/stereo` | `,i` 0/1 | stereo-link with the next channel |
| `/output/<n>/pan` | `,i` | pan −100…100 |
| `/input/<n>/gain` | `,f` | input gain |
| `/mix/<out>/input/<in>` | `,fi` | hardware input → output routing |
| `/refresh` | none | re-send the complete device state |

The authoritative list is the upstream source (`oscmix.c`).

## Scripting example

OSC messages are trivial to construct with the Python standard library --
address and type tag are NUL-terminated strings padded to 4 bytes,
arguments are big-endian:

```python
import socket, struct

def osc(path, types="", *args):
    def s(x):
        b = x.encode() + b"\x00"
        return b + b"\x00" * (-len(b) % 4)
    data = s(path) + s("," + types)
    for tag, value in zip(types, args):
        data += struct.pack(">f" if tag == "f" else ">i", value)
    return data

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(osc("/output/1/volume", "f", -12.0), ("127.0.0.1", 7222))
```

For one-off experiments, `oscmix-session --dry-run` prints the messages it
would send for your current routing.conf.
