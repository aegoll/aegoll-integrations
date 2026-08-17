"""Test paths for a repo of standalone examples rather than one installable package.

`cockpit/` and `harness/` hold modules that arrived from `aegoll` when the package shed
its UI (PLAN.md C4, C6). They are examples, not a library, so they are plain modules on
the path rather than a package with an import root — which is the right shape for code
whose job is to be read and copied.

Two consequences this file handles:

* they import each other by bare name (`import crossview`, `from scenarios import ...`),
  so both directories go on `sys.path`;
* `app.py` in `cockpit/` uses `scenarios` from `harness/`, because the cockpit runs the
  demo scenarios in a tab. That cross-directory edge is real and is recorded here rather
  than hidden by flattening the layout.

`aegoll` itself is **not** put on the path. Every example pins it from PyPI (C0.3), and a
test that silently fell back to a sibling checkout would be testing the wrong thing —
exactly the failure F-C1 describes.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

for directory in ("cockpit", "harness", "frameworks"):
    path = str(HERE / directory)
    if path not in sys.path:
        sys.path.insert(0, path)


def repo_file(*parts: str) -> Path:
    """A path inside this repository, asserted to exist.

    The assertion is the point. A test that builds a path and finds nothing there does
    not fail — it scans an empty set and passes, which is how the claim behind "universal
    plugin" went unchecked for a whole commit (PLAN.md F-C1). Anything located by path
    gets checked, every time.
    """
    path = HERE.joinpath(*parts)
    assert path.exists(), f"{path} is not there; the layout changed under the tests"
    return path


def module_source(name: str, *, where: str = "cockpit") -> Path:
    """Source file of one of the moved modules, e.g. `module_source("ui.py")`.

    Named to match `aegoll/tests/conftest.py`, but resolved differently and for a good
    reason: there, the subject is an *installed package* and is found through its import.
    Here the subject is a plain file in this repository, and a repo-relative path is the
    honest answer. What both share is that the file is asserted to exist.
    """
    return repo_file(where, name)
