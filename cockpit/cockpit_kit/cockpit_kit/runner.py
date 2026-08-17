"""Drive an async agent from Streamlit without fighting the event loop.

Streamlit runs the script synchronously and reruns it on every interaction, so an
async generator that streams for 30 seconds cannot be awaited inline. The agent
therefore runs on its own thread with its own event loop, and events cross back on
a queue that the main thread drains while updating placeholders.

Any agent module exposing `run(...) -> AsyncIterator[dict]` works here. That is the
only thing the kit requires of an agent, which is what lets one cockpit serve
three frameworks.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Iterator
from typing import Any

END = "__end__"


def stream_agent(module: Any, kwargs: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Run `module.run(**kwargs)` on a worker thread, yielding its events.

    Yields in the main thread, so callers can update Streamlit widgets directly.
    The worker owns the event loop; nothing async escapes it.
    """
    events: queue.Queue = queue.Queue()

    def worker() -> None:
        async def go() -> None:
            async for event in module.run(**kwargs):
                events.put(event)

        try:
            asyncio.run(go())
        except Exception as exc:  # pragma: no cover - defensive
            events.put(
                {"kind": "error", "message": f"{type(exc).__name__}: {exc}"}
            )
        finally:
            events.put({"kind": END})

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    while True:
        try:
            event = events.get(timeout=0.25)
        except queue.Empty:
            # Yield a heartbeat so the caller can refresh elapsed-time widgets
            # while the agent is thinking.
            yield {"kind": "__tick__"}
            continue
        if event.get("kind") == END:
            break
        yield event

    thread.join(timeout=5)
