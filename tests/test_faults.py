"""Behaviour when the environment misbehaves.

Every failure this project has actually shipped was a timing or delivery
problem, not a logic error: a link message overtaken by its own mix, two
teardown races, a stub that installed its signal handler too late. So the
adversary here is the transport and the clock, not the input.

OSC over UDP has no delivery guarantee and no ordering guarantee. These
tests take that literally -- dropping, duplicating, reordering and
delaying datagrams -- and assert the property that has to survive all of
it: the routing is still written, and the process still exits cleanly.
"""

import random
import socket
import struct
import threading
import time

import pytest
from conftest import free_udp_port


class LossyDevice(threading.Thread):
    """A device stand-in that mistreats the datagrams it receives.

    ``drop`` discards a fraction, ``duplicate`` sends replies twice, and
    ``reorder`` buffers replies and flushes them shuffled.
    """

    def __init__(self, session_mod, send_port, recv_port, dump=(),
                 drop=0.0, duplicate=False, reorder=False, seed=1):
        super().__init__(daemon=True)
        self.session_mod = session_mod
        self.recv_port = recv_port
        self.dump = list(dump)
        self.drop = drop
        self.duplicate = duplicate
        self.reorder = reorder
        self.random = random.Random(seed)
        self.received = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", send_port))
        self.sock.settimeout(0.2)
        self.stopping = threading.Event()

    def stop(self):
        self.stopping.set()

    def drain(self, quiet=0.3, limit=5.0):
        deadline = time.monotonic() + limit
        seen = -1
        while time.monotonic() < deadline:
            if len(self.received) == seen:
                return
            seen = len(self.received)
            time.sleep(quiet)

    def reply(self):
        messages = list(self.dump)
        if self.duplicate:
            messages += list(self.dump)
        if self.reorder:
            self.random.shuffle(messages)
        for message in messages:
            if self.random.random() < self.drop:
                continue
            try:
                self.sock.sendto(message, ("127.0.0.1", self.recv_port))
            except OSError:
                return

    def run(self):
        while not self.stopping.is_set():
            try:
                data, _ = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            for message in self.session_mod.iter_osc_messages(data):
                try:
                    path, _tags, _args = self.session_mod.decode_osc(message)
                except (ValueError, struct.error):
                    continue
                self.received.append(path)
                if path == "/refresh":
                    self.reply()


def make_route(session_mod):
    return session_mod.Route(name="monitors", playback=(1, 2), output=(5, 6),
                             level=0.0, volume=0.0, stereo=True)


def full_dump(session_mod, route):
    return [session_mod.encode_osc(path, types, *args)
            for path, types, args in session_mod.route_messages(route)]


def run_under(session_mod, **device_options):
    send_port, recv_port = free_udp_port(), free_udp_port()
    route = make_route(session_mod)
    device = LossyDevice(session_mod, send_port, recv_port,
                         dump=full_dump(session_mod, route), **device_options)
    device.start()
    config = session_mod.Config(routes=[route], osc_port=send_port,
                                osc_recv_port=recv_port)
    try:
        session_mod.verify_and_repair(config)
        device.drain()
    finally:
        device.stop()
        device.join(timeout=5)
        device.sock.close()
    return device


@pytest.mark.parametrize("drop", [0.0, 0.3, 0.7, 1.0])
def test_the_mix_is_re_applied_however_much_the_dump_loses(session_mod,
                                                           verify_mod,
                                                           monkeypatch, drop):
    # Losing the dump must never mean losing the routing. With everything
    # dropped the link state is unknown, and the mix still has to go out:
    # degraded beats silent.
    monkeypatch.setattr(verify_mod, "VERIFY_TIMEOUT", 0.4)
    device = run_under(session_mod, drop=drop)
    assert "/mix/5/playback/1" in device.received


def test_duplicated_reports_do_not_confuse_the_read_back(session_mod):
    # UDP may deliver the same datagram twice. A register reported twice
    # is still one register.
    device = run_under(session_mod, duplicate=True)
    assert device.received.count("/mix/5/playback/1") == 1


def test_reordered_reports_still_verify(session_mod):
    # Nothing may depend on the dump's order: it is a stream of registers
    # with no promised sequence.
    device = run_under(session_mod, reorder=True, seed=7)
    assert "/mix/5/playback/1" in device.received


def test_applying_routing_survives_a_device_that_never_answers(session_mod,
                                                               routing_mod,
                                                               monkeypatch):
    # The barrier waits for a report that may never come. It must time
    # out and write the mix anyway, within its own timeout.
    monkeypatch.setattr(routing_mod, "LINK_ECHO_TIMEOUT", 0.3)
    send_port, recv_port = free_udp_port(), free_udp_port()
    route = make_route(session_mod)
    device = LossyDevice(session_mod, send_port, recv_port, drop=1.0)
    device.start()
    started = time.monotonic()
    try:
        session_mod.apply_routing([route], send_port, recv_port)
        device.drain()
    finally:
        device.stop()
        device.join(timeout=5)
        device.sock.close()
    assert "/mix/5/playback/1" in device.received
    assert time.monotonic() - started < 3.0, "the barrier did not time out"


def test_a_dead_backend_port_does_not_raise(session_mod, routing_mod,
                                            monkeypatch):
    # Nothing is listening at all: sending to a closed UDP port can raise
    # ECONNREFUSED on Linux once an ICMP error has been seen. Applying a
    # routing must not turn that into a crashed service.
    monkeypatch.setattr(routing_mod, "LINK_ECHO_TIMEOUT", 0.1)
    monkeypatch.setattr(routing_mod, "LINK_SETTLE", 0.05)
    route = make_route(session_mod)
    for _ in range(3):
        session_mod.apply_routing([route], free_udp_port(), free_udp_port())


def test_verification_survives_a_flood_of_unrelated_registers(session_mod,
                                                              verify_mod,
                                                              monkeypatch):
    # A real dump is thousands of registers we never asked about. The
    # read-back must not slow to a crawl or mistake one for an answer.
    monkeypatch.setattr(verify_mod, "VERIFY_TIMEOUT", 1.0)
    send_port, recv_port = free_udp_port(), free_udp_port()
    route = make_route(session_mod)
    noise = [session_mod.encode_osc("/input/%d/gain" % channel, "f", 12.0)
             for channel in range(1, 200)]
    device = LossyDevice(session_mod, send_port, recv_port,
                         dump=noise + full_dump(session_mod, route))
    device.start()
    config = session_mod.Config(routes=[route], osc_port=send_port,
                                osc_recv_port=recv_port)
    started = time.monotonic()
    try:
        session_mod.verify_and_repair(config)
        device.drain()
    finally:
        device.stop()
        device.join(timeout=5)
        device.sock.close()
    assert time.monotonic() - started < 8.0
    assert "/mix/5/playback/1" in device.received
