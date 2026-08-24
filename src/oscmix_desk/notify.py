"""systemd readiness notification (Type=notify).

Kept apart from the OSC codec it used to sit beside: the two share
nothing but the word "socket".
"""

from __future__ import annotations

import os
import socket

from .log import log


def sd_notify(state: str) -> None:
    """Best-effort readiness notification for systemd (Type=notify)."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\x00" + address[1:]
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            sock.connect(address)
            sock.sendall(state.encode("ascii"))
        finally:
            sock.close()
    except OSError as exc:
        log.debug("sd_notify(%s) failed: %s", state, exc)
