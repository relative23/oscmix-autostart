"""routing.conf: the Route/Config model and its parser.

Parsing is total -- every input yields a Config or a ConfigError that
names the section and option, never a traceback."""

from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .constants import (
    CHANNEL_MAX,
    CHANNEL_MIN,
    DEFAULT_DEVICE_NAME,
    DEFAULT_OSC_PORT,
    DEFAULT_OSC_RECV_PORT,
    DEFAULT_USB_ID,
    LEVEL_MAX,
    LEVEL_MIN,
)
from .errors import ConfigError
from .log import log
from .registers import device_for_name


@dataclass(frozen=True)
class Route:
    """One playback -> hardware output route (mono or a stereo pair)."""

    name: str
    playback: Tuple[int, ...]
    output: Tuple[int, ...]
    level: float = 0.0
    volume: Optional[float] = None
    stereo: bool = True


@dataclass
class Config:
    device_name: str = DEFAULT_DEVICE_NAME
    usb_id: str = DEFAULT_USB_ID
    osc_port: int = DEFAULT_OSC_PORT
    osc_recv_port: int = DEFAULT_OSC_RECV_PORT
    routes: List[Route] = field(default_factory=list)


def discover_config_path() -> Optional[Path]:
    """Return the first existing config file in the search order."""
    env = os.environ.get("OSCMIX_CONFIG")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    for candidate in (Path(xdg) / "oscmix" / "routing.conf",
                      Path("/etc/oscmix/routing.conf")):
        if candidate.is_file():
            return candidate
    return None


def _parse_channels(raw: str, section: str, option: str) -> Tuple[int, ...]:
    """Parse ``1/2`` (stereo pair) or ``3`` (mono) into a channel tuple."""
    parts = [p.strip() for p in raw.split("/")]
    if len(parts) not in (1, 2) or not all(parts):
        raise ConfigError(
            "[%s] %s: expected a channel ('3') or a pair ('1/2'), got %r"
            % (section, option, raw)
        )
    channels = []
    for part in parts:
        try:
            value = int(part)
        except ValueError:
            raise ConfigError(
                "[%s] %s: %r is not a channel number" % (section, option, part)
            ) from None
        if not CHANNEL_MIN <= value <= CHANNEL_MAX:
            raise ConfigError(
                "[%s] %s: channel %d out of range %d..%d"
                % (section, option, value, CHANNEL_MIN, CHANNEL_MAX)
            )
        channels.append(value)
    return tuple(channels)


def _parse_db(raw: str, section: str, option: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(
            "[%s] %s: %r is not a dB value" % (section, option, raw)
        ) from None
    if not LEVEL_MIN <= value <= LEVEL_MAX:
        raise ConfigError(
            "[%s] %s: %.1f dB out of range %.0f..%.0f"
            % (section, option, value, LEVEL_MIN, LEVEL_MAX)
        )
    return value


def _parse_bool(raw: str, section: str, option: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in ("1", "yes", "true", "on"):
        return True
    if lowered in ("0", "no", "false", "off"):
        return False
    raise ConfigError("[%s] %s: %r is not a boolean" % (section, option, raw))


_KNOWN_OPTIONS = {
    "device": {"name", "usb-id"},
    "osc": {"port", "recv-port"},
    "route": {"playback", "output", "level", "volume", "stereo"},
}


def _check_options(section: str, kind: str, options: Sequence[str]) -> None:
    unknown = set(options) - _KNOWN_OPTIONS[kind]
    if unknown:
        raise ConfigError(
            "[%s]: unknown option(s) %s (valid: %s)"
            % (section, ", ".join(sorted(unknown)),
               ", ".join(sorted(_KNOWN_OPTIONS[kind])))
        )


def _parse_route(parser: configparser.ConfigParser, section: str) -> Route:
    name = section.split(":", 1)[1].strip() or section
    _check_options(section, "route", parser.options(section))
    for required in ("playback", "output"):
        if not parser.has_option(section, required):
            raise ConfigError("[%s]: missing required option %r" % (section, required))
    playback = _parse_channels(parser.get(section, "playback"), section, "playback")
    output = _parse_channels(parser.get(section, "output"), section, "output")
    if len(playback) != len(output):
        raise ConfigError(
            "[%s]: playback (%s) and output (%s) must both be mono or both be a pair"
            % (section, parser.get(section, "playback"), parser.get(section, "output"))
        )
    level = 0.0
    if parser.has_option(section, "level"):
        level = _parse_db(parser.get(section, "level"), section, "level")
    volume = None
    if parser.has_option(section, "volume"):
        volume = _parse_db(parser.get(section, "volume"), section, "volume")
    stereo = True
    if parser.has_option(section, "stereo"):
        stereo = _parse_bool(parser.get(section, "stereo"), section, "stereo")
    return Route(name=name, playback=playback, output=output,
                 level=level, volume=volume, stereo=stereo)


def load_config(path: Optional[Path]) -> Config:
    """Load routing.conf. ``path=None`` returns built-in defaults."""
    config = Config()
    if path is None:
        return config
    if not path.is_file():
        raise ConfigError("config file not found: %s" % path)

    parser = configparser.ConfigParser(
        interpolation=None, inline_comment_prefixes=("#", ";")
    )
    try:
        with open(path, encoding="utf-8") as handle:
            parser.read_file(handle)
    except (configparser.Error, OSError) as exc:
        raise ConfigError("cannot read %s: %s" % (path, exc)) from None

    for section in parser.sections():
        if section == "device":
            _check_options(section, "device", parser.options(section))
            config.device_name = parser.get(section, "name",
                                            fallback=config.device_name).strip()
            usb_id = parser.get(section, "usb-id", fallback=config.usb_id).strip()
            if not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}", usb_id):
                raise ConfigError(
                    "[device] usb-id: expected 'vvvv:pppp' hex format, got %r" % usb_id
                )
            config.usb_id = usb_id.lower()
        elif section == "osc":
            _check_options(section, "osc", parser.options(section))
            for option, attr in (("port", "osc_port"),
                                 ("recv-port", "osc_recv_port")):
                raw = parser.get(section, option, fallback=str(getattr(config, attr)))
                try:
                    port = int(raw)
                except ValueError:
                    raise ConfigError(
                        "[osc] %s: %r is not a port number" % (option, raw)
                    ) from None
                if not 1 <= port <= 65535:
                    raise ConfigError(
                        "[osc] %s: %d out of range 1..65535" % (option, port)
                    )
                setattr(config, attr, port)
        elif section.startswith("route:"):
            config.routes.append(_parse_route(parser, section))
        else:
            # A warning, not an error. See
            # docs/decisions/0006-routing-conf-compatibility.md: a section
            # this version does not know is how a *newer* version adds a
            # feature, and refusing the whole file over it leaves the
            # device in whatever state the last boot left it, with no
            # restart (RestartPreventExitStatus=2). An unknown *option*
            # inside a known section stays an error -- that is what a
            # typo looks like, and a silently ignored 'levl = -20' is a
            # wrong device state nobody is told about.
            log.warning(
                "ignoring unknown section [%s] -- this config may have been "
                "written by a newer version of oscmix-autostart "
                "(known: [device], [osc], [route:<name>])", section
            )
    _check_device_channels(config)
    _check_link_agreement(config.routes)
    return config


def _check_device_channels(config: Config) -> None:
    """Reject channels the configured device does not have.

    ``CHANNEL_MIN..CHANNEL_MAX`` is 1..64 and says nothing about any
    particular interface, so ``output = 40/41`` parsed cleanly on a
    20-channel UCX II, was applied, and did nothing -- the exact shape of
    failure this project exists to prevent, since at message level the
    routing is perfect.

    Deliberately a separate pass rather than a check inside
    ``_parse_channels``: ``[device]`` may appear after the routes in the
    file, so the device is only known once every section has been read.
    It also keeps syntax ("is this a channel number") apart from
    capability ("does this device have it").

    An unmodelled device is *no opinion*, not an error. The 802 has never
    been tested here, and a model that rejected its channels would be
    guessing at hardware nobody can check.
    """
    device = device_for_name(config.device_name)
    if device is None:
        return
    for route in config.routes:
        for option, channels, capability in (
                ("playback", route.playback, "playback"),
                ("output", route.output, "output")):
            valid = device.channels_for(capability)
            if not valid:
                # Modelled, but this capability was never recorded --
                # the 802 is listed so the device dimension is real, and
                # declares nothing because guessing is how a model
                # becomes a lie. Being in the table is not an opinion.
                continue
            for channel in channels:
                if channel not in valid:
                    raise ConfigError(
                        "[route:%s] %s: channel %d does not exist on a %s "
                        "(it has %s %d..%d)"
                        % (route.name, option, channel, device.name,
                           capability, min(valid), max(valid))
                    )


def _check_link_agreement(routes: Sequence[Route]) -> None:
    """Reject routes that disagree on whether an output pair is linked.

    The stereo link is a property of the hardware pair, not of a route, so
    two routes feeding the same outputs cannot each have their own. Left
    unchecked the last link message wins while both routes still write
    their own mix shape, and the mismatched one silently loses a channel:
    a linked pair fed by the hard-panned pair of an unlinked route folds
    both messages onto the same register, and one output goes dead.
    """
    seen: Dict[Tuple[int, ...], Route] = {}
    for route in routes:
        if len(route.output) != 2:
            continue
        previous = seen.get(route.output)
        if previous is None:
            seen[route.output] = route
        elif previous.stereo != route.stereo:
            raise ConfigError(
                "[route:%s] and [route:%s] both drive output pair %s but "
                "disagree on 'stereo' (%s vs %s); the link is a property of "
                "the hardware pair, so it has to be the same for both"
                % (previous.name, route.name,
                   "/".join(map(str, route.output)),
                   str(previous.stereo).lower(), str(route.stereo).lower())
            )
