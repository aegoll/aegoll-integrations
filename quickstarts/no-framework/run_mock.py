"""A governed buying agent in about sixty lines. No framework, no model, no wallet.

The shortest demonstration that the governance layer needs none of those (PLAN.md C2.4), and
the one CI runs on every push. Every other quickstart is this loop with a framework wrapped
around it, so if you read one, read this.

    python quickstarts/no-framework/run_mock.py

It ends in a **refusal**, on purpose. A spend cap that has never refused anything has not been
demonstrated (C2.5).

Nothing settles: the mock accepts any payment header without checking it. What this shows is the
*decision* path -- price discovered for free, decision made before money moves, envelopes
consumed on settlement, every step in a hash-chained record. What it cannot show is a signature
verifying or a payment landing on chain, and the testnet variant is for that.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "mock"))

from mock_seller import running  # noqa: E402

PORT = 4021
BASE = f"http://127.0.0.1:{PORT}"

#: Shopping list, cheapest first. The last one is deliberately unaffordable: the run has to end
#: in a refusal or it has demonstrated nothing.
WANTED = ["/market/snapshot", "/market/depth", "/premium/feed", "/expensive/report"]


def price_of(path: str) -> int:
    """What this resource costs, in atomic units. Costs nothing to ask.

    Free price discovery is what makes governance possible at all: the amount is known *before*
    anything is authorised, so a decision can be made rather than a payment regretted.
    """
    from x402.http.utils import decode_payment_required_header

    try:
        urllib.request.urlopen(BASE + path, timeout=5)
        return 0
    except urllib.error.HTTPError as exc:
        if exc.code != 402:
            raise
        header = dict(exc.headers)["PAYMENT-REQUIRED"]
        return int(decode_payment_required_header(header).accepts[0].max_amount_required)


def fetch(path: str) -> dict:
    """Pay and take delivery. The mock does not verify the header -- see its docstring."""
    request = urllib.request.Request(BASE + path)
    request.add_header("X-PAYMENT", "unverified-by-design")
    return json.loads(urllib.request.urlopen(request, timeout=5).read())


def main() -> int:
    from tesoro import Governor

    gov = Governor.load()  # reads ./tesoro.yaml, or the packaged starter if there is none
    print(f"tesoro: {gov.report().policy_name} policy, AEGS {_aegs_version()}")
    print()

    outcomes: list = []
    try:
        for path in WANTED:
            atomic = price_of(path)

            # The decision, before any money moves.
            decision = gov.authorize(
                amount_usd=atomic, vendor="mock-seller", resource=path
            )
            outcomes.append(decision)

            if not decision.approved:
                # Deliberately **not** breaking here. The first refusal in this catalogue is a
                # cautious default (no rule matched a $2.50 purchase from an unknown vendor), and
                # stopping there would show the layer hesitating rather than a limit biting. The
                # $25 resource further down trips the per-transaction ceiling outright, which is
                # the more useful thing to see -- so the loop keeps asking and reports both.
                binding = decision.budget.binding
                print(f"  REFUSED  {path:22} ${atomic / 1e6:>9.6f}")
                print(f"           verdict : {decision.verdict.value}")
                print(f"           control : {decision.attributed_control}"
                      + (f", envelope {binding}" if binding else ""))
                print(f"           because : {decision.reason}")
                continue

            fetch(path)
            gov.settle(decision, success=True)  # envelopes consume here, not above
            print(f"  bought   {path:22} ${atomic / 1e6:>9.6f}")

        print()
        report = gov.report()
        print(f"spent      : ${report.spent_usd}  over {report.settled} settled purchase(s)")
        print("by control : " + ", ".join(
            f"{name} {count}" for name, count in sorted(
                report.by_attributed_control.items(), key=lambda kv: -kv[1]
            )
        ))

        valid, problems = gov.verify()
        chain = report.chain
        print(f"evidence   : {chain.entries if chain else 0} entries, "
              f"{'VALID' if valid else 'BROKEN'}"
              f"  [{chain.hash_name if chain else '?'}, {chain.hash_bits if chain else 0} bits]")
        if chain:
            print(f"             caveat: {chain.caveat}")
        if problems:
            print(f"             problems: {problems}")

        # The exit code is the point, and it is what CI checks.
        refusals = [d for d in outcomes if not d.approved]
        by_envelope = [d for d in refusals if d.budget.binding]

        print()
        if not refusals:
            print("FAILED: nothing was refused, so no spending limit was demonstrated.")
            return 1
        if not by_envelope:
            # A run whose only refusals were cautious defaults has shown the layer hesitating,
            # not a limit enforcing. Those are different claims and only one of them is the
            # product.
            print("FAILED: refusals happened, but none named a binding envelope -- no limit "
                  "actually bit.")
            return 1
        if not valid:
            print("FAILED: the evidence chain does not verify.")
            return 1

        print(f"OK: {len(refusals)} refusal(s), {len(by_envelope)} of them from an envelope "
              f"({', '.join(sorted({d.budget.binding for d in by_envelope}))}).")
        return 0
    finally:
        gov.close()


def _aegs_version() -> str:
    """Which specification this implementation implements.

    Read from `tesoro.record` rather than the top level: 0.1.0 shipped without exporting
    `tesoro.AEGS_VERSION`, so the top-level name raises on the version this quickstart pins.
    Falls forward automatically once 0.1.1 is out.
    """
    import tesoro

    return getattr(tesoro, "AEGS_VERSION", None) or __import__(
        "tesoro.record", fromlist=["AEGS_VERSION"]
    ).AEGS_VERSION


if __name__ == "__main__":
    with running(PORT):
        raise SystemExit(main())
