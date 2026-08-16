"""Start coverage measurement in subprocesses the tests spawn.

Python imports ``sitecustomize`` automatically at interpreter start, which
is the only hook that runs before the code under test. The integration
tests put this directory on ``PYTHONPATH`` and set
``COVERAGE_PROCESS_START`` only while coverage itself is running, so a
plain ``pytest`` run is unaffected.

Without this, ``bin/oscmix-session`` -- the entry point every integration
test drives -- reports as untested even though it is exercised end to end.
"""

try:
    import coverage
except ImportError:  # pragma: no cover - coverage is a dev dependency only
    pass
else:
    coverage.process_startup()
