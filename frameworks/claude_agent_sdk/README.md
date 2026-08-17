# `claude_agent_sdk` — Claude Agent SDK x402 buyer + Streamlit cockpit

A second buyer for the same seller in `src/server/`, written in Python on the
**Claude Agent SDK**, with a Streamlit UI that shows what it spent and what it
bought.

The agent has no filesystem, no bash and no web access. `tools=[]` strips the
Agent SDK's built-in toolset, so the only capability it has is six x402 tools —
three free, three paid. If it wants a number, it has to buy it.

![The Streamlit cockpit after a completed run: guardrails in the sidebar, both
wallet balances, and the run's LLM cost, USDC spend and answer](../image.png)

The run above cost **$0.022281** of LLM budget and **$0.015 USDC** across 2 paid
calls, and moved the balances for real: buyer `19.985000`, seller `0.015000`.

## Two budgets, two kinds of money

The UI shows both side by side because they are easy to confuse:

| Budget | What it buys | Real money? | Enforced by |
|---|---|---|---|
| **LLM cost (USD)** | Anthropic tokens | **Yes** | `max_budget_usd` per run + a lifetime ledger on disk |
| **USDC spend (USD)** | x402 market data | No — Base Sepolia testnet | `X402Buyer.spend_cap_usd`, checked *before* signing |

Defaults are tuned for cheap testing: model `claude-haiku-4-5`, **$0.04 per
run**, **$0.25 lifetime cap**. A measured full run — catalogue, quote, two
purchases, written answer — costs about **$0.022** (5 turns, ~8.9k input / 1.5k
output tokens), so the cap is roughly 10 full runs.

$0.02 per run was the original default and it truncated this task about half the
time, so don't lower it much below $0.04 unless the task is smaller.

The lifetime total is journalled to `agents/claude_agent_sdk/.spend-ledger.json`, so the cap
survives restarts. `preflight()` refuses to start a run once it is reached; the
sidebar has a reset button.

> **The two budgets look alike to the model.** The Agent SDK injects the
> remaining *LLM token* budget into the agent's context, and an early version of
> this agent read that figure as its *payment* budget and made purchase decisions
> off it. The system prompt now separates them explicitly and names
> `check_budget` as the only authority on payment budget. Keep that distinction
> if you edit the prompt.

## Install

```powershell
cd D:\learning-poc\x402\agents\claude_agent_sdk
uv venv .venv
uv pip install --python .venv\Scripts\python.exe "claude-agent-sdk" "x402[evm,httpx]" streamlit python-dotenv
```

`pip install -e .` works too. Python 3.11+.

Configuration is read from the **repo-root `.env`** — the same file the
TypeScript agent uses, so both share one wallet and one seller URL. An optional
`agents/claude_agent_sdk/.env` overrides it. Everything else (model, budgets, retries) is a UI
control, not an env var.

## Get testnet funds

`.env` ships with `BUYER_PRIVATE_KEY=0x` and
`SELLER_ADDRESS=0x0000000000000000000000000000000000000000`, so **no payment can
settle until you do this**. Until then the facilitator rejects every payment with
`invalid_exact_evm_insufficient_balance` — the agent handles that cleanly and
reports it, but it never gets the data.

1. **Create a wallet.** From the repo root:

   ```powershell
   npm run wallet:new
   ```

   Paste the printed `BUYER_PRIVATE_KEY=0x…` line into `.env`.

2. **Set the seller address — and make it a *different* address.** Run
   `npm run wallet:new` a second time and put the new **address** in
   `SELLER_ADDRESS` (the seller never needs a private key).

   Reusing the buyer's own address does technically work — a self-transfer
   settles on-chain and produces a real receipt — but the buyer's balance never
   moves, because the money returns to the same wallet. That makes the demo's
   most visible signal invisible and reads exactly like a broken payment. Use two
   addresses.

3. **Fund the buyer with test USDC.** Open <https://faucet.circle.com>, choose
   **Base Sepolia**, paste the buyer address, request USDC. The faucet needs a
   browser; there is no CLI. A few dollars is plenty — the whole demo spends
   about $0.016 per run.

4. **Confirm it arrived:**

   ```powershell
   agents\claude_agent_sdk\.venv\Scripts\python.exe -m x402_agent.cli --balance
   ```

   ```json
   { "address": "0xeCD0…6d93", "eth": 0.0, "usdc": 20.0,
     "seller": { "address": "0x8F02…5E61", "usdc": 0.0, "isSelfTransfer": false } }
   ```

   It reports **both** sides plus an `isSelfTransfer` flag, and warns when buyer
   and seller are the same address. The UI's Wallet panel shows the same three
   figures.

   **`ETH: 0` is expected and correct** — under the `exact` scheme the buyer only
   signs an EIP-3009 authorization off-chain and the facilitator pays the gas. You
   never need testnet ETH.

5. **Restart the seller after any `.env` change.** `npm run server` runs under
   `tsx watch`, which watches `src/**` and **not** `.env`, and the server reads
   `SELLER_ADDRESS` once at startup. Until you restart it, it keeps advertising
   the old `payTo` and every payment fails with
   `invalid_exact_evm_transaction_simulation_failed` (a USDC transfer to the
   shipped `0x000…0` placeholder reverts in simulation). Check what it is actually
   serving:

   ```powershell
   curl -s http://localhost:4021/catalog | Select-String -Pattern '"payTo":"[^"]*"'
   ```

You do **not** need a Sepolia ETH faucet, a node, or a wallet extension.

## Run

Two terminals from the repo root.

```powershell
# terminal 1 — the seller
npm run server
```

```powershell
# terminal 2 — the UI
agents\claude_agent_sdk\.venv\Scripts\streamlit run x402_agent\app.py
```

Opens on <http://localhost:8501>.

Headless, no browser:

```powershell
agents\claude_agent_sdk\.venv\Scripts\python.exe -m x402_agent.cli --budget 0.04
agents\claude_agent_sdk\.venv\Scripts\python.exe -m x402_agent.cli --task "Is TSLA or USDC-USD riskier? Buy only what you need."
agents\claude_agent_sdk\.venv\Scripts\python.exe -m x402_agent.cli --balance
```

`--no-hard-stop` ignores the lifetime cap. `--help` lists every flag.

## Controls in the sidebar

| Control | Maps to |
|---|---|
| Model | `ClaudeAgentOptions.model` |
| Per-run LLM budget | `max_budget_usd` — the run stops with subtype `error_max_budget_usd` |
| Lifetime LLM cap + hard stop | the ledger gate in `preflight()`; off = per-run budget only |
| Max turns | `max_turns` — a cost-independent ceiling on agentic round trips |
| API retries | `CLAUDE_CODE_MAX_RETRIES` (429/5xx, exponential backoff; every attempt that reaches the model is billed) |
| Per-request timeout | `API_TIMEOUT_MS` |
| USDC spend cap | `X402Buyer.spend_cap_usd` |

## Telemetry view

Live during a run: steps, tokens in/out, USDC spent, tool calls with failures.

After the run, six tabs: **Answer**, **Data purchased** (the actual quotes,
signals and candle tables it paid for, with a close-price chart), **x402
receipts** (per-call price, settlement status, transaction hash linked to
`sepolia.basescan.org`), **Cost & tokens**, **Tool timeline** (every call with
args, outcome, price paid, latency), **History** (every journalled run).

On token counts: the per-step table deduplicates by message id, because parallel
tool calls emit several assistant messages sharing one id with identical usage.
It is still only a partial view, so the headline totals come from the result
message — `model_usage` when present (it is the only figure that includes
subagent activity), else `usage`. The tab labels which source it used.

`total_cost_usd` is a **client-side estimate** from the SDK's bundled price
table, not authoritative billing. Use the Anthropic Console for the real number.

## Layout

```
agents/claude_agent_sdk/
├── pyproject.toml
├── README.md
└── x402_agent/
    ├── config.py      repo-root .env loading, chain constants, defaults
    ├── buyer.py       X402Buyer: quotes, spend cap, payments, receipt ledger
    ├── tools.py       the six @tool definitions + the in-process MCP server
    ├── agent.py       ClaudeAgentOptions, system prompt, guardrails, event stream
    ├── telemetry.py   per-run telemetry + the persisted lifetime spend ledger
    ├── app.py         Streamlit cockpit
    └── cli.py         headless runner
```

## How payment works here

The `x402` PyPI SDK (2.18.0) speaks protocol **v2** natively — the same version
as the `@x402/*` 2.21.0 packages the TypeScript side uses — so nothing is
reimplemented:

- `register_exact_evm_client(client, EthAccountSigner(account))` registers the
  `exact` scheme for `eip155:*`.
- `wrapHttpxWithPayment(client)` returns an `httpx.AsyncClient` whose transport
  intercepts `402`, decodes the base64 `PAYMENT-REQUIRED` header, signs the
  EIP-3009 `TransferWithAuthorization`, and replays the request with
  `PAYMENT-SIGNATURE`.
- The settlement receipt comes back in `PAYMENT-RESPONSE` and is decoded with
  `decode_payment_response_header`.

`quote()` deliberately uses a plain client instead: it reads the 402, extracts
`accepts[0].amount` (atomic units — `"1000"` is $0.001 at 6 decimals) and throws
the response away. Price discovery is free.

Two behaviours worth knowing, both inherited from the seller's middleware:

- **Failed requests are free.** An unknown symbol returns 404, and the
  middleware cancels the verified authorization on any non-2xx, so the buyer is
  not charged. The tools report `charged: false` in that case.
- **The cap is checked before signing.** `get_paid()` quotes first and raises
  `SpendCapExceeded` rather than signing an authorization it cannot afford.

## Verified end to end

Against the live `x402.org/facilitator` on Base Sepolia, with a funded wallet and
two distinct addresses:

- free `/catalog` read; correct quotes for all three paid routes ($0.001 /
  $0.005 / $0.01), `/catalog` correctly detected as unpaywalled
- spend cap raises before signing when the price exceeds the remainder
- lifetime-cap hard stop, and the "per-run budget exceeds what's left" gate, both
  refuse to start
- **settlement confirmed on-chain** — two real USDC `Transfer` events matching
  the receipts in the UI:

  | amount | transaction |
  |---|---|
  | $0.010000 | [`0x766334…f45d5`](https://sepolia.basescan.org/tx/0x766334148944f5e22e887bca89e297bd07bd147986a81ac75a6d651ef5cf45d5) |
  | $0.005000 | [`0xf78ee4…dc1da`](https://sepolia.basescan.org/tx/0xf78ee4744055a9482a7f795cee25198de64eaf732f74a0b5e5b7d3dbd36dc1da) |

- **balances move**: buyer `20.000000` → `19.985000`, seller `0.000000` →
  `0.015000` after a run that bought signals ($0.01) and ETH-USD candles ($0.005)
- full Haiku 4.5 run: catalogue → quote → 2 purchases → prose answer naming the
  purchased figures, `$0.022281` LLM (56% of the $0.04 budget), 5 turns, 23.3s

This closes the one link `todo.md` recorded as untested for the TypeScript agent —
a settled payment. Both agents share the same wallet, seller and facilitator, so
the TS path settles too.

## Notes

- Starting the app prints `claude.ai connectors are disabled because
  ANTHROPIC_API_KEY … takes precedence`. Harmless — the SDK is telling you it is
  using the API key from `.env`.
- On Windows use PowerShell, not Git Bash, for any command with a leading-slash
  path argument (Git Bash rewrites `/market/snapshot` into a Windows path). This
  affects `npm run probe`; the Python CLI takes no such arguments.
- `streamlit run` executes `app.py` as a top-level script, not as a package
  module, so `app.py` puts its own package directory on `sys.path` and imports absolutely.
  Testing it with `python -m x402_agent.app` alone will not catch a relative-import
  regression — run `python x402_agent/app.py` too.
- `.spend-ledger.json` and `.seller-wallet.json` are local state, both gitignored
  in the repo root `.gitignore`. The seller wallet file exists only so testnet
  USDC sent to the seller stays recoverable; the seller itself never needs a key.
