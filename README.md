# tesoro-integrations

**Governed agents you can run.** How to put [`tesoro`](https://github.com/aegoll/tesoro)
between an agent and its wallet on each framework, and what governance looks like when it
actually fires.

> **Status: pre-release.** Three framework agents from the proof-of-concept are being ported
> here. See [`PLAN.md`](PLAN.md).

---

## Pick by what you want to see

| I want to… | Go to |
|---|---|
| Govern an agent in five minutes | `quickstarts/` |
| See the same behaviour on four frameworks | `frameworks/` |
| See a specific governance control fire | `usecases/` |
| Watch it happen on a screen | `cockpit/` |
| Reproduce a measurement | `harness/` |

## Every quickstart ends in a refusal

Not an approval. **A spend cap that has never refused anything has not been demonstrated** —
so each quickstart runs against a mock seller with no wallet and no testnet, shows the layer
saying no, and shows the real-settlement variant second.

## Frameworks

| Framework | Provider | State in the proof-of-concept |
|---|---|---|
| Claude Agent SDK | Anthropic | verified end to end |
| Google ADK | Gemini | verified end to end, real settlement |
| LangGraph | OpenAI / Gemini | wiring verified; provider account had no credits |
| CrewAI | — | new here, no prototype precedent |
| none | — | a plain Python loop, proving the layer needs no framework at all |

**No agent imports the governor.** The governor wraps the agent, duck-typed, and a test
fails if that reverses — otherwise "plugin" and "dependency" are indistinguishable. The four
agents share exactly one thing, a protocol layer that knows how to pay and nothing about how
an agent decides to.

Two things live in that shared layer deliberately: **the tool descriptions**, because they
carry the price signal a model reads before deciding to spend, and **the telemetry shape**,
because a comparison across frameworks needs identical measurements.

## Use cases

Each is a governance story with a beginning, a refusal, and evidence you can read afterwards
without running anything.

| | What it shows |
|---|---|
| `data-marketplace/` | the baseline: an agent buying market data per call, inside a budget |
| `intent-drift/` | a repurposed agent making a *perfectly ordinary* purchase. Treasury, trust, risk and policy all approve it — only intent knows what it was for |
| `delegation/` | a sub-agent may never claim more authority than its parent |
| `budget-exhaustion/` | the token budget running out mid-run, and why that must reject rather than queue for review |
| `untrusted-vendor/` | trust earned over settlements, revoked by one dispute |
| `aml-structuring/` | forty payments of one cent, paced five minutes apart, nothing refused — **shipped as a demonstration of an open gap** |
| `prompt-injection/` | vendor text trying to talk its way past a layer that does not read prose |
| `custom-policy/` | a user's own rule kind and engine, end to end |
| `evidence-audit/` | emit Decision Records, verify the chain, score them with `aegs-conformance` |

## Ground rules

- **Every example pins `tesoro` from PyPI, never a path install.** An example that only works
  from a local checkout is not an example.
- One virtual environment per framework directory. Three agent frameworks in one environment
  resolve into a fight.
- Keys come from `.env`, are never committed, and are never logged or journalled. A masked
  display path is the only way a key is ever shown.
- The Streamlit cockpit lives here and is a **demo and development surface, not the supported
  UI**. It was deliberately removed from the package: a library that drags a web framework
  into every install gets declined by exactly the teams worth having.
- Examples **link into** the specification and the package docs rather than restating them.
  A copied explanation drifts.

## What the measurements can and cannot show

Every figure in `harness/` is one run or a handful, single-agent, on testnet. Each run stamps
the policy hash, the `tesoro` version and the AEGS version — because the prototype learned the
hard way that a measurement which does not record *which policy it ran against* is invalidated
by the next rule change with no way to notice.

## Related

[`tesoro`](https://github.com/aegoll/tesoro) — the package ·
[`aegs`](https://github.com/aegoll/aegs) — the standard ·
[`Jayzilva/x402`](https://github.com/Jayzilva/x402) — the read-only proof-of-concept, and the
x402 seller these examples buy from

## Licence

Apache-2.0.
