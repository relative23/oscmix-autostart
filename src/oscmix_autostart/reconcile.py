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
from .constants import LEVEL_MIN, UNLINKED_GAIN_OFFSET
from .registers import REESTABLISHED, VERIFIABLE, Device, verify_class

Args = Tuple[object, ...]
Message = Tuple[str, str, Args]


def link_messages(route: Route) -> List[Tuple[str, str, Tuple[object, ...]]]:
    """The channel-pair link state a route needs before its mix is written.

    These must reach the device -- and be reported back to oscmix -- before
    any ``/mix`` message of the same route, see ``LINK_ECHO_TIMEOUT``.

    ``stereo = false`` states the link explicitly rather than assuming it:
    the hard-panned pair of ``/mix`` messages it produces is only correct
    against an *unlinked* pair. Applied to a linked one, both messages
    address the same pair register and the second overwrites the first,
    which leaves one half of the pair completely silent.
    """
    if len(route.output) != 2:
        return []
    kind, source = route.source
    return [
        ("/%s/%d/stereo" % (kind, source[0]), "i", (1,)),
        ("/output/%d/stereo" % route.output[0], "i",
         (1 if route.stereo else 0,)),
    ]


def mix_messages(route: Route) -> List[Tuple[str, str, Tuple[object, ...]]]:
    """The mix-matrix and volume writes of a route.

    oscmix folds stereo-linked channels onto the odd (left) channel of a
    pair: a ``/mix`` message addressed to either half of a linked pair
    writes the *same* pair register, and the pan argument acts as the
    pair's balance. Per-channel messages panned hard left/right (the
    TotalMix pattern for unlinked channels) therefore self-overwrite --
    the last message wins and the whole mix ends up panned hard right.
    A pair route instead links the playback and output pairs and writes
    the single pair register with pan 0 (= plain stereo pass-through at
    ``level`` dB).
    """
    messages: List[Tuple[str, str, Tuple[object, ...]]] = []
    kind, source = route.source
    if len(route.output) == 2:
        left, right = route.output
        pb_left = source[0]
        if route.stereo:
            messages.append(("/mix/%d/%s/%d" % (left, kind, pb_left), "fi",
                             (route.level, 0)))
        else:
            # Unlinked outputs: feed each side the matching half of the
            # (linked) source pair via the pair balance. oscmix halves
            # the gain on this path (setlevel(): ll = vol / 2), so the
            # request is raised by 6 dB to make `level` mean the same
            # thing as it does for a linked route -- measured on a UCX II
            # as an exact 6 dB deficit before this compensation.
            #
            # That measurement was taken on a *playback* source. oscmix
            # runs both kinds through the same setlevel(), so the same
            # halving is expected for an input source -- but expected is
            # not measured, and it needs a signal on a hardware input to
            # check. Flagged in the roadmap rather than assumed silently.
            unlinked = min(route.level, 0.0) + UNLINKED_GAIN_OFFSET
            messages.append(("/mix/%d/%s/%d" % (left, kind, pb_left), "fi",
                             (unlinked, -100)))
            messages.append(("/mix/%d/%s/%d" % (right, kind, pb_left), "fi",
                             (unlinked, 100)))
        if route.volume is not None:
            for out in (left, right):
                messages.append(("/output/%d/volume" % out, "f", (route.volume,)))
    else:
        (out,) = route.output
        (pb,) = source
        messages.append(("/mix/%d/%s/%d" % (out, kind, pb), "fi",
                         (route.level, 0)))
        if route.volume is not None:
            messages.append(("/output/%d/volume" % out, "f", (route.volume,)))
    return messages


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
        if matches(entry.tags, entry.args, observations[entry.path], tolerance):
            confirmed.append(entry.path)
        else:
            writes.append(Write(entry.path, entry.tags, entry.args,
                                entry.phase, MISMATCHED))

    writes.sort(key=lambda w: w.phase)
    return Plan(tuple(writes), tuple(confirmed), tuple(unverifiable))


def _both_muted(wanted: float, reported: float) -> bool:
    """Whether both values mean "no signal", written differently.

    Kept separate so the rule is one place and the citation above is
    not repeated: at or below ``LEVEL_MIN`` upstream stores zero, and
    zero is reported as -inf.
    """
    return wanted <= LEVEL_MIN and reported == float("-inf")


def matches(tags: str, want: Args, got: Args,
            tolerance: float = 0.5) -> bool:
    """Whether a reported value satisfies a desired one.

    Extra trailing arguments in the report are ignored, so a richer
    upstream dump format cannot break the comparison.

    **A gain at or below the mute floor reads back as -inf.** Upstream
    stores it as zero and reports zero as negative infinity::

        level.vol = vol <= -65.f ? 0 : powf(10.f, vol / 20.f);   # setmix
        ...vol > 0 ? 20.f * log10f(level.vol) : -INFINITY        # newmix

    So a route written at ``level = -65`` -- which routing.conf
    documents as mute -- comes back as ``-inf``, and a plain difference
    is infinite. That was invisible while the only mix registers were
    the playback ones, which the dump never reports; input routes are
    verifiable, so a muted monitoring path would have been reported
    mismatched on every start and re-sent every time.

    The two are the same value expressed twice, so they compare equal.
    """
    if len(got) < len(want):
        return False
    for tag, wanted, reported in zip(tags, want, got):
        try:
            if tag == "f":
                if _both_muted(float(wanted), float(reported)):  # type: ignore[arg-type]
                    continue
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
