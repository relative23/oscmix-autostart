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


def test_only_output_registers_are_verifiable(session_mod):
    # The playback mix matrix is not dumped at all, and the /playback/*
    # section streams so late in the multi-second dump that it cannot be
    # observed reliably. The audible /output/* path verifies fine.
    verifiable = session_mod.register_verifiable
    assert verifiable("/mix/5/playback/1") is False
    assert verifiable("/playback/1/stereo") is False
    assert verifiable("/mix/5/input/3") is True
    assert verifiable("/output/5/volume") is True
    assert verifiable("/output/5/stereo") is True


def test_register_matches_with_float_tolerance(session_mod):
    match = session_mod._register_matches
    assert match("fi", (0.0, 0), (0.4, 0)) is True       # quantization
    assert match("fi", (0.0, 0), (0.6, 0)) is False      # real deviation
    assert match("fi", (0.0, 0), (0.0, 5)) is False      # int mismatch
    assert match("fi", (0.0, 0), (0.0,)) is False        # too short
    assert match("fi", (0.0, 0), (0.0, 0, 99)) is True   # extra args ignored
    assert match("i", (1,), ("x",)) is False             # unparseable


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


def dump_reported_registers(session_mod, route):
    return {path: value for path, value
            in session_mod.expected_registers([route]).items()
            if session_mod.register_verifiable(path)}


def test_verify_confirms_matching_state(session_mod):
    route = make_route(session_mod)
    send_port, recv_port = free_udp_port(), free_udp_port()
    state = [session_mod.encode_osc(path, types, *args)
             for path, types, args in session_mod.route_messages(route)]
    reflector = Reflector(send_port, recv_port, state)
    reflector.start()
    result = session_mod.verify_routing(
        dump_reported_registers(session_mod, route),
        send_port, recv_port, timeout=3.0,
    )
    reflector.join()
    assert result == []


def test_verify_reports_wrong_volume(session_mod):
    route = make_route(session_mod)
    send_port, recv_port = free_udp_port(), free_udp_port()
    state = []
    for path, types, args in session_mod.route_messages(route):
        if path == "/output/5/volume":
            # Corrupt the register: -20 dB instead of 0 dB.
            state.append(session_mod.encode_osc(path, "f", -20.0))
        else:
            state.append(session_mod.encode_osc(path, types, *args))
    reflector = Reflector(send_port, recv_port, state)
    reflector.start()
    result = session_mod.verify_routing(
        dump_reported_registers(session_mod, route),
        send_port, recv_port, timeout=0.5,
    )
    reflector.join()
    assert result == ["/output/5/volume"]


def test_verify_returns_none_when_recv_port_taken(session_mod):
    route = make_route(session_mod)
    send_port, recv_port = free_udp_port(), free_udp_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", recv_port))
    try:
        result = session_mod.verify_routing(
            dump_reported_registers(session_mod, route),
            send_port, recv_port, timeout=0.5,
        )
    finally:
        blocker.close()
    assert result is None
