# 0005 -- Mutation testing runs against the in-process tests only

**Status:** accepted (0.2.0)

## Decision

`tests/test_session_integration.py`, `tests/test_install_sh.py` and
`tests/test_architecture.py` skip themselves during a mutation run. The
score is measured against the tests that import the package directly.

## Why

The integration tests drive `bin/oscmix-session` as a real subprocess.
The entry point resolves the package from its own location, so the
subprocess loads the checked-out source -- never the mutated copy. Such a
test cannot kill a mutant, and at ~35 s per run it would dominate the
pass while contributing nothing.

The architecture tests assert properties of the source tree, and a
mutation run deliberately rewrites it: mutmut inserts its own import into
every mutated module. Left running, they would measure mutmut.

## Consequence, stated plainly

**When this was written (0.2.0, mid-release):** 677 of 2066 mutants were
reported as "not covered". That was not dead code -- `cli`, `session`,
`process` and `notify` were covered end to end, and the coverage report
(which does follow subprocesses) showed 70-83% for them. It meant the
mutation score said nothing about those modules, and the number to read
was the survivor count in `osc`, `config`, `routing` and `verify`.

**Now:** 81 of 2501. `tests/test_lifecycle.py`, `tests/test_process.py`
and `tests/test_launcher.py` drive those modules *in process*, so they
are under evaluation like everything else, and the score is a statement
about the whole runtime rather than about its pure-logic core.

The score went **down** as a result -- 0.728 to 0.643 -- and that is the
arithmetic working, not the tests getting worse. A mutant that stops
being "not covered" starts being judged, and four modules' worth of
survivors joined a denominator they had never been in. The reasoning
above still holds for what remains excluded: the subprocess-driven tests
in `tests/test_session_integration.py`, `tests/test_install_sh.py` and
`tests/test_soak.py` skip themselves under `MUTANT_UNDER_TEST`, because
they load the original source and cannot kill a mutant.

## What this rules out

Reading a *rise* in `not_covered` as good news. It means a test that
used to reach a module in process stopped doing so, and the score will
flatter itself by shrinking its own denominator -- which is exactly what
made 0.728 an overstatement. `scripts/mutation-policy.py` prints
`not_covered` next to the score for that reason.
