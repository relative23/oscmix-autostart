"""The write sweep's judgement, tested without a Fireface.

`scripts/sweep-writes.py` needs hardware to take a measurement, but
deciding what a measurement *means* is arithmetic and belongs under test
-- the same split `test_hardware_verdicts.py` makes.

The cases below are written from the two defects this stack actually
shipped. Room EQ accepts a write and ignores it; output phase is never
put on the wire. Both look identical from this side, a write with no
report, and the sweep is only allowed to say that much: `ignored`.
Attribution needs a trace of the wire, which is the work the finding
starts rather than the work it completes.
"""

import importlib.util

import pytest
from conftest import repo_file

from oscmix_desk import registers as R


def load_sweep():
    path = repo_file("scripts", "sweep-writes.py")
    spec = importlib.util.spec_from_file_location("sweep_writes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sweep():
    return load_sweep()


def test_a_register_that_answers_is_confirmed(sweep):
    finding = sweep.verdict("/output/1/volume", -10.0,
                            [(-3.9, 6.1, -3.9)])
    assert finding["verdict"] == "confirmed"
    assert finding["step"] == 1


def test_quantisation_is_not_a_defect(sweep):
    """Silence on a small step, an answer on a larger one.

    This is the case the escalation exists for. Reporting the first
    silence as a failure would have condemned every fixed-point register
    whose quantisation is coarser than one percent of its range.
    """
    finding = sweep.verdict("/input/1/eq/band1/gain", 0.0,
                            [(0.2, 0.2, None), (2.0, 2.0, 2.0)])
    assert finding["verdict"] == "confirmed"
    assert finding["step"] == 2


def test_a_deaf_register_is_ignored(sweep):
    """Room EQ and output phase, as the meters would have shown them."""
    finding = sweep.verdict("/output/1/roomeq/band1/gain", 0.0,
                            [(0.2, 0.2, None), (2.0, 2.0, None),
                             (10.0, 10.0, None)])
    assert finding["verdict"] == "ignored"
    assert finding["attempts"] == 3


def test_a_device_that_moves_elsewhere_is_clamped(sweep):
    """The report came back, but not as the value that was asked for.

    That is the model's bound disagreeing with the device, which is a
    defect in this repository rather than in the stack below it, and it
    would read as a pass under any rule that only asked "did anything
    come back".
    """
    finding = sweep.verdict("/reverb/volume", 0.0, [(50.0, 50.0, 6.0)])
    assert finding["verdict"] == "clamped"
    assert finding["reported"] == 6.0


def test_no_legal_alternative_is_not_a_pass(sweep):
    finding = sweep.verdict("/some/register", 1, [])
    assert finding["verdict"] == "undetermined"


def test_a_bool_is_flipped(sweep):
    register = R.Register("/x", "i", R.VERIFIABLE, "input", R.BOOL)
    assert sweep.candidates(register, 1)[0][0] == 0
    assert sweep.candidates(register, 0)[0][0] == 1


def test_an_enum_tries_a_neighbour_then_the_far_end(sweep):
    register = R.Register("/x", "i", R.VERIFIABLE, "input", R.ENUM,
                          ("a", "b", "c", "d"))
    values = [value for value, _step in sweep.candidates(register, 0)]
    assert values == [1, 3]


def test_an_enum_uses_declared_wire_values(sweep):
    """`values` exists because the wire value is not always the index.

    `/controlroom/mainout` reports -1, which no index would produce.
    Writing an index to a register whose vocabulary is discontinuous
    sets the wrong thing, quietly and successfully.
    """
    register = R.Register("/x", "i", R.VERIFIABLE, "global", R.ENUM,
                          ("a", "b", "none"), values=(0, 1, -1))
    values = [value for value, _step in sweep.candidates(register, 0)]
    assert values == [1, -1]


def test_the_step_runs_away_from_the_nearer_bound(sweep):
    """A value near the floor moves up, and one near the ceiling down.

    The alternative is a large step that clips against the bound it
    started next to, which lands on a value the register already holds
    and draws no report -- the sweep's own false negative.
    """
    register = R.Register("/x", "f", R.VERIFIABLE, "output", R.NUMBER,
                          lo=-65.0, hi=6.0)
    assert sweep.candidates(register, -64.0)[0][0] > -64.0
    assert sweep.candidates(register, 5.0)[0][0] < 5.0


def test_a_register_with_no_room_has_no_candidates(sweep):
    register = R.Register("/x", "f", R.VERIFIABLE, "output", R.NUMBER,
                          lo=3.0, hi=3.0)
    assert sweep.candidates(register, 3.0) == []


def test_unbounded_registers_still_get_tried(sweep):
    """`/reverb/volume` has no bounds upstream, and is still settable."""
    register = R.Register("/x", "f", R.VERIFIABLE, "global", R.NUMBER)
    assert len(sweep.candidates(register, 0.0)) == 3


def test_no_candidate_ever_equals_the_current_value(sweep):
    """Over the real model, at four positions in each register's range.

    A candidate equal to the value already held draws no report, because
    the device reports only on change -- so this mistake would not crash,
    it would manufacture `ignored` verdicts on healthy registers.
    """
    for path, register in sweep.settable():
        lo = 0.0 if register.lo is None else register.lo
        hi = 1.0 if register.hi is None else register.hi
        for fraction in (0.0, 0.25, 0.5, 1.0):
            current = lo + (hi - lo) * fraction
            if register.domain in (R.BOOL, R.ENUM):
                current = int(current)
            for value, _step in sweep.candidates(register, current):
                assert value != current, "%s at %s" % (path, current)


def test_every_candidate_stays_inside_the_declared_bounds(sweep):
    for path, register in sweep.settable():
        if register.domain != R.NUMBER or register.lo is None:
            continue
        for fraction in (0.0, 0.5, 1.0):
            current = register.lo + (register.hi - register.lo) * fraction
            for value, _step in sweep.candidates(register, current):
                assert register.lo <= value <= register.hi, path


def test_reflevel_is_refused_and_48v_is_out_of_reach(sweep):
    """ADR 0016, checked against the model rather than asserted."""
    assert sweep.is_dangerous("/input/3/reflevel")
    assert not sweep.is_dangerous("/output/1/volume")
    reachable = [p for p, _r in sweep.settable() if "48v" in p]
    assert reachable == [], "48v must have no value domain"
