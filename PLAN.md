# `aegoll-integrations` — sub-plan

**Examples, adapters in use, and use cases.** How to govern an agent on each framework,
and what governance actually looks like when it fires.

Master plan: [`../PLAN.md`](../PLAN.md) · Context and rules: [`../CONTEXT.md`](../CONTEXT.md)
Port sources (**read-only**): `../x402/agents/` (three framework agents + `x402_core` + `cockpit_kit`, 46 tests) and the UI/demo modules leaving `../x402/aegl/` — [`../x402-REFERENCE.md`](../x402-REFERENCE.md)

**This repo exists so two claims can be checked rather than asserted:**
*framework-neutral* (the same behaviour on four harnesses) and *not a dependency*
(an agent does not import the governor — the governor wraps the agent).

It is also where everything heavy lives, so the `aegoll` package can stay light.

---

## C0 — Bootstrap ⬜

- [ ] C0.1 Licence Apache-2.0, matching the package
- [ ] C0.2 Layout decided and written in `README.md`:
      `quickstarts/` (5-minute, one per framework) · `frameworks/` (full agents) ·
      `usecases/` (governance stories) · `cockpit/` (Streamlit demo) ·
      `harness/` (matrix + measurement) · `docs/`
- [ ] C0.3 Dependency stance: **every example pins `aegoll` from PyPI, never a path install.** An example that only works from a local checkout is not an example
- [ ] C0.4 One venv per framework directory. Three agent frameworks in one environment will resolve into a fight
- [ ] C0.5 CI runs the offline-testable parts on every push; anything that needs a real key or real settlement is a separate, manual workflow
- [ ] C0.6 `.env.example` with every key named and no key present. Carry the prototype's BYOK discipline: **keys are never committed, logged, or journalled**

**Exit:** repo shaped, CI green on the offline subset.

---

## C1 — Port the three framework agents ✅

- [x] C1.1 Ported faithfully as `frameworks/` — `40dfc06`
- [x] C1.2 [`PROVENANCE.md`](PROVENANCE.md) written — after the copy this time rather than before, which is the wrong way round and is recorded as such
- [x] C1.3 `x402_core/` landed intact — wallet, six tools, the prompt, telemetry
- [x] C1.4 Both deliberate contents of `x402_core` intact — the tool descriptions carrying the price signal, and the telemetry shape
- [x] C1.5 All three framework agents landed intact
- [x] C1.6 `test_decoupling.py` carried — **and one of its assertions was found passing vacuously**, see [F-C1](#f-c1--a-test-that-stopped-checking-without-failing--2026-08-17)
- [x] C1.7 `test_governance_hook.py` carried; the cockpit shim repointed at an installed `aegoll` — `405b95f`
- [x] C1.8 **46 tests green**, matching a freshly measured POC baseline rather than a documented number
- [x] C1.9 Every `aegl` import repointed to `aegoll`
- [ ] C1.10 The seller side stays in `../x402` (`src/server/`, TypeScript). Document how to point an example at it, and how to point one at any other x402 seller instead

**Exit:** three agents running here, 46 tests green, nothing importing `aegl`.

---

## C2 — Quickstarts ⬜

The thing that decides whether anyone uses this. One page each, five minutes each, no
prior knowledge.

- [ ] C2.1 `quickstarts/claude-agent-sdk.md` — Claude Agent SDK, verified end to end in the prototype
- [ ] C2.2 `quickstarts/google-adk.md` — Google ADK, verified end to end with real settlement
- [ ] C2.3 `quickstarts/langgraph.md` — LangGraph (prototype status: wiring verified, provider account had no credits — re-verify or say so)
- [ ] C2.4 `quickstarts/no-framework.md` — a plain Python loop. Proves the layer needs no framework at all, and is the shortest possible demonstration
- [ ] C2.5 Every quickstart ends with a **refusal**, not an approval. A spend cap that has never refused anything has not been demonstrated
- [ ] C2.6 Every quickstart works against a mock seller with no wallet and no testnet, then shows the real-settlement variant second
- [ ] C2.7 Each quickstart's commands run in CI against the mock, so a broken quickstart fails a build instead of a user
- [ ] C2.8 Time each one honestly. If it is not five minutes, change the claim or change the quickstart

**Exit:** four quickstarts, CI-verified against a mock, each ending in a refusal.

---

## C3 — CrewAI, and the fourth adapter ⬜

New ground — no prototype precedent, so budget discovery time rather than porting time.

- [ ] C3.1 Read CrewAI's execution model: where a tool call happens, whether a pre-call hook exists, whether token spend is observable per step
- [ ] C3.2 Write down what the adapter needs from a framework, generalised from the four data points. This becomes the adapter contract in [A7.1](../aegoll/PLAN.md)
- [ ] C3.3 `frameworks/crewai/` — the same behaviour as the other three, same tools, same prompt
- [ ] C3.4 `quickstarts/crewai.md`
- [ ] C3.5 Feed anything the adapter contract could not express back to [A7](../aegoll/PLAN.md) as a finding, not a workaround
- [ ] C3.6 Test: CrewAI agent does not import `aegoll` — the governor wraps it

**Exit:** four frameworks, one contract, and a written list of what the contract failed to cover.

---

## C4 — The cockpit, rehomed ⬜

Streamlit is fine for a demo and wrong for a library. It moves here and stops being
part of anything shipped.

- [ ] C4.1 Receive `app.py` (853 LOC), `ui.py` (383), `ui_demo.py` (128), `ui_keys.py` (190), `crossview.py` (227) from [A2.1](../aegoll/PLAN.md)
- [ ] C4.2 Receive `cockpit_kit/` from `../x402/agents/`
- [ ] C4.3 Repoint to the published `aegoll` public API only. **If the cockpit needs a private symbol, that is a gap in the public API** — raise it against [A0.6](../aegoll/PLAN.md) instead of reaching inside
- [ ] C4.4 Carry the BYOK entry screen and the `masked()` display path unchanged
- [ ] C4.5 Carry the cross-framework comparison view
- [ ] C4.6 `cockpit/README.md` states plainly: demo and development surface, not the supported UI. The supported visual output is `aegoll serve` ([A10](../aegoll/PLAN.md))
- [ ] C4.7 Carry the 14 UI tests from `../x402/aegl/tests/test_ui*.py`
- [ ] C4.8 Once [A10](../aegoll/PLAN.md) ships, decide whether the cockpit is retired or kept as the richer demo. Record the decision either way

**Exit:** cockpit runs here against published `aegoll`, using public API only.

---

## C5 — Use cases ⬜

Each one is a governance story with a beginning, a refusal, and evidence. These are the
examples the white paper points at.

- [ ] C5.1 `usecases/data-marketplace/` — the original: agent buys market data per call, inside a budget. The baseline everything else varies from
- [ ] C5.2 `usecases/intent-drift/` — a repurposed agent making a *perfectly ordinary* purchase that every other engine approves. Treasury, trust, risk and policy all say yes; **only intent knows what it was for**
- [ ] C5.3 `usecases/delegation/` — a parent agent spawning sub-agents. Shows the delegation clamp: a sub-agent may never claim more than its parent
- [ ] C5.4 `usecases/budget-exhaustion/` — the internal channel running out mid-run. Shows why an exhausted token budget must REJECT rather than REVIEW: there is no human to ask mid-run, and starting a run that cannot finish wastes the budget that is already short
- [ ] C5.5 `usecases/untrusted-vendor/` — cold start at 0.25, trust earned over settlements, revoked by one dispute
- [ ] C5.6 `usecases/aml-structuring/` — the open red-team finding as a runnable demo: 40 × $0.001 paced five minutes apart, nothing refused. **Ships as a demonstration of the gap**, then flips to a defended state when [A11](../aegoll/PLAN.md) lands
- [ ] C5.7 `usecases/prompt-injection/` — vendor text trying to talk its way past the layer. Shows the deterministic path ignoring prose entirely
- [ ] C5.8 `usecases/custom-policy/` — a user's own rule kind and engine, end to end, matching [A6.11](../aegoll/PLAN.md)
- [ ] C5.9 `usecases/evidence-audit/` — emit Decision Records, verify the chain, score them with `aegs-conformance`. The full evidence loop in one script
- [ ] C5.10 Every use case emits its Decision Records into the repo so they can be read without running anything

**Exit:** nine use cases, each runnable offline, each producing evidence a reader can inspect.

---

## C6 — The measurement harness ⬜

The measurement code leaves the package and lives here, where a heavy dependency is fine.

- [ ] C6.1 Receive `scenarios.py` (316 LOC) and `evaluation.py` (436 LOC) from [A2.2](../aegoll/PLAN.md)
- [ ] C6.2 Receive `matrix.py` — the framework × provider × governance sweep
- [ ] C6.3 Receive the `bench` and `eval` CLI paths dropped in [A5.13](../aegoll/PLAN.md), as `harness/` scripts
- [ ] C6.4 Reproduce the prototype's sealed baselines against published `aegoll`. Where a number moves, that is a finding, not a nuisance
- [ ] C6.5 New sealed experiment record for anything the packaging changed. **Sealed records are superseded, never edited** — a corrected measurement becomes a new record with `supersedes` pointing back
- [ ] C6.6 Every harness run stamps the policy bundle hash, the `aegoll` version and the AEGS version. The prototype learned this the hard way: nothing had recorded *which policy bundle* a measurement ran against, so a rule change would have invalidated stored results with no way to notice
- [ ] C6.7 `harness/README.md` — what each measurement can and cannot show. Every prototype figure is one run or a handful; do not let a chart imply otherwise

**Exit:** the sweep reproduces, every figure stamped, limits written down.

---

## C7 — Documentation ⬜

- [ ] C7.1 `README.md` — pick an example by what you want to see, not by framework name
- [ ] C7.2 `docs/choose-a-framework.md` — an honest comparison, including where a framework has no cost ceiling at all. Two of the three in the prototype had none, and that is the actual argument for this project
- [ ] C7.3 `docs/cookbook.md` — short recipes: cap a vendor, require review above a threshold, add a custom rule, export evidence for an auditor
- [ ] C7.4 `docs/troubleshooting.md` — carried and extended from `../x402/docs/protocol/07-troubleshooting.md`
- [ ] C7.5 Link discipline: examples link **into** the spec and the package docs, never restate them. A copied explanation drifts

**Exit:** a reader lands, picks an example, and runs it without reading the spec first.

---

## Findings

### F-C1 · A test that stopped checking, without failing — 2026-08-17

`test_aegl_imports_no_agent` asserts the structural claim behind "universal plugin": the
governance layer never imports an agent's package. It located the layer as

```python
aegl_pkg = AGENTS_DIR.parent / "aegl" / "aegl"
```

Correct inside the monorepo. Moved here, that path resolves to nothing, `rglob` yields
nothing, the loop body never runs — and the test **passes**. No error, no failure. The suite
sat at 46 green while the claim went entirely unverified.

**Third instance of one pattern in this restructure**, and the second time this codebase has
produced a vacuously-passing guard:

| Where | Shape |
|---|---|
| [F-A1](../aegoll/PLAN.md) | eleven modules resolving paths outside the package |
| `cockpit_kit/governance.py` | `parents[3] / "aegl"` inserted into `sys.path` |
| this test | a guessed relative path that resolved to nothing, and passed |
| *(prototype, before this work)* | a purity test naming files that had become three-line shims |

The lesson is not "fix the path". It is that **a test which locates its subject by guessing a
relative path has two failure modes, and the silent one is worse.** A red test gets fixed; a
vacuous one gets trusted.

So the fix is more than a repoint: resolve the subject from the *installed* package, assert
it exists and holds modules, and skip explicitly when it is absent. Same discipline as
`aegoll/tests/conftest.py` and `aegoll/tests/test_paths.py`.

**Worth watching for.** Every remaining port is a chance for the same thing. Any test that
builds a path from `__file__` should be treated as suspect until it has been shown to fail
when its subject is missing.
