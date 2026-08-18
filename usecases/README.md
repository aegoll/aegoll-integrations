# Use cases

Six governance stories. Each has a beginning, a refusal, and evidence you can read without
running anything.

```bash
pip install -r usecases/requirements.txt
python usecases/run_all.py          # all six
python usecases/intent-drift/run.py # or one
```

Every case **checks its own claim** and exits non-zero if it stops holding. That is the point of
them being scripts rather than prose: a story about a spend cap that has quietly stopped refusing
things still reads perfectly.

| Case | The claim |
|---|---|
| [`data-marketplace`](data-marketplace/) | the baseline — an agent shops, the layer decides, the expensive thing does not go through |
| [`intent-drift`](intent-drift/) | **treasury, trust, risk and policy all say yes. Only intent knows what the agent was sent to do** |
| [`delegation`](delegation/) | a sub-agent can never claim more than its parent — including the one that declares *nothing* |
| [`budget-exhaustion`](budget-exhaustion/) | an exhausted token budget must **REJECT**; the same breach on a payout is **REVIEW** |
| [`prompt-injection`](prompt-injection/) | counterparty text cannot move a verdict, because nothing on the path reads prose |
| [`aml-structuring`](aml-structuring/) | **nothing is refused.** An open gap, shipped as a runnable artifact |

## Read these two first

**`intent-drift`** is the case that justifies the whole intent engine. An agent sent to buy market
data buys a follower count instead — same amount, same counterparty, same shape. Economically
nothing is wrong, and every economic control agrees:

```
treasury : ok=True  binding=nothing
trust    : 0.4800  no flags
risk     : 0.2100  no flags
policy   : matched rule 'auto-approve-micro'
intent   : `/social/followers` is outside the intent's declared resources
```

No amount of tightening a budget catches that, because nothing about it is a budget problem.

**`aml-structuring`** is the one that succeeds by failing. Forty payments of a tenth of a cent,
0.08% of the daily envelope, **nothing refused**. It ships as a demonstration of
[AEGS-0.1-SEC-6](https://github.com/aegoll/aegs/blob/main/spec/12-security-considerations.md)
rather than a paragraph about it, and it explains why tightening does not help: lowering the
per-call ceiling to a tenth of a cent would still admit all forty, and would refuse every
legitimate purchase in the catalogue.

The day a sequence-shape control lands, that case starts printing **THE GAP HAS CLOSED** and
failing — which is the correct behaviour for a test whose subject is a known weakness.

## How a case is checked

`finish()` takes the control the case is *about*:

```python
return case.finish(expect_refusal_from="intent")
```

A case that refused for an unrelated reason fails. That is
[AEGS-0.1-CONF-2](https://github.com/aegoll/aegs/blob/main/spec/11-conformance.md) applied to an
example: a right ending for the wrong reason teaches the reader something false, and it is no more
acceptable here than in a conformance run. Verified by claiming the wrong control and watching
`intent-drift` go red.

The structuring case inverts it — `expect_no_refusal_because=...` — and nothing else may use that.

## The evidence

Each case writes its Decision Records into its own `evidence/` directory (C5.10), so the output
can be read, diffed and pasted without running Python:

```
usecases/intent-drift/evidence/report.json    the full report, as the wire format
usecases/intent-drift/evidence/audit.jsonl    the hash-chained journal
```

Every run re-verifies the chain, and a case whose evidence does not verify fails regardless of how
its story ended.

## What none of these prove

No signature is verified and nothing settles on a chain. These cases exercise the **decision**
path with no wallet, no testnet and no model key — which is what makes them runnable in CI on a
clean checkout, and what they cannot tell you about.

The [`no-framework` quickstart](../quickstarts/no-framework/) adds a real x402 seller (the
[stdlib mock](../mock/)) if you want to see the protocol in the loop.
