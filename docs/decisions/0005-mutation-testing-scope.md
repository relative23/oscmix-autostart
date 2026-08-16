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

677 of 2066 mutants are reported as "not covered". That is not dead code:
`cli`, `session`, `process` and `notify` are covered end to end, and the
coverage report (which does follow subprocesses) shows 70-83% for them.
It means the mutation score says nothing about those modules. The number
to read is the survivor count in `osc`, `config`, `routing` and `verify`.

## What this rules out

Reading the mutation score as a whole-project quality figure. It is a
statement about the pure-logic core, which is the part where a wrong
value is silent and audible.
