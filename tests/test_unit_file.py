"""The systemd unit: hardening that a *user* service can actually apply.

Learned the hard way. A unit with the usual hardening block --
ProtectKernelTunables, ProtectClock, RestrictSUIDSGID, DeviceAllow,
IPAddressDeny -- refuses to start under `systemd --user` with
``218/CAPABILITIES``: the user manager is unprivileged, so it cannot drop
capabilities or program a cgroup controller. The audio stops and the
journal says "Failed to drop capabilities", which reads like a bug in
this project rather than a directive that does not belong here.

So the forbidden list below is not style. Each entry breaks the service.
"""

import pytest
from conftest import repo_file

# Applied and verified by starting the unit, not by reading the manual.
REQUIRED = [
    "NoNewPrivileges=yes",
    "PrivateTmp=yes",
    "ProtectSystem=strict",
    "ProtectHome=read-only",
    "LockPersonality=yes",
    "MemoryDenyWriteExecute=yes",
    "SystemCallArchitectures=native",
    "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
]

# Each of these fails a user unit: the first group implies dropping
# capabilities, the second needs a delegated cgroup controller.
FORBIDDEN = [
    "ProtectKernelTunables",
    "ProtectKernelLogs",
    "ProtectClock",
    "ProtectControlGroups",
    "RestrictSUIDSGID",
    "CapabilityBoundingSet",
    "AmbientCapabilities",
    "DeviceAllow",
    "IPAddressAllow",
    "IPAddressDeny",
    "PrivateDevices",
    "User=",
    "Group=",
]


@pytest.fixture(scope="module")
def unit():
    return repo_file("systemd", "oscmix.service").read_text()


@pytest.mark.parametrize("directive", REQUIRED)
def test_the_hardening_that_works_is_present(unit, directive):
    assert directive in unit


@pytest.mark.parametrize("directive", FORBIDDEN)
def test_directives_that_break_a_user_unit_stay_out(unit, directive):
    lines = [line.strip() for line in unit.splitlines()
             if not line.strip().startswith("#")]
    offenders = [line for line in lines if line.startswith(directive)]
    assert offenders == [], (
        "%s cannot be applied by an unprivileged user manager; the unit "
        "would fail with 218/CAPABILITIES and the audio would stop"
        % directive)


def test_the_notify_and_restart_contract_is_intact(unit):
    # These encode the exit-code model: 2 means a config error no restart
    # can fix, and Type=notify means "started" implies routing applied.
    assert "Type=notify" in unit
    assert "RestartPreventExitStatus=2" in unit
    assert "Restart=on-failure" in unit


def test_the_stop_timeout_outlasts_the_kill_escalation(unit, session_mod):
    # supervise() waits CHILD_STOP_GRACE before SIGKILL. If systemd gave
    # up first it would kill the session instead, and a clean shutdown
    # would be reported as a failure.
    from oscmix_autostart import constants

    stop_timeout = next(int(line.split("=")[1].rstrip("s"))
                        for line in unit.splitlines()
                        if line.startswith("TimeoutStopSec="))
    assert stop_timeout > constants.CHILD_STOP_GRACE
