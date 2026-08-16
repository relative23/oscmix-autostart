"""Translating routes into OSC messages, and applying them.

The order is load-bearing: channel links first, mix matrix second.
See docs/OSC-PROTOCOL.md for why."""

from __future__ import annotations

import socket
import struct
import time
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .config import Config, Route
from .constants import (
    DEFAULT_OSC_RECV_PORT,
    LINK_ECHO_TIMEOUT,
    LINK_SETTLE,
    LINK_SYNC_BLIND_DELAY,
    UNLINKED_GAIN_OFFSET,
)
from .log import log
from .osc import decode_osc, encode_osc, iter_osc_messages


def link_messages(route: Route) -> List[Tuple[str, str, Tuple[object, ...]]]:
    """The channel-pair link state a route needs before its mix is written.

    These must reach the device -- and be reported back to oscmix -- before
    any ``/mix`` message of the same route, see ``LINK_ECHO_TIMEOUT``.

    ``stereo = false`` states the link explicitly rather than assuming it:
    the hard-panned pair of ``/mix`` messages it produces is only correct
    against an *unlinked* pair. Applied to a linked one, both messages
    address the same pair register and the second overwrites the first,
    which leaves one half of the pair completely silent.
    """
    if len(route.output) != 2:
        return []
    pb_left, _ = route.playback
    return [
        ("/playback/%d/stereo" % pb_left, "i", (1,)),
        ("/output/%d/stereo" % route.output[0], "i",
         (1 if route.stereo else 0,)),
    ]


def mix_messages(route: Route) -> List[Tuple[str, str, Tuple[object, ...]]]:
    """The mix-matrix and volume writes of a route.

    oscmix folds stereo-linked channels onto the odd (left) channel of a
    pair: a ``/mix`` message addressed to either half of a linked pair
    writes the *same* pair register, and the pan argument acts as the
    pair's balance. Per-channel messages panned hard left/right (the
    TotalMix pattern for unlinked channels) therefore self-overwrite --
    the last message wins and the whole mix ends up panned hard right.
    A pair route instead links the playback and output pairs and writes
    the single pair register with pan 0 (= plain stereo pass-through at
    ``level`` dB).
    """
    messages: List[Tuple[str, str, Tuple[object, ...]]] = []
    if len(route.output) == 2:
        left, right = route.output
        pb_left, _ = route.playback
        if route.stereo:
            messages.append(("/mix/%d/playback/%d" % (left, pb_left), "fi",
                             (route.level, 0)))
        else:
            # Unlinked outputs: feed each side the matching half of the
            # (linked) playback pair via the pair balance. oscmix halves
            # the gain on this path (setlevel(): ll = vol / 2), so the
            # request is raised by 6 dB to make `level` mean the same
            # thing as it does for a linked route -- measured on a UCX II
            # as an exact 6 dB deficit before this compensation.
            unlinked = min(route.level, 0.0) + UNLINKED_GAIN_OFFSET
            messages.append(("/mix/%d/playback/%d" % (left, pb_left), "fi",
                             (unlinked, -100)))
            messages.append(("/mix/%d/playback/%d" % (right, pb_left), "fi",
                             (unlinked, 100)))
        if route.volume is not None:
            for out in (left, right):
                messages.append(("/output/%d/volume" % out, "f", (route.volume,)))
    else:
        (out,) = route.output
        (pb,) = route.playback
        messages.append(("/mix/%d/playback/%d" % (out, pb), "fi", (route.level, 0)))
        if route.volume is not None:
            messages.append(("/output/%d/volume" % out, "f", (route.volume,)))
    return messages


def route_messages(route: Route) -> List[Tuple[str, str, Tuple[object, ...]]]:
    """Every OSC message a route consists of, in dependency order."""
    return link_messages(route) + mix_messages(route)


def await_link_echo(expected: Mapping[str, int], recv_port: int,
                    timeout: Optional[float] = None) -> Optional[bool]:
    """Wait until oscmix reports every register in ``expected`` at its value.

    ``expected`` maps an OSC path to the integer the device has to report
    for it. The report is what actually updates oscmix's internal link
    state, so this -- not a fixed sleep -- is the correct barrier before
    writing the mix matrix. The value matters: an unlinked route waits for
    0 just as a linked one waits for 1, and a stale report of the opposite
    value must not end the wait.

    Returns True when everything arrived, False on timeout, and None when
    the receive port is unavailable (the mixer GUI holds it), in which
    case the caller falls back to a plain wait.
    """
    if not expected:
        return True
    if timeout is None:
        timeout = LINK_ECHO_TIMEOUT
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # No SO_REUSEADDR on purpose: a bind that succeeds alongside the
        # mixer GUI would split oscmix's datagrams between both readers.
        sock.bind(("127.0.0.1", recv_port))
    except OSError:
        return None
    pending = dict(expected)
    deadline = time.monotonic() + timeout
    try:
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            sock.settimeout(remaining)
            try:
                datagram, _ = sock.recvfrom(65536)
            except socket.timeout:
                return False
            except OSError:
                return False
            for message in iter_osc_messages(datagram):
                try:
                    path, _tags, args = decode_osc(message)
                except (ValueError, struct.error):
                    continue
                if path not in pending or not args:
                    continue
                try:
                    reported = int(args[0])  # type: ignore[call-overload]
                except (TypeError, ValueError):
                    continue
                if reported == pending[path]:
                    del pending[path]
        return True
    finally:
        sock.close()


def apply_routing(routes: Sequence[Route], port: int,
                  recv_port: int = DEFAULT_OSC_RECV_PORT) -> None:
    """Send the routing in two phases: link the pairs, then fill the mix.

    Both phases are separated by the link barrier above. Sending them in
    one burst is what silences every even output (see LINK_ECHO_TIMEOUT).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Only the output links need the barrier: /playback/<n>/stereo goes
        # through setinputstereo(), which updates oscmix's state right away,
        # while /output/<n>/stereo relies on the device report.
        for route in routes:
            for path, types, args in link_messages(route):
                sock.sendto(encode_osc(path, types, *args), ("127.0.0.1", port))

        timeout = LINK_ECHO_TIMEOUT
        echoed = await_link_echo(output_link_state(routes), recv_port, timeout)
        if echoed is None:
            log.info("link echo unobservable (UDP %d in use); waiting %.1fs",
                     recv_port, LINK_SETTLE)
            time.sleep(LINK_SETTLE)
        elif not echoed:
            # Normal when the pairs were already linked: no change, no echo.
            log.info("no link change reported within %.1fs; mix matrix will "
                     "be re-applied after the register sync", timeout)
        else:
            log.info("channel pairs linked and confirmed by the device")

        for route in routes:
            for path, types, args in mix_messages(route):
                sock.sendto(encode_osc(path, types, *args), ("127.0.0.1", port))
            log.info(
                "route %r: playback %s -> output %s at %+.1f dB",
                route.name,
                "/".join(map(str, route.playback)),
                "/".join(map(str, route.output)),
                route.level,
            )
    finally:
        sock.close()


def output_link_state(routes: Sequence[Route]) -> Dict[str, int]:
    """The ``/output/<n>/stereo`` values a routing depends on.

    Maps each register to the value the device has to report before the
    mix matrix may be written. Routes are applied in file order, so a
    later route targeting the same pair wins -- the same rule the mix
    writes follow.
    """
    state: Dict[str, int] = {}
    for route in routes:
        for path, _types, args in link_messages(route):
            if path.startswith("/output/"):
                state[path] = int(args[0])  # type: ignore[call-overload]
    return state


def send_mix(config: Config) -> None:
    """Write the mix matrix (and output volumes) of every route."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for route in config.routes:
            for path, types, args in mix_messages(route):
                sock.sendto(encode_osc(path, types, *args),
                            ("127.0.0.1", config.osc_port))
    finally:
        sock.close()
    log.info("mix matrix re-applied against the synchronized link state")


def blind_reapply_mix(config: Config) -> None:
    """Re-apply the mix when the device dump cannot be observed.

    The mixer GUI holds the receive port, so the link reports are
    invisible; ``/refresh`` still has to go out because that dump is what
    teaches oscmix the device's real link state, and the wait afterwards
    is a plain guess at how long it takes.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(encode_osc("/refresh"), ("127.0.0.1", config.osc_port))
    finally:
        sock.close()
    log.info("register sync unobservable (UDP %d in use); re-applying mix "
             "after %.0fs", config.osc_recv_port, LINK_SYNC_BLIND_DELAY)
    time.sleep(LINK_SYNC_BLIND_DELAY)
    send_mix(config)
