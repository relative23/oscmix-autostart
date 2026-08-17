"""Reading the applied routing back from the device."""

from __future__ import annotations

import socket
import struct
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from .config import Config, Route
from .constants import VERIFY_SETTLE, VERIFY_TIMEOUT
from .log import log
from .osc import decode_osc, encode_osc, iter_osc_messages
from .reconcile import desired
from .routing import (
    StopCheck,
    apply_routing,
    blind_reapply_mix,
    never_stop,
    output_link_state,
    send_mix,
    wait_unless_stopped,
)

# One expected register: its OSC type tags and the arguments it must
# report back. Keyed by OSC path.
Registers = Dict[str, Tuple[str, Tuple[object, ...]]]


def expected_registers(routes: Sequence[Route]) -> Registers:
    """The register state the routes should produce, keyed by OSC path.

    This is ``reconcile.desired`` projected to the shape the read-back
    has always used. Delegating rather than keeping a second walk of the
    same routes is the first thing the reconciler is load-bearing for --
    on the *reading* side, which is where a mistake is a wrong verdict
    rather than a wrong device state.

    ``tests/test_reconcile.py`` asserts the two agree for every config
    shape in its table, so this cannot drift back apart quietly.
    """
    return {entry.path: (entry.tags, entry.args)
            for entry in desired(Config(routes=list(routes)))}


def _register_matches(want_types: str, want_args: Sequence[object],
                      got_args: Sequence[object]) -> bool:
    """Compare a reported register against the expected value.

    Floats get a 0.5 dB tolerance (the device quantizes levels); extra
    trailing arguments in the report are ignored so a richer upstream
    dump format cannot break verification.
    """
    if len(got_args) < len(want_args):
        return False
    for tag, want, got in zip(want_types, want_args, got_args):
        try:
            if tag == "f":
                if abs(float(want) - float(got)) > 0.5:  # type: ignore[arg-type]
                    return False
            elif int(want) != int(got):  # type: ignore[call-overload]
                return False
        except (TypeError, ValueError):
            return False
    return True


def register_promptly_reported(path: str) -> bool:
    """Whether a register is expected early in a /refresh dump.

    This is a hint, not a filter: every register that *does* appear in
    the dump is compared, whatever this function says. It steers two
    things only -- the early-exit condition of the observation window,
    and whether an *absent* register counts as a problem (promptly
    reported but missing = probably lost, worth a re-send) or as merely
    unverifiable (logged as information).

    Two families are not promptly reported, both measured against the
    real device: upstream dumps the input mix matrix
    (``/mix/<out>/input/<in>``, oscmix.c) but not the playback mix
    matrix, so ``/mix/*/playback/*`` never appears at all; and the
    ``/playback/*`` section sits near the end of a dump that streams
    several thousand messages over MIDI for many seconds. The
    ``/output/*`` registers -- the audible signal path -- arrive early
    and verify reliably.
    """
    if path.startswith("/mix/") and "/playback/" in path:
        return False
    if path.startswith("/playback/"):  # noqa: SIM103 -- one branch per family
        return False
    return True


@dataclass
class VerifyResult:
    """Per-register outcome of a routing read-back."""

    confirmed: List[str]
    mismatched: List[str]
    unobserved: List[str]


def _absorb_dump(datagram: bytes, registers: Registers,
                 confirmed: Set[str], mismatched: Set[str],
                 on_observed: Optional[Callable[[str, Sequence[object]],
                                                None]]) -> None:
    """Classify every register in one datagram of the device dump.

    A datagram may be a bundle, so this is per datagram rather than per
    message. Malformed messages are skipped rather than raised on: this
    reads off a socket, and one bad message must not end a dump that is
    otherwise confirming registers.
    """
    for message in iter_osc_messages(datagram):
        try:
            path, _tags, args = decode_osc(message)
        except (ValueError, struct.error):
            continue
        if on_observed is not None:
            on_observed(path, args)
        expected = registers.get(path)
        if expected is None or path in confirmed:
            continue
        if _register_matches(expected[0], expected[1], args):
            confirmed.add(path)
            mismatched.discard(path)
        else:
            mismatched.add(path)


def verify_routing(registers: Registers, send_port: int, recv_port: int,
                   timeout: float = VERIFY_TIMEOUT,
                   on_observed: Optional[Callable[[str, Sequence[object]],
                                                  None]] = None,
                   should_stop: StopCheck = never_stop
                   ) -> Optional[VerifyResult]:
    """Ask oscmix to dump its state and compare it against ``registers``.

    Returns ``None`` when verification is impossible (the receive port is
    taken, normally because the mixer GUI is listening there), otherwise
    a :class:`VerifyResult` classifying every expected register as
    confirmed (reported with a matching value), mismatched (reported
    with a different value -- a later matching report overrides), or
    unobserved (never reported within the window).

    ``on_observed`` is called with each register path and its reported
    arguments the moment it is
    first reported. That is how the mix re-apply hooks into this dump
    instead of requesting a second one: two overlapping dumps measurably
    starve each other and confirm fewer registers.
    """
    confirmed: Set[str] = set()
    mismatched: Set[str] = set()
    prompt = {path for path in registers if register_promptly_reported(path)}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        try:
            sock.bind(("127.0.0.1", recv_port))
        except OSError:
            return None
        sock.settimeout(0.25)
        sock.sendto(encode_osc("/refresh"), ("127.0.0.1", send_port))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # A stop request ends the window at the top of the loop, so
            # the longest this can hold the shutdown is one socket
            # timeout (0.25 s). What has been observed so far is
            # returned rather than discarded -- the caller decides
            # whether to act on it, and it will not.
            if should_stop():
                break
            # Exit early only while nothing is mismatched: a mismatch
            # keeps the window open so a later correcting report (stale
            # value echoed during settling) can still override it.
            if not mismatched:
                if len(confirmed) == len(registers):
                    break  # every register observed and matching
                if prompt and prompt <= confirmed:
                    break  # the reliably-reported set fully matches
            try:
                datagram, _ = sock.recvfrom(65536)
            except socket.timeout:
                continue
            _absorb_dump(datagram, registers, confirmed, mismatched,
                         on_observed)
        unobserved = [path for path in registers
                      if path not in confirmed and path not in mismatched]
        return VerifyResult(sorted(confirmed), sorted(mismatched),
                            sorted(unobserved))
    finally:
        sock.close()


def _link_sync_observer(config: Config, pending_links: Dict[str, int],
                        reapplied: Dict[str, bool], should_stop: StopCheck
                        ) -> Callable[[str, Sequence[object]], None]:
    """Watch the dump for the link state, and re-apply the mix once it lands.

    This is the point of sharing one ``/refresh`` between verification
    and the re-apply (ADR 0002): the moment the dump has reported every
    ``/output/<n>/stereo`` at its expected value, oscmix's own link state
    is correct and the mix matrix can be written from a known-good state.
    Requesting a second dump for it measurably starves both.

    ``pending_links`` and ``reapplied`` are mutated in place; they are
    the caller's, because the caller still needs to know afterwards
    whether the re-apply happened.
    """
    def on_observed(path: str, args: Sequence[object]) -> None:
        # Only a report of the *expected* link value means oscmix's state
        # is right; a stale opposite value must not release the re-apply.
        if path in pending_links and args:
            try:
                reported = int(args[0])  # type: ignore[call-overload]
            except (TypeError, ValueError):
                return
            if reported != pending_links[path]:
                return
            del pending_links[path]
        if not pending_links and not reapplied["done"]:
            # Write 1 of 3 (ADR 0009). Reached from inside the dump
            # observation, so the verify loop's own stop check has not
            # run since this datagram arrived.
            if should_stop():
                return
            reapplied["done"] = True
            send_mix(config)

    return on_observed


def _reapply_without_confirmation(config: Config,
                                  pending_links: Dict[str, int],
                                  reapplied: Dict[str, bool]) -> None:
    """Write 2 of 3: the dump ended without ever reporting the links.

    The device reports a register only when it *changes*, so a pair that
    was already linked produces no report however long the window is.
    Writing the mix anyway is correct in that case and harmless in the
    other; leaving it unwritten would strand the routing on whatever the
    foreground apply managed before the barrier.
    """
    reapplied["done"] = True
    log.warning("dump never reported %s; re-applying mix anyway",
                ", ".join(sorted(pending_links)))
    send_mix(config)


def _unconfirmed(result: VerifyResult) -> List[str]:
    """The registers that count as a problem worth re-sending for.

    Mismatched always counts. Absent counts only for the families the
    dump reports promptly -- ``/mix/*/playback/*`` never appears at all,
    so treating its absence as a problem would put every run into a
    retry it cannot win.
    """
    lost = [path for path in result.unobserved
            if register_promptly_reported(path)]
    return sorted(result.mismatched + lost)


def verify_and_repair(config: Config,
                      should_stop: StopCheck = never_stop) -> None:
    """Read the applied routing back and re-send once on problems.

    A register is a *problem* when the device reported a different value
    (mismatched) or when a promptly-reported register never appeared
    (probably lost). Registers the dump is known not to report in time
    are logged as information, never as a warning -- but if one of them
    does appear, it is compared like any other, so a future oscmix that
    dumps more (or different) registers is handled without code changes.

    Verification is advisory: OSC over UDP has no delivery guarantee, so
    a failed read-back is logged (and retried once) but never brings the
    service down -- a restart loop would not improve anything.

    The dump this requests doubles as the link-state sync -- see
    ``_link_sync_observer``. The mix matrix itself is unverifiable (a
    ``/mix`` write draws no reply and the dump omits the playback
    matrix), so it is re-established rather than checked.

    ``should_stop`` is asked between every phase and before each of the
    three writes below, and the session waits for this thread before
    exiting: docs/decisions/0009-verifier-stop-contract.md.
    """
    registers = expected_registers(config.routes)
    pending_links = output_link_state(config.routes)
    reapplied = {"done": not pending_links}
    on_observed = _link_sync_observer(config, pending_links, reapplied,
                                      should_stop)

    problems: List[str] = []
    for attempt in (1, 2):
        if should_stop():
            return
        result = verify_routing(registers, config.osc_port,
                                config.osc_recv_port, VERIFY_TIMEOUT,
                                on_observed=on_observed,
                                should_stop=should_stop)
        if should_stop():
            return
        if result is None:
            log.info("routing verification skipped: UDP %d in use "
                     "(mixer GUI running?)", config.osc_recv_port)
            blind_reapply_mix(config, should_stop)
            return
        if not reapplied["done"]:
            _reapply_without_confirmation(config, pending_links, reapplied)
        problems = _unconfirmed(result)
        if not problems:
            log.info("routing verified against device state "
                     "(%d confirmed; %d not reported by the device dump)%s",
                     len(result.confirmed), len(result.unobserved),
                     "" if attempt == 1 else " -- after retry")
            return
        if attempt == 1:
            # Write 3 of 3, and the only full re-apply. Both phases of it
            # would run against a terminating backend.
            if should_stop():
                return
            log.warning("%d register(s) unconfirmed (%s); re-sending routing",
                        len(problems), ", ".join(problems))
            apply_routing(config.routes, config.osc_port,
                          config.osc_recv_port)
            if wait_unless_stopped(VERIFY_SETTLE, should_stop):
                return
    log.warning("unconfirmed after retry: %s", ", ".join(problems))
