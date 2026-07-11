# Architecture

## Layers

Four layers have to cooperate for audio to work; oscmix-autostart owns the
glue between them:

```
┌──────────────────────────────────────────────────────────────┐
│ 1  USB / kernel                                              │
│    snd-usb-audio registers the Fireface as an ALSA card and  │
│    MIDI device (class compliant, no custom driver).          │
├──────────────────────────────────────────────────────────────┤
│ 2  udev (udev/90-rme-fireface.rules)                         │
│    On hotplug: disables USB autosuspend for the device and   │
│    asks the user's systemd instance to start oscmix.service  │
│    (SYSTEMD_USER_WANTS). On removal it tags the event so     │
│    systemd drops the pull-in and StopWhenUnneeded stops the  │
│    service.                                                  │
├──────────────────────────────────────────────────────────────┤
│ 3  backend (systemd/oscmix.service → bin/oscmix-session)     │
│    Discovers the ALSA sequencer client, runs                 │
│    `alsaseqio <client>:1 oscmix`, applies routing.conf via   │
│    OSC, supervises the process.                              │
├──────────────────────────────────────────────────────────────┤
│ 4  frontend (desktop entry → bin/oscmix-launch → oscmix-gtk) │
│    Checks the device is present, ensures the backend runs,   │
│    then execs the GTK mixer.                                 │
└──────────────────────────────────────────────────────────────┘
```

## oscmix-session in detail

1. **Wait for the device.** Poll `/proc/asound/seq/clients` (up to
   `--timeout`, default 30 s) for a client whose name contains the
   configured device name. Parsing the proc file instead of `aconnect -l`
   output avoids a dependency on alsa-utils and the classic trap that the
   device name also appears in *port* lines. If the proc file does not
   exist yet, opening `/dev/snd/seq` makes the kernel autoload `snd-seq`.

2. **Distinguish "absent" from "broken".** If no client appears, sysfs
   (`/sys/bus/usb/devices/*/idVendor|idProduct`) tells us whether the
   device is physically connected:
   - not connected → exit **0** ("nothing to do", no restart loop, no red
     `failed` unit at boot without the device)
   - connected but no MIDI client → exit **1** (driver problem; systemd
     retries via `Restart=on-failure`)

3. **Start the bridge.** `alsaseqio <client>:1 <oscmix>` connects to port
   `:1` of the client -- port 0 is regular MIDI, port 1 is the SysEx
   control port the mixer protocol uses. Binary paths are resolved
   explicitly (env override → `PATH` → `~/.local/bin`, `/usr/local/bin`,
   `/usr/bin`) because the systemd user manager's `PATH` may not include
   `~/.local/bin`.

4. **Wait until oscmix listens.** `/proc/net/udp{,6}` is polled for the
   OSC port (no `ss`/`netstat` dependency). If the port does not appear
   within 10 s the session logs a warning and continues -- sending UDP
   datagrams to a not-yet-listening port is harmless, and killing the
   backend would only cause a restart loop.

5. **Apply routing.** Each `[route:*]` section of routing.conf is
   translated into the OSC messages TotalMix would generate (see
   [OSC-PROTOCOL.md](OSC-PROTOCOL.md)) and sent to `127.0.0.1:<port>`.
   The state ends up in the device's hardware mixer: zero latency,
   independent of PipeWire/PulseAudio/JACK.

6. **Signal readiness.** With the backend up and the routing sent, the
   session reports `READY=1` (`Type=notify`), so for systemd -- and
   anything ordered after the service -- "started" means "backend up,
   routing applied". The no-device exit also notifies before exiting 0
   to avoid a protocol failure.

7. **Verify in the background.** OSC over UDP is fire-and-forget, so a
   background thread reads the state back: it binds the receive port
   (8222, where oscmix reports state), sends `/refresh`, and compares
   the reported registers against the expected ones -- with a 0.5 dB
   tolerance for the device's level quantization. On mismatch the
   routing is re-sent once. The thread starts ~12 s after startup
   because oscmix's initial register sync saturates the MIDI link and
   makes earlier read-backs unreliable. Verification is advisory: a
   failed read-back is logged, never fatal (a restart loop would not
   improve anything), and it is skipped when the port is taken because
   the mixer GUI is running. Two register families are excluded from the
   comparison: `/mix/*/playback/*` (upstream dumps the input mix matrix
   but not the playback matrix) and `/playback/*` (that section streams
   so late in the multi-second dump that no sane window observes it).
   The audible signal path -- output stereo links and volumes -- arrives
   early in the dump and verifies reliably.

8. **Supervise.** On SIGTERM/SIGINT the child gets SIGTERM, after a 5 s
   grace period SIGKILL, and the session exits 0. If the child dies on its
   own, the USB check decides again: device gone → 0 (normal unplug),
   device still there → 1 (systemd restarts).

### Exit codes

| Code | Meaning | systemd reaction |
|---|---|---|
| 0 | device absent, clean shutdown, or clean backend exit | none |
| 1 | runtime failure | restart after 3 s (max 5 per 2 min) |
| 2 | routing.conf error | **no** restart (`RestartPreventExitStatus=2`) |

## Design decisions

- **Python, standard library only.** The original implementation was shell
  + inline Python. A single Python process gives testable pure functions,
  real signal handling and process supervision, and error messages that
  name the section/option at fault -- without adding a single dependency
  beyond what the shell version already needed.

- **Per-user installation.** Everything lives in `~/.local` and
  `~/.config`; only the udev rule needs root. `--no-udev` allows a fully
  rootless install (launcher-triggered start still works).

- **`oscmix-session` and `oscmix-launch` are self-contained.** They share
  ~25 lines of sysfs/procfs helpers by copy instead of a shared module.
  Deliberate: it keeps installation a plain file copy with no Python
  packaging, and the launcher must never break because of a backend
  refactor.

- **Routing lives in the config, not in code.** The backend re-applies it
  on every start, so the device state is reproducible regardless of what
  the hardware remembered or what was changed interactively in the GUI.

- **udev remove matches `ENV{PRODUCT}`.** At remove time the sysfs
  attributes are already gone, so an `ATTR{idVendor}` match never fires.
  This is easy to get wrong and results in a service that keeps running
  after unplug.

- **Stale cleanup is surgical.** If the OSC port is already taken at
  startup, only processes whose `/proc/<pid>/cmdline` is literally
  `oscmix` and that belong to the current user get SIGTERM -- no blanket
  `pkill` patterns.

- **Named PipeWire sinks are generated, not hardcoded.**
  `oscmix-session --pipewire-sinks` derives one loopback sink per stereo
  route from routing.conf and auto-detects the Fireface sink node via
  `pw-dump`, so the desktop integration follows the same single source of
  truth as the hardware mixer.

## Installed files

```
~/.local/bin/oscmix                  backend (built from upstream)
~/.local/bin/oscmix-gtk              GTK mixer (built from upstream)
~/.local/bin/alsaseqio               ALSA sequencer bridge (built from upstream)
~/.local/bin/oscmix-session          backend supervisor (this project)
~/.local/bin/oscmix-launch           desktop launcher (this project)
~/.config/oscmix/routing.conf        your routing (never overwritten)
~/.config/systemd/user/oscmix.service
~/.local/share/applications/oscmix-gtk.desktop
~/.local/share/icons/hicolor/scalable/apps/oscmix.svg
~/.local/share/glib-2.0/schemas/oscmix.gschema.xml   (needed by oscmix-gtk)
/etc/udev/rules.d/90-rme-fireface.rules              (only root-owned file)
```
