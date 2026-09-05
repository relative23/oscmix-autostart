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
    from oscmix_desk import session

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

        from oscmix_desk import Config
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
    from oscmix_desk import cli

    path = tmp_path / "routing.conf"
    path.write_text("[route:x]\nplayback = 1/2\noutput = nonsense\n")
    assert cli.main(["--config", str(path)]) == session_mod.EXIT_CONFIG


def test_a_signal_death_is_named_not_just_numbered(session_module, monkeypatch,
                                                   caplog, tmp_path):
    # A bare "status -13" sent the first reader of the midnight crash
    # cluster to the exit-code tables; the log now says SIGPIPE itself.
    monkeypatch.setattr(session_module, "usb_device_present",
                        lambda *_a: True)
    with caplog.at_level("ERROR"):
        code = session_module._exit_code_for(
            -13, session_module.Config(routes=[]), tmp_path, {"stop": False})
    assert code == session_module.EXIT_FAILURE
    assert "status -13 (SIGPIPE)" in caplog.text


# --------------------------------------------------------------------------
# What counts as "nothing to apply"
# --------------------------------------------------------------------------

class RunningChild:
    """A backend that is still up, so a verifier may start."""

    def poll(self):
        return None


def test_a_config_without_routes_is_still_applied(session_module, monkeypatch):
    """Since 0.4.0 a file may declare channel or global state and no route.

    `_apply_and_verify` returned before `apply_routing` whenever
    `config.routes` was empty -- a guard from 0.1.0, when routes were all
    a file could say, that survived every release the surface grew in.
    An `[input:3]` or `[clock]` section in such a file parsed, showed in
    `--dry-run`, went out on a SIGHUP reload, and never reached the
    device at start. The check is on what the config *declares* now.
    """
    from oscmix_desk import ChannelSetting, Config
    from oscmix_desk.config import GlobalSetting

    applied = []
    monkeypatch.setattr(session_module, "apply_routing",
                        lambda config, *a, **k: applied.append(config))
    monkeypatch.setattr(session_module, "verify_and_repair",
                        lambda *a, **k: None)
    monkeypatch.setattr(session_module, "VERIFY_SETTLE", 0.0)

    config = Config(channels=[ChannelSetting("input", 3, "gain", 12.0)],
                    globals=[GlobalSetting("clock", "source", "Internal")])
    verifier = session_module._apply_and_verify(RunningChild(), config,
                                                {"stop": False})
    assert applied == [config]
    assert verifier is not None, "a config with state to verify got no verifier"
    verifier.join(timeout=5)
    assert not verifier.is_alive()


def test_an_empty_config_leaves_the_desk_alone(session_module, monkeypatch,
                                               caplog):
    # The other half of the rule above: a file that declares nothing
    # writes nothing and starts no verifier, and says so.
    from oscmix_desk import Config

    monkeypatch.setattr(session_module, "apply_routing",
                        lambda *a, **k: pytest.fail("nothing to apply"))
    with caplog.at_level("INFO"):
        verifier = session_module._apply_and_verify(RunningChild(), Config(),
                                                    {"stop": False})
    assert verifier is None
    assert "leaving mixer state untouched" in caplog.text
