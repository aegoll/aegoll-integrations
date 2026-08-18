"""Run every use case, and fail if any of them stops demonstrating its own point.

This is what CI runs. Each case is a story with a claim, and the claim is checked rather than
narrated — a case that ends without the refusal it is about, or with a refusal from the wrong
control, exits non-zero and takes the build with it.

The structuring case is the exception, and it is an exception with a reason: it exists to show
that **nothing is refused**. If a refusal ever appears there, the gap has closed, and the case
says so loudly rather than passing quietly — good news that still needs a human to rewrite the
case and update the specification's open-findings list.

    python usecases/run_all.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: In reading order rather than alphabetical. `data-marketplace` is the baseline the others vary
#: from, so it goes first and the gap goes last.
CASES = [
    "data-marketplace",
    "intent-drift",
    "delegation",
    "budget-exhaustion",
    "prompt-injection",
    "aml-structuring",
]


def main() -> int:
    results: list[tuple[str, int]] = []

    for name in CASES:
        script = HERE / name / "run.py"
        if not script.is_file():
            print(f"!! {name}: no run.py -- PLAN.md C5")
            results.append((name, 1))
            continue

        completed = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True
        )
        results.append((name, completed.returncode))
        if completed.returncode != 0:
            print(f"\n=== {name} FAILED (exit {completed.returncode}) ===")
            print(completed.stdout[-3000:])
            print(completed.stderr[-2000:])

    print()
    print("=" * 62)
    for name, code in results:
        print(f"  {'ok  ' if code == 0 else 'FAIL'}  {name}")

    failed = [name for name, code in results if code != 0]
    print("=" * 62)
    if failed:
        print(f"{len(failed)} use case(s) failed: {', '.join(failed)}")
        return 1
    print(f"all {len(results)} use cases demonstrated what they claim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
