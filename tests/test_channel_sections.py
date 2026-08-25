"""`[input:N]` and `[output:N]`: channel state that survives a reboot.

The largest surface 0.3.0 adds, and the one where a measurement already
taken decides the design: after a cold plug the device does **not**
report channel state for every channel, so verifying it naively would
warn and re-send the whole routing on every hotplug.

Nothing here lists which options exist or what they accept. All of it
comes out of the register model, which was derived from a recorded dump
and independently agrees with upstream's own device table.
"""

import pytest

from oscmix_desk import reconcile, registers, verify


def write(tmp_path, text):
    path = tmp_path / "routing.conf"
    path.write_text(text)
    return path


DEVICE = "[device]\nname = Fireface UCX II\n\n"


# --------------------------------------------------------------------------
# The settable surface is derived, not listed.
# --------------------------------------------------------------------------

def test_the_options_come_from_the_register_model():
    assert set(registers.settable_options(registers.UCX2, "input")) == {
        "gain", "hi-z", "mute", "phase", "reflevel"}
    # No `phase` on outputs: oscmix cannot write it. See
    # test_output_phase_is_reported_and_not_settable below.
    assert set(registers.settable_options(registers.UCX2, "output")) == {
        "crossfeed", "mute", "reflevel", "volume"}


def test_phantom_power_is_modelled_but_not_settable():
    """The roadmap's rule, enforced by the absence of a value domain.

    `48v` is in the model -- verifiable, readable, on channels 1-2 -- and
    has no domain, so no config can reach it. It stays out until a
    hardware case proves the channel it names is the channel it hits.
    An off-by-one in a silent output is a bug; an off-by-one in phantom
    power is a damaged ribbon microphone.
    """
    assert "48v" not in registers.settable_options(registers.UCX2, "input")
    assert registers.verify_class(
        registers.UCX2, "/input/1/48v") == registers.VERIFIABLE
    assert registers.UCX2.channels_for("48v") == (1, 2)


def test_asking_for_phantom_power_says_why_it_is_refused(session_mod, tmp_path):
    with pytest.raises(session_mod.ConfigError) as excinfo:
        session_mod.load_config(write(tmp_path, DEVICE +
                                      "[input:1]\n48v = true\n"))
    message = str(excinfo.value)
    assert "48v" in message
    assert "hardware case" in message


# --------------------------------------------------------------------------
# Per-channel capability, which is not per-device.
# --------------------------------------------------------------------------

def test_a_section_parses_every_domain(session_mod, tmp_path):
    config = session_mod.load_config(write(tmp_path, DEVICE + (
        "[input:3]\ngain = 12.0\nreflevel = +19dBu\nhi-z = true\nphase = false\n"
        "\n[output:5]\nvolume = -10.0\nmute = false\nreflevel = +4dBu\n")))
    got = {(c.family, c.channel, c.option): c.value for c in config.channels}
    assert got[("input", 3, "gain")] == 12.0
    assert got[("input", 3, "reflevel")] == "+19dBu"
    assert got[("input", 3, "hi-z")] == 1
    assert got[("input", 3, "phase")] == 0
    assert got[("output", 5, "volume")] == -10.0
    assert got[("output", 5, "reflevel")] == "+4dBu"


def test_an_option_the_channel_does_not_have_is_refused(session_mod, tmp_path):
    # The mic preamps have gain and 48V but no reference level; inputs
    # 3-8 have reflevel. That is per *channel*, not per device, and it
    # is why a single capability list would be wrong.
    with pytest.raises(session_mod.ConfigError) as excinfo:
        session_mod.load_config(write(tmp_path, DEVICE +
                                      "[input:1]\nreflevel = +13dBu\n"))
    assert "reflevel on 3..8" in str(excinfo.value)


def test_the_device_s_own_vocabulary_is_the_only_one_accepted(session_mod,
                                                              tmp_path):
    # `+4dBu` is an *output* reference level. Inputs take +13/+19, and a
    # config that reads well while setting nothing is the failure mode
    # this refuses.
    with pytest.raises(session_mod.ConfigError) as excinfo:
        session_mod.load_config(write(tmp_path, DEVICE +
                                      "[input:3]\nreflevel = +4dBu\n"))
    assert "+13dBu, +19dBu" in str(excinfo.value)


def test_an_unknown_option_lists_what_is_valid(session_mod, tmp_path):
    # A name that cannot land, not a real option this version lacks.
    # This test used `crossfeed`, which 0.4.0 then declared -- at which
    # point it asserted that a *known* option is rejected. Same trap the
    # forward-compatible section shapes fell into.
    with pytest.raises(session_mod.ConfigError) as excinfo:
        session_mod.load_config(write(tmp_path, DEVICE +
                                      "[output:5]\nnosuchoption = 3\n"))
    assert "crossfeed, mute, reflevel, volume" in str(excinfo.value)


def test_a_gain_outside_the_range_is_refused(session_mod, tmp_path):
    with pytest.raises(session_mod.ConfigError, match="out of range"):
        session_mod.load_config(write(tmp_path, DEVICE +
                                      "[input:3]\ngain = 99\n"))


# --------------------------------------------------------------------------
# What it writes, and when.
# --------------------------------------------------------------------------

def test_channel_state_is_written_after_the_mix(session_mod, tmp_path):
    # A fader or a reference level landing before the routing exists
    # would be audible for the width of the link barrier.
    config = session_mod.load_config(write(tmp_path, DEVICE + (
        "[route:main]\nplayback = 1/2\noutput = 1/2\n\n"
        "[output:5]\nvolume = -10.0\n")))
    phases = [e.phase for e in reconcile.desired(config)]
    assert phases == sorted(phases)
    assert phases[-1] == reconcile.PHASE_CHANNEL


def test_an_enum_goes_out_as_an_index_not_a_name(session_mod, tmp_path):
    """Upstream takes either for outputs and only an int for inputs.

    `/output/<n>/reflevel` is `setenum` (string or int);
    `/input/<n>/reflevel` is `setint`. Writing the name would have been
    ignored on inputs alone, silently, since a rejected write draws no
    reply.
    """
    config = session_mod.load_config(write(tmp_path, DEVICE + (
        "[input:3]\nreflevel = +19dBu\n\n[output:5]\nreflevel = +4dBu\n")))
    written = {e.path: (e.tags, e.args) for e in reconcile.desired(config)}
    assert written["/input/3/reflevel"] == ("i", (1,))
    assert written["/output/5/reflevel"] == ("i", (0,))


def test_the_reported_name_does_not_make_it_a_mismatch(session_mod):
    # Written ,i (index); reported ,is (index, name). The comparison
    # reads as many arguments as were asked for.
    assert reconcile.matches("i", (1,), (1, "+19dBu"))
    assert not reconcile.matches("i", (1,), (0, "+13dBu"))


# --------------------------------------------------------------------------
# The cold-plug finding, which is why this needed a measurement first.
# --------------------------------------------------------------------------

def test_channel_state_missing_after_a_hotplug_is_a_note_not_a_problem():
    """Without this, every hotplug would warn and re-send the routing.

    Measured across a real USB replug: `/output/N/mute` came back for
    channels 1, 2, 3, 8, 9 and 10 and not for 4-7 or 11-20.
    """
    assert not verify.register_promptly_reported("/output/5/mute",
                                                 registers.UCX2)
    assert not verify.register_promptly_reported("/output/5/reflevel",
                                                 registers.UCX2)
    assert not verify.register_promptly_reported("/input/3/gain",
                                                 registers.UCX2)


def test_what_0_2_0_verified_is_still_treated_as_promptly_reported():
    # The stereo flags come back for every channel within ~2.3 s, which
    # is why this release works. They must keep counting as lost when
    # absent, or a genuinely dropped datagram stops being re-sent.
    assert verify.register_promptly_reported("/output/5/stereo",
                                             registers.UCX2)


def test_an_unmodelled_device_keeps_the_old_classification():
    # No model, no opinion: everything outside the two measured families
    # counts as promptly reported, exactly as before 0.3.0.
    assert verify.register_promptly_reported("/output/5/mute", None)
    assert not verify.register_promptly_reported("/mix/5/playback/1", None)


def test_write_only_registers_are_never_expected_back():
    assert not verify.register_promptly_reported("/output/1/name",
                                                 registers.UCX2)
    assert not verify.register_promptly_reported("/output/1/loopback",
                                                 registers.UCX2)


# --------------------------------------------------------------------------
# One domain for quantities, with the bounds on the register.
# --------------------------------------------------------------------------

def test_a_quantity_carries_its_own_bounds_and_unit(session_mod):
    """`GAIN` and `DB` were the same shape with different numbers.

    Two domains, two hand-written range checks and two hand-written
    messages, for "a number between these bounds". That is the pattern
    that lets a validator and a register table disagree about what is
    legal -- and 0.4.0 adds families whose quantities are seconds and
    ratios, which would have been two more.

    The bounds come from upstream's node table, so a value this rejects
    is one the device would reject too.
    """
    from oscmix_desk.registers import NUMBER, device_for_name, register_at

    device = device_for_name("Fireface UCX II")
    by_path = {r.template: r for r in device.registers}

    volume = by_path["/output/{ch}/volume"]
    assert volume.domain == NUMBER
    assert (volume.lo, volume.hi, volume.unit) == (
        session_mod.LEVEL_MIN, session_mod.LEVEL_MAX, "dB")

    # Gain has three rows, so a template lookup is ambiguous by design:
    # the two mic preamps reach 75 dB, the two instrument channels 24,
    # and Analog 5-8 take no gain at all. Ask per channel.
    mic = register_at(device, "/input/1/gain")
    assert mic.domain == NUMBER
    assert (mic.lo, mic.hi, mic.unit) == (0.0, 75.0, "dB")
    inst = register_at(device, "/input/3/gain")
    assert (inst.lo, inst.hi) == (0.0, 24.0)
    assert register_at(device, "/input/5/gain").domain is None


def test_a_quantity_out_of_range_names_the_range(tmp_path):
    import pytest

    from oscmix_desk import ConfigError
    from oscmix_desk.config import load_config

    path = tmp_path / "routing.conf"
    # Input 3 is an instrument channel: upstream clamps it at 24 dB, and
    # a config that promised 75 there would be silently cut down by
    # `setinputgain` rather than refused. Measured by the write sweep.
    path.write_text("[input:3]\ngain = 80.0\n")
    with pytest.raises(ConfigError, match=r"80\.0 dB out of range 0\.0\.\.24\.0"):
        load_config(path)
    path.write_text("[input:1]\ngain = 80.0\n")
    with pytest.raises(ConfigError, match=r"80\.0 dB out of range 0\.0\.\.75\.0"):
        load_config(path)


def test_an_unbounded_quantity_is_only_checked_for_being_a_number():
    """Where upstream declares no bound, neither does the model.

    A range invented here would reject values the device accepts, and a
    config that will not load is worse than an error the device reports.
    """
    from oscmix_desk.config import _parse_number
    from oscmix_desk.registers import NUMBER, Register

    free = Register("/x", "i", "verifiable", "global", NUMBER)
    assert free.lo is None
    assert free.hi is None
    assert _parse_number("1234.5", "x", "y", free) == 1234.5


def test_output_phase_is_reported_and_not_settable(session_mod, tmp_path):
    """`ctltoreg` gates OUTPUT_PHASE on `INPUT_HAS_REFLEVEL`, bit 2 of the
    *input* flags. An output only ever sets `OUTPUT_HAS_REFLEVEL`, bit 0,
    so the guard always breaks, ctltoreg returns -1 and `setval` writes
    nothing. Every output, not just some.

    Measured rather than deduced: `/input/1/phase` goes 0 -> 1 and reads
    back, `/output/1/phase` and `/output/9/phase` stay 0. Tracing what
    oscmix writes to the MIDI pipe during those writes shows register
    0x0007 twice for the input and nothing at all for the outputs, so
    the write never leaves rather than the device refusing it.

    Reported as michaelforney/oscmix#34. Until it moves, a config that
    accepted `phase` on an output would set nothing and say it had.
    """
    by_path = {r.template: r for r in registers.UCX2.registers}
    assert by_path["/output/{ch}/phase"].domain is None
    assert by_path["/input/{ch}/phase"].domain is not None

    with pytest.raises(session_mod.ConfigError) as excinfo:
        session_mod.load_config(write(tmp_path, DEVICE +
                                      "[output:5]\nphase = true\n"))
    assert "phase" in str(excinfo.value)


def test_input_phase_still_works(session_mod, tmp_path):
    """The half that must not change with it."""
    config = session_mod.load_config(write(tmp_path, DEVICE +
                                           "[input:3]\nphase = true\n"))
    assert config.channels


def test_gain_resolves_per_channel_not_per_name(tmp_path):
    """The three gain rows, as a config sees them.

    Upstream's channel table is the authority and it disagrees with
    itself by channel: `.gain={0, 750}` on the mic preamps, `{0, 240}`
    on the instrument channels, and no range at all on Analog 5-8, which
    `setinputgain` then clamps to {0, 0}. The write sweep measured the
    consequence on 2026-08-25: inputs 1-4 take a value, 5-8 never move.

    Resolving the option by name alone returned whichever row came last,
    so `[input:1] gain` was validated against the instrument ceiling and
    refused outright.
    """
    import pytest

    from oscmix_desk import ConfigError
    from oscmix_desk.config import load_config

    path = tmp_path / "routing.conf"
    path.write_text("[input:1]\ngain = 60.0\n")
    assert load_config(path).channels

    path.write_text("[input:3]\ngain = 60.0\n")
    with pytest.raises(ConfigError, match=r"out of range 0\.0\.\.24\.0"):
        load_config(path)

    # Analog 5-8 are readable and not settable, the same shape as 48v.
    path.write_text("[input:5]\ngain = 6.0\n")
    with pytest.raises(ConfigError, match=r"channel 5 does not have it"):
        load_config(path)
