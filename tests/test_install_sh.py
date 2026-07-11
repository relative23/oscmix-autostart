"""Functional tests for install.sh / uninstall.sh.

Both scripts run against a throwaway HOME with stubbed systemctl/sudo on
PATH, so no real service, udev rule, or user file is touched. The build
step is skipped (--no-build) with fake oscmix binaries pre-installed.
"""

import os
import stat
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def make_fake_home(tmp_path):
    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    for tool in ("oscmix", "alsaseqio", "oscmix-gtk"):
        fake = bin_dir / tool
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)

    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    log = tmp_path / "calls.log"
    for tool in ("systemctl", "udevadm", "sudo"):
        stub = stub_bin / tool
        # The sudo stub must never execute its arguments -- uninstall.sh
        # would otherwise touch the real /etc/udev rule on dev machines.
        stub.write_text('#!/bin/sh\necho "%s $@" >> "%s"\nexit 0\n'
                        % (tool, log))
        stub.chmod(0o755)

    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "PATH": "%s:%s" % (stub_bin, env["PATH"]),
    })
    return home, env, log


def run(script, args, env):
    return subprocess.run(
        ["bash", str(PROJECT_ROOT / script)] + args,
        env=env, capture_output=True, text=True, timeout=60,
        cwd=str(PROJECT_ROOT),
    )


def test_install_no_build_installs_everything(tmp_path):
    home, env, log = make_fake_home(tmp_path)
    result = run("install.sh", ["--no-build", "--no-udev"], env)
    assert result.returncode == 0, result.stderr + result.stdout

    bin_dir = home / ".local" / "bin"
    for script in ("oscmix-session", "oscmix-launch"):
        installed = bin_dir / script
        assert installed.is_file()
        assert installed.stat().st_mode & stat.S_IXUSR

    config = home / ".config" / "oscmix" / "routing.conf"
    example = PROJECT_ROOT / "config" / "routing.conf.example"
    assert config.read_text() == example.read_text()
    assert (home / ".config" / "oscmix" / "routing.conf.example").is_file()

    unit = home / ".config" / "systemd" / "user" / "oscmix.service"
    assert "Type=notify" in unit.read_text()

    desktop = home / ".local" / "share" / "applications" / "oscmix-gtk.desktop"
    assert ("Exec=%s/oscmix-launch" % bin_dir) in desktop.read_text()
    icon = (home / ".local" / "share" / "icons" / "hicolor" / "scalable"
            / "apps" / "oscmix.svg")
    assert icon.is_file()

    calls = log.read_text()
    assert "systemctl --user daemon-reload" in calls
    assert "systemctl --user enable --quiet oscmix.service" in calls
    assert "udevadm" not in calls  # --no-udev


def test_install_is_idempotent_and_keeps_user_config(tmp_path):
    home, env, _ = make_fake_home(tmp_path)
    assert run("install.sh", ["--no-build", "--no-udev"], env).returncode == 0

    config = home / ".config" / "oscmix" / "routing.conf"
    config.write_text("# customized by the user\n")
    result = run("install.sh", ["--no-build", "--no-udev"], env)
    assert result.returncode == 0
    assert config.read_text() == "# customized by the user\n"
    assert "keeping existing" in result.stdout


def test_uninstall_removes_files_but_keeps_config(tmp_path):
    home, env, _ = make_fake_home(tmp_path)
    assert run("install.sh", ["--no-build", "--no-udev"], env).returncode == 0

    result = run("uninstall.sh", [], env)
    assert result.returncode == 0, result.stderr
    bin_dir = home / ".local" / "bin"
    for script in ("oscmix-session", "oscmix-launch", "oscmix", "alsaseqio"):
        assert not (bin_dir / script).exists()
    assert not (home / ".config" / "systemd" / "user"
                / "oscmix.service").exists()
    # User configuration survives a plain uninstall.
    assert (home / ".config" / "oscmix" / "routing.conf").is_file()


def test_uninstall_purge_removes_config(tmp_path):
    home, env, _ = make_fake_home(tmp_path)
    assert run("install.sh", ["--no-build", "--no-udev"], env).returncode == 0
    result = run("uninstall.sh", ["--purge"], env)
    assert result.returncode == 0, result.stderr
    assert not (home / ".config" / "oscmix").exists()
