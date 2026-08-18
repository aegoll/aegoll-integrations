"""A mock x402 seller. Stdlib only, no wallet, no testnet, no chain.

Every quickstart in this repository claims it works "against a mock seller with no wallet and
no testnet" (PLAN.md C2.6). That claim was **false**: the only seller was the TypeScript one in
the read-only proof-of-concept, started with `npm run server`, so following a quickstart meant
cloning another repository and running Node. This is the mock that makes the claim true.

**It speaks real x402.** The 402 response carries a genuine `PAYMENT-REQUIRED` header built with
the SDK's own `encode_payment_required_header`, so the buyer's `decode_payment_required_header`
parses it exactly as it parses a live seller's. A mock that invented its own header shape would
prove the agent can talk to *this file* and nothing else.

**What it deliberately does not do is verify a payment.** It accepts any `X-PAYMENT` header and
returns the content plus a synthetic `PAYMENT-RESPONSE`. That is the point: settlement needs a
signer, a funded wallet and a chain, and none of those belong in a quickstart or in CI.

So be precise about what a green run against this mock proves and what it does not:

* **proves** -- the agent's loop works, the governance layer is wired in, a budget is authorised
  before the run, a ceiling stops it mid-run, envelopes consume on settle, and the evidence
  chain records all of it;
* **does not prove** -- that a signature verifies, that a settlement lands on chain, or that a
  facilitator accepts the payload.

The second list is what the testnet variant of each quickstart is for. Conflating the two would
be the same mistake as a test that passes because it checked nothing.
"""

from __future__ import annotations

import argparse
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

#: A Base Sepolia USDC address, and a payee. Both are real testnet values so the payload a buyer
#: builds is well formed; neither is ever used, because nothing here settles.
USDC_BASE_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
PAY_TO = "0x0000000000000000000000000000000000000402"

#: The catalogue. Prices in USDC atomic units (6 decimals), because that is what the protocol
#: carries -- "10000" is one cent. Free endpoints exist so price discovery can be exercised
#: without any payment path at all.
CATALOGUE: dict[str, dict[str, Any]] = {
    "/market/snapshot": {"atomic": "10000", "description": "market snapshot"},
    "/market/depth": {"atomic": "50000", "description": "order book depth"},
    "/premium/feed": {"atomic": "2500000", "description": "premium feed"},
    "/expensive/report": {"atomic": "25000000", "description": "a report worth refusing"},
    "/catalogue": {"atomic": None, "description": "what is for sale, free"},
    "/health": {"atomic": None, "description": "liveness, free"},
}


def _payment_required_header(path: str, atomic: str, description: str) -> str:
    """A real `PAYMENT-REQUIRED` header for this resource.

    Built through the SDK's encoder rather than by hand. If the wire format changes, this breaks
    at the import or the call -- which is the correct failure, because a mock that kept emitting
    last year's shape would let a quickstart pass against a protocol nobody speaks.
    """
    from x402.http.utils import PaymentRequiredV1, encode_payment_required_header
    from x402.schemas.v1 import PaymentRequirementsV1

    return encode_payment_required_header(
        PaymentRequiredV1(
            x402_version=1,
            error=None,
            accepts=[
                PaymentRequirementsV1(
                    scheme="exact",
                    network="base-sepolia",
                    max_amount_required=atomic,
                    resource=path,
                    description=description,
                    mime_type="application/json",
                    pay_to=PAY_TO,
                    max_timeout_seconds=60,
                    asset=USDC_BASE_SEPOLIA,
                )
            ],
        )
    )


def _payment_response_header() -> str:
    """A synthetic settlement receipt.

    `transaction` is an obvious placeholder rather than a plausible hash. A mock returning
    something that looked like a real transaction id would end up pasted into a block explorer
    by somebody, and finding nothing there is a worse five minutes than reading `0xMOCK`.
    """
    from x402.http.utils import SettleResponse, encode_payment_response_header

    return encode_payment_response_header(
        SettleResponse(
            success=True,
            transaction="0xMOCK-NO-CHAIN-INVOLVED",
            network="base-sepolia",
            payer=PAY_TO,
        )
    )


class Handler(BaseHTTPRequestHandler):
    """One handler, three behaviours: free, 402, and paid."""

    #: Reset by `serve()`. Counts what was asked for, so a test can assert the agent actually
    #: reached the seller rather than deciding not to.
    calls: dict[str, int] = {}

    #: HTTP/1.1 so `Content-Length` and status codes behave the way a real seller's do, but
    #: every response closes its connection. With keep-alive on, a client that opens a fresh
    #: connection per request -- which `urllib` does -- leaves the server holding threads until
    #: it stops accepting, and a sixty-request loop times out partway through. A fixture that
    #: works for ten requests and hangs at forty is worse than one that is slightly slower.
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: Any) -> None:
        """Silent. A mock printing to stderr on every request makes a quickstart's output
        unreadable, and the interesting output is the agent's."""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
        path = self.path.split("?")[0]
        Handler.calls[path] = Handler.calls.get(path, 0) + 1

        if path == "/health":
            return self._json({"status": "ok", "seller": "mock", "settles": False})

        if path == "/catalogue":
            return self._json({
                "endpoints": [
                    {"path": p, "atomic": v["atomic"], "description": v["description"]}
                    for p, v in CATALOGUE.items()
                ],
                "asset": USDC_BASE_SEPOLIA,
                "network": "base-sepolia",
                "note": "prices are USDC atomic units, 6 decimals. Nothing here settles.",
            })

        entry = CATALOGUE.get(path)
        if entry is None:
            return self._json({"error": "no such resource: " + path}, status=404)

        if entry["atomic"] is None:
            return self._json({"path": path, "free": True})

        # Paid: 402 unless a payment header is present. The header's *contents* are not checked,
        # which is stated in the module docstring and is the one thing this mock cannot do.
        if not self.headers.get("X-PAYMENT"):
            try:
                header = _payment_required_header(path, entry["atomic"], entry["description"])
            except Exception as exc:  # pragma: no cover - a broken SDK is worth saying out loud
                return self._json(
                    {"error": "cannot build a payment-required header: " + str(exc)},
                    status=500,
                )
            return self._json(
                {"error": "payment required", "resource": path},
                status=402,
                extra_headers={"PAYMENT-REQUIRED": header},
            )

        return self._json(
            {
                "path": path,
                "description": entry["description"],
                "data": {"mock": True, "asOf": "1970-01-01T00:00:00Z"},
            },
            extra_headers={"PAYMENT-RESPONSE": _payment_response_header()},
        )

    def _json(
        self,
        payload: dict[str, Any],
        status: int = 200,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


def serve(port: int = 4021) -> ThreadingHTTPServer:
    """Start the mock on `port` and return the server.

    Binds `127.0.0.1`, never `0.0.0.0`. It is a fixture sitting next to a governance layer, and
    the same reasoning as invariant 13 applies: nothing here should be reachable from a network.

    **Stop it with `running()` or with `shutdown()` *and* `server_close()`.** `shutdown()` alone
    stops the request loop and leaves the listening socket open, so a second `serve()` on the
    same port appears to succeed while requests may reach the abandoned server -- which shows up
    as a timeout several tests later, nowhere near the cause. That cost an hour to find once.
    """
    Handler.calls = {}
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@contextmanager
def running(port: int = 4021):
    """The mock, guaranteed to be shut down and closed.

    Exists so `server_close()` cannot be forgotten -- see `serve()`. Prefer this everywhere.
    """
    server = serve(port)
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="A mock x402 seller. Nothing settles.")
    parser.add_argument("--port", type=int, default=4021)
    args = parser.parse_args()

    server = serve(args.port)
    paid = "  ".join(p for p, v in CATALOGUE.items() if v["atomic"] is not None)
    print("mock x402 seller on http://127.0.0.1:" + str(args.port))
    print("  free    : /health  /catalogue")
    print("  paid    : " + paid)
    print("  settles : no. Any X-PAYMENT header is accepted unverified -- see the docstring.")
    print("Ctrl-C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
