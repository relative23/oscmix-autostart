# 0013 -- Reconcile on events, never on a clock

## Status

Accepted, 0.3.0. Measured on a Fireface UCX II, serial 24216011.

## Context

[ADR 0012](0012-pin-and-remember.md) gave every register a policy, and
then had to admit what "pinned" could mean. The device does not announce
its own changes -- of everything a config sets, only
`/output/{ch}/stereo` is pushed to listeners -- so nothing can react to a
fader being moved without polling a 2002-register dump. Pinning therefore
means *the config wins while this session is looking*, and the open
question was: **when is it looking?**

The roadmap listed three moments: SIGHUP, resume, hotplug. Only two of
them needed anything built.

## Decision

**Triggers are events. There is no timer, and there will not be one.**

A timer would be a background process that argues with the user on a
schedule, and -- because the device reports nothing -- each tick would
cost a full dump. `tests/test_reconcile_triggers.py` asserts no `.timer`
unit and no `OnCalendar`/`OnUnitActiveSec` exists.

### Hotplug: already covered, and left alone

`udev/90-rme-fireface.rules` pulls `oscmix.service` in on `add`;
`StopWhenUnneeded=yes` drops it on `remove`. A replug is therefore a full
process restart with a full apply, which
`tests/data/cold-plug-timeline.json` recorded directly: *"cold USB replug
-- device unplugged 14.4 s, udev restarted the unit"*.

Building a session-level hotplug trigger would have been a second
mechanism for something already working -- the mistake this release found
three times over. Instead both halves are asserted by test, so if the
rule or the unit ever loses its part, that shows up as a failure rather
than as a device that quietly stops being configured.

### SIGHUP: reconcile, not restart

`ExecReload=/bin/kill -HUP $MAINPID`. A reload re-reads `routing.conf`,
reads the device back, and applies what the config pins while leaving
what it remembers.

**`$MAINPID` and not `systemctl kill`, measured.** `systemctl --user kill
--signal=SIGHUP oscmix.service` signals *every* process in the unit.
Neither oscmix nor alsaseqio installs a SIGHUP handler, so the default
action applies: both died and the service went inactive. `ExecReload`
reaches the session process alone.

The handler sets a flag and returns. A signal handler runs between two
bytecodes of whatever was executing, so opening a socket or waiting out
the link barrier there means doing it *inside* the apply it was meant to
follow. The supervise loop picks the flag up, and clears it before
running the reconcile so a SIGHUP arriving during one queues another
rather than being swallowed.

A config that no longer parses is reported and **not** applied; the
session keeps running on the configuration it has. Exiting would turn a
typo in a file nobody was forced to edit into silence on a desk somebody
is listening to.

Measured end to end on the UCX II, fader moved to −20.0 dB by hand and
then SIGHUP:

| config | log | device |
|---|---|---|
| remembered | `1 left to the device (/output/1/volume)` | keeps −20.0 |
| `[pin] output.volume = pin` | `1 to correct` | back to −6.0 |

### Resume: a system-sleep hook, and it is honest about being unproven

A user unit with `WantedBy=sleep.target` would install, enable, and never
run: on systemd 259 `systemctl --user cat sleep.target` reports *"No
files found for sleep.target"*. The user manager has no such target.
Checked before writing the unit, which is the only reason it is not in
this repository.

So `/usr/lib/systemd/system-sleep/oscmix`, running as root on `post`,
reaching each logged-in user's manager with `--machine=<user>@.host
reload`. It is installed by the same root step as the udev rule and
removed by `uninstall.sh`, because a hook left behind fires on every wake
for a service that is gone.

**Whether this device needs it is not established.** Answering it means a
real suspend/resume cycle, and a resume that fails leaves someone locked
out of a machine nobody is sitting at -- not a reasonable thing to risk
for a measurement. What is known: the reconcile is cheap and idempotent,
so running it on a wake where nothing was lost costs one dump; and the
*other* way this device loses state, a replug, is already covered above.

## Consequences

- A reconcile reads before it writes. That read is the only way to know
  which remembered registers to protect, which is what makes this a
  reconcile rather than a re-apply.
- **A held receive port is a refusal, not a blind write.** With no dump
  there is no way to tell a pinned register from a remembered one at the
  device, so writing anyway would be the indiscriminate re-apply ADR 0012
  exists to end. The mixer GUI holding UDP 8222 is the normal desktop
  case, so this will happen, and it says so in the log.
- **The unit and the package must be installed together.** `ExecReload`
  against a version without the SIGHUP handler is fatal: the default
  action terminates the session. Seen while testing, on a machine whose
  unit had been updated ahead of its package. `install.sh` writes both.

## Alternatives considered

**Restart the unit on resume.** One line, no new code, and it puts
remembered faders back exactly as they were configured -- undoing the
whole point of ADR 0012 on every wake.

**Poll `/clock/samplerate` and reconcile on a rate change.** The roadmap
wants this and it is the one trigger that would cover a real, routine way
the mixer loses state. Not done, and not guessed at: whether the UCX II
resets the matrix on a rate change is unmeasured, and measuring it means
changing the sample rate on somebody's working machine. It stays open,
marked unmeasured.

**A D-Bus listener for logind's `PrepareForSleep`.** Would remove the
root install. Rejected: the runtime imports nothing outside the standard
library, and a D-Bus client is a large dependency for a signal a
five-line shell script already delivers.
