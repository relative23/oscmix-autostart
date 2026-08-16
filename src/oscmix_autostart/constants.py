"""Shared constants and environment overrides.

Values live next to nothing else on purpose: every module may import
this one, so it must never import back."""

from __future__ import annotations

import math
import os

__version__ = "0.2.0"

DEFAULT_DEVICE_NAME = "Fireface UCX II"
DEFAULT_USB_ID = "2a39:3fd9"
DEFAULT_OSC_PORT = 7222
DEFAULT_OSC_RECV_PORT = 8222
DEFAULT_DEVICE_TIMEOUT = 30.0
PORT_READY_TIMEOUT = 10.0
CHILD_STOP_GRACE = float(os.environ.get("OSCMIX_STOP_GRACE", "5"))
# The full /refresh dump is several thousand MIDI-SysEx-backed messages
# and takes a few seconds on a 20-channel interface; the loop exits early
# once every expected register is confirmed, so a generous window only
# costs time in the mismatch case.
VERIFY_TIMEOUT = 10.0
VERIFY_SETTLE = 0.5
# oscmix only learns that an output pair is stereo-linked when the *device*
# echoes /output/<n>/stereo back over MIDI (newoutputstereo() in oscmix.c);
# the OSC setter is a plain setbool that forwards the register and leaves
# oscmix's own state untouched. A /mix write that overtakes that echo is
# evaluated against the stale flag, takes the unlinked branch in setlevel()
# and never writes the pair's right channel -- every even output stays
# silent. Link messages therefore go out first, and the mix matrix only
# after the echo arrived (or LINK_SETTLE elapsed, when nobody can listen).
#
# The echo only fires on an actual *change*: writing stereo=1 to a pair
# the device already has linked changes nothing and stays silent. The
# barrier below is therefore opportunistic -- short, and a timeout is
# normal rather than an error. What closes the gap for good is that
# oscmix reports every register once its initial sync completes (measured
# on a UCX II: /output/1..12/stereo arrive ~15 s after start, far too late
# to block readiness on). So the mix is written twice: immediately, so
# audio works, and again after that sync, when oscmix's link state is
# guaranteed correct.
LINK_ECHO_TIMEOUT = float(os.environ.get("OSCMIX_LINK_TIMEOUT", "1.5"))
LINK_SETTLE = float(os.environ.get("OSCMIX_LINK_SETTLE", "1.5"))
# Used when the receive port is taken and the sync cannot be observed.
LINK_SYNC_BLIND_DELAY = float(os.environ.get("OSCMIX_LINK_SYNC_DELAY", "20"))

LEVEL_MIN, LEVEL_MAX = -65.0, 6.0
# An unlinked pair route reaches oscmix's setlevel() branch that halves the
# gain (ll = vol / 2), so its request is raised by 6.02 dB to make `level`
# mean the same thing on both paths. oscmix clamps the gain it derives at
# 2.0 -- exactly this offset -- so an unlinked route cannot be pushed above
# unity: positive `level` values saturate instead of scaling.
UNLINKED_GAIN_OFFSET = 20.0 * math.log10(2.0)
CHANNEL_MIN, CHANNEL_MAX = 1, 64

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CONFIG = 2

# The pause _cleanup_stale_backend takes after signalling a leftover
# backend, so the port it held is free before the new one binds.
STALE_BACKEND_SETTLE = 0.5


def startup_budget(device_timeout: float = DEFAULT_DEVICE_TIMEOUT) -> float:
    """Worst-case seconds from process start to ``READY=1``.

    Eight waits govern this path and two systemd deadlines have to
    contain it. The relationship used to live in a comment in the unit
    file, where nothing checked it and `--timeout` -- a command-line
    argument in `ExecStart` -- could push the start past
    `TimeoutStartSec` and have the unit killed *mid-apply*. That is a
    torn routing state reached by editing a number.

    The terms, in the order `run_session` reaches them:

    * ``device_timeout``    -- ``wait_for_seq_client``
    * ``STALE_BACKEND_SETTLE`` -- ``_cleanup_stale_backend``
    * ``PORT_READY_TIMEOUT``   -- ``_await_backend_port``
    * the link barrier      -- ``LINK_ECHO_TIMEOUT`` when the receive
      port is observable, ``LINK_SETTLE`` when the mixer GUI holds it.
      Never both, so the worst case is the larger.

    Verification is deliberately *not* in here: it runs on a daemon
    thread after ``READY=1``, which is the whole point of deferring it.
    """
    return (device_timeout
            + STALE_BACKEND_SETTLE
            + PORT_READY_TIMEOUT
            + max(LINK_ECHO_TIMEOUT, LINK_SETTLE))
