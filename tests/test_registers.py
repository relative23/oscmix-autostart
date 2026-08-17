"""The register model, checked against the recordings it came from.

A hand-written model of a device is knowledge that decays silently:
nothing fails when it goes stale, the device just does something other
than what the config says. These tests are the difference between a
model and a memory -- every claim `registers.py` makes about the UCX II
is held against `tests/data/refresh-dump.json` (a warm `/refresh`) and
`tests/data/cold-plug-timeline.json` (a real USB replug).

Two claims are deliberately *not* checked this way, and both are noted
where they arise: the meter channels, which the model records but 0.2.0
never writes, and the odd-channel-only shape of the input mix matrix,
which is link state rather than a capability.
"""

import json
import re

import pytest
from conftest import repo_file

from oscmix_autostart import registers


@pytest.fixture(scope="module")
def warm():
    return json.loads(repo_file("tests", "data", "refresh-dump.json").read_text())


@pytest.fixture(scope="module")
def cold():
    return json.loads(
        repo_file("tests", "data", "cold-plug-timeline.json").read_text())


# --------------------------------------------------------------------------
# The device dimension exists from the first line, not retrofitted.
# --------------------------------------------------------------------------

def test_the_model_is_indexed_by_device():
    assert len(registers.DEVICES) >= 2
    assert registers.UCX2.usb_id != registers.FF802.usb_id
    # `48v` on 1-2 and `hi-z` on 3-4 are UCX II facts, not Fireface facts.
    assert registers.UCX2.channels_for("48v") == (1, 2)
    assert registers.UCX2.channels_for("hi-z") == (3, 4)


def test_an_untested_device_declares_nothing_rather_than_guesses():
    # "May work" as a property of the data. Guessing the 802's registers
    # is how a model becomes a lie about hardware nobody here can test.
    assert registers.FF802.supported is False
    assert registers.FF802.registers == ()
    assert registers.FF802.channels == {}
    assert registers.FF802.evidence is None


def test_a_supported_device_names_its_evidence():
    # The roadmap's bar: register table declared, capabilities recorded,
    # and one hardware evidence artifact.
    for device in registers.DEVICES:
        if device.supported:
            assert device.registers, "%s claims support with no registers" % device.key
            assert device.channels
            assert device.evidence, "%s claims support with no evidence" % device.key


def test_an_unmodelled_device_is_no_opinion_not_an_error():
    # Every caller must treat None as "keep doing what you did".
    assert registers.device_for_name("Fireface UFX III") is None
    assert registers.channel_limit(None) is None
    assert registers.verify_class(None, "/output/1/volume") is None
    assert registers.cold_plug_complete(None, "/output/1/stereo") is False


def test_the_configured_device_name_resolves():
    assert registers.device_for_name("Fireface UCX II") is registers.UCX2
    assert registers.device_for_name("  fireface ucx ii  ") is registers.UCX2


# --------------------------------------------------------------------------
# Every channel range, against the recording it was read from.
# --------------------------------------------------------------------------

def channels_in(dump, prefix, leaf):
    found = set()
    for path in dump:
        match = re.fullmatch(r"/%s/(\d+)/%s" % (prefix, re.escape(leaf)), path)
        if match:
            found.add(int(match.group(1)))
    return tuple(sorted(found))


@pytest.mark.parametrize(("capability", "prefix", "leaf"), [
    ("output", "output", "stereo"),
    ("output", "output", "volume"),
    ("input", "input", "stereo"),
    ("playback", "playback", "stereo"),
    ("48v", "input", "48v"),
    ("hi-z", "input", "hi-z"),
    ("input-gain", "input", "gain"),
    ("input-reflevel", "input", "reflevel"),
    ("output-reflevel", "output", "reflevel"),
])
def test_every_channel_range_matches_the_recording(warm, capability, prefix, leaf):
    recorded = channels_in(warm["registers"], prefix, leaf)
    assert registers.UCX2.channels_for(capability) == recorded, (
        "the model says /%s/N/%s exists on %s, the device reported %s"
        % (prefix, leaf, registers.UCX2.channels_for(capability), recorded))


def test_the_meters_run_further_than_the_control_registers(warm):
    # The reason a single "channel count" per device would already be
    # wrong: meters go to 22, everything that can be *set* stops at 20.
    meters = channels_in(warm["registers"], "output", "level")
    assert registers.UCX2.channels_for("meter") == meters
    assert max(meters) > max(registers.UCX2.channels_for("output"))


# --------------------------------------------------------------------------
# Verification classes, against what the dump does and does not report.
# --------------------------------------------------------------------------

def test_every_verifiable_register_really_is_reported(warm):
    reported = set(warm["registers"])
    missing = [p for p in registers.declared_paths(registers.UCX2)
               if registers.verify_class(registers.UCX2, p) == registers.VERIFIABLE
               and p not in reported]
    assert missing == [], (
        "declared verifiable but absent from the recorded dump: %s" % missing[:8])


def test_every_write_only_register_really_is_absent(warm):
    reported = set(warm["registers"])
    present = [p for p in registers.declared_paths(registers.UCX2)
               if registers.verify_class(registers.UCX2, p) == registers.WRITE_ONLY
               and p in reported]
    assert present == [], (
        "declared write-only but the device reported it: %s -- if upstream "
        "started dumping these, the verifier may confirm them" % present[:8])


def test_the_playback_matrix_is_the_only_re_established_family(warm):
    reest = [r for r in registers.UCX2.registers
             if r.verify == registers.REESTABLISHED]
    assert [r.template for r in reest] == ["/mix/{out}/playback/{pb}"]
    # ... and it is absent, which is what forces the class.
    assert not [p for p in warm["registers"]
                if p.startswith("/mix/") and "/playback/" in p]


def test_the_input_matrix_is_verifiable_which_0_3_0_depends_on(warm):
    assert registers.verify_class(registers.UCX2, "/mix/5/input/1") == \
        registers.VERIFIABLE
    assert len([p for p in warm["registers"]
                if p.startswith("/mix/") and "/input/" in p]) >= 100


def test_the_class_of_an_unknown_path_is_unknown():
    # Not a default of "verifiable": a register nobody modelled must not
    # inherit a promise.
    assert registers.verify_class(registers.UCX2, "/reverb/type") is None
    assert registers.verify_class(registers.UCX2, "/output/1/crossfeed") is None


def test_every_declared_class_is_one_of_the_three():
    for device in registers.DEVICES:
        for register in device.registers:
            assert register.verify in registers.VERIFY_CLASSES


# --------------------------------------------------------------------------
# The cold-plug dimension, which the warm dump alone cannot tell you.
# --------------------------------------------------------------------------

def test_the_families_called_complete_really_arrive_whole(cold):
    """Every channel, not most of them.

    This is the claim that matters: 0.2.0 works after a hotplug because
    the stereo flags come back for all 20 channels within ~2.3 s. If a
    pin bump made that partial, everything this project applies would be
    verifying against a half-filled cache.
    """
    reported = set(cold["first_report_seconds"])
    for register in registers.UCX2.registers:
        if not register.per_channel:
            continue
        if not registers.cold_plug_complete(registers.UCX2,
                                            register.path(ch=1)):
            continue
        missing = [register.path(ch=c)
                   for c in registers.UCX2.channels_for(register.channels)
                   if register.path(ch=c) not in reported]
        assert missing == [], (
            "%s is declared complete after a cold plug but %d channel(s) "
            "were not reported: %s"
            % (register.template, len(missing), missing[:6]))


def test_everything_else_is_not_claimed_to_be_complete(cold):
    """The honest half, and the reason this is a list of what *is* whole.

    A cold plug delivered 1234 of 1932 non-meter registers, and what was
    missing is ragged rather than lawful: `/output/N/mute` came back for
    channels 1, 2, 3, 8, 9 and 10, and not for 4-7 or 11-20. That is a
    truncated stream, not a rule, and modelling it per family or per
    channel would encode one recording as a device property.

    So the model refuses to answer for anything it did not measure whole
    -- including registers nobody measured at all.
    """
    reported = set(cold["first_report_seconds"])
    partial = []
    for register in registers.UCX2.registers:
        if not register.per_channel:
            continue
        channels = registers.UCX2.channels_for(register.channels)
        if not channels or register.verify != registers.VERIFIABLE:
            continue
        seen = sum(1 for c in channels if register.path(ch=c) in reported)
        if 0 < seen < len(channels):
            partial.append((register.template, seen, len(channels)))
            assert not registers.cold_plug_complete(
                registers.UCX2, register.path(ch=channels[0])), (
                "%s arrived for %d of %d channels but is declared complete"
                % (register.template, seen, len(channels)))
    assert partial, (
        "nothing arrived partially -- if a cold plug is complete now, "
        "re-record and simplify this away")


def test_what_0_2_0_verifies_survives_a_cold_plug(cold):
    # The reason this gap went unnoticed for two releases: everything
    # this release actually checks is in the fast, complete part.
    reported = set(cold["first_report_seconds"])
    for path in ("/output/1/stereo", "/output/5/stereo", "/output/7/stereo",
                 "/playback/1/stereo"):
        assert path in reported, "%s missing from a cold plug" % path
        assert registers.verify_class(registers.UCX2, path) == registers.VERIFIABLE
        assert registers.cold_plug_complete(registers.UCX2, path)


def test_an_unmeasured_register_is_never_called_complete():
    # A verifier must not fail a register into a warning because a
    # hotplug was still filling the cache, and "unknown" must not read
    # as "fine".
    assert not registers.cold_plug_complete(registers.UCX2, "/reverb/type")
    assert not registers.cold_plug_complete(registers.UCX2, "/output/1/mute")
    assert not registers.cold_plug_complete(None, "/output/1/stereo")
