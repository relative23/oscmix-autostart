"""Parsing /proc/asound/seq/clients (fixture captured from a real system)."""

# Trimmed real output: the Fireface name also appears in port lines and
# there is a "Midi Through" client before it -- both historic footguns.
REAL_OUTPUT = """\
Client info
  cur  clients : 6
  peak clients : 21
  max  clients : 192

Client   0 : "System" [Kernel Legacy]
  Port   0 : "Timer" (Rwe-) [In/Out]
    Connecting To: 144:0
Client  14 : "Midi Through" [Kernel Legacy]
  Port   0 : "Midi Through Port-0" (RWe-) [In/Out]
Client  24 : "Fireface UCX II (24216011)" [Kernel Legacy]
  Port   0 : "Fireface UCX II (24216011) Port" (RWeX) [In/Out]
  Port   1 : "Fireface UCX II (24216011) Port" (RWeX) [In/Out]
    Connecting To: 128:0
Client 128 : "alsaseq" [User Legacy]
  Port   0 : "alsaseq" (rwe-) [In/Out]
Client 144 : "PipeWire-System" [User UMP MIDI2]
  Port   0 : "input" (rwe-) [In/Out]
"""


def test_parses_all_clients(session_mod):
    clients = session_mod.parse_seq_clients(REAL_OUTPUT)
    assert clients == [
        (0, "System"),
        (14, "Midi Through"),
        (24, "Fireface UCX II (24216011)"),
        (128, "alsaseq"),
        (144, "PipeWire-System"),
    ]


def test_finds_fireface_client_number(session_mod):
    assert session_mod.find_seq_client(REAL_OUTPUT, "Fireface UCX II") == 24


def test_port_lines_do_not_shadow_client_line(session_mod):
    # The device name appears in "Port 0/1" lines too; only the Client
    # line may match (the old grep -B1 approach picked "Midi Through").
    result = session_mod.find_seq_client(REAL_OUTPUT, "Fireface UCX II")
    assert result == 24
    assert result != 14


def test_absent_device_returns_none(session_mod):
    assert session_mod.find_seq_client(REAL_OUTPUT, "Babyface Pro") is None


def test_empty_input(session_mod):
    assert session_mod.parse_seq_clients("") == []
    assert session_mod.find_seq_client("", "Fireface UCX II") is None
