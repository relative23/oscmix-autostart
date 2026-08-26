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


def test_device_serial_reads_the_product_string(tmp_path):
    """The number RME prints on the box, not the USB iSerial.

    Moved into the library from verify-hardware.py when the write sweep
    needed the same answer -- an evidence artifact that cannot name its
    box stops being evidence the moment there is a second one.
    """
    from oscmix_desk.discovery import device_serial

    cards = tmp_path / "cards"
    cards.write_text(
        " 0 [NVidia       ]: HDA-Intel - HDA NVidia\n"
        " 2 [II24216011   ]: USB-Audio - Fireface UCX II (24216011)\n")
    assert device_serial(cards) == "24216011"

    cards.write_text(" 0 [NVidia ]: HDA-Intel - HDA NVidia\n")
    assert device_serial(cards) is None

    assert device_serial(tmp_path / "missing") is None


def test_built_backend_revision_reads_the_checkout(tmp_path):
    """The revision comes from the checkout, not from the pin.

    Reading what is actually built keeps install.sh's pin honest: if the
    two ever disagree, the artifact names the binary that ran, which is
    the one the measurement is about.
    """
    import subprocess

    from oscmix_desk.discovery import built_backend_revision

    # No build/oscmix at all: no answer, not a crash.
    assert built_backend_revision(tmp_path) is None

    build = tmp_path / "build" / "oscmix"
    build.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=build, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "x"],
                   cwd=build, check=True)
    revision = built_backend_revision(tmp_path)
    assert revision is not None
    assert len(revision) == 40
