"""Shared test fixtures.

Unit tests import the ``oscmix_autostart`` package directly; the thin
executables in bin/ are covered end to end by the integration tests,
which run them as real subprocesses.

``bin/oscmix-launch`` is still a standalone script with no .py extension,
so it is loaded via SourceFileLoader. Its ``if __name__ == "__main__"``
guard keeps the import side-effect free.
"""

import importlib.machinery
import importlib.util
import socket
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))


def free_udp_port():
    """An ephemeral UDP port that was free a moment ago."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def load_executable(name):
    path = PROJECT_ROOT / "bin" / name
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    # dataclasses (3.14+) resolves annotations via sys.modules[__module__].
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def session_mod():
    """The runtime package: its public surface, as ``__all__`` defines it."""
    import oscmix_autostart

    return oscmix_autostart


@pytest.fixture(scope="session")
def routing_mod():
    """Reach into routing for its own knobs.

    Constants are imported by value, so patching them has to target the
    module that reads them -- patching the package re-export would set an
    attribute nobody consults.
    """
    from oscmix_autostart import routing

    return routing


@pytest.fixture(scope="session")
def verify_mod():
    from oscmix_autostart import verify

    return verify


@pytest.fixture(scope="session")
def pipewire_mod():
    from oscmix_autostart import pipewire

    return pipewire


@pytest.fixture(scope="session")
def launch_mod():
    return load_executable("oscmix-launch")


@pytest.fixture
def fake_sysfs(tmp_path):
    """A sysfs USB tree containing one Fireface UCX II."""
    root = tmp_path / "sysfs-usb"
    dev = root / "5-2"
    dev.mkdir(parents=True)
    (dev / "idVendor").write_text("2a39\n")
    (dev / "idProduct").write_text("3fd9\n")
    # An interface directory without id files, as in real sysfs.
    (root / "5-2:1.0").mkdir()
    return root


@pytest.fixture
def empty_sysfs(tmp_path):
    root = tmp_path / "sysfs-usb-empty"
    root.mkdir()
    hub = root / "usb1"
    hub.mkdir()
    (hub / "idVendor").write_text("1d6b\n")
    (hub / "idProduct").write_text("0002\n")
    return root
