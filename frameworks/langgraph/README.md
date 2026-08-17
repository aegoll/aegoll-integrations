# LangGraph + OpenAI x402 agent

Buys market data over x402 using `langgraph.prebuilt.create_react_agent`.

```powershell
cd D:\learning-poc\x402\agents
.venv\Scripts\python.exe run_agent.py langgraph
.venv\Scripts\python.exe run_agent.py langgraph --provider gemini   # same harness, different model
```

## Status

Wiring verified: the agent builds, binds all six tools, and reaches the API.
**OpenAI returns `429 — no credits remaining`**, which is an account state rather
than a defect. Add credits and it runs unchanged.

Proven on `--provider gemini`: full tool loop, real settlement of $0.001 USDC
([`0x8300de7c…`](https://sepolia.basescan.org/tx/0x8300de7cedfc6a67213b88abb3132c40f81d4f67df9fc41239ae83b0f658ef55)),
4 steps, $0.002825 of tokens.

## Notes

- `ChatOpenAI(stream_usage=True)` is **required**. Without it a streamed run
  reports zero tokens, which looks like a free agent rather than an unmeasured one.
- Tools are `StructuredTool.from_function(coroutine=...)`, so the shared async
  operations are awaited directly — no thread hop.
- `recursion_limit` is a step ceiling. LangGraph has **no cost ceiling**, so the
  only spend guards are the x402 cap and that limit.
- `build_chat_model()` is the only provider-specific code in the agent.
