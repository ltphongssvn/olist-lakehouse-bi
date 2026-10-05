"""The module graph must stay acyclic, enforced rather than remembered.

WHAT CHANGED, AND WHY THIS FILE IS SHORTER THAN PLANNED
nix_output needed types from nix_contract while nix_contract imported
nix_output -- a real cycle, hidden behind a TYPE_CHECKING guard. Three tests
were drafted to defend that guard.

Defending a workaround is the treadmill. The guidance is explicit: "do not move
imports into if TYPE_CHECKING solely to break circular imports... avoid any
pattern whose sole purpose is to hide imports from runtime while exposing them
only to the type checker", and the named fix is "extract the shared code into a
new module C that neither A nor B imports back".

The models moved to nix_models and the guard is gone, so two of those three
tests had nothing left to assert. This one remains, because "the graph is
acyclic" is a property worth enforcing even when it is currently true by
construction -- the next module is where it would be broken.
"""

from __future__ import annotations

import ast
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def first_party_imports(module: Path) -> set[str]:
    """Modules in scripts/ that this one imports.

    NO TYPE_CHECKING SPECIAL CASE, deliberately. There are no guarded imports
    left, and writing the exemption would invite the pattern back: a future
    cycle could be hidden behind a guard and this test would approve of it.
    """
    tree = ast.parse(module.read_text())
    local = {path.stem for path in SCRIPTS.glob("*.py")}

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in local:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name in local)

    return found


def test_the_module_graph_has_no_cycles() -> None:
    """A cycle fails at import time, which is the worst place to find one.

    It surfaces as "cannot import name X from partially initialized module",
    which reads like a broken install rather than a design mistake, and it can
    appear on one machine and not another depending on entry point.
    """
    graph = {module.stem: first_party_imports(module) for module in SCRIPTS.glob("*.py")}

    visiting: set[str] = set()
    settled: set[str] = set()
    cycles: list[str] = []

    def walk(name: str, trail: list[str]) -> None:
        if name in visiting:
            cycles.append(" -> ".join([*trail[trail.index(name) :], name]))
            return
        if name in settled:
            return

        visiting.add(name)
        for imported in sorted(graph.get(name, set())):
            walk(imported, [*trail, name])
        visiting.discard(name)
        settled.add(name)

    for module in sorted(graph):
        walk(module, [])

    assert not cycles, f"import cycles: {cycles}"


def test_the_models_module_stays_a_leaf() -> None:
    """nix_models must not grow edges back up.

    It exists so that nix_contract and nix_output can both depend on it without
    depending on each other. An import of either from here would close the loop
    it was extracted to open, and the failure would look like the one that was
    just fixed.
    """
    imports = first_party_imports(SCRIPTS / "nix_models.py")

    assert "nix_contract" not in imports
    assert "nix_output" not in imports


def test_no_guarded_imports_have_returned() -> None:
    """The pattern, not just this instance.

    A TYPE_CHECKING guard is how the previous cycle was concealed. Its return
    would mean a new cycle is being hidden rather than removed -- and the cycle
    test above would pass, because a guarded import never executes.
    """
    offenders = [
        path.name for path in SCRIPTS.glob("*.py") if "if TYPE_CHECKING:" in path.read_text()
    ]

    assert not offenders, (
        f"guarded imports in {offenders}. If it is breaking a cycle, extract "
        "the shared types instead; that is what nix_models is for."
    )
