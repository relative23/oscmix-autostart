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
    for address in MEASURED.values():
        assert address in listed, "0x%04X asserted here, absent from the doc" % address


def test_the_unconfirmed_address_is_not_asserted_as_measured():
    """Room EQ decoded 0x3000 away from the arithmetic, and the doc says
    the decoder is the suspect rather than recording an address that was
    never established. It must not appear here as if it had been."""
    assert 0x3653 not in MEASURED.values()
    text = repo_file("docs", "register-addresses.md").read_text()
    assert "not confirmed" in text
