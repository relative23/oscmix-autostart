# Architecture

How oscmix-desk is built, in the present tense. It carries no history:
why a thing is the way it is lives in [the decision
records](decisions/), and what was measured to get there lives in
[the roadmap](ROADMAP.md).

**This page is checked against the code.** `tests/test_architecture.py`
requires every runtime module to be named here and every module named
here to exist. A page that drifts fails the suite, which is the only
reason to trust one.

## The system it sits in

Four layers have to cooperate for audio to work; oscmix-desk owns the
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

## The shape of the whole thing

Everything this project does is one pipeline, and every command is a
different place to stop along it:

```
routing.conf ──config──▶ Config
                           │
                    reconcile.desired()
                           ▼
                        Entry[]           what the file asks for
                           │
      device ──backend──▶ reconcile.observed()
                           ▼
                        seen{}            what the device reports
                           │
                    reconcile.plan()
                           ▼
                        Plan              what to write, and why
                           │
              ┌────────────┴────────────┐
        routing.apply()            cli --diff
        (sends it)                 (prints it)
```

`--dump-config` runs the middle of it backwards: device state in,
`routing.conf` out. `--snapshot` stops one step earlier and prints
`seen{}` verbatim, which is the only view that includes registers a
config cannot express.

**The reconciler is pure.** No socket, no clock, no device. That is what
lets it be tested against recorded dumps instead of hardware, and it is
why the register model is data rather than code.

## The modules

Layered: each may import only from those below it, enforced as an
acyclic graph.

| Module | What it owns |
|---|---|
| `constants` | every timing constant and exit code, each with the measurement that produced it |
| `errors` | `ConfigError`, the one exception a user ever sees |
| `log` | journal-shaped logging, no configuration |
| `osc` | encode and decode OSC messages; no I/O |
| `registers` | the register model as data: paths, tags, bounds, verification class, policy, per-device channel maps |
| `config` | parse `routing.conf` into a `Config`, refusing anything the model does not declare |
| `discovery` | find the device: ALSA sequencer clients, USB presence, whether a UDP port is bound |
| `notify` | `sd_notify`, so `Type=notify` means "the routing is applied" |
| `reconcile` | `desired` / `observed` / `plan`, and rendering a `Config` back to text |
| `backend` | the one place that opens a socket to the device; its `Traits` name the upstream behaviour the timing constants work around |
| `routing` | send a plan in two phases, with the link barrier between them |
| `verify` | read the device back and say confirmed, mismatched or unverifiable |
| `process` | supervise the backend: start, `SIGTERM`, escalate to `SIGKILL`, reap |
| `pipewire` | generate named virtual sinks from the same config |
| `profiles` | switch to `profiles/<name>.conf` as a transaction, reporting an outcome rather than raising |
| `session` | the service lifecycle: wait for the device, start the backend, apply, signal ready, verify, shut down |
| `launcher` | the desktop entry's entry point; deliberately depends on almost nothing |
| `cli` | argument parsing and the exit-code mapping, and nothing else |
| `__init__` | the public surface, and the only module that re-exports |

## The register model is data

`registers.py` declares every register as a row: path template, OSC type
tags, which channels have it on which device, how it verifies, what a
config may set it to, its bounds and unit, and who wins after the first
write.

Two consequences run through everything else:

- **A config can set exactly what declares a value domain.** Phantom
  power, Room EQ and `/output/{ch}/phase` have none, so no `routing.conf`
  can reach them. That is one rule in one place instead of a list of
  exceptions in the parser.
- **The wire type comes from the declared tag**, never from the Python
  value. A `,f` written to a register that reads integers is accepted,
  dropped, and changes nothing.

The table itself is exempt from mutation testing and checked against
recorded device dumps instead ([ADR 0015](decisions/0015-the-register-table-is-not-mutated.md)).

## Who wins: pin and remember

Every settable register carries a policy. `REMEMBER` is the default: the
file describes the value, a dump shows it as a comment, and the device
keeps whatever it has. `PIN` means the file owns it and every start
writes it back.

The device does not announce most of its own changes, so "pinned" means
*the config wins while this session is looking*
([ADR 0012](decisions/0012-pin-and-remember.md),
[ADR 0013](decisions/0013-reconcile-triggers.md)).

## The two-phase apply

Channel links are written before the mix matrix, with a barrier between
them. Sending both in one burst silences every even output, because
oscmix only learns a pair is linked when the device echoes the change
back over MIDI, and a `/mix` write that overtakes that echo is evaluated
against the stale flag ([ADR 0001](decisions/0001-two-phase-routing-apply.md)).

The barrier waits for the echo, or for a fixed settle when the receive
port is held by the mixer GUI and the echo cannot be observed.

## The two seams

**`backend`** is the only module that opens a socket. Everything above it
takes a `Backend` argument, which is what lets the whole apply and verify
path be driven by a fake in tests.

**`registers.Device`** is the only place that knows a device exists. The
model is indexed by device from the first line, so a second interface is
a table rather than a rewrite. Only the UCX II has one; the 802 has its
channel map and no registers, because oscmix cannot drive it.

### Exit codes

| Code | Meaning | systemd reaction |
|---|---|---|
| 0 | device absent, clean shutdown, or clean backend exit | none |
| 1 | runtime failure | restart after 3 s (max 5 per 2 min) |
| 2 | routing.conf error | **no** restart (`RestartPreventExitStatus=2`) |
| 3 | `--diff` only: the device and the config disagree | never seen; the service runs no flag |

`diff(1)` returns 1 for "differing" and that is not available here,
because 1 already means a failure. A caller has to be able to tell *the
desk drifted* from *the backend never answered*: conflating them makes a
monitoring check report healthy silence while the backend is down.

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
