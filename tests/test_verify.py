"""Routing verification: state read-back over the OSC receive port."""

import socket
import threading

from conftest import free_udp_port


def make_route(session_mod, **kwargs):
    defaults = dict(name="monitors", playback=(1, 2), output=(5, 6),
                    level=0.0, volume=0.0, stereo=True)
    defaults.update(kwargs)
    return session_mod.Route(**defaults)


def test_expected_registers_keyed_by_path(session_mod):
    registers = session_mod.expected_registers([make_route(session_mod)])
    assert registers["/mix/5/playback/1"] == ("fi", (0.0, 0))
    assert registers["/output/5/stereo"] == ("i", (1,))
    assert len(registers) == 5


def test_prompt_reporting_hint(session_mod):
    # The playback mix matrix is not dumped at all, and the /playback/*
    # section streams so late in the multi-second dump that it cannot be
    # awaited. The audible /output/* path arrives early.
    prompt = session_mod.register_promptly_reported
    assert prompt("/mix/5/playback/1") is False
    assert prompt("/playback/1/stereo") is False
    assert prompt("/mix/5/input/3") is True
    assert prompt("/output/5/volume") is True
    assert prompt("/output/5/stereo") is True


def test_register_matches_with_float_tolerance(verify_mod):
    # Expected values are deliberately non-zero: with want = 0.0 a sign
    # error in the comparison (want - got vs want + got) is invisible,
    # which is exactly what a surviving mutant showed.
    match = verify_mod._register_matches
    assert match("fi", (-6.0, 0), (-5.7, 0)) is True     # quantization
    assert match("fi", (-6.0, 0), (-5.4, 0)) is False    # real deviation
    assert match("fi", (-6.0, 0), (6.0, 0)) is False     # sign flipped
    assert match("f", (3.0,), (-3.0,)) is False          # sign flipped
    assert match("fi", (-6.0, 0), (-6.0, 5)) is False    # int mismatch
    assert match("fi", (-6.0, 0), (-6.0,)) is False      # too short
    assert match("fi", (-6.0, 0), (-6.0, 0, 99)) is True  # extra args ignored
    assert match("i", (1,), ("x",)) is False             # unparseable
    assert match("i", (1,), (-1,)) is False              # sign, integer path


class Reflector(threading.Thread):
    """Minimal oscmix stand-in: replies to /refresh with canned state."""

    def __init__(self, send_port, recv_port, state):
        super().__init__(daemon=True)
        self.recv_port = recv_port
        self.state = state
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", send_port))
        self.sock.settimeout(5)

    def run(self):
        try:
            data, _ = self.sock.recvfrom(65536)
        except socket.timeout:
            return
        if data.startswith(b"/refresh"):
            for message in self.state:
                self.sock.sendto(message, ("127.0.0.1", self.recv_port))
        self.sock.close()


def run_verify(session_mod, registers, state, timeout=3.0):
    send_port, recv_port = free_udp_port(), free_udp_port()
    reflector = Reflector(send_port, recv_port, state)
    reflector.start()
    result = session_mod.verify_routing(registers, send_port, recv_port,
                                        timeout=timeout)
    reflector.join()
    return result


def test_verify_confirms_matching_state(session_mod):
    route = make_route(session_mod)
    registers = session_mod.expected_registers([route])
    state = [session_mod.encode_osc(path, types, *args)
             for path, types, args in session_mod.route_messages(route)]
    result = run_verify(session_mod, registers, state)
    # Every register was replayed verbatim -- including the ones the
    # real device would not dump -- so all of them count as confirmed.
    assert result.mismatched == []
    assert result.unobserved == []
    assert sorted(registers) == result.confirmed


def test_verify_classifies_wrong_value_as_mismatch(session_mod):
    route = make_route(session_mod)
    registers = session_mod.expected_registers([route])
    state = []
    for path, types, args in session_mod.route_messages(route):
        if path == "/output/5/volume":
            # Corrupt the register: -20 dB instead of 0 dB.
            state.append(session_mod.encode_osc(path, "f", -20.0))
        else:
            state.append(session_mod.encode_osc(path, types, *args))
    result = run_verify(session_mod, registers, state, timeout=0.5)
    assert result.mismatched == ["/output/5/volume"]
    assert result.unobserved == []


def test_verify_classifies_missing_register_as_unobserved(session_mod):
    route = make_route(session_mod)
    registers = session_mod.expected_registers([route])
    state = [session_mod.encode_osc(path, types, *args)
             for path, types, args in session_mod.route_messages(route)
             if path != "/mix/5/playback/1"]
    result = run_verify(session_mod, registers, state, timeout=0.5)
    assert result.mismatched == []
    assert result.unobserved == ["/mix/5/playback/1"]


def test_hint_excluded_register_is_still_compared_when_reported(session_mod):
    # Self-healing: if a future oscmix starts dumping the playback mix
    # matrix, a wrong value must surface as a mismatch even though the
    # hint says the register is not promptly reported.
    registers = {"/mix/5/playback/1": ("fi", (0.0, 0))}
    state = [session_mod.encode_osc("/mix/5/playback/1", "fi", -30.0, 0)]
    result = run_verify(session_mod, registers, state, timeout=0.5)
    assert result.mismatched == ["/mix/5/playback/1"]


def test_later_matching_report_overrides_mismatch(session_mod):
    # During settling the device may first echo a stale value; a later
    # matching report must win.
    registers = {"/output/5/volume": ("f", (0.0,))}
    state = [session_mod.encode_osc("/output/5/volume", "f", -20.0),
             session_mod.encode_osc("/output/5/volume", "f", 0.0)]
    result = run_verify(session_mod, registers, state)
    assert result.confirmed == ["/output/5/volume"]
    assert result.mismatched == []


def test_verify_returns_none_when_recv_port_taken(session_mod):
    route = make_route(session_mod)
    registers = session_mod.expected_registers([route])
    send_port, recv_port = free_udp_port(), free_udp_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", recv_port))
    try:
        result = session_mod.verify_routing(registers, send_port, recv_port,
                                            timeout=0.5)
    finally:
        blocker.close()
    assert result is None


def test_a_mismatch_keeps_the_window_open(session_mod):
    # The early exit is guarded by `not mismatched`: while anything is
    # wrong the loop must keep listening, because the device may still
    # send a corrected value. Dropping that guard made the read-back
    # return the first, stale answer.
    registers = {"/output/5/volume": ("f", (0.0,)),
                 "/output/5/stereo": ("i", (1,))}
    state = [session_mod.encode_osc("/output/5/volume", "f", -20.0),
             session_mod.encode_osc("/output/5/stereo", "i", 1),
             session_mod.encode_osc("/output/5/volume", "f", 0.0)]
    result = run_verify(session_mod, registers, state)
    assert result.mismatched == []
    assert sorted(result.confirmed) == ["/output/5/stereo",
                                        "/output/5/volume"]


def test_exiting_early_needs_every_prompt_register_not_merely_some(session_mod):
    # The condition is `prompt <= confirmed`, a subset test. A proper
    # subset would exit while one promptly-reported register was still
    # missing, and report it as unobserved.
    registers = {"/output/5/volume": ("f", (0.0,)),
                 "/output/6/volume": ("f", (0.0,)),
                 "/output/5/stereo": ("i", (1,))}
    state = [session_mod.encode_osc(path, types, *args)
             for path, (types, args) in registers.items()]
    result = run_verify(session_mod, registers, state)
    assert result.unobserved == []
    assert len(result.confirmed) == 3


def test_registers_outside_the_expectation_are_ignored(session_mod):
    # The dump carries thousands of registers we never asked about. The
    # guard is `expected is None or path in confirmed`; with `and` an
    # unexpected path would fall through into the comparison.
    registers = {"/output/5/volume": ("f", (0.0,))}
    state = [session_mod.encode_osc("/input/3/gain", "f", 12.0),
             session_mod.encode_osc("/hardware/ccmix", "i", 0),
             session_mod.encode_osc("/output/5/volume", "f", 0.0)]
    result = run_verify(session_mod, registers, state)
    assert result.confirmed == ["/output/5/volume"]
    assert result.mismatched == []


def test_a_corrupt_message_does_not_end_the_dump(session_mod):
    # Decode failures `continue` rather than `break`: one malformed
    # datagram in a multi-thousand-message dump must not abandon the rest.
    registers = {"/output/5/volume": ("f", (0.0,))}
    state = [b"\x01\x02\x03",                      # no NUL: undecodable
             session_mod.encode_osc("/output/5/volume", "f", 0.0)]
    result = run_verify(session_mod, registers, state)
    assert result.confirmed == ["/output/5/volume"]


def test_observer_receives_the_path_and_its_arguments(session_mod):
    # verify_and_repair hangs the mix re-apply off these arguments; a
    # caller handed None for either would never fire it.
    seen = []
    registers = {"/output/5/stereo": ("i", (1,))}
    state = [session_mod.encode_osc("/output/5/stereo", "i", 1)]
    send_port, recv_port = free_udp_port(), free_udp_port()
    reflector = Reflector(send_port, recv_port, state)
    reflector.start()
    session_mod.verify_routing(registers, send_port, recv_port, 3.0,
                               on_observed=lambda path, args:
                               seen.append((path, tuple(args))))
    reflector.join()
    assert ("/output/5/stereo", (1,)) in seen
