"""What registers a device has, as data rather than as knowledge.

0.3.0 multiplies the register surface by roughly ten. Today the facts
about that surface are spread across three places and none of them is
checkable: format strings in ``routing.py``, a channel range in
``constants.py`` that is not device-specific at all, and two hand-written
family rules in ``verify.py``. Ten times as much of that is not
maintainable, and it is the sort of knowledge that decays silently --
nothing fails when it goes stale, the device just does something other
than what the config says.

**Indexed by device from the first line.** ``48v`` on inputs 1-2 and
``hi-z`` on 3-4 are UCX II facts, not Fireface facts. A model without a
device dimension casts this one interface into the structure and puts the
untested 802 permanently out of reach -- in the very refactor that could
have brought it closer.

**Derived from a recording, not from memory.** Every channel range below
was read out of ``tests/data/refresh-dump.json``, and
``tests/test_registers.py`` checks the model against that recording and
against ``tests/data/cold-plug-timeline.json``. A claim here that the
device does not support is a failing test, not a surprise on someone
else's desk.

Nothing in this module talks to a device or decides anything. It answers
questions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple

from .constants import LEVEL_MAX, LEVEL_MIN

# --------------------------------------------------------------------------
# Verification classes.
#
# The dump splits the surface into three, and naming the class is what
# keeps verification from over-claiming as the surface grows. Today the
# distinction lives in `register_promptly_reported` and in prose, which
# is fine for six registers and not for sixty.
# --------------------------------------------------------------------------

#: Reported by the dump, so a value is confirmed, mismatched or missing.
VERIFIABLE = "verifiable"

#: Accepted by the device, never reported back. The verifier must say
#: *unverifiable*, never *confirmed* -- `/input/*/name`, `/output/*/name`,
#: `/output/*/loopback`, all confirmed absent from a full dump.
WRITE_ONLY = "write-only"

#: Unverifiable *and* dependent on link state, so it is rewritten from a
#: known-good state rather than checked. The playback mix matrix is the
#: only member: a `/mix` write draws no reply and the dump omits it.
REESTABLISHED = "re-established"

VERIFY_CLASSES = (VERIFIABLE, WRITE_ONLY, REESTABLISHED)


# --------------------------------------------------------------------------
# Who wins after the initial write.
#
# Measured on a UCX II, and the measurement is what shapes this. Of every
# register a config can set, exactly one is *pushed* to listeners when it
# changes: `/output/{ch}/stereo`, which the device echoes over MIDI --
# the echo the two-phase apply already waits for. (`/clock/samplerate` is
# pushed as well, measured later; no config sets it, so it does not
# change the argument below -- but it is the one register a session can
# react to without asking.) `volume`, `mute`,
# `hi-z`, `gain`, `reflevel` and `/playback/{ch}/stereo` all change
# silently; only a `/refresh` reveals them.
#
# So "pin" cannot mean "snaps back when the mixer GUI changes it". There
# is nothing to react to short of polling a 2002-register dump, against
# a device already streaming ~880 meter datagrams a second. What pin can
# honestly mean is: **the config wins for as long as this session is
# still looking** -- through the read-back window, and through any
# future reconcile trigger.
#
# What that replaces is an accident. Today a declared option behaves as
# pinned for roughly the two seconds the apply and dump take, and as
# remembered after -- measured by turning a fader at 0.5, 1.5, 3 and 6
# seconds after a restart: only the 0.5 s change was overwritten, and by
# the ordinary start-up apply rather than by the verifier. The cut-off
# was the shape of the timing, not anybody's decision.

#: The config wins. A device value that disagrees is a mismatch: the
#: read-back re-sends it, and so does any later reconcile.
PIN = "pin"

#: The device wins after the initial write. The config value is applied
#: at start and then let go -- a later disagreement is the user having
#: turned something, which is information, not a fault.
REMEMBER = "remember"

POLICIES = (PIN, REMEMBER)


#: Value domains, as a config author has to satisfy them.
BOOL = "bool"
ENUM = "enum"
#: A quantity with a declared range and unit. Replaces the separate
#: GAIN (0..75 dB) and DB (LEVEL_MIN..LEVEL_MAX) domains, which were the
#: same shape with different bounds and a hand-written message each --
#: two ways to say one thing, which is how a validator and a register
#: table come to disagree about what is legal.
#:
#: ``lo``/``hi`` are ``None`` where upstream's node table declares no
#: bound. A range this project invented would reject values the device
#: accepts, and that is worse than accepting one it does not: the first
#: is a config that will not load, the second is an error the device
#: reports.
NUMBER = "number"


@dataclass(frozen=True)
class Register:
    """One register family: where it lives, what it holds, how it verifies.

    ``template`` uses ``{ch}``, or ``{out}`` and ``{pb}``/``{in_}`` for
    the matrix families. ``channels`` names a capability in the device's
    channel map rather than repeating a range, because the same range is
    shared by several registers and a copy is a place to disagree.
    """

    template: str
    tags: str
    verify: str
    channels: str
    #: What a config may set it to, or None when this project does not
    #: expose it as a setting. A register with no domain is readable and
    #: writable by the code, not by a `routing.conf`.
    domain: Optional[str] = None
    #: For ENUM: the accepted names, exactly as the device reports them.
    #: Taken from upstream's device table, which is where the device's
    #: own vocabulary lives -- inventing synonyms here would mean a
    #: config that reads well and sets nothing.
    choices: Tuple[str, ...] = ()
    #: For NUMBER: the inclusive bounds and the unit, taken from
    #: upstream's node table (``min``/``max``/``scale``) rather than
    #: from what a device happened to report. ``None`` means upstream
    #: declares no bound.
    lo: Optional[float] = None
    hi: Optional[float] = None
    unit: str = ""
    #: Who wins after the initial write, PIN or REMEMBER. The default is
    #: REMEMBER because that is ADR 0003's rule -- do not wipe what the
    #: user left in the mixer -- and a register that forgot to declare a
    #: policy should fall on the side that surprises nobody.
    #:
    #: PIN belongs to registers that describe the *installation* rather
    #: than a preference: a reference level or a hi-Z switch has to match
    #: the cable that is plugged in, and a wrong value there is a real
    #: signal problem rather than a matter of taste. REMEMBER belongs to
    #: everything a person reaches for during a session.
    policy: str = REMEMBER

    @property
    def per_channel(self) -> bool:
        """Whether one channel number names the register.

        The matrix families take two (``/mix/{out}/input/{in_}``), and a
        caller that assumes one gets a KeyError -- so the distinction is
        answered here rather than rediscovered at each call site.
        """
        return "{ch}" in self.template

    def path(self, **channels: int) -> str:
        return self.template.format(**channels)


@dataclass(frozen=True)
class Device:
    """A Fireface, and what its registers are.

    ``channels`` maps a capability name to the channels that have it.
    ``supported`` states the bar from the roadmap plainly: a device is
    supported when its register table is declared, its channel
    capabilities are recorded, and one hardware evidence artifact exists
    for it. Below that line it is "may work", and saying so in the data
    is better than saying it in a README nobody reads at the right time.
    """

    key: str
    name: str
    usb_id: str
    channels: Mapping[str, Tuple[int, ...]]
    registers: Tuple[Register, ...]
    supported: bool
    #: Families measured to arrive *complete*, for every channel, within
    #: seconds of a cold plug. See ``cold_plug_complete`` -- everything
    #: not listed here may be partially delivered, and 0.3.0 must not
    #: fail a verification over it.
    complete_after_cold_plug: Tuple[str, ...] = ()
    evidence: Optional[str] = None

    def channels_for(self, capability: str) -> Tuple[int, ...]:
        return self.channels.get(capability, ())

    def has(self, capability: str, channel: int) -> bool:
        return channel in self.channels_for(capability)


def _seq(first: int, last: int) -> Tuple[int, ...]:
    return tuple(range(first, last + 1))


# --------------------------------------------------------------------------
# Fireface UCX II.
#
# Every range below was read out of a recorded /refresh dump against the
# pinned oscmix revision, not typed from the manual. Two of them would
# have been wrong if guessed:
#
#   * the level meters run to 22 while every control register stops at
#     20 -- so a single "channel count" for the device is already wrong;
#   * `/mix/<out>/input/<in>` appeared only on odd channels in the
#     recording. That is *link state*, not a capability: linked pairs
#     fold onto the odd channel. It is deliberately not modelled here.
# --------------------------------------------------------------------------

UCX2 = Device(
    key="ucx2",
    name="Fireface UCX II",
    usb_id="2a39:3fd9",
    channels={
        "input": _seq(1, 20),
        "output": _seq(1, 20),
        "playback": _seq(1, 20),
        # Meters exist for two more than the control registers do.
        "meter": _seq(1, 22),
        "48v": (1, 2),
        "hi-z": (3, 4),
        "input-gain": _seq(1, 8),
        "input-reflevel": _seq(3, 8),
        "output-reflevel": _seq(1, 8),
    },
    registers=(
        # --- what 0.2.0 already writes ---------------------------------
        Register("/playback/{ch}/stereo", "i", VERIFIABLE, "playback",
                 policy=PIN),
        Register("/output/{ch}/stereo", "i", VERIFIABLE, "output",
                 policy=PIN),
        Register("/output/{ch}/volume", "f", VERIFIABLE, "output", NUMBER,
                 lo=LEVEL_MIN, hi=LEVEL_MAX, unit="dB"),
        # The playback matrix: a /mix write draws no reply and the dump
        # omits it entirely. Re-established from a known link state.
        Register("/mix/{out}/playback/{pb}", "fi", REESTABLISHED, "output",
                 policy=PIN),

        # --- the surface 0.3.0 declares --------------------------------
        # Reported, so almost all of the new surface is verifiable --
        # unlike the playback matrix this project started with.
        Register("/mix/{out}/input/{in_}", "fi", VERIFIABLE, "output",
                 policy=PIN),
        # 48v deliberately has NO domain: it is readable by the code and not
        # settable from a routing.conf. See registers.settable_options and
        # the roadmap's rule -- phantom power is not exposed until a
        # hardware case proves the channel it names is the channel it
        # hits, because an off-by-one is damaged equipment, not silence.
        Register("/input/{ch}/48v", "i", VERIFIABLE, "48v", policy=PIN),
        Register("/input/{ch}/hi-z", "i", VERIFIABLE, "hi-z", BOOL,
                 policy=PIN),
        Register("/input/{ch}/gain", "f", VERIFIABLE, "input-gain", NUMBER,
                 lo=0.0, hi=75.0, unit="dB", policy=PIN),
        Register("/input/{ch}/reflevel", "is", VERIFIABLE, "input-reflevel", ENUM,
                 ("+13dBu", "+19dBu"), policy=PIN),
        Register("/input/{ch}/mute", "i", VERIFIABLE, "input", BOOL),
        Register("/input/{ch}/phase", "i", VERIFIABLE, "input", BOOL),
        Register("/input/{ch}/stereo", "i", VERIFIABLE, "input", policy=PIN),
        # Verifiable, but see complete_after_cold_plug below: a cold
        # plug delivers these only for some channels.
        Register("/output/{ch}/mute", "i", VERIFIABLE, "output", BOOL),
        Register("/output/{ch}/phase", "i", VERIFIABLE, "output", BOOL),
        Register("/output/{ch}/reflevel", "is", VERIFIABLE, "output-reflevel", ENUM,
                 ("+4dBu", "+13dBu", "+19dBu"), policy=PIN),

        # --- accepted, never reported ----------------------------------
        Register("/input/{ch}/name", "s", WRITE_ONLY, "input"),
        Register("/output/{ch}/name", "s", WRITE_ONLY, "output"),
        Register("/output/{ch}/loopback", "i", WRITE_ONLY, "output"),
    ),
    supported=True,
    # Measured across a real USB replug: the stereo flags arrive for all
    # 20 channels within ~2.3 s, and nothing else does. /output/N/mute
    # came back for channels 1,2,3,8,9,10 and not for 4-7 or 11-20 --
    # a truncated stream rather than a rule, which is exactly why this
    # is a list of what IS complete rather than a flag on what is not.
    complete_after_cold_plug=("/output/{ch}/stereo", "/playback/{ch}/stereo"),
    evidence="hardware-evidence.json attached to v0.2.0",
)


# The 802 has never been tested. It is listed so the device dimension is
# real from the first line rather than retrofitted, and so "may work" is
# a property of the data instead of a sentence in the README. It declares
# no registers on purpose: guessing them is how a model becomes a lie.
FF802 = Device(
    key="ff802",
    name="Fireface 802",
    usb_id="2a39:3fc0",
    channels={},
    registers=(),
    supported=False,
)

DEVICES: Tuple[Device, ...] = (UCX2, FF802)


def device_for_name(name: str) -> Optional[Device]:
    """The device a ``routing.conf`` names, or None if it is not modelled.

    Matching is on the configured device name, which is what the config
    already uses to find the ALSA client. None is a normal answer: an
    unmodelled device must keep working exactly as it did, which is why
    every caller treats it as "no opinion" rather than as an error.
    """
    for device in DEVICES:
        if device.name.lower() == name.strip().lower():
            return device
    return None


def channel_limit(device: Optional[Device], capability: str = "output") -> Optional[int]:
    """The highest channel a device has, or None when it is not modelled."""
    if device is None:
        return None
    channels = device.channels_for(capability)
    return max(channels) if channels else None


def register_policy(device: Optional[Device], path: str) -> str:
    """PIN or REMEMBER for a concrete path, from the register table.

    REMEMBER for anything the model does not know, matching the field
    default: an unmodelled register is not something this project should
    start insisting on.
    """
    if device is None:
        return REMEMBER
    for register in device.registers:
        if _matches(register.template, path):
            return register.policy
    return REMEMBER


def verify_class(device: Optional[Device], path: str) -> Optional[str]:
    """How a concrete OSC path verifies, or None when nothing is known.

    Concrete paths, not templates: the caller has a path off the wire.
    """
    if device is None:
        return None
    for register in device.registers:
        if _matches(register.template, path):
            return register.verify
    return None


def _matches(template: str, path: str) -> bool:
    """Whether a concrete path is an instance of a template."""
    want = template.split("/")
    got = path.split("/")
    if len(want) != len(got):
        return False
    for part_want, part_got in zip(want, got):
        if part_want.startswith("{") and part_want.endswith("}"):
            if not part_got.isdigit():
                return False
        elif part_want != part_got:
            return False
    return True


def cold_plug_complete(device: Optional[Device], path: str) -> bool:
    """Whether a cold plug reports this register for *every* channel.

    Measured across a real USB replug: the device delivers 1234 of 1932
    non-meter registers within seconds, and the rest may not arrive for
    minutes -- 276 s of further observation saw nothing more. The stereo
    flags come complete for all 20 channels; `/output/N/mute` came back
    for 1, 2, 3, 8, 9 and 10 but not for 4-7 or 11-20.

    That ragged set is a truncated stream, not a rule, so this answers
    only the question that generalises: *is this family known to arrive
    whole?* Anything else is False, including registers nobody measured
    -- a verifier must not fail a register into a warning because a
    hotplug was still filling the cache.
    """
    if device is None:
        return False
    return any(_matches(template, path)
               for template in device.complete_after_cold_plug)


def declared_paths(device: Device, capability_channels: Optional[
        Dict[str, Sequence[int]]] = None) -> Tuple[str, ...]:
    """Every concrete path the model declares for a device.

    Used by the tests to check the model against a recording. Matrix
    families are skipped: their second index is a different capability
    and enumerating the cross product says nothing the per-family checks
    do not already say.
    """
    paths = []
    for register in device.registers:
        if "{out}" in register.template:
            continue
        channels = (capability_channels or {}).get(
            register.channels, device.channels_for(register.channels))
        for channel in channels:
            paths.append(register.path(ch=channel))
    return tuple(paths)


def settable_options(device: Optional[Device], family: str) -> Dict[str, Register]:
    """Options a ``[input:N]`` / ``[output:N]`` section may set.

    Derived from the model rather than listed twice: a register is
    settable exactly when it declares a value domain. That is also how
    ``48v`` stays out -- it is modelled, verifiable and readable, and it
    has no domain, so no config can reach it.

    The roadmap's rule for phantom power is why: it may not be settable
    from a text file until a hardware case proves the channel it names
    is the channel it hits. An off-by-one in a silent output is a bug;
    an off-by-one in phantom power is a damaged ribbon microphone.
    """
    if device is None:
        return {}
    prefix = "/%s/{ch}/" % family
    return {r.template[len(prefix):]: r for r in device.registers
            if r.domain is not None and r.template.startswith(prefix)}
