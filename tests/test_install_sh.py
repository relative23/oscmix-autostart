"""Functional tests for install.sh / uninstall.sh.

Both scripts run against a throwaway HOME with stubbed systemctl/sudo on
PATH, so no real service, udev rule, or user file is touched. The build
step is skipped (--no-build) with fake oscmix binaries pre-installed.
"""

import os
import stat
import subprocess

import pytest
from conftest import repo_file

PROJECT_ROOT = repo_file("install.sh").parent

# These drive real subprocesses. The entry point resolves the package from
# its own location, so a subprocess loads the checked-out source and never
# the mutated copy: such a test cannot kill a mutant, and at ~35 s per run
# it would dominate a mutation pass for nothing.
pytestmark = pytest.mark.skipif(
    bool(os.environ.get("MUTANT_UNDER_TEST")),
    reason="subprocess tests cannot observe mutants",
)


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


# --------------------------------------------------------------------------
# Roadmap item J: nothing proved an install actually works.
#
# The tests above assert the *file set*. That is not the same as the
# installed tree being runnable: this release moved the runtime from
# lib/ to src/ and rewrote that path in three places, and the entry
# points resolve their package from their own location -- a layout that
# only exists after an install. Running them from the checkout, which
# every other test does, exercises the other branch of that lookup.
# --------------------------------------------------------------------------

SEQ_CLIENTS = """\
Client info
  cur  clients : 2

Client   0 : "System" [Kernel]
Client  42 : "Fireface UCX II (00000000)" [Kernel]
  Port   1 : "Port" (RWeX) [In/Out]
"""


def fake_proc_and_sysfs(tmp_path, *, with_usb):
    proc_root = tmp_path / "proc"
    (proc_root / "asound" / "seq").mkdir(parents=True)
    (proc_root / "asound" / "seq" / "clients").write_text(SEQ_CLIENTS)
    sysfs = tmp_path / "sysfs"
    sysfs.mkdir()
    if with_usb:
        dev = sysfs / "5-2"
        dev.mkdir()
        (dev / "idVendor").write_text("2a39\n")
        (dev / "idProduct").write_text("3fd9\n")
    return proc_root, sysfs


def test_the_installed_session_runs_from_the_installed_tree(tmp_path):
    home, env, _ = make_fake_home(tmp_path)
    assert run("install.sh", ["--no-build", "--no-udev"], env).returncode == 0

    # The package has to be where the shim looks for it: ~/.local/bin is
    # next to ~/.local/lib/oscmix-autostart, not next to a src/.
    lib = home / ".local" / "lib" / "oscmix-autostart" / "oscmix_autostart"
    assert (lib / "__init__.py").is_file()
    assert (lib / "launcher.py").is_file(), \
        "the launcher moved into the package but install.sh did not follow"

    proc_root, sysfs = fake_proc_and_sysfs(tmp_path, with_usb=True)
    config = tmp_path / "routing.conf"
    config.write_text("[route:main]\nplayback = 1/2\noutput = 5/6\n")

    run_env = dict(env)
    run_env.update({
        "OSCMIX_PROC_ROOT": str(proc_root),
        "OSCMIX_SYSFS_USB": str(sysfs),
    })
    # Deliberately from a directory that is not the checkout: the shim
    # must resolve its package from its own path, not from the cwd.
    result = subprocess.run(
        [str(home / ".local" / "bin" / "oscmix-session"),
         "--config", str(config), "--dry-run"],
        env=run_env, capture_output=True, text=True, timeout=60,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "would send: /output/5/stereo ,i 1" in result.stdout
    assert "would send: /mix/5/playback/1" in result.stdout
    # Same order rule as everywhere else: links before the mix matrix.
    assert (result.stdout.index("/output/5/stereo")
            < result.stdout.index("/mix/5/playback/1"))


def test_the_installed_launcher_resolves_its_package(tmp_path):
    # oscmix-launch was a standalone script until this release and is a
    # shim now; if install.sh missed launcher.py the shim would die with
    # ImportError on a desktop double-click, with no notification.
    home, env, _ = make_fake_home(tmp_path)
    assert run("install.sh", ["--no-build", "--no-udev"], env).returncode == 0

    proc_root, sysfs = fake_proc_and_sysfs(tmp_path, with_usb=False)
    run_env = dict(env)
    run_env.update({
        "OSCMIX_PROC_ROOT": str(proc_root),
        "OSCMIX_SYSFS_USB": str(sysfs),
        "OSCMIX_NO_NOTIFY": "1",
    })
    result = subprocess.run(
        [str(home / ".local" / "bin" / "oscmix-launch")],
        env=run_env, capture_output=True, text=True, timeout=60,
        cwd=str(tmp_path),
    )
    assert result.returncode == 1
    assert "is not connected" in result.stderr
    assert "Traceback" not in result.stderr
    assert "ImportError" not in result.stderr


def test_the_installed_tree_carries_every_runtime_module(tmp_path):
    # install.sh globs src/oscmix_autostart/*.py. A module added in a
    # subdirectory, or one that stops matching the glob, would be missing
    # only at runtime on a user's machine.
    home, env, _ = make_fake_home(tmp_path)
    assert run("install.sh", ["--no-build", "--no-udev"], env).returncode == 0

    source = {path.name for path in
              (PROJECT_ROOT / "src" / "oscmix_autostart").glob("*.py")}
    installed = {path.name for path in
                 (home / ".local" / "lib" / "oscmix-autostart"
                  / "oscmix_autostart").glob("*.py")}
    assert source == installed, "not installed: %s" % sorted(source - installed)
