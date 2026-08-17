# Provenance

Code here was **ported** from the proof-of-concept at
[`Jayzilva/x402`](https://github.com/Jayzilva/x402), which is read-only and stays intact.

Porting was done by copying rather than `git subtree split`, so `git log --follow` does not
reach the prototype's commits. That cost was accepted deliberately; this file and the commit
trailers are the mitigation.

**Source commit:** `e3e295b` (branch `agents`) — the state that recorded 46 passing tests
across three framework agents and the shared protocol layer.

---

## Ported

| Here | From `Jayzilva/x402` | Commit | Changed since |
|---|---|---|---|
| `frameworks/x402_core/` | `agents/x402_core/` | `40dfc06` | unchanged |
| `frameworks/claude_agent_sdk/` | `agents/claude_agent_sdk/` | `40dfc06` | unchanged |
| `frameworks/langgraph/` | `agents/langgraph/` | `40dfc06` | unchanged |
| `frameworks/google_adk/` | `agents/google_adk/` | `40dfc06` | unchanged |
| `frameworks/cockpit_kit/` | `agents/cockpit_kit/` | `40dfc06` | imports an installed `aegoll` instead of a monorepo sibling — `405b95f` |
| `frameworks/tests/` — 46 tests | `agents/tests/` | `40dfc06` | one test stopped passing vacuously — `405b95f` |
| `frameworks/matrix.py`, `run_agent.py` | `agents/` | `40dfc06` | unchanged |

**Baseline verified, not assumed.** The prototype's agents suite could not run when the
port started — `eth_account` and the x402 SDK were absent from the machine. With them
installed, the proof-of-concept scores the documented **46**, and this copy scores **46**.
So the port is checked against a real measurement rather than against a number in a
document.

## Changed after the faithful copy, and why

**The cockpit's governance shim.** It resolved the governance layer as
`Path(__file__).resolve().parents[3] / "aegl"` and inserted that into `sys.path`. Correct
inside one repository; impossible once the layer is a separately installed package. It now
imports `aegoll` the way any consumer would.

**`test_aegoll_imports_no_agent`.** It located the layer by walking up from the tests
directory. Moved here, that path resolved to nothing, so the loop scanned zero files and the
test **passed while checking nothing** — no error, just a silent stop, with the structural
claim behind "universal plugin" going unverified inside a green suite. It now resolves the
package from the installed `aegoll`, asserts the directory holds modules, and skips
explicitly when the layer is absent.

## Not yet ported

| Expected here | From | Task |
|---|---|---|
| `cockpit/` — the Streamlit cockpit | `aegoll/src/aegoll/{app,ui,ui_demo,ui_keys,crossview}.py` | [C4](PLAN.md) / [A2.1](../aegoll/PLAN.md) |
| `harness/` — scenarios and measurement | `aegoll/src/aegoll/{scenarios,evaluation}.py` | [C6](PLAN.md) / [A2.2](../aegoll/PLAN.md) |

Those come *from `aegoll`*, not from the POC: they were ported into the package with
everything else and leave it when the package sheds its UI. Until then, `frameworks/` keeps
the flat shape it had in the prototype rather than being pre-arranged around files that have
not arrived.

## Not ported

| Not ported | Why |
|---|---|
| `src/` — the TypeScript seller and reference buyer | Stays in the POC and keeps running as the counterparty these examples buy from. Second-language evidence is worth more where it is |
| `docs/protocol/` | The best description of the x402 rail anywhere in these repos. Linked, never copied |
