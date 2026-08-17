"""The agents must stay independent of each other.

The structural claim of this folder is that three agents share one protocol layer
and nothing else. If one agent ever imports another, that claim quietly stops being
true -- and the "swap the framework" story with it. So it is asserted, not assumed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parents[1]
NEWLINE_INDENT = chr(10) + "  "

AGENT_PACKAGES = {
    "langgraph": AGENTS_DIR / "langgraph" / "langgraph_x402",
    "google_adk": AGENTS_DIR / "google_adk" / "adk_x402",
    "claude_agent_sdk": AGENTS_DIR / "claude_agent_sdk" / "x402_agent",
}
CORE = AGENTS_DIR / "x402_core" / "x402_core"

# What each agent is allowed to reach for, beyond the standard library.
FOREIGN = {
    "langgraph": {"google.adk", "adk_x402", "claude_agent_sdk", "claude_agent_sdk.x402_agent"},
    "google_adk": {"langgraph", "langchain_core", "langchain_openai", "langgraph_x402"},
    # The Claude agent may import aegl (it is a host of the governance layer), but
    # never another agent.
    "claude_agent_sdk": {"langgraph", "langgraph_x402", "adk_x402", "google.adk"},
}


def _imports(path: Path) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, node.lineno))
    return found


@pytest.mark.parametrize("name", sorted(AGENT_PACKAGES))
def test_agent_does_not_import_another_agent(name):
    offenders = []
    for path in AGENT_PACKAGES[name].rglob("*.py"):
        for module, line in _imports(path):
            for banned in FOREIGN[name]:
                if module == banned or module.startswith(banned + "."):
                    offenders.append(f"{path.name}:{line} imports {module}")
    assert not offenders, (
        f"the {name} agent reached into another agent:\n  " + "\n  ".join(offenders)
    )


def test_no_other_agent_imports_the_claude_agent():
    """`x402_agent` is the Claude agent's package. The others must not reach into it."""
    offenders = []
    for name, pkg in AGENT_PACKAGES.items():
        if name == "claude_agent_sdk":
            continue  # its own modules import it, obviously
        for path in pkg.rglob("*.py"):
            for module, line in _imports(path):
                if module.startswith("x402_agent"):
                    offenders.append(f"{name}/{path.name}:{line} imports {module}")
    assert not offenders, NEWLINE_INDENT.join(offenders)


def test_aegoll_imports_no_agent():
    """The governance layer depends on the payment rail, never on an agent.

    This is the structural claim behind "universal plugin": if the layer imported one
    agent's package it could not honestly be installed into another framework.

    Resolved from the **installed** `aegoll`, and asserted to exist. The prototype's
    version read

        aegl_pkg = AGENTS_DIR.parent / "aegl" / "aegl"

    which was correct inside the monorepo. Moved here, that path resolves to nothing,
    `rglob` yields nothing, and the test **passed while checking nothing** — no error,
    no failure, just a silent stop. That is a worse outcome than a red test, and it is
    the third time this exact shape has appeared in this restructure.
    """
    aegoll = pytest.importorskip(
        "aegoll", reason="the governance layer is not installed; `pip install aegoll`"
    )
    assert aegoll.__file__ is not None, "aegoll is a namespace package, not a real one"
    pkg = Path(aegoll.__file__).resolve().parent

    modules = list(pkg.rglob("*.py"))
    assert modules, f"{pkg} holds no modules — this test would pass by checking nothing"

    agent_packages = {"x402_agent", "langgraph_x402", "adk_x402", "claude_agent_sdk"}
    offenders = []
    for path in modules:
        for module, line in _imports(path):
            if module.split(".")[0] in agent_packages:
                offenders.append(f"{path.relative_to(pkg)}:{line} imports {module}")
    assert not offenders, (
        "aegoll reached into an agent package:" + NEWLINE_INDENT
        + NEWLINE_INDENT.join(offenders)
    )


def test_the_buyer_is_not_duplicated():
    """One implementation of the code that signs payments.

    A second copy diverging silently is the worst failure mode available here.
    """
    source = (AGENTS_DIR / "claude_agent_sdk" / "x402_agent" / "buyer.py").read_text(
        encoding="utf-8"
    )
    assert "from x402_core.buyer import" in source
    assert "class X402Buyer" not in source, "buyer implementation duplicated again"


def test_core_imports_no_framework_and_no_llm_sdk():
    """x402_core must stay pure protocol.

    The moment it imports a framework or a model client, it stops being the thing
    three different agents can share.
    """
    banned = {
        "langgraph", "langchain_core", "langchain_openai", "google.adk",
        "openai", "anthropic", "groq", "claude_agent_sdk",
    }
    offenders = []
    for path in CORE.rglob("*.py"):
        for module, line in _imports(path):
            root = module.split(".")[0]
            if module in banned or root in {b.split(".")[0] for b in banned} - {"google"}:
                offenders.append(f"{path.name}:{line} imports {module}")
            if module.startswith("google.adk"):
                offenders.append(f"{path.name}:{line} imports {module}")
    assert not offenders, (
        "x402_core is no longer framework-agnostic:\n  " + "\n  ".join(offenders)
    )


def test_every_agent_uses_the_shared_prompt_and_descriptions():
    """Comparability depends on the models seeing identical tool text."""
    for name, pkg in AGENT_PACKAGES.items():
        source = "\n".join(p.read_text(encoding="utf-8") for p in pkg.rglob("*.py"))
        assert "SYSTEM_PROMPT" in source, f"{name} does not use the shared system prompt"
        assert "DESCRIPTIONS" in source, f"{name} does not use the shared tool descriptions"


def test_agents_report_the_same_telemetry_shape():
    import sys

    for sub in ("x402_core", "langgraph", "google_adk"):
        p = str(AGENTS_DIR / sub)
        if p not in sys.path:
            sys.path.insert(0, p)

    from x402_core import RunTelemetry

    keys = set(RunTelemetry(framework="f", provider="p", model="m").as_dict())
    expected = {
        "framework", "provider", "model", "llmCostUsd", "inputTokens", "outputTokens",
        "steps", "toolCalls", "wallClockS", "stopReason", "error", "answer",
    }
    assert expected <= keys
