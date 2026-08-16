"""OSC 1.0 encoding and decoding -- the subset oscmix understands."""

from __future__ import annotations

import struct
from typing import Iterator, List, Tuple


def _osc_string(value: str) -> bytes:
    """Encode an OSC string: ASCII, NUL-terminated, padded to 4 bytes."""
    raw = value.encode("ascii") + b"\x00"
    return raw + b"\x00" * (-len(raw) % 4)


def encode_osc(path: str, types: str = "", *args: object) -> bytes:
    """Encode a single OSC message.

    Supported type tags: ``f`` (float32), ``i`` (int32), ``s`` (string).
    """
    if len(types) != len(args):
        raise ValueError(
            "type tag %r expects %d arguments, got %d" % (types, len(types), len(args))
        )
    data = _osc_string(path) + _osc_string("," + types)
    for tag, value in zip(types, args):
        if tag == "f":
            data += struct.pack(">f", float(value))  # type: ignore[arg-type]
        elif tag == "i":
            data += struct.pack(">i", int(value))  # type: ignore[call-overload]
        elif tag == "s":
            data += _osc_string(str(value))
        else:
            raise ValueError("unsupported OSC type tag %r" % tag)
    return data


def _decode_string(data: bytes, offset: int) -> Tuple[str, int]:
    end = data.index(b"\x00", offset)
    value = data[offset:end].decode("ascii")
    end += 1
    return value, end + (-end % 4)


def decode_osc(data: bytes) -> Tuple[str, str, Tuple[object, ...]]:
    """Decode a single OSC message (type tags ``f``, ``i``, ``s``)."""
    try:
        path, offset = _decode_string(data, 0)
        tags, offset = _decode_string(data, offset)
    except (ValueError, IndexError):
        raise ValueError("truncated OSC message") from None
    if not tags.startswith(","):
        raise ValueError("missing OSC type tag string")
    args: List[object] = []
    try:
        for tag in tags[1:]:
            if tag == "f":
                (value,) = struct.unpack_from(">f", data, offset)
                offset += 4
            elif tag == "i":
                (value,) = struct.unpack_from(">i", data, offset)
                offset += 4
            elif tag == "s":
                value, offset = _decode_string(data, offset)
            else:
                raise ValueError("unsupported OSC type tag %r" % tag)
            args.append(value)
    except (struct.error, IndexError):
        raise ValueError("truncated OSC arguments") from None
    return path, tags[1:], tuple(args)


def iter_osc_messages(datagram: bytes) -> Iterator[bytes]:
    """Yield the OSC messages in a datagram, unwrapping #bundle framing."""
    if datagram.startswith(b"#bundle\x00"):
        offset = 16  # "#bundle\0" plus 8-byte time tag
        while offset + 4 <= len(datagram):
            (size,) = struct.unpack_from(">i", datagram, offset)
            offset += 4
            if size <= 0 or offset + size > len(datagram):
                return
            yield from iter_osc_messages(datagram[offset:offset + size])
            offset += size
    else:
        yield datagram
