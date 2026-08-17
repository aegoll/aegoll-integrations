# `agents/` — the same x402 buying agent on three frameworks

One behaviour, three harnesses, three LLM providers. Each agent buys market data
over x402 from the seller in `src/server/`, within a USDC budget, using the same
six tools and the same prompt.

They exist to be **compared** — and to prove the AEGL governance layer is not
coupled to any one framework.

| Folder | Framework | Provider | Default model | Status |
|---|---|---|---|---|
| `langgraph/` | LangGraph | OpenAI | `gpt-4o-mini` | wiring verified; **OpenAI account has no credits** |
| `google_adk/` | Google ADK | Gemini | `gemini-flash-latest` | ✅ verified end to end, real settlement |
| `claude_agent_sdk/` | Claude Agent SDK | Anthropic | `claude-haiku-4-5` | ✅ verified end to end |

## The architecture, and why

```
                    ┌──────────────────┐
                    │    x402_core     │  wallet · 6 operations · telemetry
                    │  (no framework,  │  no LLM SDK, no agent
                    │   no LLM SDK)    │
                    └────────┬─────────┘
             ┌───────────────┼───────────────┐
             ▼               ▼               ▼
        langgraph/      google_adk/      claude_agent_sdk/
        + OpenAI        + Gemini         + Anthropic
```

**No agent imports another agent.** They share exactly one thing: `x402_core`,
which knows how to pay over x402 and nothing about how an agent decides to. That
separation is enforced by `tests/test_decoupling.py`, not just intended —
including an assertion that `x402_core` never imports a framework or a model
client.

Two things live in `x402_core` that might look like they belong to an agent, and
are there deliberately:

- **The tool descriptions.** They carry the price signal a model reads before
  deciding to spend. If each agent wrote its own, the three would no longer be
  measuring the same thing.
- **The telemetry shape.** A comparison needs identical measurements; three
  incompatible reports would be worthless.

## Run them

```powershell
cd D:\learning-poc\x402\agents
uv venv .venv
uv pip install --python .venv\Scripts\python.exe langgraph langchain-openai `
  langchain-google-genai google-adk "x402[evm,httpx]" pytest

# terminal 1, from the repo root: the seller must be up
npm run server
```

```powershell
.venv\Scripts\python.exe run_agent.py --list
.venv\Scripts\python.exe run_agent.py adk
.venv\Scripts\python.exe run_agent.py langgraph
.venv\Scripts\python.exe run_agent.py adk --task "Which instrument is calmest?" --json
```

Each agent is also importable on its own — `run_agent.py` is a convenience for
driving all three identically, not a dependency.

## Verified

Both new agents settled real payments on Base Sepolia against the live seller:

| Agent | Answer | LLM cost | USDC | Steps/tools | Wall clock |
|---|---|---|---|---|---|
| Google ADK + Gemini | TSLA, 91,344,210 | $0.002027 | $0.001 | 1 / 4 | 38.6s |
| LangGraph + Gemini¹ | TSLA, 91,344,210 | $0.002825 | $0.001 | 4 / 3 | 20.1s |

¹ Run with `--provider gemini` — see the OpenAI note below. Transactions:
[`0x2d1801e2…`](https://sepolia.basescan.org/tx/0x2d1801e2bddc5da1dc77167bc1e4e63e183ab1049073a4085e368873e38cf915),
[`0x8300de7c…`](https://sepolia.basescan.org/tx/0x8300de7cedfc6a67213b88abb3132c40f81d4f67df9fc41239ae83b0f658ef55).

Both reached the same answer through the same tools, which is the result that
matters: the behaviour is in `x402_core`, not in the harness.

## OpenAI: key valid, account empty

The LangGraph agent is wired for OpenAI as asked, and the integration is correct —
it builds the agent, binds the tools, and reaches the API. But every call returns:

```
RateLimitError 429 — You have no credits remaining.
```

That is an account state, not a bug. Add credits at
<https://platform.openai.com/settings/organization/billing> and
`run_agent.py langgraph` works with no code change.

To prove the LangGraph harness itself works meanwhile, `--provider gemini` runs
the same agent on a different model. That option is kept as a real feature rather
than a test hook: it separates *"the framework integration is broken"* from *"this
account cannot serve requests"*, and it is what makes a framework × provider
matrix possible.

## What the frameworks do and do not give you

Directly relevant to the governance work, because it decides what AEGL has to
supply itself:

| | Claude Agent SDK | LangGraph | Google ADK |
|---|---|---|---|
| Tool loop | built in | `create_react_agent` | built in |
| Step ceiling | `max_turns` | `recursion_limit` | `max_llm_calls` |
| **Cost ceiling** | **`max_budget_usd`** | **none** | **none** |
| Tool declaration | `@tool` decorator | `StructuredTool` | function introspection |
| Usage field | `ResultMessage.usage` | `AIMessage.usage_metadata` | `event.usage_metadata` |

**Only the Claude Agent SDK ships a spend ceiling.** On the other two the sole
guards are the x402 spend cap and a step limit — which is a concrete argument for
a governance layer that sits outside the framework rather than relying on one.

## Framework gotchas worth knowing

- **LangGraph**: `ChatOpenAI(stream_usage=True)` is required, or a streamed run
  reports zero tokens — which reads as a free agent rather than an unmeasured one.
- **Google ADK**: tools are plain functions; the declaration is built from the
  name, signature and **docstring**, so the shared descriptions are assigned to
  `__doc__`. Sessions are created through `runner.session_service.create_session`
  (a coroutine) before `run_async`.
- **Gemini models**: the pinned `gemini-2.x` ids return `404 — no longer available
  to new users` on a fresh key, and `gemini-2.0-flash` is gone entirely. The
  moving `-latest` aliases are the defaults for that reason. Their price is
  whatever they currently point at, so the figures in `telemetry.PRICING` can
  drift.
- **ADK partial events**: skipped when counting, or streamed text inflates both
  the step count and the transcript.

## One shared buyer, not three

`x402_core/buyer.py` is the only implementation of the code that signs payments.
It used to be duplicated — the Claude agent carried a byte-identical copy — which
is the worst place in a repo to carry a fork. That agent's `buyer.py` is now a
re-export, and a test (`test_the_buyer_is_not_duplicated`) fails if the class
reappears there.

The tool descriptions and system prompt are shared the same way. Previously the
Claude agent had its own copies, so the three agents were showing their models
subtly different text about what things cost — which quietly undermines the
comparison the three exist to support. `test_every_agent_uses_the_shared_prompt_and_descriptions`
now enforces it.

## Cockpits

Each agent has its own Streamlit UI, so they can be exercised separately:

| Port | Cockpit | Launch from |
|---|---|---|
| 8501 | Claude Agent SDK (+ the AEGL layer) | `claude_agent_sdk/` |
| 8503 | LangGraph | `agents/` |
| 8504 | Google ADK | `agents/` |

```powershell
cd D:\learning-poc@2gents
.venv\Scripts\streamlit run langgraphpp.py  --server.port 8503 --server.address 127.0.0.1
.venv\Scripts\streamlit run google_adkpp.py --server.port 8504 --server.address 127.0.0.1
```

The two new cockpits are ~40 lines each: everything visual comes from
`cockpit_kit/`, which takes any module exposing `FRAMEWORK`, `PROVIDER`,
`DEFAULT_MODEL`, `MODELS` and an async `run()`. Adding a fourth framework means
writing an agent, not an app.

## Layout

```
agents/
├── README.md
├── run_agent.py           drive any agent identically
├── x402_core/             shared protocol layer — the only shared dependency
│   └── x402_core/
│       ├── buyer.py       wallet, quotes, spend cap, receipts
│       ├── toolset.py     the six operations + descriptions + prompt
│       ├── telemetry.py   one measurement shape, plus pricing
│       └── config.py      chain constants, .env loading
├── cockpit_kit/           shared Streamlit cockpit (panels, runner, factory)
├── langgraph/             LangGraph + OpenAI
│   ├── langgraph_x402/agent.py
│   └── app.py             cockpit :8503
├── google_adk/            Google ADK + Gemini
│   ├── adk_x402/agent.py
│   └── app.py             cockpit :8504
├── claude_agent_sdk/      Claude Agent SDK + Anthropic (+ AEGL host)
│   └── x402_agent/        cockpit :8501
└── tests/test_decoupling.py
```
