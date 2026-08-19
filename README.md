# oscmix-autostart

[![CI](https://github.com/relative23/oscmix-autostart/actions/workflows/ci.yml/badge.svg)](https://github.com/relative23/oscmix-autostart/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Plug-and-play RME Fireface UCX II on Linux.** Plug the interface in, the
mixer backend starts automatically, your routing is applied, and the mixer
GUI is one click away in your app menu. No terminal required after install.

[oscmix] by Michael Forney already does the hard part: it speaks the
Fireface's MIDI SysEx protocol and exposes the hardware mixer via OSC,
with a GTK GUI similar to TotalMix FX. What oscmix deliberately does not
ship is the desktop integration -- and that is exactly what this project
adds:

| Piece | What it does |
|---|---|
| udev rule | starts the backend on hotplug, disables Fireface USB autosuspend, and keeps affected ASM4242 host controllers awake |
| systemd user service | supervises the backend, restarts it on failure (`Type=notify`: "started" means "audio works") |
| `oscmix-session` | finds the ALSA MIDI port, launches `alsaseqio` + `oscmix`, applies your routing and verifies it against the device state |
| `routing.conf` | your default mixer routing, applied on every start |
| `--pipewire-sinks` | optional: named outputs ("Monitors", "Headphones") in your desktop's sound settings |
| desktop entry + launcher | "RME Fireface Mixer" in the app menu, with sanity checks and notifications |
| `install.sh` | builds oscmix from source and installs everything per-user |

[oscmix]: https://github.com/michaelforney/oscmix

![oscmix-gtk showing the Fireface UCX II hardware mixer](docs/img/oscmix-gtk.png)
*The upstream oscmix-gtk mixer on a UCX II -- this project makes it a
one-click, always-configured part of your desktop.*

## Why you want this

Out of the box, the UCX II works as a class-compliant USB audio device on
Linux (`snd-usb-audio`), but the hardware mixer is a black box: whether you
hear anything depends on whatever routing state the device happens to be
in. PipeWire also maps the 8 analog outputs as "7.1 surround", so stereo
audio only reaches outputs 1/2 -- if your monitors are connected elsewhere,
you get silence.

oscmix-autostart makes the state predictable: every time the device is
plugged in or the machine boots, the routing you declared in a small config
file is applied to the hardware mixer. Zero-latency hardware routing,
independent of the audio server.

## Requirements

- Linux with systemd and udev (any mainstream distro)
- Python >= 3.9 (standard library only)
- To build oscmix: `git`, `make`, a C compiler, `pkg-config`,
  ALSA headers, and GTK 3 headers for the GUI

  ```sh
  # Debian/Ubuntu
  sudo apt install build-essential git pkg-config libasound2-dev \
                   libgtk-3-dev libglib2.0-dev-bin
  # Fedora
  sudo dnf install gcc make git pkgconf-pkg-config alsa-lib-devel gtk3-devel
  # Arch
  sudo pacman -S --needed base-devel git alsa-lib gtk3
  ```

## Install

```sh
git clone https://github.com/relative23/oscmix-autostart
cd oscmix-autostart
./install.sh
```

The installer builds oscmix from upstream, installs everything into
`~/.local` / `~/.config`, and asks for sudo once -- only for the udev rule
in `/etc/udev/rules.d/`. Run `./install.sh --no-udev` for a fully rootless
install (you lose hotplug autostart; the launcher still starts the backend
on demand). Existing files are backed up, an existing `routing.conf` is
never overwritten.

Then plug in the Fireface (or reboot) and open **RME Fireface Mixer** from
the app menu.

## Configure your routing

Edit `~/.config/oscmix/routing.conf`:

```ini
[route:main-out]          # headphones on the front panel
playback = 1/2
output = 1/2

[route:monitors]          # speakers on rear outputs 5/6
playback = 1/2
output = 5/6
level = 0.0               # mix gain in dB (0 = unity, -65 = mute)
```

Apply with `systemctl --user restart oscmix.service`. Mono routes
(`playback = 3` / `output = 7`) work too. PipeWire and PulseAudio send
stereo audio to playback channels 1/2, so most setups only route 1/2 to
wherever their speakers are connected.

**A route rewrites exactly the registers it declares, and nothing else.**
So mute, EQ and the output faders keep whatever you set in the mixer, and
survive every restart. The one exception is opt-in: adding `volume = <dB>`
to a route pins that output's fader, and every backend start forces it
back to that value. That is what you want for a fixed installation, and
what you do not want if you set your monitor level by hand -- in which
case just leave the line out. Note that `level` is a different thing: it
is the routing itself, the mix-matrix gain, and is always written.

Shortly after startup,
`oscmix-session` also reads the state back from the device in the
background and re-sends once on mismatch -- the journal line `routing
verified against device state` is your proof that the hardware is
actually configured.

## Profiles

Several routings, and a command to switch between them -- TotalMix's
snapshots, but as text files you can diff and keep in version control.

A profile is a whole `routing.conf`, in a `profiles` directory beside
your main one:

```
~/.config/oscmix/routing.conf
~/.config/oscmix/profiles/tracking.conf
~/.config/oscmix/profiles/mixdown.conf
```

```sh
oscmix-session --list-profiles
oscmix-session --profile tracking
```

Leave `[osc]` and `[device]` out of a profile. Those describe the
machine, not the desk, and are taken from your main config unless a
profile states them itself.

A switch reports exactly one of three things, and never half-applies:

```
applied 'tracking' and verified it at the device
applied 'tracking'; 1 register(s) this backend cannot report: /mix/1/playback/1
refused 'tracking', nothing written: [route:x] output: channel 99 out of range 1..64
```

**A refusal costs nothing.** The profile is parsed and validated in
full before the first byte goes out, so a typo costs you an error
message rather than your monitoring. That matters because there is no
undo on a mixer: once a fader value is on the wire, the speakers already
have it.

The middle line is the normal outcome on a desktop, and it is not a
problem. The playback mix matrix is one of the few things oscmix never
reports back, so a perfectly good switch still cannot confirm it -- and
if you have the mixer GUI open it holds the port the read-back needs, so
nothing at all can be confirmed. Both cases say so instead of claiming
success. The reasoning is in
[ADR 0011](docs/decisions/0011-a-profile-switch-states-its-outcome.md).

## Named outputs in your sound settings (PipeWire)

PipeWire presents the Fireface's analog outputs as a single "7.1
surround" device. If you would rather pick "Monitors" or "Headphones" by
name in GNOME/KDE sound settings, generate one virtual sink per stereo
route:

```sh
mkdir -p ~/.config/pipewire/pipewire.conf.d
oscmix-session --pipewire-sinks > ~/.config/pipewire/pipewire.conf.d/oscmix-sinks.conf
systemctl --user restart pipewire wireplumber
```

Each sink feeds the device playback channels that match the route's
output pair, so those pairs need an identity route (`playback = output`)
in routing.conf -- the generated file contains a ready-to-paste note if
one is missing. The Fireface sink node and its real channel layout are
auto-detected via `pw-dump`, so the mapping is correct in both the
surround and the pro-audio/Direct profile; pass
`--pipewire-target <node.name>` to override the detection.

## How it works

```
USB hotplug ── udev rule ── systemd user service ── oscmix-session
                                                        │
                                     ┌──────────────────┼─────────────────┐
                                 finds MIDI       starts alsaseqio    applies routing
                                 client via       + oscmix (OSC ⇆    from routing.conf
                                 /proc/asound     MIDI SysEx)         via OSC/UDP
```

Details, including the failure model and exit-code semantics, are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Notes on the OSC interface
oscmix exposes are in [docs/OSC-PROTOCOL.md](docs/OSC-PROTOCOL.md), and
the choices that are not obvious from the code are recorded in
[docs/decisions/](docs/decisions/). What the service is trusted with --
including the fact that the control port is unauthenticated -- is in
[docs/SECURITY-MODEL.md](docs/SECURITY-MODEL.md). Where this is heading
is in [docs/ROADMAP.md](docs/ROADMAP.md).

## Troubleshooting

```sh
systemctl --user status oscmix.service      # is the backend running?
journalctl --user -u oscmix.service -e      # backend logs
oscmix-session --dry-run                    # what would be started/sent?
```

More in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Other Fireface models

oscmix has (experimental) support for the Fireface 802FS as well. The
device name and USB ID are configurable in `routing.conf` (`[device]`
section); for hotplug you would additionally adapt the IDs in
`udev/90-rme-fireface.rules`. Reports welcome.

## Development

```sh
pip install -r requirements-dev.txt

make check            # everything CI enforces, fastest failure first
make test             # pytest, no hardware needed
make lint             # ruff + shellcheck + syntax check
make typecheck        # mypy --strict over the runtime package
make deadcode         # vulture
make coverage         # with the ratchet from pyproject.toml
make flake            # the suite five times over, to surface races
make soak             # restart cycles; the gate is the scheduled workflow
make mutation         # do the assertions actually catch a wrong value?
make verify-hardware  # measure the audio itself (needs a Fireface)
```

Install the dev requirements before trusting a green run. Without
`hypothesis`, `tests/test_contracts.py` skips itself -- the suite says so
loudly at the end, and `OSCMIX_REQUIRE_CONTRACTS=1` turns that skip into
an error, which is how CI runs it.

The integration tests run `oscmix-session` against a stub backend with a
fake `/proc` and sysfs, so the full startup/routing/shutdown path is tested
without a Fireface attached. The device stand-ins in
`tests/test_apply_routing.py` go one step further and model oscmix's
stereo-link state machine, which is what pins down the ordering the mixer
matrix depends on.

Two gates exist because this project got burned by exactly what they
catch. The Python matrix runs 3.9 through 3.13: a test helper that shadowed
a private `threading.Thread` attribute passed on 3.14 and failed on
everything older. And `make flake` repeats the suite, because the tests
bind real UDP sockets and drive background threads, where a teardown race
survived several consecutive green runs.

A third runs nightly rather than per commit: `.github/workflows/soak.yml`
restarts the session 200 times and checks the routing datagrams byte for
byte every time. Every failure mode found in this project so far was a
timing bug, and every one of them survived a green single run.

The runtime itself has no Python dependencies -- `oscmix-session` uses only
the standard library, so it runs before any package manager is involved.

## Uninstall

```sh
./uninstall.sh          # keeps ~/.config/oscmix
./uninstall.sh --purge  # removes the config too
```

## Credits and license

All the actual protocol work happens in [oscmix] (ISC license) -- this
project is just the glue that makes it feel native on a Linux desktop.
oscmix-autostart is MIT licensed, see [LICENSE](LICENSE).
