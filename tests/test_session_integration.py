"""End-to-end tests: run bin/oscmix-session against a stub backend.

The stub replaces alsaseqio: it records its argv, binds the OSC UDP port,
appends every received datagram (hex) to a file, and exits on SIGTERM.
It also publishes the fake /proc/net/udp entry only after binding, so the
session's port-readiness loop is exercised for real.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSION_BIN = PROJECT_ROOT / "bin" / "oscmix-session"

SEQ_CLIENTS = """\
Client info
  cur  clients : 3

Client   0 : "System" [Kernel Legacy]
  Port   0 : "Timer" (Rwe-) [In/Out]
Client  42 : "Fireface UCX II (00000000)" [Kernel Legacy]
  Port   0 : "Fireface UCX II (00000000) Port" (RWeX) [In/Out]
  Port   1 : "Fireface UCX II (00000000) Port" (RWeX) [In/Out]
"""

UDP_HEADER = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when "
    "retrnsmt   uid  timeout inode ref pointer drops\n"
)

STUB_ALSASEQIO = """\
#!/usr/bin/env python3
import json, os, signal, socket, sys

stub_dir = os.environ["STUB_DIR"]
port = int(os.environ["STUB_PORT"])

with open(os.path.join(stub_dir, "argv.json"), "w") as f:
    json.dump(sys.argv[1:], f)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", port))
sock.settimeout(0.2)

# Only now advertise the port in the fake /proc/net/udp.
with open(os.environ["STUB_PROC_UDP"], "w") as f:
    f.write(os.environ["STUB_PROC_UDP_HEADER"])
    f.write("  100: 0100007F:%04X 00000000:0000 07 00000000:00000000 "
            "00:00000000 00000000  1000        0 1 2 0 0\\n" % port)

running = [True]
signal.signal(signal.SIGTERM, lambda *a: running.__setitem__(0, False))

log = open(os.path.join(stub_dir, "datagrams.hex"), "a")
while running[0]:
    try:
        data, _ = sock.recvfrom(65536)
    except socket.timeout:
        continue
    log.write(data.hex() + "\\n")
    log.flush()
sys.exit(0)
"""

ROUTING_CONF = """\
[osc]
port = {port}

[route:monitors]
playback = 1/2
output = 5/6
level = 0.0
volume = 0.0
"""


def free_udp_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def make_env(tmp_path, *, with_client, with_usb, port=None):
    proc_root = tmp_path / "proc"
    (proc_root / "asound" / "seq").mkdir(parents=True)
    (proc_root / "net").mkdir(parents=True)
    if with_client:
        (proc_root / "asound" / "seq" / "clients").write_text(SEQ_CLIENTS)
    (proc_root / "net" / "udp").write_text(UDP_HEADER)

    sysfs = tmp_path / "sysfs"
    sysfs.mkdir()
    if with_usb:
        dev = sysfs / "5-2"
        dev.mkdir()
        (dev / "idVendor").write_text("2a39\n")
        (dev / "idProduct").write_text("3fd9\n")

    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    stub = stub_dir / "alsaseqio-stub"
    stub.write_text(STUB_ALSASEQIO)
    stub.chmod(0o755)
    backend = stub_dir / "oscmix-dummy"
    backend.write_text("#!/bin/sh\nexit 0\n")
    backend.chmod(0o755)

    env = dict(os.environ)
    env.update({
        # Keep the test hermetic: never read the real user config.
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "OSCMIX_PROC_ROOT": str(proc_root),
        "OSCMIX_SYSFS_USB": str(sysfs),
        "OSCMIX_SEQ_DEV": str(tmp_path / "no-such-seq-device"),
        "OSCMIX_BIN_ALSASEQIO": str(stub),
        "OSCMIX_BIN_BACKEND": str(backend),
        "STUB_DIR": str(stub_dir),
        "STUB_PORT": str(port or 0),
        "STUB_PROC_UDP": str(proc_root / "net" / "udp"),
        "STUB_PROC_UDP_HEADER": UDP_HEADER,
    })
    return env, stub_dir, backend


def run_session(args, env):
    return subprocess.run(
        [sys.executable, str(SESSION_BIN)] + args,
        env=env, capture_output=True, text=True, timeout=30,
    )


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_full_startup_routing_and_shutdown(tmp_path, session_mod):
    port = free_udp_port()
    env, stub_dir, backend = make_env(
        tmp_path, with_client=True, with_usb=True, port=port
    )
    config = tmp_path / "routing.conf"
    config.write_text(ROUTING_CONF.format(port=port))

    proc = subprocess.Popen(
        [sys.executable, str(SESSION_BIN), "--config", str(config), "--timeout", "5"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        datagram_log = stub_dir / "datagrams.hex"
        expected_count = 5  # playback+output stereo links, 1 mix, 2 volume
        assert wait_for(
            lambda: datagram_log.exists()
            and len(datagram_log.read_text().splitlines()) >= expected_count
        ), "routing messages did not arrive: %s" % proc.stderr

        # The stub must have been invoked with the discovered client:port
        # and the resolved backend binary.
        argv = json.loads((stub_dir / "argv.json").read_text())
        assert argv == ["42:1", str(backend)]

        # Byte-exact routing messages, in order.
        expected = [
            session_mod.encode_osc("/playback/1/stereo", "i", 1),
            session_mod.encode_osc("/output/5/stereo", "i", 1),
            session_mod.encode_osc("/mix/5/playback/1", "fi", 0.0, 0),
            session_mod.encode_osc("/output/5/volume", "f", 0.0),
            session_mod.encode_osc("/output/6/volume", "f", 0.0),
        ]
        received = [bytes.fromhex(line)
                    for line in datagram_log.read_text().splitlines()]
        assert received[:expected_count] == expected

        # Clean shutdown: SIGTERM -> child terminated -> exit code 0.
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_device_not_connected_exits_zero(tmp_path):
    env, _, _ = make_env(tmp_path, with_client=False, with_usb=False)
    result = run_session(["--timeout", "1"], env)
    assert result.returncode == 0
    assert "not connected" in result.stderr


def test_usb_present_but_no_midi_client_fails(tmp_path):
    env, _, _ = make_env(tmp_path, with_client=False, with_usb=True)
    result = run_session(["--timeout", "1"], env)
    assert result.returncode == 1
    assert "snd-usb-audio" in result.stderr


def test_config_error_exits_two(tmp_path):
    env, _, _ = make_env(tmp_path, with_client=True, with_usb=True)
    config = tmp_path / "broken.conf"
    config.write_text("[route:x]\nplayback = 1/2\n")  # missing 'output'
    result = run_session(["--config", str(config)], env)
    assert result.returncode == 2
    assert "configuration error" in result.stderr


def test_dry_run_prints_plan_without_starting(tmp_path):
    port = free_udp_port()
    env, stub_dir, _ = make_env(tmp_path, with_client=True, with_usb=True, port=port)
    config = tmp_path / "routing.conf"
    config.write_text(ROUTING_CONF.format(port=port))
    result = run_session(["--config", str(config), "--dry-run"], env)
    assert result.returncode == 0
    assert "would run: alsaseqio 42:1" in result.stdout
    assert "/mix/5/playback/1" in result.stdout
    assert not (stub_dir / "argv.json").exists()  # nothing was spawned


def test_launcher_exits_one_without_device(tmp_path):
    env, _, _ = make_env(tmp_path, with_client=False, with_usb=False)
    env["OSCMIX_NO_NOTIFY"] = "1"
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "bin" / "oscmix-launch")],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1
    assert "not connected" in result.stderr
