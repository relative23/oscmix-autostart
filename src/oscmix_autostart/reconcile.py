"""Desired state, observed state, and the plan between them.

What this project *is*, is a reconciler: desired state from the config,
observed state from the device dump, the difference applied. What the
code grew into is four partly overlapping paths over the same data --
``apply_routing``, ``send_mix``, ``blind_reapply_mix`` and
``verify_and_repair`` -- each with its own idea of what to write and
when.

Stated as ``desired(config)``, ``observed(reports)`` and
``plan(desired, observed)``, apply and verify are one path, and two
planned features fall out of it instead of becoming paths five and six:
``--dump-config`` is ``observed()`` rendered as config, and ``--diff`` is
``plan()`` printed instead of sent.

This module is deliberately **pure**. It opens no socket, reads no
clock and decides nothing about timing; it answers what should be
written, in what order, and why. That is what makes it testable against
the recordings rather than against a device.

The register model is what makes it pay for itself: a plan is a set of
registers, and whether an entry is compared, skipped or rewritten
unconditionally is a property of its row in that table
(``registers.verify_class``) rather than a branch in the routing code.

**Nothing in the runtime writes through this yet.** It reproduces the
existing behaviour with exactly one stated difference:
``tests/test_reconcile.py`` asserts that ``plan()`` against an empty
observation is the datagram sequence ``routing_plan()`` produces today,
ordering included, *minus repeats*. A register two routes share --
``/output/5/stereo`` for two routes feeding the same pair,
``/playback/1/stereo`` for three routes fed from the same source -- goes
out once instead of two or three times. A state holds each register once.

That is a change on the wire, so it is pinned by a second test rather
than argued: every dropped repeat must carry the value already in the
plan. Two routes sharing an output pair must agree on its link state
(``_check_link_agreement`` rejects configs where they do not), and
``/playback/N/stereo`` is always 1.

Landing the abstraction and switching the audible path over to it are
two changes, and this is the first: every defect this project has
shipped was in that path and invisible at message level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .config import Config, Route
from .registers import REESTABLISHED, VERIFIABLE, Device, verify_class
from .routing import link_messages, mix_messages

Args = Tuple[object, ...]

#: The two phases of an apply. The link barrier sits between them: every
#: link of every route goes out, the device reports back, and only then
#: is the mix matrix written. Phase is a property of the register, not of
#: the route it came from -- which is exactly what walking route by route
#: got wrong.
PHASE_LINK = 0
PHASE_MIX = 1

#: Why a write is in the plan.
MISSING = "missing"            # observed nothing for it
MISMATCHED = "mismatched"      # observed a different value
REWRITE = "re-established"     # unverifiable and link-dependent; always written
UNCONDITIONAL = "unconditional"  # nothing was observed at all (a blind apply)


@dataclass(frozen=True)
class Entry:
    """One register the config asks for."""

    path: str
    tags: str
    args: Args
    phase: int


@dataclass(frozen=True)
class Write:
    """One register the plan says to write, and why."""

    path: str
    tags: str
    args: Args
    phase: int
    reason: str

    def message(self) -> Tuple[str, str, Args]:
        """The shape the OSC encoder and the dry run both consume."""
        return self.path, self.tags, self.args


@dataclass(frozen=True)
class Plan:
    """What to write, plus what did not need writing and what cannot be told."""

    writes: Tuple[Write, ...]
    confirmed: Tuple[str, ...]
    unverifiable: Tuple[str, ...]

    def links(self) -> Tuple[Write, ...]:
        return tuple(w for w in self.writes if w.phase == PHASE_LINK)

    def mix(self) -> Tuple[Write, ...]:
        return tuple(w for w in self.writes if w.phase == PHASE_MIX)

    def messages(self) -> Tuple[Tuple[str, str, Args], ...]:
        """Every write in send order: all links, the barrier, then all mix."""
        return tuple(w.message() for w in self.writes)


def desired(config: Config) -> Tuple[Entry, ...]:
    """The register state a config asks the device to be in.

    Ordered the way it is sent, which is per *routing* and not per
    route: every link of every route, then every mix write. Walking
    route by route and emitting link-then-mix for each is the reading
    that silenced every even output, and it is why phase lives on the
    entry rather than being recovered from the path later.

    A later route targeting the same register wins, matching the
    file-order rule the apply already follows -- but the *position* of
    the register is the first one that claimed it, so a duplicate does
    not reorder the plan.
    """
    entries: Dict[str, Entry] = {}
    for phase, produce in ((PHASE_LINK, link_messages), (PHASE_MIX, mix_messages)):
        for route in config.routes:
            for path, tags, args in produce(route):
                entries[path] = Entry(path, tags, tuple(args), phase)
    return tuple(sorted(entries.values(), key=_send_order(config)))


def _send_order(config: Config) -> Callable[[Entry], int]:
    """Sort key restoring the order the messages were produced in."""
    position: Dict[str, int] = {}
    index = 0
    for produce in (link_messages, mix_messages):
        for route in config.routes:
            for path, _tags, _args in produce(route):
                if path not in position:
                    position[path] = index
                    index += 1
    return lambda entry: position[entry.path]


def observed(reports: Mapping[str, Sequence[object]]) -> Dict[str, Args]:
    """The device's own view, as the dump reported it.

    A plain projection today. It is a named step because
    ``--dump-config`` is this rendered as config, and because "what the
    device says" deserves to be a value rather than a dict that happens
    to be lying around inside the verifier.
    """
    return {path: tuple(args) for path, args in reports.items()}


def plan(entries: Sequence[Entry],
         seen: Optional[Mapping[str, Args]] = None,
         device: Optional[Device] = None,
         tolerance: float = 0.5) -> Plan:
    """What to write to get from ``seen`` to ``entries``.

    ``seen=None`` means *nothing was observed* -- the dump could not be
    read, or this is a first apply. Then every entry is written, which
    is exactly what ``apply_routing`` does today and why the equivalence
    test below can compare the two.

    ``device=None`` means the register model has no opinion, and every
    entry is treated as comparable. That keeps an unmodelled interface
    behaving as it always did.

    Floats compare with a tolerance because the device quantizes levels;
    0.5 dB is the value the read-back has used since 0.1.2.
    """
    writes: List[Write] = []
    confirmed: List[str] = []
    unverifiable: List[str] = []
    blind = seen is None
    observations: Mapping[str, Args] = {} if seen is None else seen

    for entry in entries:
        klass = verify_class(device, entry.path) if device else VERIFIABLE
        if blind:
            writes.append(Write(entry.path, entry.tags, entry.args,
                                entry.phase, UNCONDITIONAL))
            continue
        if klass == REESTABLISHED:
            # Unverifiable *and* dependent on link state: rewritten from
            # a known-good state rather than compared. Comparing it would
            # mean trusting a value the dump never carries.
            writes.append(Write(entry.path, entry.tags, entry.args,
                                entry.phase, REWRITE))
            unverifiable.append(entry.path)
            continue
        if entry.path not in observations:
            writes.append(Write(entry.path, entry.tags, entry.args,
                                entry.phase, MISSING))
            continue
        if _matches(entry.tags, entry.args, observations[entry.path], tolerance):
            confirmed.append(entry.path)
        else:
            writes.append(Write(entry.path, entry.tags, entry.args,
                                entry.phase, MISMATCHED))

    writes.sort(key=lambda w: w.phase)
    return Plan(tuple(writes), tuple(confirmed), tuple(unverifiable))


def _matches(tags: str, want: Args, got: Args, tolerance: float) -> bool:
    """Whether a reported value satisfies a desired one.

    Extra trailing arguments in the report are ignored, so a richer
    upstream dump format cannot break the comparison.
    """
    if len(got) < len(want):
        return False
    for tag, wanted, reported in zip(tags, want, got):
        try:
            if tag == "f":
                if abs(float(wanted) - float(reported)) > tolerance:  # type: ignore[arg-type]
                    return False
            elif int(wanted) != int(reported):  # type: ignore[call-overload]
                return False
        except (TypeError, ValueError):
            return False
    return True


def unreachable(config: Config, device: Optional[Device]) -> Tuple[str, ...]:
    """Registers the config asks for that this device cannot verify.

    Not an error -- write-only registers are legitimate, and 0.3.0 adds
    several (`/input/*/name`, `/output/*/loopback`). It is the list a
    verifier must report as *unverifiable* rather than silently counting
    as confirmed, which is how verification starts over-claiming as the
    surface grows.
    """
    if device is None:
        return ()
    return tuple(entry.path for entry in desired(config)
                 if verify_class(device, entry.path) not in (VERIFIABLE, None))


def routes_of(config: Config) -> Tuple[Route, ...]:
    """The routes a plan came from, for callers that still need them."""
    return tuple(config.routes)
