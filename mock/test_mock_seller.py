"""The mock seller, and what a run against it does and does not prove.

A mock that nobody checks is worse than no mock: a quickstart green against a broken fixture
reads as a working quickstart. So these assert the two properties the mock's whole value rests
on --

* it speaks **real** x402, decoded by the SDK's own decoder rather than by a matching fake;
* it is **honest about not settling**, so nobody mistakes a green quickstart for a verified
  payment path.

The second is the one worth being strict about. Every other test file here can afford to be
wrong in a way that fails loudly; this one, wrong, would make a whole documentation set lie.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mock_seller import CATALOGUE, Handler, running  # noqa: E402

PORT = 4032
BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture
def seller():
    """A fresh mock per test. `running()` closes the listening socket as well as stopping the
    loop -- without that, each test leaves a dead server on the port and a later test times out
    for reasons that have nothing to do with it."""
    with running(PORT) as server:
        yield server


def get(path: str, *, payment: bool = False) -> tuple[int, dict, dict]:
    request = urllib.request.Request(BASE + path)
    if payment:
        request.add_header("X-PAYMENT", "unverified-by-design")
    try:
        response = urllib.request.urlopen(request, timeout=5)
        return response.status, dict(response.headers), json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), json.loads(exc.read())


# --- it speaks real x402 --------------------------------------------------


def test_the_payment_required_header_is_decoded_by_the_sdk(seller):
    """The load-bearing test. Not "a header is present" -- a header the *real client* can read.

    A mock emitting its own header shape, parsed by a matching fake, would prove the agent can
    talk to this file and nothing else. Decoding with the SDK's own function is what makes a run
    against the mock evidence about a run against a seller.
    """
    from x402.http.utils import decode_payment_required_header

    status, headers, _ = get("/market/snapshot")
    assert status == 402
    assert "PAYMENT-REQUIRED" in headers

    decoded = decode_payment_required_header(headers["PAYMENT-REQUIRED"])
    requirement = decoded.accepts[0]

    assert requirement.scheme == "exact"
    assert requirement.network == "base-sepolia"
    assert requirement.max_amount_required == CATALOGUE["/market/snapshot"]["atomic"]
    assert requirement.asset.startswith("0x")
    assert requirement.pay_to.startswith("0x")
    assert requirement.max_timeout_seconds > 0


def test_prices_are_atomic_unit_strings(seller):
    """The protocol carries atomic units as strings, and so must the mock.

    A price expressed as a JSON number would have lost precision before any implementation read
    it -- the same reason AEGS-0.1-ARITH-9 requires string amounts in the test vectors. A mock
    that emitted `0.01` would be teaching the wrong shape.
    """
    from x402.http.utils import decode_payment_required_header

    _, headers, _ = get("/premium/feed")
    requirement = decode_payment_required_header(headers["PAYMENT-REQUIRED"]).accepts[0]

    assert isinstance(requirement.max_amount_required, str)
    assert requirement.max_amount_required == "2500000", "2.50 USDC is 2500000 atomic units"


def test_a_paid_resource_is_402_until_a_payment_header_arrives(seller):
    assert get("/market/snapshot")[0] == 402
    assert get("/market/snapshot", payment=True)[0] == 200


def test_a_settled_response_carries_a_receipt(seller):
    from x402.http.utils import decode_payment_response_header

    status, headers, body = get("/market/snapshot", payment=True)
    assert status == 200
    assert "PAYMENT-RESPONSE" in headers

    settled = decode_payment_response_header(headers["PAYMENT-RESPONSE"])
    assert settled.success is True
    assert body["data"]["mock"] is True


# --- it is honest about not settling --------------------------------------


def test_the_mock_says_it_does_not_settle(seller):
    """`/health` reports `settles: false`, so a caller can tell what it is talking to.

    Not decoration. Somebody will eventually point a real agent at the wrong port, and a seller
    that cannot be asked whether it settles is one that will be assumed to.
    """
    _, _, body = get("/health")
    assert body["settles"] is False
    assert body["seller"] == "mock"


def test_any_payment_header_is_accepted(seller):
    """Stated as a test because it is a **limitation**, not a feature.

    Verifying a signature needs a facilitator; settling needs a chain. Neither belongs in CI. So
    this asserts the gap exists exactly where the docstring says it does -- if someone later adds
    verification, this test fails and the documentation has to be corrected with it.
    """
    request = urllib.request.Request(BASE + "/market/snapshot")
    request.add_header("X-PAYMENT", "this is not a signature and is not checked")
    response = urllib.request.urlopen(request, timeout=5)
    assert response.status == 200


def test_the_transaction_id_is_obviously_fake(seller):
    """A plausible-looking hash would get pasted into a block explorer by somebody.

    Finding nothing there is a worse five minutes than reading `0xMOCK` and knowing immediately.
    """
    from x402.http.utils import decode_payment_response_header

    _, headers, _ = get("/market/snapshot", payment=True)
    settled = decode_payment_response_header(headers["PAYMENT-RESPONSE"])
    assert "MOCK" in settled.transaction.upper()


# --- the shape ------------------------------------------------------------


def test_free_endpoints_need_no_payment(seller):
    """Price discovery must cost nothing, or `quote()` is not free and the buyer's whole
    free-discovery design is defeated."""
    for path in ("/health", "/catalogue"):
        assert get(path)[0] == 200, path


def test_the_catalogue_lists_every_resource(seller):
    _, _, body = get("/catalogue")
    assert {e["path"] for e in body["endpoints"]} == set(CATALOGUE)


def test_there_is_something_expensive_enough_to_be_refused(seller):
    """C2.5: every quickstart ends in a refusal. That needs a resource the starter policy will
    actually refuse -- a catalogue of one-cent endpoints cannot demonstrate a spend cap."""
    from x402.http.utils import decode_payment_required_header

    _, headers, _ = get("/expensive/report")
    requirement = decode_payment_required_header(headers["PAYMENT-REQUIRED"]).accepts[0]
    assert int(requirement.max_amount_required) >= 10_000_000, (
        "nothing in the catalogue is expensive enough for a refusal to be demonstrable"
    )


def test_an_unknown_resource_is_404_not_402(seller):
    """Charging for something that does not exist would be its own kind of wrong."""
    status, _, body = get("/nope")
    assert status == 404
    assert "no such resource" in body["error"]


def test_requests_are_counted(seller):
    """So a test can assert the agent *reached* the seller. An agent that decided not to buy
    anything and an agent that could not reach the seller look identical from the outside."""
    get("/health")
    get("/health")
    get("/market/snapshot")
    assert Handler.calls["/health"] == 2
    assert Handler.calls["/market/snapshot"] == 1


def test_it_binds_localhost_only(seller):
    """Invariant 13's reasoning, applied to a fixture that sits beside a governance layer."""
    assert seller.server_address[0] == "127.0.0.1"
