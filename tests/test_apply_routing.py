"""Applying a routing: channel linking must precede the mix matrix.

The device stand-in here models the one oscmix behaviour that makes the
order load-bearing: ``/output/<n>/stereo`` does not change oscmix's own
link state, only the *device echo* of that register does
(``newoutputstereo()`` in oscmix.c). A ``/mix`` write that overtakes the
echo is evaluated unlinked and never reaches the pair's right channel,
which silences every even output.
"""

import socket
import threading
import time

from conftest import free_udp_port


def make_route(session_mod, **kwargs):
    defaults = dict(name="monitors", playback=(1, 2), output=(5, 6),
                    level=0.0, volume=None, stereo=True)
    defaults.update(kwargs)
    return session_mod.Route(**defaults)


class FakeOscmix(threading.Thread):
    """oscmix + device, reduced to the stereo-link state machine.

    ``echo_delay`` stands in for the MIDI round-trip: the link only
    becomes effective once the echo has been sent back.
    """

    def __init__(self, session_mod, send_port, recv_port, echo_delay=0.05,
                 echo=True):
        super().__init__(daemon=True)
        self.session_mod = session_mod
        self.recv_port = recv_port
        self.echo_delay = echo_delay
        self.echo = echo
        self.linked = set()          # output pairs oscmix considers linked
        self.stereo_playback = set()
        self.mix_writes = []         # (path, was_linked_when_written)
        self.order = []              # every path, in arrival order
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", send_port))
        self.sock.settimeout(3.0)
        self.stopping = threading.Event()
        self.timers = []             # pending echo timers, cancelled on stop

    def stop(self):
        self.stopping.set()
        # An echo timer that fires after teardown writes to a closed
        # socket; cancelling here keeps the fake from outliving its test.
        for timer in self.timers:
            timer.cancel()

    def record(self, path):
        self.order.append(path)
        parts = path.split("/")
        if path.startswith("/output/") and path.endswith("/stereo"):
            channel = int(parts[2])
            pair = channel - (channel - 1) % 2
            if self.echo:
                # The echo is what updates oscmix's state; it arrives
                # only after the device round-trip.
                timer = threading.Timer(self.echo_delay, self.send_link_echo,
                                        [pair, path])
                timer.daemon = True
                self.timers.append(timer)
                timer.start()
        elif path.startswith("/playback/") and path.endswith("/stereo"):
            # setinputstereo() updates oscmix's state synchronously.
            self.stereo_playback.add(int(parts[2]))
        elif path.startswith("/mix/"):
            channel = int(parts[2])
            pair = channel - (channel - 1) % 2
            self.mix_writes.append((path, pair in self.linked))

    def send_link_echo(self, pair, path):
        if self.stopping.is_set():
            return               # cancel() lost the race with the timer
        self.linked.add(pair)
        try:
            self.sock.sendto(self.session_mod.encode_osc(path, "i", 1),
                             ("127.0.0.1", self.recv_port))
        except OSError:
            pass                 # socket already closed by teardown

    def run(self):
        while not self.stopping.is_set():
            try:
                data, _ = self.sock.recvfrom(65536)
            except socket.timeout:
                return
            except OSError:
                return
            for message in self.session_mod.iter_osc_messages(data):
                try:
                    path, _tags, _args = self.session_mod.decode_osc(message)
                except ValueError:
                    continue
                self.record(path)


def run_apply(session_mod, routes, **kwargs):
    send_port, recv_port = free_udp_port(), free_udp_port()
    device = FakeOscmix(session_mod, send_port, recv_port, **kwargs)
    device.start()
    try:
        session_mod.apply_routing(routes, send_port, recv_port)
    finally:
        device.stop()
        device.join(timeout=3)
        device.sock.close()
    return device


def test_device_fakes_avoid_private_thread_names(session_mod):
    """The fakes share a namespace with threading.Thread's internals.

    ``Thread._stop`` is a method on every version and 3.13 added
    ``Thread._handle``; shadowing either breaks the thread machinery on
    exactly the interpreters that define it. Both slipped through a green
    local run, so the rule is now mechanical: these classes use no
    single-underscore names at all.
    """
    inherited = set(vars(threading.Thread(daemon=True)))
    for cls in (FakeOscmix, DumpingOscmix):
        device = cls(session_mod, free_udp_port(), free_udp_port(),
                     *([] if cls is FakeOscmix else [[]]))
        try:
            names = (set(vars(device)) - inherited) | {
                n for n in vars(cls) if not n.startswith("__")}
        finally:
            device.sock.close()
        private = sorted(n for n in names
                         if n.startswith("_") and not n.startswith("__"))
        assert private == [], (
            "%s uses private names that may collide with threading.Thread: %s"
            % (cls.__name__, private))


def test_mix_is_written_only_after_the_device_confirmed_the_link(session_mod):
    # The regression: with a single-phase send every mix write lands on an
    # unlinked pair and the right channel is never touched.
    device = run_apply(session_mod, [make_route(session_mod)])
    assert device.mix_writes, "no mix message was sent at all"
    unlinked = [path for path, linked in device.mix_writes if not linked]
    assert unlinked == [], (
        "mix written before the device confirmed the stereo link: %s" % unlinked
    )


def test_all_routes_are_linked_before_any_mix_is_written(session_mod):
    # Routes share output pairs, so the barrier has to be global rather
    # than per route -- otherwise route 2's link races route 1's mix.
    routes = [
        make_route(session_mod, name="main", playback=(1, 2), output=(1, 2)),
        make_route(session_mod, name="phones", playback=(1, 2), output=(7, 8)),
        make_route(session_mod, name="direct", playback=(7, 8), output=(7, 8)),
    ]
    device = run_apply(session_mod, routes)
    first_mix = next(i for i, p in enumerate(device.order)
                     if p.startswith("/mix/"))
    later_links = [p for p in device.order[first_mix:]
                   if p.endswith("/stereo")]
    assert later_links == [], (
        "link message sent after the mix phase started: %s" % later_links
    )
    assert all(linked for _, linked in device.mix_writes)


def test_every_stereo_route_links_both_pairs(session_mod):
    route = make_route(session_mod, playback=(7, 8), output=(3, 4))
    links = {path: args
             for path, _t, args in session_mod.link_messages(route)}
    assert links == {"/playback/7/stereo": (1,), "/output/3/stereo": (1,)}


def test_unlinked_route_does_not_link_its_outputs(session_mod):
    route = make_route(session_mod, stereo=False)
    paths = [path for path, _t, _a in session_mod.link_messages(route)]
    assert paths == ["/playback/1/stereo"]
    # ... and its mix writes use the hard-panned pair balance instead.
    mixes = [(path, args)
             for path, _t, args in session_mod.mix_messages(route)]
    assert mixes == [("/mix/5/playback/1", (0.0, -100)),
                     ("/mix/6/playback/1", (0.0, 100))]


def test_mono_route_needs_no_linking(session_mod):
    route = make_route(session_mod, playback=(1,), output=(9,))
    assert session_mod.link_messages(route) == []
    assert [p for p, _t, _a in session_mod.mix_messages(route)] == \
        ["/mix/9/playback/1"]


def test_route_messages_is_the_two_phases_in_order(session_mod):
    # expected_registers() and the verification build on this identity.
    route = make_route(session_mod, volume=-3.0)
    assert session_mod.route_messages(route) == (
        session_mod.link_messages(route) + session_mod.mix_messages(route))


def test_routing_is_applied_even_when_the_echo_never_arrives(session_mod,
                                                             monkeypatch):
    # A device that stays silent must not cost more than the timeout, and
    # the mix has to be sent regardless -- degraded beats no audio.
    monkeypatch.setattr(session_mod, "LINK_ECHO_TIMEOUT", 0.2)
    device = run_apply(session_mod, [make_route(session_mod)], echo=False)
    assert [p for p, _ in device.mix_writes] == ["/mix/5/playback/1"]


def test_falls_back_to_a_fixed_wait_when_the_port_is_taken(session_mod,
                                                           monkeypatch):
    # The mixer GUI holds the receive port; the echo is then unobservable
    # and apply_routing waits blind instead of skipping the barrier.
    monkeypatch.setattr(session_mod, "LINK_SETTLE", 0.05)
    send_port, recv_port = free_udp_port(), free_udp_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", recv_port))
    device = FakeOscmix(session_mod, send_port, recv_port, echo_delay=0.01)
    device.start()
    try:
        session_mod.apply_routing([make_route(session_mod)], send_port,
                                  recv_port)
    finally:
        blocker.close()
        device.stop()
        device.join(timeout=3)
        device.sock.close()
    assert [p for p, _ in device.mix_writes] == ["/mix/5/playback/1"]
    assert all(linked for _, linked in device.mix_writes)


def test_await_link_echo_reports_port_unavailable(session_mod):
    recv_port = free_udp_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", recv_port))
    try:
        result = session_mod.await_link_echo(["/output/5/stereo"], recv_port,
                                             timeout=0.1)
    finally:
        blocker.close()
    assert result is None


def test_await_link_echo_times_out_without_echo(session_mod):
    assert session_mod.await_link_echo(["/output/5/stereo"], free_udp_port(),
                                       timeout=0.1) is False


def test_await_link_echo_ignores_unlinking_echo(session_mod):
    # stereo=0 is not a confirmation; waiting must continue.
    recv_port = free_udp_port()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.sendto(session_mod.encode_osc("/output/5/stereo", "i", 0),
                  ("127.0.0.1", recv_port))
    try:
        assert session_mod.await_link_echo(["/output/5/stereo"], recv_port,
                                           timeout=0.2) is False
    finally:
        sender.close()


def test_await_link_echo_without_paths_is_immediate(session_mod):
    assert session_mod.await_link_echo([], free_udp_port()) is True


def test_output_link_paths_are_unique_and_output_only(session_mod):
    routes = [
        make_route(session_mod, name="a", playback=(1, 2), output=(7, 8)),
        make_route(session_mod, name="b", playback=(7, 8), output=(7, 8)),
        make_route(session_mod, name="c", playback=(1, 2), output=(1, 2)),
        make_route(session_mod, name="mono", playback=(1,), output=(9,)),
    ]
    assert session_mod.output_link_paths(routes) == ["/output/7/stereo",
                                                     "/output/1/stereo"]


def make_config(session_mod, routes, port, recv_port):
    return session_mod.Config(routes=routes, osc_port=port,
                              osc_recv_port=recv_port)


class DumpingOscmix(threading.Thread):
    """Records every write and answers /refresh with a canned dump.

    Whatever the dump contains, oscmix's link state is only correct once
    it has reported ``/output/<n>/stereo`` -- which is what the mix
    re-apply hangs off.
    """

    def __init__(self, session_mod, send_port, recv_port, dump):
        super().__init__(daemon=True)
        self.session_mod = session_mod
        self.recv_port = recv_port
        self.dump = dump
        self.order = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", send_port))
        self.sock.settimeout(0.2)
        self.stopping = threading.Event()

    def stop(self):
        self.stopping.set()

    def drain(self, quiet=0.3, limit=5.0):
        """Wait until no further datagram arrives for ``quiet`` seconds.

        UDP sends return immediately, so stopping the moment
        verify_and_repair() returns would race the last datagrams and
        make the order assertions flaky.
        """
        deadline = time.monotonic() + limit
        seen = -1
        while time.monotonic() < deadline:
            if len(self.order) == seen:
                return
            seen = len(self.order)
            time.sleep(quiet)

    def run(self):
        while not self.stopping.is_set():
            try:
                data, _ = self.sock.recvfrom(65536)
            except socket.timeout:
                continue          # keep listening past the verify window
            except OSError:
                return
            for message in self.session_mod.iter_osc_messages(data):
                try:
                    path, _tags, _args = self.session_mod.decode_osc(message)
                except ValueError:
                    continue
                self.order.append(path)
                if path == "/refresh":
                    for register in self.dump:
                        self.sock.sendto(register,
                                         ("127.0.0.1", self.recv_port))


def run_verify_and_repair(session_mod, routes, dump, recv_port=None,
                          blocked=False):
    send_port = free_udp_port()
    recv_port = recv_port or free_udp_port()
    blocker = None
    if blocked:
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("127.0.0.1", recv_port))
    device = DumpingOscmix(session_mod, send_port, recv_port, dump)
    device.start()
    try:
        session_mod.verify_and_repair(
            make_config(session_mod, routes, send_port, recv_port))
        device.drain()
    finally:
        if blocker is not None:
            blocker.close()
        device.stop()
        device.join(timeout=5)
        device.sock.close()
    return device


def full_dump(session_mod, routes):
    return [session_mod.encode_osc(path, types, *args)
            for route in routes
            for path, types, args in session_mod.route_messages(route)]


def test_mix_is_reapplied_once_the_dump_reports_the_link_state(session_mod):
    # The dump is what teaches oscmix the device's real link state, so the
    # matrix is rewritten off the back of it rather than from a guess.
    routes = [make_route(session_mod, volume=0.0)]
    device = run_verify_and_repair(session_mod, routes,
                                   full_dump(session_mod, routes))
    assert device.order == ["/refresh", "/mix/5/playback/1",
                            "/output/5/volume", "/output/6/volume"]


def test_reapply_repeats_no_link_message(session_mod):
    # Re-linking would make the device echo again and could restart the
    # very race this repairs; only the matrix is rewritten.
    routes = [make_route(session_mod, volume=0.0)]
    device = run_verify_and_repair(session_mod, routes,
                                   full_dump(session_mod, routes))
    assert [p for p in device.order if p.endswith("/stereo")] == []


def test_mix_is_reapplied_even_when_the_dump_omits_the_links(session_mod,
                                                             monkeypatch):
    # Degraded beats silent: without the link report the state is unknown,
    # but leaving the matrix as written at startup is the worse option.
    monkeypatch.setattr(session_mod, "VERIFY_TIMEOUT", 0.3)
    routes = [make_route(session_mod)]
    dump = [session_mod.encode_osc(path, types, *args)
            for path, types, args in session_mod.route_messages(routes[0])
            if path != "/output/5/stereo"]
    device = run_verify_and_repair(session_mod, routes, dump)
    assert device.order.count("/mix/5/playback/1") >= 1


def test_blind_reapply_when_the_receive_port_is_taken(session_mod,
                                                      monkeypatch):
    # The mixer GUI holds the port: nothing can be observed, so /refresh
    # still goes out to sync oscmix and the matrix follows after a wait.
    monkeypatch.setattr(session_mod, "LINK_SYNC_BLIND_DELAY", 0.05)
    routes = [make_route(session_mod, volume=0.0)]
    device = run_verify_and_repair(session_mod, routes, [], blocked=True)
    assert device.order == ["/refresh", "/mix/5/playback/1",
                            "/output/5/volume", "/output/6/volume"]


def test_routes_without_pairs_still_verify(session_mod):
    # A mono-only routing has no links to wait for; the re-apply must not
    # block on a report that can never come.
    routes = [make_route(session_mod, playback=(1,), output=(9,))]
    device = run_verify_and_repair(session_mod, routes,
                                   full_dump(session_mod, routes))
    assert device.order[0] == "/refresh"
