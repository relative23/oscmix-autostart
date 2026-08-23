"""Room EQ: 640 registers on the outputs, and the last family of 0.4.0.

It was blocked for the whole release. `device_ffucxii.c` recombined each
output's Room EQ offset with `|` against a base whose low five bits were
already set, so offsets 16..31 collided and folded onto the lower half:
320 registers reported where 640 exist, every one of them a double
report of another. That is michaelforney/oscmix#32, filed from here with
a measurement, fixed upstream in 55802a6, and declared only after the
pin moved and the fix was measured on the device -- 640 reported.

The generic checks are in `test_sub_families.py`, which now sweeps six
sub-families. This file is what only Room EQ knows.
"""

import pytest

from oscmix_autostart.config import load_config
from oscmix_autostart.errors import ConfigError
from oscmix_autostart.registers import (
    UCX2,
    declared_paths,
    nested_families,
    settable_nested,
)


def test_it_is_an_output_family_only():
    """Upstream hangs `roomeq` off the output tree and nowhere else, and
    the recording agrees: 640 paths, all under `/output/`."""
    assert "roomeq" in nested_families(UCX2, "output")
    assert "roomeq" not in nested_families(UCX2, "input")
    paths = [p for p in declared_paths(UCX2) if "roomeq" in p]
    assert len(paths) == 640
    assert all(p.startswith("/output/") for p in paths)


def test_it_has_nine_bands_where_the_channel_eq_has_three():
    import re
    paths = {p for p in declared_paths(UCX2) if "/output/1/roomeq" in p}
    bands = {m.group(1) for m in
             (re.search(r"/band(\d)", p) for p in paths) if m}
    assert bands == set("123456789")
    assert len(paths) == 32            # switch + delay + 9x3 + 3 types


@pytest.mark.parametrize("band", [1, 8, 9])
def test_only_three_bands_have_a_filter_type(band):
    """Band 1 offers a Low shelf and the last two a High shelf -- the
    same odd-one-out that made the channel EQ worth generating from a
    table. Checked on the declared paths, since none of them is
    settable."""
    paths = {p for p in declared_paths(UCX2) if "roomeq" in p}
    assert "/output/5/roomeq/band%dtype" % band in paths


@pytest.mark.parametrize("band", [2, 3, 4, 5, 6, 7])
def test_the_middle_bands_have_no_type(band):
    paths = {p for p in declared_paths(UCX2) if "roomeq" in p}
    assert "/output/5/roomeq/band%dtype" % band not in paths


# --------------------------------------------------------------------------
# Reported, and not settable. The measurement that decided it.
# --------------------------------------------------------------------------

def test_not_one_room_eq_register_carries_a_value_domain():
    """"A config cannot set what oscmix cannot write" -- the line
    `/clock/samplerate` already sits on, applied to 640 registers.

    Measured at 55802a6 on outputs 1 and 5, with the channel EQ as a
    control in the same run:

        /output/N/eq/band1gain      -6.0  ->  reads back -6.0
        /output/N/roomeq/band1gain  -6.0  ->  reads back  0.0

    Output 1 fails too, where the channel offset is zero and the address
    is the base exactly, so it is not the offset arithmetic. 55802a6
    fixed `regtoctl` -- the *read* path -- which is why 640 registers are
    reported where 320 were. Writes still do nothing.
    """
    for register in UCX2.registers:
        if "roomeq" in register.template:
            assert register.domain is None, register.template
    assert settable_nested(UCX2, "roomeq", "output") == {}


def test_a_room_eq_section_is_refused_rather_than_ignored(tmp_path):
    """The failure this replaces: `[roomeq:output:5]` was accepted and
    produced nothing. A config that looks like it sets a shelf and sets
    no register is worse than one that will not load."""
    path = tmp_path / "routing.conf"
    path.write_text("[device]\nname = Fireface UCX II\n\n"
                    "[roomeq:output:5]\nband1gain = -6.0\n")
    with pytest.raises(ConfigError) as raised:
        load_config(path)
    assert "cannot be set" in str(raised.value)


def test_an_unmodelled_device_still_gets_no_opinion(tmp_path):
    """The half that must not change. An empty settable set means "this
    family is read-only" for a device we model, and "no opinion" for one
    we do not -- opposite answers from the same empty dict."""
    path = tmp_path / "routing.conf"
    path.write_text("[device]\nname = Some Other Interface\n\n"
                    "[roomeq:output:5]\nband1gain = -6.0\n")
    assert load_config(path).channels == []
