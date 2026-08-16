"""Finding the device and the backend: ALSA sequencer, USB sysfs, UDP."""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from typing import List, Optional, Tuple

from .log import log

_CLIENT_RE = re.compile(r'^Client\s+(\d+)\s*:\s*"(.*)"', re.MULTILINE)


def parse_seq_clients(text: str) -> List[Tuple[int, str]]:
    """Parse /proc/asound/seq/clients into (client number, name) pairs."""
    return [(int(num), name) for num, name in _CLIENT_RE.findall(text)]


def find_seq_client(text: str, device_name: str) -> Optional[int]:
    for number, name in parse_seq_clients(text):
        if device_name in name:
            return number
    return None


def _trigger_snd_seq_load() -> None:
    """Opening /dev/snd/seq makes the kernel autoload the snd-seq module."""
    device = os.environ.get("OSCMIX_SEQ_DEV", "/dev/snd/seq")
    try:
        os.close(os.open(device, os.O_RDONLY | os.O_NONBLOCK))
    except OSError:
        pass


def wait_for_seq_client(device_name: str, timeout: float,
                        proc_root: Path) -> Optional[int]:
    clients_file = proc_root / "asound" / "seq" / "clients"
    deadline = time.monotonic() + timeout
    while True:
        if clients_file.is_file():
            client = find_seq_client(clients_file.read_text(), device_name)
            if client is not None:
                return client
        else:
            _trigger_snd_seq_load()
        if time.monotonic() >= deadline:
            return None
        time.sleep(1.0)


def usb_device_present(usb_id: str, sysfs_usb: Path) -> bool:
    """Check for a USB device by scanning sysfs (no lsusb dependency)."""
    vendor, product = usb_id.lower().split(":")
    try:
        entries = list(sysfs_usb.iterdir())
    except OSError:
        return False
    for entry in entries:
        try:
            dev_vendor = (entry / "idVendor").read_text().strip().lower()
            dev_product = (entry / "idProduct").read_text().strip().lower()
        except OSError:
            continue
        if dev_vendor == vendor and dev_product == product:
            return True
    return False


def udp_port_listening(port: int, proc_root: Path) -> bool:
    """Check /proc/net/udp{,6} for a socket bound to ``port``."""
    for name in ("udp", "udp6"):
        try:
            lines = (proc_root / "net" / name).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 2 or ":" not in fields[1]:
                continue
            local_port = int(fields[1].rsplit(":", 1)[1], 16)
            if local_port == port:
                return True
    return False


def resolve_binary(name: str, env_var: str) -> Optional[str]:
    """Locate a binary: env override, then PATH, then standard locations.

    The systemd user manager's PATH does not necessarily include
    ~/.local/bin, so the fallback list checks it explicitly.
    """
    override = os.environ.get(env_var)
    if override:
        if os.access(override, os.X_OK):
            return override
        log.error("%s=%s is not an executable file", env_var, override)
        return None
    found = shutil.which(name)
    if found:
        return found
    for directory in (os.path.expanduser("~/.local/bin"),
                      "/usr/local/bin", "/usr/bin"):
        candidate = os.path.join(directory, name)
        if os.access(candidate, os.X_OK):
            return candidate
    return None
