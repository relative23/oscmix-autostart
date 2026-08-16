"""Structural guarantees, enforced instead of asserted in a comment.

The package was extracted from a single 1386-line script. Splitting it is
only worth something if the properties that made the split desirable stay
true, so they are checked here rather than trusted:

* the runtime imports nothing outside the standard library, which is what
  lets it run from a checkout on a bare system
* modules form a layered graph with no cycles
* the entry point in bin/ stays a shim
* the public surface is what ``__all__`` says it is
"""

import ast
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = PROJECT_ROOT / "src" / "oscmix_autostart"

# These assertions describe the *source* tree. A mutation run deliberately
# rewrites it -- mutmut inserts its own import into every mutated module --
# so asserting source properties there would only measure mutmut.
pytestmark = pytest.mark.skipif(
    bool(os.environ.get("MUTANT_UNDER_TEST")),
    reason="architecture describes the source tree, not a mutated copy",
)

# Which modules a module may import. A module absent from a value list is
# forbidden, so adding a dependency is a deliberate edit here, not an
# accident in an import block.
ALLOWED_IMPORTS = {
    "constants": set(),
    "errors": set(),
    "log": set(),
    "osc": set(),
    "notify": {"log"},
    "discovery": {"log"},
    "config": {"constants", "errors"},
    "routing": {"config", "constants", "log", "osc"},
    "verify": {"config", "constants", "log", "osc", "routing"},
    "pipewire": {"config", "errors", "log"},
    "process": {"constants", "discovery", "log"},
    "session": {"config", "constants", "discovery", "log", "notify",
                "process", "routing", "verify"},
    "cli": {"config", "constants", "errors", "log", "pipewire", "session"},
    "__init__": {"config", "constants", "discovery", "errors", "log",
                 "notify", "osc", "pipewire", "process", "routing",
                 "session", "verify"},
}


def module_paths():
    return sorted(PACKAGE.glob("*.py"))


def parse(path):
    return ast.parse(path.read_text(), filename=str(path))


def imports_of(path):
    """(stdlib_or_absolute, relative) module names imported by ``path``."""
    absolute, relative = set(), set()
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                absolute.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:                       # from .x import y
                if node.module:
                    relative.add(node.module.split(".")[0])
            elif node.module:
                absolute.add(node.module.split(".")[0])
    return absolute, relative


def test_every_module_is_listed_in_the_layering():
    # A new module must be placed in the graph deliberately; defaulting to
    # "anything goes" would make this test decorative.
    listed = set(ALLOWED_IMPORTS)
    actual = {path.stem for path in module_paths()}
    assert actual == listed, (
        "modules not placed in ALLOWED_IMPORTS: %s; listed but missing: %s"
        % (sorted(actual - listed), sorted(listed - actual))
    )


@pytest.mark.parametrize("path", module_paths(), ids=lambda p: p.stem)
def test_runtime_imports_only_the_standard_library(path):
    # The one dependency claim the README makes. It is what allows the
    # package to run before any package manager is involved.
    absolute, _ = imports_of(path)
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    if not stdlib:                               # pragma: no cover (py<3.10)
        pytest.skip("sys.stdlib_module_names needs Python 3.10+")
    foreign = {name for name in absolute
               if name not in stdlib and not name.startswith("_")}
    assert foreign == set(), "%s imports non-stdlib: %s" % (path.name,
                                                            sorted(foreign))


@pytest.mark.parametrize("path", module_paths(), ids=lambda p: p.stem)
def test_module_only_imports_its_declared_layer(path):
    _, relative = imports_of(path)
    allowed = ALLOWED_IMPORTS[path.stem]
    assert relative <= allowed, (
        "%s imports %s, which its layer does not allow (allowed: %s)"
        % (path.name, sorted(relative - allowed), sorted(allowed) or "nothing")
    )


def test_the_import_graph_is_acyclic():
    # Guaranteed by the layering above, but stated separately: a cycle is
    # the failure this whole arrangement exists to prevent.
    graph = {path.stem: imports_of(path)[1] for path in module_paths()}
    visiting, done = set(), set()

    def visit(name, trail):
        if name in done:
            return
        assert name not in visiting, "import cycle: %s" % " -> ".join(
            trail + [name])
        visiting.add(name)
        for dependency in sorted(graph.get(name, ())):
            visit(dependency, trail + [name])
        visiting.discard(name)
        done.add(name)

    for module in sorted(graph):
        visit(module, [])


def test_the_entry_point_stays_a_shim():
    # Logic in bin/ is logic that unit tests cannot reach, because the
    # file has no .py suffix and is only ever run as a subprocess.
    tree = parse(PROJECT_ROOT / "bin" / "oscmix-session")
    defined = [node.name for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
    assert defined == ["_package_root"], (
        "bin/oscmix-session should only locate the package, but defines %s"
        % defined)


def test_public_surface_matches_dunder_all(session_mod):
    exported = {name for name in vars(session_mod)
                if not name.startswith("_")
                and getattr(vars(session_mod)[name], "__module__", "")
                .startswith("oscmix_autostart")}
    declared = set(session_mod.__all__)
    assert exported <= declared, (
        "re-exported but not declared in __all__: %s" % sorted(exported - declared))
    missing = {name for name in declared if not hasattr(session_mod, name)}
    assert missing == set(), "declared in __all__ but absent: %s" % sorted(missing)


@pytest.mark.parametrize("path", module_paths(), ids=lambda p: p.stem)
def test_functions_stay_readable(path):
    # run_session was 106 lines before the split and did six things. The
    # ceiling is a smell detector, not a style rule.
    too_long = []
    for node in ast.walk(parse(path)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = (node.end_lineno or node.lineno) - node.lineno
            if length > 70:
                too_long.append("%s (%d lines)" % (node.name, length))
    assert too_long == [], "%s has oversized functions: %s" % (path.name,
                                                               too_long)


@pytest.mark.parametrize("path", module_paths(), ids=lambda p: p.stem)
def test_every_module_documents_itself(path):
    assert ast.get_docstring(parse(path)), "%s has no module docstring" % path.name
