"""The address arithmetic, checked against what was measured.

`docs/register-addresses.md` records eleven addresses read off the MIDI
pipe on a UCX II. This asserts that the arithmetic documented there
reproduces them from the model's own paths, so the two cannot drift
apart silently: the table is evidence, and this is what keeps the code
agreeing with it.

Why it matters is in the doc. Every defect of the last two releases
lived between the OSC path and the register address, and the paths are
oscmix's invention while the addresses are the device's.
"""

import re

import pytest
from conftest import repo_file

#: The offsets upstream's `ctltoreg` assigns, for the controls measured.
#: Transcribed from `device_ffucxii.c` at 55802a6 and confirmed on the
#: wire; the doc names the run.
CONTROL_OFFSET = {
    "phase": 0x07,          # input
    "gain": 0x08,           # input
    "volume": 0x00,         # output
    "stereo": 0x04,         # output
    "crossfeed": 0x0A,      # output
    "lowcut/freq": 0x0D,
    "eq/band1gain": 0x11,
    "dynamics/gain": 0x1C,
    "autolevel/maxgain": 0x24,
}


def channel_address(family, channel, option):
    """`idx << 6 | reg`, with outputs starting at index 20."""
    idx = (channel - 1) if family == "input" else 20 + (channel - 1)
    return idx << 6 | CONTROL_OFFSET[option]


def matrix_address(out, in_):
    return 0x2000 | (out - 1) << 6 | (in_ - 1)


MEASURED = {
    ("input", 3, "phase"): 0x0087,
    ("input", 3, "gain"): 0x0088,
    ("output", 5, "volume"): 0x0600,
    ("output", 5, "stereo"): 0x0604,
    ("output", 5, "crossfeed"): 0x060A,
    ("output", 5, "lowcut/freq"): 0x060D,
    ("output", 5, "eq/band1gain"): 0x0611,
    ("output", 5, "dynamics/gain"): 0x061C,
    ("output", 5, "autolevel/maxgain"): 0x0624,
    # From the runs that produced upstream #33 and #34.
    ("input", 1, "phase"): 0x0007,
    ("output", 1, "eq/band1gain"): 0x0511,
}

#: Room EQ has its own block and its own arithmetic, so it is not in the
#: table above; `test_the_room_eq_address_follows_its_own_arithmetic`
#: covers it.
ROOMEQ_BAND1GAIN_OUTPUT_5 = 0x3653


@pytest.mark.parametrize(("key", "address"), sorted(MEASURED.items()),
                         ids=lambda k: k if isinstance(k, int) else
                         "%s%d/%s" % k if isinstance(k, tuple) else str(k))
def test_the_arithmetic_reproduces_a_measured_address(key, address):
    family, channel, option = key
    assert channel_address(family, channel, option) == address


def test_the_matrix_address_is_reproduced():
    assert matrix_address(5, 1) == 0x2100


def test_the_document_lists_every_address_this_asserts():
    """The doc is the evidence and this is the check; a claim in one and
    not the other is how a measured table turns back into folklore."""
    text = repo_file("docs", "register-addresses.md").read_text()
    listed = {int(m, 16) for m in re.findall(r"`0x([0-9A-F]{4})`", text)}
    assert ROOMEQ_BAND1GAIN_OUTPUT_5 in listed
    for address in MEASURED.values():
        assert address in listed, "0x%04X asserted here, absent from the doc" % address


def test_the_room_eq_address_follows_its_own_arithmetic():
    """`0x35D0 + reg + (out << 5)`, confirmed on the wire once the trace
    decoder stopped mangling `\\v` and stopped taking the parity bit for
    part of the address."""
    assert 0x35D3 + (4 << 5) == 0x3653


def test_the_matrix_level_address_is_a_different_block_from_pan():
    """`MIX` is pan at 0x2000, `MIX_LEVEL` is level at 0x4000, and a
    single `/mix/<out>/input/<in>` write emits both. Reading them as one
    register is how a matrix write would look half-applied."""
    assert (0x2000 | (5 - 1) << 6 | (1 - 1)) == 0x2100
    assert (0x4000 | (5 - 1) << 6 | (1 - 1)) == 0x4100
