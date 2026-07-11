"""UDP port detection via /proc/net/udp (no ss/netstat dependency)."""

# Real /proc/net/udp format; 0x1C36 == 7222.
UDP_WITH_OSCMIX = """\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops
  100: 0100007F:1C36 00000000:0000 07 00000000:00000000 00:00000000 00000000  1000        0 123456 2 0000000000000000 0
  101: 00000000:0044 00000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 654321 2 0000000000000000 0
"""

UDP_WITHOUT_OSCMIX = """\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops
  101: 00000000:0044 00000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 654321 2 0000000000000000 0
"""

UDP6_WITH_OSCMIX = """\
  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops
  200: 00000000000000000000000001000000:1C36 00000000000000000000000000000000:0000 07 00000000:00000000 00:00000000 00000000  1000        0 999999 2 0000000000000000 0
"""


def make_proc(tmp_path, udp=None, udp6=None):
    net = tmp_path / "proc" / "net"
    net.mkdir(parents=True)
    if udp is not None:
        (net / "udp").write_text(udp)
    if udp6 is not None:
        (net / "udp6").write_text(udp6)
    return tmp_path / "proc"


def test_detects_listening_port(session_mod, tmp_path):
    proc = make_proc(tmp_path, udp=UDP_WITH_OSCMIX)
    assert session_mod.udp_port_listening(7222, proc) is True


def test_ignores_other_ports(session_mod, tmp_path):
    proc = make_proc(tmp_path, udp=UDP_WITHOUT_OSCMIX)
    assert session_mod.udp_port_listening(7222, proc) is False


def test_detects_ipv6_socket(session_mod, tmp_path):
    proc = make_proc(tmp_path, udp=UDP_WITHOUT_OSCMIX, udp6=UDP6_WITH_OSCMIX)
    assert session_mod.udp_port_listening(7222, proc) is True


def test_missing_proc_files(session_mod, tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    assert session_mod.udp_port_listening(7222, proc) is False


def test_find_stale_backends_matches_only_oscmix(session_mod, tmp_path):
    proc = tmp_path / "proc"
    for pid, argv0 in ((101, b"/usr/local/bin/oscmix"),
                       (102, b"/usr/local/bin/alsaseqio"),
                       (103, b"oscmix"),
                       (104, b"oscmix-gtk")):
        entry = proc / str(pid)
        entry.mkdir(parents=True)
        (entry / "cmdline").write_bytes(argv0 + b"\x00")
    (proc / "self").mkdir()  # non-numeric entries are skipped
    (proc / "105").mkdir()   # missing cmdline is skipped
    assert session_mod.find_stale_backends(proc) == [101, 103]
