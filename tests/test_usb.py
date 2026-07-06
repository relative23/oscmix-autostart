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
