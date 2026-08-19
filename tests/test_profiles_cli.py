"""`--profile` and `--list-profiles` as commands.

The outcome logic is covered in tests/test_profiles.py against a
recording backend. This is the part that turns an outcome into an exit
code and a line of stdout -- the only part a shell script can see.

Written at the same time as the feature rather than after the coverage
ratchet complained, which is the difference from --dump-config: that one
landed at 53% on cli.py and was found by the gate, on a push.
"""

from conftest import free_udp_port, write_config

from oscmix_autostart import cli
from oscmix_autostart.constants import EXIT_CONFIG, EXIT_OK

GOOD = """
[route:main]
output = 1/2
playback = 1/2
level = 0.0

[output:1]
volume = -10.0
"""


def _config_with(tmp_path, profiles):
    """A routing.conf plus a profiles/ directory beside it.

    The ports are free ones, and the profiles inherit them from here
    rather than restating them. That inheritance is not a convenience:
    without it these profiles fall back to the compiled-in 7222, and on
    a developer machine with a Fireface attached that is the live
    backend. This suite moved a fader on real hardware exactly once.
    """
    for name, text in profiles.items():
        write_config(tmp_path / "profiles" / ("%s.conf" % name), text)
        assert "[osc]" not in text, (
            "a profile fixture must not state its own port -- inheriting "
            "it from the tmp_path config is what keeps this off the "
            "hardware")
    return write_config(tmp_path / "routing.conf",
                        "[osc]\nport = %d\nrecv-port = %d\n"
                        % (free_udp_port(), free_udp_port()))


def test_listing_profiles_prints_one_line_each(tmp_path, capsys):
    path = _config_with(tmp_path, {"tracking": GOOD, "mixdown": GOOD})
    assert cli.main(["--config", str(path), "--list-profiles"]) == EXIT_OK
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("mixdown")
    assert lines[1].startswith("tracking")


def test_listing_with_no_profiles_prints_nothing_and_succeeds(tmp_path,
                                                              capsys):
    path = write_config(tmp_path / "routing.conf", "[osc]\nport = 7222\n")
    assert cli.main(["--config", str(path), "--list-profiles"]) == EXIT_OK
    assert capsys.readouterr().out == ""


def test_a_refused_profile_exits_config_and_says_nothing_was_written(
        tmp_path, capsys):
    """The exit code a script branches on.

    EXIT_CONFIG rather than EXIT_FAILURE because it is the same failure
    as a bad routing.conf at startup: it did not parse, so nothing
    happened. A script that retries on failure must not retry this.
    """
    path = _config_with(tmp_path, {
        "bad": "[route:x]\noutput = 99\nplayback = 1\n"})
    assert cli.main(["--config", str(path), "--profile", "bad"]) == EXIT_CONFIG
    out = capsys.readouterr().out
    assert "refused" in out
    assert "nothing written" in out
    assert "bad" in out


def test_a_missing_profile_exits_config(tmp_path, capsys):
    path = _config_with(tmp_path, {})
    assert cli.main(["--config", str(path),
                     "--profile", "nosuch"]) == EXIT_CONFIG
    assert "nosuch" in capsys.readouterr().out


def test_an_applied_but_unverifiable_switch_still_exits_ok(tmp_path, capsys):
    """No backend is running, so the read-back confirms nothing.

    This is the desktop case in miniature: applied, unconfirmable, and
    that is EXIT_OK because the registers did go out. Reporting failure
    here would make every switch on a machine with the mixer GUI open
    look broken.
    """
    path = _config_with(tmp_path, {"tracking": GOOD})
    assert cli.main(["--config", str(path),
                     "--profile", "tracking"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "applied" in out
    assert "unconfirmed" in out
    assert "/output/1/volume" in out, (
        "the channel section has to appear in the unconfirmed list -- "
        "it was missing from the read-back entirely until 0.3.0, and "
        "then present but structurally unreachable because the window "
        "closed as soon as the stereo flags matched")
