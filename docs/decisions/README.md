# Decision records

Short notes on the choices that are not obvious from the code, and that
cost a measurement session to arrive at. Each one states what was decided,
what it rules out, and what evidence produced it.

They exist because the reasoning behind the routing behaviour lived only
in commit messages. Anyone changing that code needs to know why it looks
the way it does, or they will "simplify" it straight back into a bug that
silences half the outputs.

| # | Decision |
|---|---|
| [0001](0001-two-phase-routing-apply.md) | Channel links are written before the mix matrix |
| [0002](0002-one-dump-for-verify-and-reapply.md) | Verification and the mix re-apply share one `/refresh` |
| [0003](0003-declared-registers-only.md) | A route rewrites only the registers it declares |
| [0004](0004-package-with-stdlib-only-runtime.md) | The runtime is a package, and imports only the standard library |
| [0005](0005-mutation-testing-scope.md) | Mutation testing runs against the in-process tests only |
