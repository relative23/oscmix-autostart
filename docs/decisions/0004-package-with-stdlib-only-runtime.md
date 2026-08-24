# 0004 -- The runtime is a package, and imports only the standard library

**Status:** accepted (0.2.0)

## Decision

The logic lives in `src/oscmix_desk/`, a layered package.
`bin/oscmix-session` locates it and calls `cli.main()`, nothing more.
The package imports nothing outside the standard library, and
`tests/test_architecture.py` enforces both properties.

## Why

The single 1386-line script was working code, and the monolith bought
something real: no install step, no dependencies, runnable from a
checkout on a bare system. That property is worth more than tidiness and
is why the file stayed monolithic for as long as it did.

What forced the change was measurement, not taste:

* `run_session` was 106 lines doing six things.
* mutation testing could not run at all -- mutmut cannot find code to
  mutate in an extension-less script.
* `--strict` typing and unit-level tests of the session lifecycle were
  awkward to the point of being skipped.

So the package ships **alongside** the executable rather than replacing
it. Nothing about the deployment story changes: `install.sh` copies the
modules to `~/.local/lib/oscmix-desk`, the shim finds them there or
in a checkout, and there is still nothing to pip install.

## What this rules out

A third-party runtime dependency, however convenient. The architecture
test fails on the first one. Also: logic in `bin/`, which unit tests
cannot reach because the file has no `.py` suffix.

## Cost

Two layouts to keep working (checkout and installed), and an installer
that must wipe the target directory so stale modules from an older
version cannot be importable and silently win.
