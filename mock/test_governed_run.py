"""A governed buying loop against the mock seller, end to end, with no wallet and no model.

This is the test that makes the mock worth having. `test_mock_seller.py` proves the fixture
speaks x402; this proves the **governance layer sits in the path and refuses things** -- which is
the claim the whole project rests on and, until now, nothing in this repository checked end to
end.

No framework and no model provider, deliberately. A plain loop is the shortest possible
demonstration that the layer needs neither (PLAN.md C2.4), and it means this runs in CI on a
clean checkout with no keys.

Every case here ends in a **refusal**, per C2.5: a spend cap that has never refused anything has
not been demonstrated.

What this does not cover, so nobody reads more into a green run than is there: no signature is
verified and nothing settles on chain. The mock accepts any payment header, which its own
docstring says and `test_mock_seller.py` asserts.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mock_seller import running  # noqa: E402

PORT = 4033
BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture
def seller():
    """A fresh mock per test. `running()` closes the listening socket as well as stopping the
    loop -- without that, each test leaves a dead server on the port and a later test times out
    for reasons that have nothing to do with it."""
    with running(PORT) as server:
        yield server


@pytest.fixture
def gov(tmp_path, monkeypatch):
    """A governor in a scratch directory, so each test has its own envelopes and journal."""
    monkeypatch.chdir(tmp_path)
    from tesoro import Governor

    governor = Governor.load()
    yield governor
    governor.close()


def quote(path: str) -> int:
    """Ask the seller what a resource costs, in atomic units. Free discovery -- no payment.

    This is the step that makes governance possible at all: the price is known *before* anything
    is authorised, so a decision can be made rather than a payment reversed.
    """
    from x402.http.utils import decode_payment_required_header

    try:
        urllib.request.urlopen(urllib.request.Request(BASE + path), timeout=5)
        return 0  # a free resource
    except urllib.error.HTTPError as exc:
        if exc.code != 402:
            raise
        header = dict(exc.headers)["PAYMENT-REQUIRED"]
        return int(decode_payment_required_header(header).accepts[0].max_amount_required)


def buy(path: str) -> dict:
    """Pay for a resource. The mock does not verify the header; that is its stated limitation."""
    request = urllib.request.Request(BASE + path)
    request.add_header("X-PAYMENT", "unverified-by-design")
    return json.loads(urllib.request.urlopen(request, timeout=5).read())


# --- the loop -------------------------------------------------------------


def test_a_governed_purchase_is_authorized_then_settled(seller, gov):
    """The happy path, which has to exist or an implementation that refuses everything scores
    perfectly."""
    atomic = quote("/market/snapshot")
    assert atomic == 10_000, "the seller's price changed; this test asserts a known one"

    decision = gov.authorize(
        amount_usd=atomic, vendor="mock-seller", resource="/market/snapshot"
    )
    assert decision.approved, decision.reason

    payload = buy("/market/snapshot")
    gov.settle(decision, success=True)

    assert payload["data"]["mock"] is True
    assert gov.report().settled == 1


def test_an_expensive_resource_is_refused_before_any_money_moves(seller, gov):
    """C2.5, and the shape of the whole product: the refusal happens **before** the request.

    Note the ordering. The price is discovered for free, the layer decides, and only then would a
    payment be made. A cap that refused *after* the money left would be a report.
    """
    atomic = quote("/expensive/report")
    assert atomic == 25_000_000, "the expensive resource is no longer expensive"

    decision = gov.authorize(
        amount_usd=atomic, vendor="mock-seller", resource="/expensive/report"
    )

    assert not decision.approved, "a $25 purchase was approved by the starter policy"
    assert decision.attributed_control, "a refusal with no attributable cause is not evidence"
    assert decision.reason, "no reason carried the verdict"

    # Nothing was bought, so nothing was consumed.
    assert gov.report().settled == 0


def test_the_refusal_names_which_control_decided(seller, gov):
    """Counts by verdict say what happened; the attributed control says what governed.

    This is the field an operator actually needs at 2am, and the one a plain spend cap cannot
    produce because it has only one rule to blame.
    """
    decision = gov.authorize(
        amount_usd=quote("/expensive/report"),
        vendor="mock-seller",
        resource="/expensive/report",
    )
    assert decision.attributed_control in {"treasury", "policy", "risk", "trust"}, (
        decision.attributed_control
    )


def test_a_cumulative_budget_refuses_what_no_per_payment_cap_would(seller, tmp_path, monkeypatch):
    """The claim that distinguishes this from a per-payment cap, demonstrated rather than argued.

    Every purchase here is **one cent** against a **ten dollar** per-payment ceiling, so no
    per-payment cap ever written would refuse any of them. What refuses the last one is a
    cumulative daily envelope -- and the refused payment is byte-for-byte identical to the ones
    that were approved. A per-payment cap cannot express that, because it has no memory.

    The daily limit is lowered to five cents for this test rather than using the starter pack's
    fifty dollars. Exhausting fifty dollars a cent at a time needs five thousand purchases, and a
    test that slow would not be run. The mechanism under test is the envelope, not the number.

    Written this way after the first attempt got it wrong: it used $2.50 purchases, which the
    starter policy refuses on the *first* call for low vendor trust. That would have looked like a
    cumulative refusal and been nothing of the kind -- a test passing for the wrong reason, which
    is what CONF-2 exists to catch in implementations and is no more acceptable here.
    """
    monkeypatch.chdir(tmp_path)
    _write_tight_daily_policy(tmp_path, daily_usd="0.05", per_transaction_usd="10")

    from tesoro import Governor

    gov = Governor.load()
    try:
        atomic = quote("/market/snapshot")
        assert atomic == 10_000, "one cent, in atomic units"

        approved, refused = 0, None
        for _ in range(12):
            decision = gov.authorize(
                amount_usd=atomic, vendor="mock-seller", resource="/market/snapshot"
            )
            if not decision.approved:
                refused = decision
                break
            buy("/market/snapshot")
            gov.settle(decision, success=True)
            approved += 1

        assert approved >= 4, (
            f"only {approved} of twelve one-cent purchases were approved against a five-cent "
            "daily limit; something other than the envelope is refusing them"
        )
        assert refused is not None, (
            f"{approved} one-cent purchases were all approved against a five-cent daily limit; "
            "the cumulative envelope is not binding"
        )
        assert refused.attributed_control, "the cumulative refusal is unattributed"
        assert refused.budget.binding, (
            "the refusal names no binding envelope, so it was not the budget that refused"
        )
    finally:
        gov.close()


def _write_tight_daily_policy(directory, *, daily_usd: str, per_transaction_usd: str) -> None:
    """A project whose daily envelope is reachable in a test, and whose per-payment ceiling is not.

    Derived from the packaged starter pack rather than written from scratch, so this exercises the
    same rules a user gets and only the two numbers under test differ.
    """
    from importlib import resources

    packaged = resources.files("tesoro") / "policies" / "default.yaml"
    pack = directory / "policies"
    pack.mkdir(exist_ok=True)

    text = packaged.read_text(encoding="utf-8")
    text = text.replace('daily_usd: "50"', f'daily_usd: "{daily_usd}"')
    text = text.replace(
        'per_transaction_usd: "10"', f'per_transaction_usd: "{per_transaction_usd}"'
    )
    (pack / "tight.yaml").write_text(text, encoding="utf-8")

    (directory / "tesoro.yaml").write_text(
        "\n".join(
            [
                "profile: aegs-1",
                "policy: policies/tight.yaml",
                "evidence:",
                "  journal: .tesoro/audit.jsonl",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_the_evidence_chain_records_the_whole_run(seller, gov):
    """Approvals and refusals both. A journal holding only successes is a marketing channel."""
    decision = gov.authorize(
        amount_usd=quote("/market/snapshot"), vendor="mock-seller", resource="/market/snapshot"
    )
    if decision.approved:
        buy("/market/snapshot")
        gov.settle(decision, success=True)

    gov.authorize(
        amount_usd=quote("/expensive/report"),
        vendor="mock-seller",
        resource="/expensive/report",
    )

    report = gov.report()
    assert report.decisions_total >= 2
    verdicts = set(report.by_verdict)
    assert len(verdicts) >= 2, f"only one kind of verdict was recorded: {verdicts}"

    valid, problems = gov.verify()
    assert valid, problems
    assert report.chain is not None and "truncation" in report.chain.caveat


def test_the_run_needs_no_wallet_and_no_model_key(seller, gov):
    """The claim C2.6 makes, asserted rather than assumed.

    If either were required, this test could not have reached this line -- there is no key in the
    environment and no signer anywhere in the process.
    """
    import os

    for variable in ("X402_PRIVATE_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        assert not os.environ.get(variable), (
            f"{variable} is set, so this test cannot prove the run works without it"
        )

    decision = gov.authorize(
        amount_usd=quote("/market/snapshot"), vendor="mock-seller", resource="/market/snapshot"
    )
    assert decision.verdict is not None
