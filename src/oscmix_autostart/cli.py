"""Argument parsing and the process entry point."""

from __future__ import annotations

import logging
import sys
import time
from argparse import ArgumentParser
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from .backend import loopback
from .config import Config, discover_config_path, load_config
from .constants import (
    DEFAULT_DEVICE_TIMEOUT,
    EXIT_CONFIG,
    EXIT_FAILURE,
    EXIT_OK,
    __version__,
)
from .errors import ConfigError
from .log import log
from .pipewire import generate_pipewire_conf, pw_sink_info
from .profiles import REFUSED, describe_profiles, switch_profile
from .reconcile import (
    channels_from_observed,
    observed,
    render_config,
    routes_from_observed,
)
from .registers import device_for_name
from .session import run_session

#: How long --dump-config listens for the device's reply. The dump is
#: over in ~2 s on a UCX II (tests/data/cold-plug-timeline.json); this is
#: several times that so a slower device is not truncated, and it costs
#: nothing on a fast one because the read stops when the window ends.
DUMP_READ_SECONDS = 8.0

#: Stop early once no *new* register has arrived for this long.
DUMP_QUIET_SECONDS = 1.0


def build_arg_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="oscmix-session",
        description="Supervise the oscmix backend for an RME Fireface interface.",
    )
    parser.add_argument("--config", type=Path, metavar="FILE",
                        help="routing config (default: ~/.config/oscmix/routing.conf)")
    parser.add_argument("--device", metavar="NAME",
                        help="ALSA client name to wait for (overrides config)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_DEVICE_TIMEOUT,
                        metavar="SECONDS", help="how long to wait for the device")
    parser.add_argument("--osc-port", type=int, metavar="PORT",
                        help="UDP port oscmix listens on (overrides config)")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would be started and sent, then exit")
    parser.add_argument("--dump-config", action="store_true",
                        help="ask the running device for its state and print "
                             "a routing.conf that reproduces what it reports")
    parser.add_argument("--pipewire-sinks", action="store_true",
                        help="print a PipeWire config with one named sink "
                             "per stereo route, then exit")
    parser.add_argument("--pipewire-target", metavar="NODE",
                        help="Fireface sink node.name for --pipewire-sinks "
                             "(default: auto-detect via pw-dump)")
    parser.add_argument("--profile", metavar="NAME",
                        help="switch the desk to profiles/NAME.conf and "
                             "report the outcome, then exit")
    parser.add_argument("--list-profiles", action="store_true",
                        help="list the profiles found beside the config")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    config_path = args.config or discover_config_path()
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        log.error("configuration error: %s", exc)
        return EXIT_CONFIG
    if config_path is None:
        log.info("no routing.conf found; using defaults without routing")
    else:
        log.info("configuration: %s (%d route(s))", config_path, len(config.routes))

    if args.device:
        config.device_name = args.device
    if args.osc_port:
        config.osc_port = args.osc_port

    if args.list_profiles:
        for line in describe_profiles(config_path):
            sys.stdout.write(line + "\n")
        return EXIT_OK

    if args.profile:
        return _switch_profile(args.profile, config_path)

    if args.dump_config:
        return _dump_config(config)

    if args.pipewire_sinks:
        target, positions = args.pipewire_target, None
        info = pw_sink_info(config.device_name, target=target)
        if info:
            target, positions = info
            log.info("target sink %s (%s channel layout)", target,
                     "%d-channel" % len(positions) if positions else "unknown")
        elif target is None:
            log.warning("could not auto-detect the Fireface sink via pw-dump; "
                        "replace the FIXME target in the output "
                        "('wpctl status' shows the sink name)")
        try:
            sys.stdout.write(generate_pipewire_conf(config, target, positions))
        except ConfigError as exc:
            log.error("%s", exc)
            return EXIT_CONFIG
        return EXIT_OK

    return run_session(args, config)


def _switch_profile(name: str, config_path: Optional[Path]) -> int:
    """Apply a profile and turn its outcome into an exit code.

    Three states, three codes, and the distinction the caller needs is
    between "nothing happened" and "something happened that I could not
    check" -- a script that treats those the same will re-run a switch
    that already took effect.

    EXIT_CONFIG for a refusal is the same code a bad routing.conf gives
    at startup, because it is the same failure: the config did not parse
    and nothing was written.
    """
    outcome = switch_profile(name, config_path=config_path)
    sys.stdout.write(outcome.describe() + "\n")
    if outcome.state == REFUSED:
        return EXIT_CONFIG
    return EXIT_OK


def _dump_config(config: Config) -> int:
    """Print a routing.conf built from what the device reports.

    Needs a running backend: this reads the device rather than the
    config it was started from. An empty read is a failure and says so
    -- printing an empty config would look like "you have no routing"
    when it means "nobody answered", and the two call for opposite
    responses.
    """
    device = loopback(config.osc_port, config.osc_recv_port)
    listener = device.listen()
    if listener is None:
        log.error("UDP %d is in use -- close the mixer GUI; its meters and "
                  "this read would split the device's replies",
                  config.osc_recv_port)
        return EXIT_FAILURE

    seen: Dict[str, Tuple[object, ...]] = {}
    try:
        device.request_dump()
        deadline = time.monotonic() + DUMP_READ_SECONDS
        quiet_after = deadline
        while time.monotonic() < deadline:
            fresh = False
            for path, _tags, args in listener.messages(0.25):
                if path not in seen:
                    fresh = True
                seen.setdefault(path, tuple(args))
            if fresh:
                # Stop once the dump goes quiet rather than always
                # waiting out the window: it is over in ~2 s on a UCX II,
                # and a command that takes 8 s regardless invites being
                # interrupted halfway. The level meters keep streaming,
                # so "quiet" means no register we had not already seen.
                quiet_after = time.monotonic() + DUMP_QUIET_SECONDS
            elif seen and time.monotonic() > quiet_after:
                break
    finally:
        listener.close()

    if not seen:
        log.error("no reply from the backend on UDP %d -- is oscmix running?",
                  config.osc_recv_port)
        return EXIT_FAILURE

    model = device_for_name(config.device_name)
    dumped = Config(device_name=config.device_name, usb_id=config.usb_id,
                    osc_port=config.osc_port,
                    osc_recv_port=config.osc_recv_port,
                    routes=list(routes_from_observed(observed(seen))),
                    channels=list(channels_from_observed(seen, model)))
    log.info("read %d registers; %d input route(s) and %d channel "
             "setting(s) reconstructed",
             len(seen), len(dumped.routes), len(dumped.channels))
    sys.stdout.write(render_config(dumped, model))
    return EXIT_OK
