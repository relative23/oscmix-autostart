"""Argument parsing and the process entry point."""

from __future__ import annotations

import logging
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Optional, Sequence

from .config import discover_config_path, load_config
from .constants import DEFAULT_DEVICE_TIMEOUT, EXIT_CONFIG, EXIT_OK, __version__
from .errors import ConfigError
from .log import log
from .pipewire import generate_pipewire_conf, pw_sink_info
from .session import run_session


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
    parser.add_argument("--pipewire-sinks", action="store_true",
                        help="print a PipeWire config with one named sink "
                             "per stereo route, then exit")
    parser.add_argument("--pipewire-target", metavar="NODE",
                        help="Fireface sink node.name for --pipewire-sinks "
                             "(default: auto-detect via pw-dump)")
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
