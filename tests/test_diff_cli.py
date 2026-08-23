"""`--diff`: the plan printed instead of sent.

The reconciler already answers "what would an apply write" -- `plan()`
is what the session runs on every start. This prints its result. The
test that matters most is the one asserting the device is never written
to: a diagnostic that changes what it inspects is worse than none.

Shares the FakeBackend from the dump-config tests, because the two
commands ask the device the same question and differ only in what they
do with the answer.
"""

import socket

from conftest import free_udp_port
from test_dump_config_cli import FakeBackend, dump_of

from oscmix_autostart import cli

CONFIG = ("[device]\nname = Fireface UCX II\n\n"
          "[route:main]\nplayback = 1/2\noutput = 5/6\nlevel = 0.0\n\n"
          "[input:3]\ngain = 12.0\n")


def run_diff(session_mod, capsys, tmp_path, registers, *, hold_port=False):
    """Returns (exit code, stdout, every message the backend received)."""
    send_port, recv_port = free_udp_port(), free_udp_port()
    path = tmp_path / "routing.conf"
    path.write_text(CONFIG + "\n[osc]\nport = %d\nrecv-port = %d\n"
                    % (send_port, recv_port))
    config = session_mod.load_config(path)

    blocker = None
    if hold_port:
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("127.0.0.1", recv_port))

    backend = RecordingBackend(session_mod, send_port, recv_port,
                               dump_of(session_mod, registers))
    backend.start()
    try:
        code = cli._diff(config)
    finally:
        backend.stop()
        backend.join(timeout=3)
        backend.sock.close()
        if blocker is not None:
            blocker.close()
    return code, capsys.readouterr().out, backend.received


class RecordingBackend(FakeBackend):
    """FakeBackend that also keeps every address it was sent."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.received = []

    def run(self):
        while not self.stopping.is_set():
            try:
                data, _ = self.sock.recvfrom(65536)
            except (socket.timeout, OSError):
                if self.stopping.is_set():
                    return
                continue
            for message in self.session_mod.iter_osc_messages(data):
                try:
                    path, _t, _a = self.session_mod.decode_osc(message)
                except ValueError:
                    continue
                self.received.append(path)
                if path == "/refresh":
                    for register in self.dump:
                        self.sock.sendto(register, ("127.0.0.1", self.recv_port))


#: What a device would report if it already held the config above.
IN_SYNC = [
    ("/output/5/stereo", "i", (1,)),
    ("/playback/1/stereo", "i", (1,)),
    ("/mix/5/input/1", "fi", (0.0, 0)),
    ("/input/3/gain", "f", (12.0,)),
    ("/output/5/volume", "f", (0.0,)),
    ("/output/6/volume", "f", (0.0,)),
]

DRIFTED = [(path, tags, (3.0,) if path == "/input/3/gain" else args)
           for path, tags, args in IN_SYNC]


# --------------------------------------------------------------------------
# The property the whole command rests on.
# --------------------------------------------------------------------------

def test_it_writes_nothing_to_the_device(session_mod, capsys, tmp_path):
    """A diagnostic that changes what it inspects is worse than none.

    Asserted against every address the backend saw, not against a mock's
    call list -- the question is what reached the wire.
    """
    _code, _out, received = run_diff(session_mod, capsys, tmp_path, DRIFTED)
    assert received, "the backend saw nothing at all -- the test proves nothing"
    assert set(received) == {"/refresh"}


def test_a_drifted_register_is_reported_with_both_values(session_mod, capsys,
                                                         tmp_path):
    code, out, _ = run_diff(session_mod, capsys, tmp_path, DRIFTED)
    assert code == 0
    assert "/input/3/gain" in out
    assert "12.0" in out          # what the config asks for
    assert "3.0" in out           # what the device holds
    assert "mismatched" in out


def test_a_device_that_matches_says_so_plainly(session_mod, capsys, tmp_path):
    code, out, _ = run_diff(session_mod, capsys, tmp_path, IN_SYNC)
    assert code == 0
    assert "the device matches the config" in out
    assert "mismatched" not in out


# --------------------------------------------------------------------------
# A rewrite is not a difference.
# --------------------------------------------------------------------------

def test_the_playback_matrix_is_counted_apart_from_real_differences():
    """`/mix/<out>/playback/<pb>` is never reported (ADR 0002), so it is
    written on every apply whatever the device holds. Listing it as a
    difference would answer "has the desk drifted?" with a number that
    is never zero.
    """
    from oscmix_autostart.reconcile import REWRITE, desired, plan
    from oscmix_autostart.registers import UCX2

    config_paths = {"/mix/5/playback/1"}
    entries = [e for e in desired(_config()) if e.path in config_paths]
    assert entries, "no playback matrix entry to judge"
    result = plan(entries, {}, UCX2)
    assert all(w.reason == REWRITE for w in result.writes)


def _config():
    from oscmix_autostart.config import Config, Route
    return Config(device_name="Fireface UCX II",
                  routes=[Route(name="main", playback=(1, 2), output=(5, 6),
                                level=0.0)])


def test_the_rewrites_are_named_in_the_output(session_mod, capsys, tmp_path):
    _code, out, _ = run_diff(session_mod, capsys, tmp_path, IN_SYNC)
    assert "rewritten regardless" in out
    assert "ADR 0002" in out


# --------------------------------------------------------------------------
# Failure paths, which are the ones a user meets first.
# --------------------------------------------------------------------------

def test_a_held_receive_port_is_refused_rather_than_half_read(session_mod,
                                                              capsys,
                                                              tmp_path):
    code, out, _ = run_diff(session_mod, capsys, tmp_path, IN_SYNC,
                            hold_port=True)
    assert code == 1
    assert out == ""


def test_silence_is_an_error_not_an_empty_diff(session_mod, capsys, tmp_path,
                                               monkeypatch):
    """"nobody answered" and "nothing differs" are opposite situations and
    must not print the same thing.

    The window is shortened because this test's whole point is that it
    expires -- paying the real 8 s to learn that is what pushed the CI
    mutation job past its limit once already.
    """
    monkeypatch.setattr(cli, "DUMP_READ_SECONDS", 0.6)
    code, out, _ = run_diff(session_mod, capsys, tmp_path, [])
    assert code == 1
    assert "matches the config" not in out
