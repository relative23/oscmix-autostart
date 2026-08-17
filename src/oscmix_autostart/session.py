"""The session lifecycle: discover, launch, apply, signal, supervise.

This is the only module that composes the others; everything it calls
is testable on its own.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from .config import Config
from .constants import (
    EXIT_FAILURE,
    EXIT_OK,
    PORT_READY_TIMEOUT,
    VERIFIER_STOP_GRACE,
    VERIFY_SETTLE,
)
from .discovery import resolve_binary, udp_port_listening, usb_device_present, wait_for_seq_client
from .log import log
from .notify import sd_notify
from .process import _cleanup_stale_backend, supervise
from .reconcile import desired, plan
from .routing import apply_routing, wait_unless_stopped
from .verify import verify_and_repair


def _print_dry_run(client: int, config: Config) -> None:
    """Show what would be started and sent, in the order it would happen.

    Reads the same plan ``apply_routing`` sends, so the printed sequence
    *is* the sent sequence. It used to walk route by route and print
    link, mix, link, mix -- an order the apply never uses, and the only
    thing CI inspected to guard this project's most expensive bug.

    Both sides moved to ``reconcile.plan`` together, for the same
    reason: the guarantee is that they read one source, not that they
    read a particular one.
    """
    print("would run: alsaseqio %d:1 oscmix" % client)
    for path, types, values in plan(desired(config)).messages():
        print("would send: %s ,%s %s"
              % (path, types, " ".join(map(str, values))))


def _start_backend(client: int, config: Config) -> Optional["subprocess.Popen[bytes]"]:
    """Launch ``alsaseqio <client>:1 oscmix``, or None if a binary is missing."""
    alsaseqio = resolve_binary("alsaseqio", "OSCMIX_BIN_ALSASEQIO")
    backend = resolve_binary("oscmix", "OSCMIX_BIN_BACKEND")
    if alsaseqio is None or backend is None:
        log.error("alsaseqio/oscmix not found -- run install.sh first")
        return None

    # Pass the configured ports through to oscmix -- its compiled-in
    # defaults are 7222/8222 and would silently diverge from routing.conf
    # otherwise. (oscmix-gtk keeps its own port settings; users changing
    # these also need to adjust the GUI's connection settings.)
    command = [alsaseqio, "%d:1" % client, backend,
               "-r", "udp!127.0.0.1!%d" % config.osc_port,
               "-s", "udp!127.0.0.1!%d" % config.osc_recv_port]
    log.info("starting: %s", " ".join(command))
    return subprocess.Popen(command)


def _install_stop_handlers(child: "subprocess.Popen[bytes]",
                           stop_requested: Dict[str, bool]) -> None:
    """Turn SIGTERM/SIGINT into an orderly backend shutdown."""
    def handle_stop(signum: int, _frame: object) -> None:
        stop_requested["stop"] = True
        log.info("received %s; stopping backend", signal.Signals(signum).name)
        sd_notify("STOPPING=1")
        if child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)


def _await_backend_port(child: "subprocess.Popen[bytes]", config: Config,
                        proc_root: Path) -> None:
    """Wait until oscmix binds its OSC port, or the child dies trying."""
    deadline = time.monotonic() + PORT_READY_TIMEOUT
    while time.monotonic() < deadline:
        if udp_port_listening(config.osc_port, proc_root):
            log.info("oscmix is listening on UDP %d", config.osc_port)
            return
        if child.poll() is not None:
            return
        time.sleep(0.25)
    log.warning("oscmix not listening on UDP %d after %.0fs; continuing",
                config.osc_port, PORT_READY_TIMEOUT)


def _apply_and_verify(child: "subprocess.Popen[bytes]", config: Config,
                      stop_requested: Dict[str, bool]
                      ) -> Optional[threading.Thread]:
    """Apply the routing, then verify it in the background.

    One background dump does both jobs: it syncs oscmix's link state
    (which triggers the mix re-apply) and verifies the routing, without
    holding up the readiness signal.

    Returns the verifier thread so ``run_session`` can wait for it to
    stop before exiting. It used to read ``stop_requested`` and
    ``child.poll()`` exactly once, here, before starting -- and then run
    for two verification windows plus a blind delay, writing routing at
    three points, with nobody looking again. See
    docs/decisions/0009-verifier-stop-contract.md.
    """
    if not config.routes:
        log.info("no routes configured; leaving mixer state untouched")
        return None

    apply_routing(config.routes, config.osc_port, config.osc_recv_port)

    def should_stop() -> bool:
        # A dead backend counts as a stop: its port is gone, so every
        # write from here would go nowhere and the log would claim a
        # re-apply that never landed anywhere.
        return stop_requested["stop"] or child.poll() is not None

    def deferred_verify() -> None:
        if wait_unless_stopped(VERIFY_SETTLE, should_stop):
            return
        verify_and_repair(config, should_stop)

    thread = threading.Thread(target=deferred_verify, name="verify",
                              daemon=True)
    thread.start()
    return thread


def _exit_code_for(returncode: int, config: Config, sysfs_usb: Path,
                   stop_requested: Dict[str, bool]) -> int:
    """Translate the backend's exit into the service's exit contract.

    Every clean exit must have signalled READY under Type=notify --
    exiting 0 without it counts as a protocol failure and would put the
    unit into a restart loop. Re-sending READY is harmless.
    """
    if stop_requested["stop"]:
        log.info("backend stopped (shutdown requested)")
    elif not usb_device_present(config.usb_id, sysfs_usb):
        log.info("backend exited (%d): device was disconnected", returncode)
    elif returncode == 0:
        log.info("backend exited cleanly")
    else:
        log.error("backend exited with status %d", returncode)
        return EXIT_FAILURE
    sd_notify("READY=1")
    return EXIT_OK


def run_session(args: argparse.Namespace, config: Config) -> int:
    """Discover the device, run the backend, and supervise it."""
    proc_root = Path(os.environ.get("OSCMIX_PROC_ROOT", "/proc"))
    sysfs_usb = Path(os.environ.get("OSCMIX_SYSFS_USB", "/sys/bus/usb/devices"))

    log.info("waiting for %r (ALSA sequencer, timeout %.0fs)",
             config.device_name, args.timeout)
    client = wait_for_seq_client(config.device_name, args.timeout, proc_root)
    if client is None:
        if not usb_device_present(config.usb_id, sysfs_usb):
            log.info("device %s not connected; nothing to do", config.usb_id)
            sd_notify("READY=1")  # Type=notify: a clean no-op start
            return EXIT_OK
        log.error(
            "USB device %s is connected but no ALSA sequencer client named %r "
            "appeared within %.0fs -- is snd-usb-audio loaded?",
            config.usb_id, config.device_name, args.timeout,
        )
        return EXIT_FAILURE
    log.info("found %r as ALSA sequencer client %d", config.device_name, client)

    if args.dry_run:
        _print_dry_run(client, config)
        return EXIT_OK

    _cleanup_stale_backend(config.osc_port, proc_root)
    child = _start_backend(client, config)
    if child is None:
        return EXIT_FAILURE

    stop_requested = {"stop": False}
    _install_stop_handlers(child, stop_requested)
    _await_backend_port(child, config, proc_root)

    verifier = None
    if child.poll() is None:
        verifier = _apply_and_verify(child, config, stop_requested)
        # The service is "started": backend up, routing applied.
        sd_notify("READY=1")

    returncode = supervise(child, stop_requested)
    _await_verifier(verifier)
    return _exit_code_for(returncode, config, sysfs_usb, stop_requested)


def _await_verifier(verifier: Optional[threading.Thread]) -> None:
    """Do not exit while the verifier may still be writing routing.

    "The mix is never left half-applied" is the property the two-phase
    design exists for, and on the shutdown path nobody used to state it:
    the process exited when ``supervise`` returned and cut the daemon
    thread wherever it happened to be, possibly between two mix writes.

    The verifier checks for a stop between every phase and before every
    write, so once the backend is gone this returns within one socket
    timeout. The grace period is the bound on being wrong about that,
    and it fits inside ``TimeoutStopSec`` alongside ``CHILD_STOP_GRACE``
    -- asserted in ``tests/test_unit_file.py``.
    """
    if verifier is None or not verifier.is_alive():
        return
    verifier.join(timeout=VERIFIER_STOP_GRACE)
    if verifier.is_alive():
        log.warning("verifier still running after %.1fs; exiting anyway",
                    VERIFIER_STOP_GRACE)
