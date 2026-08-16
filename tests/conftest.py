"""Shared test fixtures.

Unit tests import the ``oscmix_autostart`` package directly; the thin
executables in bin/ are covered end to end by the integration tests,
which run them as real subprocesses.

``load_executable`` remains for the bin/ shims themselves: they have no
.py extension, so they need SourceFileLoader, and their
``if __name__ == "__main__"`` guard keeps the import side-effect free.
"""

import importlib.machinery
import importlib.util
import socket
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def repo_file(*parts):
    """Locate a file that ships with the repository.

    Not simply ``PROJECT_ROOT / parts``: a mutation run executes a copied
    tree that contains only sources and tests, no shipped data files. That
    copy lives inside the real checkout, so walking up finds the original.
    """
    for base in Path(__file__).resolve().parents:
        candidate = base.joinpath(*parts)
        if candidate.exists():
            return candidate
    raise FileNotFoundError("/".join(parts))


def free_udp_port():
    """An ephemeral UDP port that was free a moment ago."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def load_executable(name):
    path = repo_file("bin", name)
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
    """The launcher, now a package module rather than a standalone script."""
    from oscmix_autostart import launcher

    return launcher


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


def _hypothesis_available():
    try:
        import hypothesis  # noqa: F401
    except ImportError:
        return False
    return True


def pytest_report_header(config):
    """Say up front whether the contract tests are going to run at all."""
    if _hypothesis_available():
        return None
    return ("contract tests: DISABLED -- hypothesis is not installed "
            "(pip install -r requirements-dev.txt)")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Refuse to let a skipped contract suite look like a green run.

    tests/test_contracts.py skips itself without hypothesis. With `-q`
    that is one digit in a summary line, so a checkout missing the dev
    requirements reports "all passed" having checked no contract at all
    -- including the two that exist because of shipped defects. Set
    OSCMIX_REQUIRE_CONTRACTS=1 (CI does) to make it an error instead.
    """
    if _hypothesis_available():
        return
    terminalreporter.write_sep("=", "CONTRACT TESTS DID NOT RUN", red=True,
                               bold=True)
    terminalreporter.write_line(
        "hypothesis is not installed, so tests/test_contracts.py was "
        "skipped in full.")
    terminalreporter.write_line(
        "Nothing checked the OSC codec against hostile input, that a route "
        "writes only")
    terminalreporter.write_line(
        "what it declares, or that config parsing is total. This run proves "
        "less than it says.")
    terminalreporter.write_line("")
    terminalreporter.write_line("    pip install -r requirements-dev.txt")
