"""Backend process supervision: stale cleanup and stop escalation."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from .constants import CHILD_STOP_GRACE
from .discovery import udp_port_listening
from .log import log


def find_stale_backends(proc_root: Path) -> List[int]:
    """PIDs of oscmix processes owned by this user.

    Matches the kernel comm name (what ``pkill -x`` used) as well as the
    argv0 basename, so a rewritten or empty cmdline cannot hide a stale
    backend.
    """
    pids = []
    uid = os.getuid()
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            owned = entry.stat().st_uid == uid
        except OSError:
            continue  # the process is gone, or its ownership is unreadable
        if not owned:
            continue
        try:
            comm = (entry / "comm").read_text().strip()
        except OSError:
            comm = ""
        try:
            argv0 = (entry / "cmdline").read_bytes().split(b"\x00", 1)[0]
        except OSError:
            argv0 = b""
        if comm == "oscmix" or \
                os.path.basename(argv0.decode("utf-8", "replace")) == "oscmix":
            pids.append(int(entry.name))
    return sorted(pids)


def _cleanup_stale_backend(port: int, proc_root: Path) -> None:
    """A stale oscmix (e.g. from a manual run) would hold the OSC port."""
    if not udp_port_listening(port, proc_root):
        return
    pids = find_stale_backends(proc_root)
    if not pids:
        log.warning("UDP port %d is in use by an unknown process; "
                    "oscmix may fail to bind it", port)
        return
    log.warning("UDP port %d already in use; terminating stale oscmix (pid %s)",
                port, ", ".join(map(str, pids)))
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    time.sleep(0.5)


def supervise(child: "subprocess.Popen[bytes]",
              stop_requested: Dict[str, bool]) -> int:
    """Wait for the child; escalate SIGTERM -> SIGKILL on shutdown."""
    kill_deadline: Optional[float] = None
    while True:
        try:
            return child.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
        if stop_requested["stop"]:
            now = time.monotonic()
            if kill_deadline is None:
                kill_deadline = now + CHILD_STOP_GRACE
            elif now >= kill_deadline:
                log.warning("backend ignored SIGTERM; sending SIGKILL")
                child.kill()
                return child.wait()
