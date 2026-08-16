"""USB presence detection via sysfs (no lsusb dependency)."""


def test_device_found(session_mod, fake_sysfs):
    assert session_mod.usb_device_present("2a39:3fd9", fake_sysfs) is True


def test_case_insensitive_match(session_mod, fake_sysfs):
    assert session_mod.usb_device_present("2A39:3FD9", fake_sysfs) is True


def test_device_absent(session_mod, empty_sysfs):
    assert session_mod.usb_device_present("2a39:3fd9", empty_sysfs) is False


def test_missing_sysfs_dir(session_mod, tmp_path):
    assert session_mod.usb_device_present("2a39:3fd9", tmp_path / "nope") is False


def test_launcher_uses_same_detection(launch_mod, fake_sysfs, empty_sysfs):
    assert launch_mod.usb_device_present("2a39:3fd9", fake_sysfs) is True
    assert launch_mod.usb_device_present("2a39:3fd9", empty_sysfs) is False


def test_the_launcher_entry_point_is_exported(session_mod, launch_mod):
    # The launcher moved into the package in 0.2.0; it was the last file
    # outside the architecture test, the mutation scope and the coverage
    # everything else is held to.
    assert session_mod.launch_mixer is launch_mod.main


def test_the_launcher_no_longer_duplicates_device_detection(launch_mod):
    # It used to carry its own copies of usb_device_present and
    # udp_port_listening so it could stand alone. The package is
    # installed beside it now, so the copies bought nothing but a second
    # place for the same bug.
    from oscmix_autostart import discovery

    assert launch_mod.usb_device_present is discovery.usb_device_present
    assert launch_mod.udp_port_listening is discovery.udp_port_listening
