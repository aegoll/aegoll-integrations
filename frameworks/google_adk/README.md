# Google ADK + Gemini x402 agent

Buys market data over x402 using `google.adk.agents.Agent` and `InMemoryRunner`.

```powershell
cd D:\learning-poc\x402\agents
.venv\Scripts\python.exe run_agent.py adk
.venv\Scripts\python.exe run_agent.py adk --model gemini-flash-lite-latest
```

## Status

✅ Verified end to end: catalogue → quote → budget check → purchase → answer, with
a real settlement of $0.001 USDC
([`0x2d1801e2…`](https://sepolia.basescan.org/tx/0x2d1801e2bddc5da1dc77167bc1e4e63e183ab1049073a4085e368873e38cf915)),
$0.002027 of tokens in 38.6s.

## Notes

- Tools are **plain async functions**. ADK builds the declaration from the name,
  signature and docstring, so the shared descriptions are assigned to `__doc__`.
  There is no decorator and no schema object.
- `Agent` is an alias for `LlmAgent`. A session must be created via
  `runner.session_service.create_session(...)` — a coroutine — before `run_async`.
- Everything arrives as `Event`s carrying `google.genai` `Content`. Function calls
  and responses are `Part`s, not distinct event types, so translation inspects
  parts rather than event classes.
- Usage is `event.usage_metadata.prompt_token_count` / `.candidates_token_count`.
- **Partial events are skipped** when counting; ADK streams incremental text and
  counting it inflates both step count and transcript.
- **Model availability**: the pinned `gemini-2.x` ids return `404 — no longer
  available to new users` on a fresh key. The `-latest` aliases are the defaults
  for that reason.
- Like LangGraph, ADK has **no cost ceiling** — only `max_llm_calls` and the x402
  spend cap.
