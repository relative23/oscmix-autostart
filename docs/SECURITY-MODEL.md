# Security model

What this project trusts, and what it does not. Short, because the
surface is small -- but one item on it deserves to be stated plainly
rather than discovered.

## The control port is unauthenticated

oscmix listens on **UDP 127.0.0.1:7222** and acts on every datagram it
receives. There is no authentication, no authorisation and no origin
check beyond the loopback bind. **Any process running as your user can
write any mixer register**, including this project's own routing.

That is upstream's design, and on a single-user desktop it is a
reasonable one -- it is the same trust level as your audio server. It is
worth naming anyway, because the consequences grow with what the mixer
can do:

- today: routing and output faders. A hostile local process can silence
  your monitors, or make them very loud.
- from 0.3.0, when `[input:N]` sections land: **phantom power**. `48v`
  is a register like any other. Sending 48 V into a ribbon microphone
  damages it.

If that matters for your setup, the port is the boundary to defend --
either by not running untrusted code as your audio user, or by moving
oscmix into a namespace where 7222 is not reachable. This project cannot
fix it from the outside; it can only avoid making it worse.

## What the service is allowed to do

`systemd/oscmix.service` is sandboxed as far as an unprivileged **user**
unit can be. The hardening that a user manager cannot apply is documented
in `tests/test_unit_file.py` along with why -- capability-dropping and
cgroup-based directives fail with `218/CAPABILITIES`, which stops the
audio rather than securing it.

Applied: `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`,
`PrivateTmp`, `LockPersonality`, `MemoryDenyWriteExecute`,
`SystemCallArchitectures=native`, and `RestrictAddressFamilies` limited to
UNIX and IP sockets.

The session writes nothing: the routing config is read-only, and its only
outputs are UDP datagrams to loopback and the systemd notification socket.
`ReadWritePaths` is therefore empty, which is the strongest form of that
statement a unit can make.

### "Writes nothing" is a property of today's feature set, not a principle

It is true because nothing the session currently does needs a file. That
stops being true in 0.3.0: `--dump-config` writes a `routing.conf`,
profiles need somewhere to keep several of them, and any cached device
state needs a path. Each of those turns an empty `ReadWritePaths` into a
directory the service may write.

This is written down here, before that happens, for one reason: the first
feature that needs a file will otherwise widen the sandbox as an
implementation detail in the commit that adds it. Widening it is a
decision, and it has to be argued rather than noticed. When it comes up,
the questions this section is asking in advance are:

- **Which directory, and does the session need to write it, or only the
  CLI?** `--dump-config` is a command a user runs, not something the
  boot-time service does. If only the interactive path writes, the
  *service* can stay at an empty `ReadWritePaths` and the write happens
  outside it -- which is the outcome to aim for.
- **`StateDirectory=` rather than a hand-written path.** It gives a
  single directory under `~/.local/state` with the right ownership and
  keeps `ProtectHome=read-only` otherwise intact.
- **Does the routing config itself become writable?** It should not. A
  config the service can rewrite is no longer a reviewable source of
  truth, which is the project's premise; `--dump-config` writing to
  stdout or to a path the user names keeps that property.
- **What happens on a partial write?** A truncated `routing.conf` is an
  unbootable device state. Write to a temporary file and rename.

Until one of those is answered, the claim above stands as written and the
unit stays as it is. `tests/test_unit_file.py` asserts the empty
`ReadWritePaths`, so relaxing it cannot happen quietly.

## Signalling other processes

`_cleanup_stale_backend` terminates a leftover `oscmix` that is holding
the OSC port. It only considers processes owned by the calling user whose
`comm` or argv0 is `oscmix`, and it signals through `os.pidfd_open` so a
PID recycled between the `/proc` scan and the signal cannot be hit by
mistake. A process it cannot verify is reported, never signalled.

## The supply chain

`install.sh` clones and compiles upstream oscmix -- the only place this
project executes code from the network. It builds a **pinned commit**
(`OSCMIX_REF`, default a full SHA), verifies that the checkout landed on
exactly that commit, and records the built revision in the hardware
evidence artifact. Tracking upstream is an explicit opt-in:

```sh
OSCMIX_REF=master ./install.sh
```

There is no signature verification: upstream publishes no signed tags.
That is a real gap, and it is the reason the default is a specific commit
that has been measured against real hardware rather than a moving branch.

## Not in scope

Multi-user separation, remote access, and anything about the audio data
itself. This project configures a mixer; it does not carry audio.
