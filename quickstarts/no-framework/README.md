# Quickstart — no framework

A governed buying agent in about sixty lines. **No framework, no model, no wallet, no testnet.**

This is the shortest possible demonstration that the governance layer needs none of those, which
is why it is worth reading first: every other quickstart is this same loop with a framework
wrapped around it.

```bash
pip install -r quickstarts/no-framework/requirements.txt
python quickstarts/no-framework/run_mock.py
```

That is the whole setup. No keys, no `.env`, nothing to sign up for.

## What you see

```
aegoll: default policy, AEGS 0.1

  bought   /market/snapshot       $ 0.010000
  bought   /market/depth          $ 0.050000
  REFUSED  /premium/feed          $ 2.500000
           verdict : REVIEW
           control : policy
           because : no rule matched; defaulting to review
  REFUSED  /expensive/report      $25.000000
           verdict : REVIEW
           control : treasury, envelope per_transaction
           because : per_transaction (per call (base)) admits $10.000000 but the request is $25.000000

spent      : $0.060000  over 2 settled purchase(s)
by control : policy 3, treasury 1
evidence   : 6 entries, VALID  [sha256, 128 bits]
             caveat: a hash chain detects edits and middle-deletions, not truncation: any
             prefix of a valid chain is itself valid. Closing that needs an external anchor.

OK: 2 refusal(s), 1 of them from an envelope (per_transaction).
```

## The four things worth noticing

**The price is discovered for free, before anything is authorised.** `price_of()` reads the 402
and throws the response away. That is what makes governance possible at all — the amount is known
*before* the decision, so a payment can be refused rather than regretted. A layer that could only
react after settlement would be a report.

**Two refusals, and they are not the same kind.** The `$2.50` one is the policy being *cautious*:
no rule matched an unknown vendor at a non-trivial amount, so it defaults to review. The `$25` one
is a **limit biting** — `treasury`, envelope `per_transaction`, with both numbers in the message.
The script's exit code requires at least one of the second kind, because a run whose only refusals
were cautious defaults has shown the layer hesitating rather than a limit enforcing, and those are
different claims.

**`by control` is the line to read.** Counts by verdict tell you what happened; counts by
*attributed control* tell you what actually governed this agent. Here `policy` decided three times
and `treasury` once — and it is the `treasury` one an operator needs to find at 2am. A
per-payment cap has only one rule to blame, so it can never produce this column.

**Envelopes consume on `settle()`, not on `authorize()`.** `$0.06` was spent, not `$27.56`: the
two refused purchases consumed nothing, and neither would an approved purchase that was abandoned
before payment. That distinction is why the two calls are separate.

## What this does not prove

Stated plainly, because a green run is easy to over-read.

The mock seller **does not verify payments**. It accepts any `X-PAYMENT` header and returns a
synthetic receipt whose transaction id is literally `0xMOCK-NO-CHAIN-INVOLVED`. Verifying a
signature needs a facilitator; settling needs a chain and a funded wallet. Neither belongs in a
quickstart or in CI.

| Proven by this run | Not proven |
|---|---|
| the loop works with no framework and no model | that a signature verifies |
| a decision is made before money moves | that a settlement lands on chain |
| a cumulative envelope consumes on settlement | that a facilitator accepts the payload |
| a limit refuses, naming the control and the envelope | anything about mainnet |
| every step lands in a verifiable hash chain | |

`/health` on the mock reports `settles: false`, so a caller can always ask what it is talking to.

## Real settlement

Point the same loop at a real x402 seller and give it a funded testnet wallet:

```bash
export X402_SELLER_URL=http://localhost:4021    # or any x402 resource server
export X402_PRIVATE_KEY=0x...                   # Base Sepolia. Testnet only.
```

**Testnet only. Never a mainnet key.** The governance layer's job is to make an agent's spending
bounded and explicable; it is not a substitute for keeping a funded key out of an example script.

## The governance in three calls

Strip the printing and the loop is this:

```python
from aegoll import Governor

gov = Governor.load()

atomic = price_of("/market/snapshot")                        # free discovery
decision = gov.authorize(amount_usd=atomic,                  # decide
                         vendor="mock-seller",
                         resource="/market/snapshot")
if decision.approved:
    fetch("/market/snapshot")                                # your payment call, any rail
    gov.settle(decision, success=True)                       # consume the envelope
else:
    print(decision.attributed_control, decision.reason)      # which control, and why
```

`amount_usd` takes an `int` of **atomic units** — which is what the x402 header carries — or a
decimal string like `"2.50"`. A `float` raises: `0.1 + 0.2` is not `0.3`, and there is no rounding
this layer could pick that you would know about.

Next: [`docs/quickstart.md`](https://github.com/aegoll/aegoll/blob/main/docs/quickstart.md) in the
package itself, or [`docs/adapters.md`](https://github.com/aegoll/aegoll/blob/main/docs/adapters.md)
if you are wiring a framework in.
