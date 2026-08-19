"""The service contract: exit codes and the readiness protocol.

systemd acts on both. The exit code decides whether the unit restarts, and
under ``Type=notify`` a process that exits 0 without ever sending
``READY=1`` counts as a protocol failure -- which puts the unit into
exactly the restart loop the exit codes are chosen to avoid.

Until now these rules were stated in a module docstring and exercised by
one integration test. Here they are the assertion.
"""

import argparse

import pytest


@pytest.fixture
def session_module():
    from oscmix_autostart import session

    return session


def make_args(**overrides):
    values = dict(timeout=1.0, dry_run=False)
    values.update(overrides)
    return argparse.Namespace(**values)


class FakeChild:
    """A backend that is already finished."""

    def __init__(self, returncode=0):
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True


@pytest.fixture
def lifecycle(session_module, monkeypatch):
    """run_session with every outside interaction replaced.

    Returns a helper that records the readiness notifications sent, so a
    test can assert not only *that* READY was sent but how often.
    """
    notifications = []

    def run(*, seq_client=42, usb_present=True, binaries=True,
            returncode=0, stop_requested=False, routes=(), **args):
        monkeypatch.setattr(session_module, "sd_notify", notifications.append)
        monkeypatch.setattr(session_module, "wait_for_seq_client",
                            lambda *a, **k: seq_client)
        monkeypatch.setattr(session_module, "usb_device_present",
                            lambda *a, **k: usb_present)
        monkeypatch.setattr(session_module, "resolve_binary",
                            lambda *a, **k: "/bin/true" if binaries else None)
        monkeypatch.setattr(session_module, "_cleanup_stale_backend",
                            lambda *a, **k: None)
        monkeypatch.setattr(session_module, "_install_stop_handlers",
                            lambda *a, **k: None)
        monkeypatch.setattr(session_module, "_await_backend_port",
                            lambda *a, **k: None)
        monkeypatch.setattr(session_module, "_apply_and_verify",
                            lambda *a, **k: None)
        monkeypatch.setattr(session_module, "subprocess",
                            type("S", (), {"Popen": staticmethod(
                                lambda *a, **k: FakeChild(returncode))})())

        def fake_supervise(child, stop, on_reload=None,
                           reload_requested=None):
            # Signature mirrors the real one, keywords included: a double
            # that accepts **kwargs would have swallowed the reconcile
            # trigger silently instead of failing here.
            stop["stop"] = stop_requested
            return returncode

        monkeypatch.setattr(session_module, "supervise", fake_supervise)

        from oscmix_autostart import Config
        config = Config(routes=list(routes))
        return session_module.run_session(make_args(**args), config)

    run.notifications = notifications
    return run


def ready_count(notifications):
    return notifications.count("READY=1")


def test_no_device_exits_zero_and_signals_ready_once(session_mod, lifecycle):
    # The unit is pulled in by udev whether or not the interface is on.
    # "Nothing to do" is a successful start, not a failure to restart.
    assert lifecycle(seq_client=None, usb_present=False) == session_mod.EXIT_OK
    assert ready_count(lifecycle.notifications) == 1


def test_device_present_without_a_midi_port_is_a_runtime_failure(session_mod,
                                                                 lifecycle):
    # Plugged in but no ALSA client: a driver problem a restart may fix.
    assert lifecycle(seq_client=None,
                     usb_present=True) == session_mod.EXIT_FAILURE
    assert ready_count(lifecycle.notifications) == 0, (
        "a failing start must not claim readiness")


def test_missing_binaries_fail_without_claiming_readiness(session_mod,
                                                          lifecycle):
    assert lifecycle(binaries=False) == session_mod.EXIT_FAILURE
    assert ready_count(lifecycle.notifications) == 0


def test_a_clean_backend_exit_is_success_with_readiness(session_mod,
                                                        lifecycle):
    assert lifecycle(returncode=0) == session_mod.EXIT_OK
    assert ready_count(lifecycle.notifications) >= 1


def test_a_crashed_backend_is_a_runtime_failure(session_mod, lifecycle):
    assert lifecycle(returncode=1) == session_mod.EXIT_FAILURE


def test_a_crash_after_unplugging_is_not_a_failure(session_mod, lifecycle):
    # The backend dies because the device went away. Restarting cannot
    # help and would loop until the unit hits its start limit.
    assert lifecycle(returncode=1, usb_present=False) == session_mod.EXIT_OK
    assert ready_count(lifecycle.notifications) >= 1


def test_a_requested_stop_is_success(session_mod, lifecycle):
    assert lifecycle(returncode=1,
                     stop_requested=True) == session_mod.EXIT_OK
    assert ready_count(lifecycle.notifications) >= 1


@pytest.mark.parametrize("case", [
    {"seq_client": None, "usb_present": False},
    {"returncode": 0},
    {"returncode": 1, "usb_present": False},
    {"returncode": 1, "stop_requested": True},
])
def test_every_zero_exit_signalled_readiness(session_mod, lifecycle, case):
    # The contract in one line: exit 0 implies READY was sent. Type=notify
    # treats the alternative as a protocol failure.
    assert lifecycle(**case) == session_mod.EXIT_OK
    assert ready_count(lifecycle.notifications) >= 1


def test_a_dry_run_starts_nothing(session_mod, lifecycle, capsys):
    route = session_mod.Route(name="m", playback=(1, 2), output=(5, 6))
    assert lifecycle(dry_run=True, routes=[route]) == session_mod.EXIT_OK
    printed = capsys.readouterr().out
    assert "would run: alsaseqio 42:1" in printed
    assert "/output/5/stereo" in printed
    assert ready_count(lifecycle.notifications) == 0, (
        "a dry run is not a started service")


def test_a_config_error_exits_two_without_restarting(session_mod, tmp_path):
    # RestartPreventExitStatus=2: a broken routing.conf must stop the unit
    # rather than loop, because no restart can fix a typo.
    from oscmix_autostart import cli

    path = tmp_path / "routing.conf"
    path.write_text("[route:x]\nplayback = 1/2\noutput = nonsense\n")
    assert cli.main(["--config", str(path)]) == session_mod.EXIT_CONFIG
