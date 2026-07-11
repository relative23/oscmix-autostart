"""routing.conf parsing: valid configs, defaults, and error reporting."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def write(tmp_path, text):
    path = tmp_path / "routing.conf"
    path.write_text(text)
    return path


def test_defaults_without_file(session_mod):
    config = session_mod.load_config(None)
    assert config.device_name == "Fireface UCX II"
    assert config.usb_id == "2a39:3fd9"
    assert config.osc_port == 7222
    assert config.osc_recv_port == 8222
    assert config.routes == []


def test_recv_port_option(session_mod, tmp_path):
    path = write(tmp_path, "[osc]\nport = 9000\nrecv-port = 9001\n")
    config = session_mod.load_config(path)
    assert config.osc_port == 9000
    assert config.osc_recv_port == 9001


def test_shipped_example_config_parses(session_mod):
    config = session_mod.load_config(PROJECT_ROOT / "config" / "routing.conf.example")
    assert config.device_name == "Fireface UCX II"
    assert len(config.routes) == 1
    route = config.routes[0]
    assert route.name == "main-out"
    assert route.playback == (1, 2)
    assert route.output == (1, 2)
    assert route.level == 0.0


def test_full_config(session_mod, tmp_path):
    path = write(tmp_path, """
[device]
name = Fireface 802
usb-id = 2A39:3FC0

[osc]
port = 9000

[route:monitors]
playback = 1/2
output = 5/6
level = -3.0
volume = 0.0

[route:sub]
playback = 3
output = 7
level = -6
stereo = no
""")
    config = session_mod.load_config(path)
    assert config.device_name == "Fireface 802"
    assert config.usb_id == "2a39:3fc0"  # normalized to lowercase
    assert config.osc_port == 9000
    monitors, sub = config.routes
    assert monitors.playback == (1, 2)
    assert monitors.output == (5, 6)
    assert monitors.level == -3.0
    assert monitors.volume == 0.0
    assert monitors.stereo is True
    assert sub.playback == (3,)
    assert sub.output == (7,)
    assert sub.volume is None
    assert sub.stereo is False


def test_inline_comments_are_stripped(session_mod, tmp_path):
    path = write(tmp_path, """
[route:main]
playback = 1/2  # stereo pair
output = 1/2    ; main out
""")
    config = session_mod.load_config(path)
    assert config.routes[0].playback == (1, 2)


@pytest.mark.parametrize("snippet, hint", [
    ("[route:x]\nplayback = 1/2/3\noutput = 1/2\n", "playback"),
    ("[route:x]\nplayback = 1/2\noutput = five/6\n", "channel number"),
    ("[route:x]\nplayback = 1/2\noutput = 5\n", "both"),
    ("[route:x]\nplayback = 1/2\noutput = 0/1\n", "out of range"),
    ("[route:x]\nplayback = 1/2\noutput = 5/6\nlevel = 20\n", "out of range"),
    ("[route:x]\noutput = 5/6\n", "playback"),
    ("[route:x]\nplayback = 1/2\noutput = 5/6\nstereo = maybe\n", "boolean"),
    ("[route:x]\nplayback = 1/2\noutput = 5/6\nlevle = 0\n", "unknown option"),
    ("[routes:x]\nplayback = 1/2\noutput = 5/6\n", "unknown section"),
    ("[device]\nusb-id = fireface\n", "usb-id"),
    ("[osc]\nport = 99999\n", "out of range"),
    ("[osc]\nport = auto\n", "port"),
])
def test_invalid_configs_raise_helpful_errors(session_mod, tmp_path, snippet, hint):
    path = write(tmp_path, snippet)
    with pytest.raises(session_mod.ConfigError) as excinfo:
        session_mod.load_config(path)
    assert hint in str(excinfo.value)


def test_missing_explicit_file_raises(session_mod, tmp_path):
    with pytest.raises(session_mod.ConfigError):
        session_mod.load_config(tmp_path / "nope.conf")


def test_stereo_route_writes_single_pair_register(session_mod):
    # oscmix folds a stereo-linked pair onto its odd channel: one /mix
    # message with pan 0 is the whole route. Hard-panned per-channel
    # messages would overwrite each other (last pan wins -> hard right).
    route = session_mod.Route(
        name="monitors", playback=(1, 2), output=(5, 6),
        level=0.0, volume=0.0, stereo=True,
    )
    assert session_mod.route_messages(route) == [
        ("/playback/1/stereo", "i", (1,)),
        ("/output/5/stereo", "i", (1,)),
        ("/mix/5/playback/1", "fi", (0.0, 0)),
        ("/output/5/volume", "f", (0.0,)),
        ("/output/6/volume", "f", (0.0,)),
    ]


def test_unlinked_pair_route_uses_pair_balance(session_mod):
    route = session_mod.Route(
        name="split", playback=(1, 2), output=(5, 6), stereo=False,
    )
    assert session_mod.route_messages(route) == [
        ("/playback/1/stereo", "i", (1,)),
        ("/mix/5/playback/1", "fi", (0.0, -100)),
        ("/mix/6/playback/1", "fi", (0.0, 100)),
    ]


def test_mono_route_messages(session_mod):
    route = session_mod.Route(name="sub", playback=(3,), output=(7,), level=-6.0)
    assert session_mod.route_messages(route) == [
        ("/mix/7/playback/3", "fi", (-6.0, 0)),
    ]


def test_pair_without_volume_sends_no_volume_messages(session_mod):
    route = session_mod.Route(name="m", playback=(1, 2), output=(1, 2))
    paths = [path for path, _, _ in session_mod.route_messages(route)]
    assert not any("volume" in path for path in paths)
