"""Families with no channel dimension, and the section that sets them.

The 0.4.0 plan splits its 1466 registers in two: 42 have no channel and
need one new section each, and 1424 are nested per-channel and need a
config-format decision first. This is the first half, proven on `[echo]`
-- seven registers that between them exercise every value type the model
has: a bool, two enums, a bounded quantity, an unbounded one, and a dB
range shared with the faders.

Everything here is checked against `tests/data/refresh-dump.json` or
against upstream's node table, never against what looked plausible.
"""

import json

import pytest
from conftest import repo_file

from oscmix_autostart.config import GlobalSetting, load_config
from oscmix_autostart.registers import (
    ENABLE_OPTION,
    GLOBAL,
    device_for_name,
    global_families,
    settable_globals,
)

UCX2 = device_for_name("Fireface UCX II")


@pytest.fixture(scope="module")
def warm():
    return json.loads(repo_file("tests", "data", "refresh-dump.json").read_text())


# --------------------------------------------------------------------------
# The vocabulary comes from the table, not from the parser.
# --------------------------------------------------------------------------

def test_the_section_names_come_from_the_register_table():
    assert global_families(UCX2) == ("echo",)
    assert global_families(None) == ()


def test_the_options_are_the_last_path_segments():
    """Derived, so a row added to the table is settable without a second edit.

    A list kept in the parser is a second place to disagree with the
    device -- the rule this project already applies to channel sections.
    """
    known = settable_globals(UCX2, "echo")
    assert sorted(known) == ["delay", ENABLE_OPTION, "feedback", "highcut",
                             "type", "volume", "width"]
    for option, register in known.items():
        if option == ENABLE_OPTION:
            assert register.template == "/echo"
        else:
            assert register.template == "/echo/" + option


def test_the_enable_option_is_the_only_invented_word():
    """`/echo` is a node with a value *and* a subtree.

    Its switch has no path segment, so the device has no name for it and
    this one is ours. Every other option is the last segment of a real
    path. Asserting that keeps the exception single and visible instead
    of letting a second invented name in quietly.
    """
    invented = [option for option, register in settable_globals(UCX2, "echo").items()
                if not register.template.endswith("/" + option)]
    assert invented == [ENABLE_OPTION]


# --------------------------------------------------------------------------
# Parsing.
# --------------------------------------------------------------------------

def _conf(tmp_path, body):
    path = tmp_path / "routing.conf"
    path.write_text("[device]\nname = Fireface UCX II\n" + body)
    return path


def test_a_global_section_parses_into_settings(tmp_path):
    config = load_config(_conf(tmp_path, """
[echo]
enabled = true
type = Pong Echo
delay = 0.35
volume = -12.0
highcut = 8kHz
"""))
    got = {s.option: (s.value, s.path) for s in config.globals}
    assert got["enabled"] == (1, "/echo")
    assert got["type"] == ("Pong Echo", "/echo/type")
    assert got["delay"] == (0.35, "/echo/delay")
    assert got["volume"] == (-12.0, "/echo/volume")
    assert got["highcut"] == ("8kHz", "/echo/highcut")


@pytest.mark.parametrize(("body", "why"), [
    ("[echo]\nshimmer = 1\n", "no such option"),
    ("[echo]\ndelay = 5.0\n", "outside the declared 0..2 s"),
    ("[echo]\ntype = Hall\n", "not one of the device's names"),
    ("[echo]\nenabled = perhaps\n", "not a boolean"),
])
def test_a_bad_global_value_is_refused(tmp_path, body, why):
    from oscmix_autostart import ConfigError

    with pytest.raises(ConfigError):
        load_config(_conf(tmp_path, body))


def test_an_unbounded_option_takes_what_upstream_takes(tmp_path):
    """`feedback` is `setint` with no min or max in oscmix.c.

    So the model declares none, and a config may say what the device
    would accept. Inventing 0..100 here would look tidy and reject
    values that work.
    """
    config = load_config(_conf(tmp_path, "[echo]\nfeedback = 250\n"))
    assert [(s.option, s.value) for s in config.globals] == [("feedback", 250.0)]


# --------------------------------------------------------------------------
# And it has to reach the wire.
# --------------------------------------------------------------------------

def test_every_global_setting_becomes_a_register_to_write(tmp_path):
    """The guard this release has needed three times.

    Parsed, validated, shown in --dry-run and never sent is the shape of
    two defects already fixed here. A new section is exactly where it
    happens again.
    """
    from oscmix_autostart.reconcile import desired

    config = load_config(_conf(tmp_path, """
[echo]
enabled = true
type = Pong Echo
delay = 0.35
"""))
    paths = {e.path for e in desired(config)}
    assert {"/echo", "/echo/type", "/echo/delay"} <= paths


def test_an_enum_goes_out_as_its_index(tmp_path):
    """Same rule as channel sections, and now the same code.

    Upstream takes an int for some enums and either for others; writing
    a name where only an int is read is ignored silently, since a write
    draws no reply. One encoder for both section kinds is what keeps
    that rule in one place.
    """
    from oscmix_autostart.reconcile import desired

    config = load_config(_conf(tmp_path, "[echo]\ntype = Pong Echo\n"))
    entry, = [e for e in desired(config) if e.path == "/echo/type"]
    assert (entry.tags, entry.args) == ("i", (2,))


def test_global_settings_are_read_back_like_any_other(tmp_path):
    from oscmix_autostart.verify import expected_registers

    config = load_config(_conf(tmp_path, "[echo]\nvolume = -12.0\n"))
    assert "/echo/volume" in expected_registers(config)


# --------------------------------------------------------------------------
# Against the recording.
# --------------------------------------------------------------------------

def test_the_declared_echo_registers_are_all_in_the_dump(warm):
    declared = {r.template for r in UCX2.registers if r.channels == GLOBAL}
    assert declared, "no global registers declared"
    assert sorted(declared - set(warm["registers"])) == []


def test_nothing_in_the_dump_is_left_undeclared(warm):
    declared = {r.template for r in UCX2.registers}
    reported = {p for p in warm["registers"] if p.startswith("/echo")}
    assert sorted(reported - declared) == []


def test_a_global_setting_knows_its_own_path():
    assert GlobalSetting("echo", ENABLE_OPTION, 1).path == "/echo"
    assert GlobalSetting("echo", "delay", 0.5).path == "/echo/delay"
