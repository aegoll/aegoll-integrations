"""Shared scaffolding for the use cases. Deliberately thin.

Each use case is a governance story with a beginning, a refusal, and evidence. What they share
is only the boring part: a scratch directory, a policy pack, a printer, and the check that the
story actually ended the way it claims. The interesting part stays in the case, where a reader
can see it.

Two rules every case follows, and this module enforces both:

* **it ends in a refusal** — a spend cap that has never refused anything has not been
  demonstrated (PLAN.md C2.5), so `finish()` exits non-zero if nothing was refused;
* **it writes its Decision Records into the repository** (C5.10), so the evidence can be read
  without running anything.

`main()` returns the process exit code, so CI can run every case and a case that stops
demonstrating its own point turns a build red rather than printing a story nobody reads.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent


def policy(**overrides: str) -> str:
    """The packaged starter pack, with named numbers changed.

    Derived from the real default rather than written fresh, so a case exercises the rules a
    user actually gets and only the values under test differ. Every override is a literal
    substitution on the YAML text and is asserted to have matched — a silently-ignored override
    would make a case demonstrate the default and claim otherwise.
    """
    import re

    text = (resources.files("aegoll") / "policies" / "default.yaml").read_text(encoding="utf-8")
    for key, value in overrides.items():
        # Money is quoted in the pack (`daily_usd: "50"`) because it is a decimal string and must
        # never become a float; counts are not (`velocity_60s: 10`). Both are overridable, and
        # the quoting is preserved either way -- rewriting `"50"` as `50` would change a money
        # value into a YAML number, which is exactly the mistake ARITH-9 exists to prevent.
        quoted = re.compile(rf'^(\s*{re.escape(key)}:\s*)"[^"]*"', re.M)
        bare = re.compile(rf'^(\s*{re.escape(key)}:\s*)(-?\d+(?:\.\d+)?)', re.M)

        if quoted.search(text):
            text = quoted.sub(rf'\g<1>"{value}"', text, count=1)
        elif bare.search(text):
            text = bare.sub(rf"\g<1>{value}", text, count=1)
        else:
            raise AssertionError(
                f"no such policy key to override: {key}. Overriding nothing would make a case "
                "demonstrate the default while claiming otherwise, so this is an error rather "
                "than a no-op."
            )
    return text


class Story:
    """One use case: a governor in a scratch directory, and a record of what happened."""

    def __init__(self, name: str, *, pack: str | None = None) -> None:
        self.name = name
        self.decisions: list[Any] = []
        self._dir = Path(tempfile.mkdtemp(prefix=f"usecase-{name}-"))
        self._cwd = Path.cwd()

        packs = self._dir / "policies"
        packs.mkdir()
        (packs / "case.yaml").write_text(pack or policy(), encoding="utf-8")
        (self._dir / "aegoll.yaml").write_text(
            "\n".join(
                [
                    "profile: aegs-1",
                    "policy: policies/case.yaml",
                    "evidence:",
                    "  journal: .aegoll/audit.jsonl",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        import os

        os.chdir(self._dir)
        from aegoll import Governor

        self.gov = Governor.load()

    # --- narration --------------------------------------------------------

    def say(self, text: str = "") -> None:
        print(text)

    def heading(self, text: str) -> None:
        print()
        print(text)
        print("-" * len(text))

    def ask(self, *, label: str, **kwargs: Any) -> Any:
        """Authorise one action and narrate the answer.

        Prints the attributed control on every line, approved or not. That is the field this
        whole project exists to be able to produce, and a story that only showed it on refusals
        would suggest an approval has no attribution — it does, and knowing *which* control
        cleared something is as useful as knowing which one stopped it.
        """
        decision = self.gov.authorize(**kwargs)
        self.decisions.append(decision)

        mark = "APPROVE" if decision.approved else decision.verdict.value
        amount = kwargs.get("amount_usd", "")
        shown = f"${int(amount) / 1e6:.6f}" if isinstance(amount, int) else f"${amount}"
        print(f"  {mark:9} {label:34} {shown:>12}   [{decision.attributed_control}]")
        if not decision.approved and decision.reason:
            print(f"            why: {decision.reason}")
        return decision

    def settle(self, decision: Any, **kwargs: Any) -> None:
        self.gov.settle(decision, **kwargs)

    # --- the ending -------------------------------------------------------

    def finish(
        self,
        *,
        expect_refusal_from: str | None = None,
        expect_no_refusal_because: str | None = None,
    ) -> int:
        """Write the evidence, check the story ended as claimed, return an exit code.

        `expect_refusal_from` names the control the case is *about*. Without it a case could pass
        by being refused for an unrelated reason, which is the mistake AEGS-0.1-CONF-2 exists to
        catch in implementations and is no more acceptable in an example: a right ending for the
        wrong reason teaches the reader something false.

        `expect_no_refusal_because` inverts the rule, and exactly one case needs it: the
        structuring demo, which exists to show that **nothing is refused**. That is an open
        finding shipped as a runnable artifact rather than a paragraph, so for that case a
        refusal would mean the gap had closed — and the case says so, loudly, instead of passing
        quietly. Never use it to excuse a case that merely failed to demonstrate anything.
        """
        report = self.gov.report(limit=200)
        records = self._write_evidence(report)

        refusals = [d for d in self.decisions if not d.approved]
        controls = {d.attributed_control for d in refusals}

        self.heading("evidence")
        print(f"  decisions : {report.decisions_total}  settled {report.settled}  "
              f"spent ${report.spent_usd}")
        print(f"  by control: " + ", ".join(
            f"{k} {v}" for k, v in sorted(report.by_attributed_control.items(), key=lambda kv: -kv[1])
        ))
        valid, problems = self.gov.verify()
        chain = report.chain
        print(f"  chain     : {chain.entries if chain else 0} entries, "
              f"{'VALID' if valid else 'BROKEN'}")
        print(f"  written   : {records.relative_to(HERE.parent)}")

        self.heading("did this story end the way it claims?")
        code = 0

        if expect_no_refusal_because is not None:
            if refusals:
                print(f"  THE GAP HAS CLOSED: {len(refusals)} refusal(s) from "
                      f"{sorted(controls)}, and this case exists to show that nothing is "
                      f"refused. That is good news and this case is now wrong -- rewrite it as "
                      f"a defended case and update the spec's open-findings list.")
                return 1
            print(f"  OK, and not OK: nothing was refused, which is the point. "
                  f"{expect_no_refusal_because}")
            return 0 if valid else 1

        if not refusals:
            print("  FAILED: nothing was refused, so nothing was demonstrated.")
            code = 1
        elif expect_refusal_from and expect_refusal_from not in controls:
            print(f"  FAILED: refused by {sorted(controls)}, but this case is about "
                  f"{expect_refusal_from!r}. A right ending for the wrong reason teaches "
                  f"the reader something false.")
            code = 1
        else:
            print(f"  OK: {len(refusals)} refusal(s), attributed to {sorted(controls)}.")
        if not valid:
            print(f"  FAILED: the evidence chain does not verify: {problems}")
            code = 1
        return code

    def _write_evidence(self, report: Any) -> Path:
        """C5.10: the records land in the repository so they can be read without running."""
        out = HERE / self.name / "evidence"
        out.mkdir(parents=True, exist_ok=True)

        (out / "report.json").write_text(
            json.dumps(report.as_dict(), indent=2), encoding="utf-8"
        )
        journal = self._dir / ".aegoll" / "audit.jsonl"
        if journal.is_file():
            shutil.copy2(journal, out / "audit.jsonl")
        return out

    def close(self) -> None:
        import os

        self.gov.close()
        os.chdir(self._cwd)
        shutil.rmtree(self._dir, ignore_errors=True)


def run(name: str, story: Callable[[Story], int], *, pack: str | None = None) -> int:
    """Run one case, always cleaning up, and return its exit code."""
    print(f"=== {name} ===")
    case = Story(name, pack=pack)
    try:
        return story(case)
    finally:
        case.close()


def main(name: str, story: Callable[[Story], int], *, pack: str | None = None) -> None:
    sys.exit(run(name, story, pack=pack))
