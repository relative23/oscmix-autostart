"""The hardware harness's verdict logic, tested without hardware.

`scripts/verify-hardware.py` needs a Fireface to take a measurement, but
deciding what a measurement *means* is pure arithmetic and belongs under
test. The cases below are the three defects this project actually shipped,
expressed as the numbers the meters would have shown.

The methodology is worth stating because the first version got it wrong:
each output is compared against **itself** across the two tone runs, not
against the other output within one run. Anything else playing at the same
time sits in both measurements, so a left-versus-right comparison measures
that audio's stereo image instead of the routing. That mistake produced a
confident 3.4 dB "failure" on a route that was working perfectly.
"""

import importlib.util

import pytest
from conftest import repo_file


def load_harness():
    path = repo_file("scripts", "verify-hardware.py")
    spec = importlib.util.spec_from_file_location("verify_hardware", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness():
    return load_harness()


QUIET = {5: -144.0, 6: -144.0}


def test_a_working_pair_passes(harness):
    verdict = harness.check_route(
        "monitors", (5, 6),
        left={5: -20.0, 6: -144.0},
        right={5: -144.0, 6: -20.0},
        silence=QUIET)
    assert verdict["ok"], verdict["problems"]


def test_a_silent_even_output_fails(harness):
    # The 0.1.2 defect: outputs 1, 5 and 7 carried a mono sum while 2, 6
    # and 8 were digitally silent. Output 6 never responds.
    verdict = harness.check_route(
        "monitors", (5, 6),
        left={5: -20.0, 6: -144.0},
        right={5: -20.0, 6: -144.0},
        silence=QUIET)
    assert not verdict["ok"]
    assert any("output 6" in problem for problem in verdict["problems"])


def test_a_mono_summed_pair_fails(harness):
    # Both outputs carry both channels: each responds to either tone, so
    # neither shows a response difference. Audibly this is "everything is
    # there but the stereo image is gone", which no message-level test
    # would notice.
    verdict = harness.check_route(
        "monitors", (5, 6),
        left={5: -20.0, 6: -20.0},
        right={5: -20.0, 6: -20.0},
        silence=QUIET)
    assert not verdict["ok"]
    assert len(verdict["problems"]) == 2


def test_a_half_dead_unlinked_pair_fails(harness):
    # The 0.1.3 defect: `stereo = false` left one output of the pair
    # completely dead while the other still played.
    verdict = harness.check_route(
        "phones", (7, 8),
        left={7: -144.0, 8: -25.0},
        right={7: -144.0, 8: -20.0},
        silence={7: -144.0, 8: -144.0})
    assert not verdict["ok"]
    assert any("output 7" in problem for problem in verdict["problems"])


def test_competing_audio_is_reported_rather_than_judged(harness):
    # Music on the same bus masks the tone. The honest answer is "stop
    # other audio and retry", not a verdict on the routing -- the first
    # version failed a healthy route this way.
    verdict = harness.check_route(
        "monitors", (5, 6),
        left={5: -40.0, 6: -43.0},
        right={5: -44.0, 6: -40.0},
        silence={5: -44.0, 6: -44.0})
    assert not verdict["ok"]
    assert all("stop other audio" in problem for problem in verdict["problems"])


def test_a_missing_output_is_named(harness):
    verdict = harness.check_route(
        "monitors", (5, 6),
        left={5: -20.0}, right={}, silence=QUIET)
    assert not verdict["ok"]
    assert any("never reported" in problem for problem in verdict["problems"])


def test_the_verdict_records_what_was_measured(harness):
    # The evidence artifact is the point: a verdict nobody can re-read is
    # not evidence.
    verdict = harness.check_route(
        "monitors", (5, 6),
        left={5: -20.0, 6: -144.0},
        right={5: -144.0, 6: -20.0},
        silence=QUIET)
    peaks = verdict["peaks_db"]
    assert peaks["output_5"]["left_tone"] == -20.0
    assert peaks["output_5"]["right_tone"] == -144.0
    assert verdict["response_left_db"] == 124.0
    assert verdict["response_right_db"] == 124.0


def test_tone_generation_puts_the_signal_on_one_side(harness, tmp_path):
    import struct
    import wave

    path = tmp_path / "left.wav"
    harness.write_tone(path, left=True, right=False)
    with wave.open(str(path)) as handle:
        assert handle.getnchannels() == 2
        frames = handle.readframes(min(handle.getnframes(), 48000))
    samples = struct.unpack("<%dh" % (len(frames) // 2), frames)
    assert max(abs(value) for value in samples[0::2]) > 1000
    assert max(abs(value) for value in samples[1::2]) == 0


# --------------------------------------------------------------------------
# Saying *why* an output is silent.
#
# The first real run of this tool against a UCX II failed the `main-out`
# route and blamed other audio on the bus. The actual cause was
# /output/1/volume sitting at -65 dB -- the fader pulled shut on a rear
# output the owner does not use. The device reports that, the tool could
# read it, and the verdict said something else.
#
# It matters because the two look identical in the levels and are
# opposite in what they ask of the reader: one says "stop your music and
# try again", the other says "this output is off, and deliberately so".
# --------------------------------------------------------------------------

SHUT = {"volume": -65.0, "mute": 0}
OPEN = {"volume": 0.0, "mute": 0}


def test_a_shut_fader_is_named_instead_of_blaming_the_bus(harness):
    verdict = harness.check_route(
        "main-out", (1, 2),
        left={1: -144.0, 2: -144.0},
        right={1: -144.0, 2: -144.0},
        silence={1: -144.0, 2: -144.0},
        state={1: SHUT, 2: SHUT})
    assert not verdict["ok"]
    assert all("fader is shut" in problem for problem in verdict["problems"])
    assert all("stop other audio" not in problem
               for problem in verdict["problems"])
    # ... and it says whose value that is: a route without 'volume'
    # leaves the fader to the user (ADR 0003).
    assert all("yours" in problem for problem in verdict["problems"])


def test_a_muted_output_is_named(harness):
    verdict = harness.check_route(
        "monitors", (5, 6),
        left={5: -144.0, 6: -144.0},
        right={5: -144.0, 6: -144.0},
        silence={5: -144.0, 6: -144.0},
        state={5: {"volume": 0.0, "mute": 1}, 6: {"volume": 0.0, "mute": 1}})
    assert not verdict["ok"]
    assert any("mute is set" in problem for problem in verdict["problems"])


def test_competing_audio_is_still_blamed_when_the_faders_are_open(harness):
    # The regression guard for the fix: adding the explanation must not
    # swallow the case it was bolted onto.
    verdict = harness.check_route(
        "monitors", (5, 6),
        left={5: -40.0, 6: -43.0},
        right={5: -44.0, 6: -40.0},
        silence={5: -44.0, 6: -44.0},
        state={5: OPEN, 6: OPEN})
    assert not verdict["ok"]
    assert all("stop other audio" in problem for problem in verdict["problems"])


def test_an_unknown_output_state_changes_nothing(harness):
    # The state read is best-effort: it sends /refresh and takes what
    # arrives. A verdict must not depend on it having arrived.
    verdict = harness.check_route(
        "monitors", (5, 6),
        left={5: -40.0, 6: -43.0},
        right={5: -44.0, 6: -40.0},
        silence={5: -44.0, 6: -44.0},
        state={})
    assert not verdict["ok"]
    assert all("stop other audio" in problem for problem in verdict["problems"])


def test_a_healthy_route_records_its_open_faders(harness):
    # The evidence artifact carries the state either way: "this passed,
    # and here is the fader it passed at" is a stronger record than a
    # bare ok.
    verdict = harness.check_route(
        "monitors", (5, 6),
        left={5: -20.0, 6: -144.0},
        right={5: -144.0, 6: -20.0},
        silence=QUIET,
        state={5: OPEN, 6: OPEN})
    assert verdict["ok"]
    assert verdict["output_state"] == {"output_5": OPEN, "output_6": OPEN}


def test_a_quiet_but_not_shut_fader_is_reported_with_its_value(harness):
    # Between "shut" and "fine" there is "someone turned it down". Worth
    # naming with the number rather than guessing at a threshold.
    verdict = harness.check_route(
        "monitors", (5, 6),
        left={5: -144.0, 6: -144.0},
        right={5: -144.0, 6: -144.0},
        silence={5: -144.0, 6: -144.0},
        state={5: {"volume": -40.0, "mute": 0},
               6: {"volume": -40.0, "mute": 0}})
    assert not verdict["ok"]
    assert any("-40.0 dB" in problem for problem in verdict["problems"])
