"""OSC 1.0 encoding: golden bytes and error handling."""

import struct

import pytest


def test_mix_message_golden_bytes(session_mod):
    # /mix/5/playback/1 ,fi 0.0 -100 -- the exact message the old
    # shell implementation sent, byte for byte.
    expected = (
        b"/mix/5/playback/1\x00\x00\x00"  # 17 chars + NUL, padded to 20
        + b",fi\x00"
        + struct.pack(">f", 0.0)
        + struct.pack(">i", -100)
    )
    assert session_mod.encode_osc("/mix/5/playback/1", "fi", 0.0, -100) == expected


def test_path_length_multiple_of_four_gets_full_pad(session_mod):
    # A 3-char path needs exactly one NUL; a 4-char path needs four
    # (OSC strings always carry at least one NUL terminator).
    assert session_mod.encode_osc("/ab") == b"/ab\x00,\x00\x00\x00"
    assert session_mod.encode_osc("/abc") == b"/abc\x00\x00\x00\x00,\x00\x00\x00"


def test_int_argument(session_mod):
    msg = session_mod.encode_osc("/output/5/stereo", "i", 1)
    assert msg.endswith(struct.pack(">i", 1))
    assert b",i\x00\x00" in msg


def test_float_argument_big_endian(session_mod):
    msg = session_mod.encode_osc("/output/5/volume", "f", -6.5)
    assert msg.endswith(struct.pack(">f", -6.5))


def test_string_argument(session_mod):
    msg = session_mod.encode_osc("/x", "s", "abc")
    assert msg.endswith(b"abc\x00")


def test_message_length_is_multiple_of_four(session_mod):
    for path in ("/a", "/ab", "/abc", "/abcd", "/mix/10/playback/12"):
        assert len(session_mod.encode_osc(path, "fi", 1.5, 2)) % 4 == 0


def test_argument_count_mismatch_raises(session_mod):
    with pytest.raises(ValueError):
        session_mod.encode_osc("/x", "fi", 1.0)


def test_unsupported_type_tag_raises(session_mod):
    with pytest.raises(ValueError):
        session_mod.encode_osc("/x", "b", b"blob")
