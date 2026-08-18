"""The sweep harness: planning, accounting and reporting.

None of these spend anything. The parts worth testing are the ones that decide
*what* to run and how to report it -- a harness that quietly drops a failed cell,
or averages a single sample, produces a table that looks better than the run was.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parents[1]

#: `matrix.py` moved to `harness/` with the other measurement code (PLAN.md C6).
MATRIX = AGENTS_DIR.parent / "harness" / "matrix.py"
assert MATRIX.is_file(), f"{MATRIX} is not there; the layout changed"
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

import matrix  # noqa: E402


def cell(framework="adk", provider="gemini", governed=False, ok=True, **kw):
    return matrix.Cell(
        framework=framework, provider=provider,
        model=matrix.FRAMEWORKS[framework]["providers"][provider],
        governed=governed, ok=ok, **kw,
    )


# --- planning -------------------------------------------------------------


def test_compare_mode_pairs_every_cell_governed_and_ungoverned():
    combos = matrix.plan(["adk"], None, [False, True])
    assert combos == [("adk", "gemini", False), ("adk", "gemini", True)]


def test_a_provider_filter_narrows_the_sweep():
    combos = matrix.plan(["langgraph"], ["openai"], [False])
    assert combos == [("langgraph", "openai", False)]


def test_langgraph_sweeps_both_providers_by_default():
    """It is the provider-agnostic framework; that is the point of having it."""
    providers = {p for _f, p, _g in matrix.plan(["langgraph"], None, [False])}
    assert providers == {"gemini", "openai"}


def test_adk_is_gemini_only():
    providers = {p for _f, p, _g in matrix.plan(["adk"], None, [False])}
    assert providers == {"gemini"}


def test_every_configured_model_is_named_not_defaulted():
    """A sweep that let each agent pick its own default would not be comparable."""
    for framework, spec in matrix.FRAMEWORKS.items():
        for provider, model in spec["providers"].items():
            assert model, f"{framework}/{provider} has no pinned model"


# --- accounting -----------------------------------------------------------


def test_the_estimate_scales_with_the_number_of_cells():
    small = len(matrix.plan(["adk"], None, [False])) * matrix.ESTIMATE_PER_RUN_USD
    big = len(matrix.plan(["adk", "langgraph"], None, [False, True])) * matrix.ESTIMATE_PER_RUN_USD
    assert big > small


def test_the_estimate_is_an_upper_bound_on_measured_runs():
    """Measured runs are $0.0007-$0.003; the estimate must over-warn, not under."""
    assert matrix.ESTIMATE_PER_RUN_USD >= 0.003


# --- reporting: the honesty rules ----------------------------------------


def test_a_failed_cell_appears_in_the_table():
    text = matrix._fmt_matrix([cell(ok=False, error="RateLimitError: no credits")])
    assert "FAIL" in text
    assert "RateLimitError" in text


def test_a_failed_pair_is_reported_as_not_comparable_not_silently_skipped():
    """Comparing against a run that never happened would invent a number."""
    text = matrix._fmt_compare(
        [cell(governed=False, ok=True, llm_cost_usd=0.0007),
         cell(governed=True, ok=False, error="quota")]
    )
    assert "not comparable" in text
    assert "governed run failed" in text


def test_a_missing_half_of_a_pair_is_reported():
    text = matrix._fmt_compare([cell(governed=False, ok=True, llm_cost_usd=0.0007)])
    assert "incomplete pair" in text


def test_a_complete_pair_reports_both_costs_and_the_difference():
    text = matrix._fmt_compare(
        [cell(governed=False, ok=True, llm_cost_usd=0.001),
         cell(governed=True, ok=True, llm_cost_usd=0.0012, decisions=2, refused=0)]
    )
    assert "0.001000" in text and "0.001200" in text
    assert "20.0%" in text


def test_the_comparison_refuses_to_call_model_variance_an_overhead():
    """The load-bearing caveat. Without it the table reads as '20% overhead'."""
    text = matrix._fmt_compare(
        [cell(governed=False, ok=True, llm_cost_usd=0.001),
         cell(governed=True, ok=True, llm_cost_usd=0.0012, decisions=2)]
    )
    assert "not the layer's cost" in text
    # A *range*, not a point. This asserted `128 us` for as long as that figure was quoted,
    # and EXP-007 then measured p50 across ten runs at 139-330 us -- putting the single-run 128
    # below the observed minimum. A test that pins an over-precise number keeps it alive, so this
    # now requires the spread to be stated rather than a headline.
    assert "us" in text, "no deterministic overhead figure at all"
    assert "139-330" in text, (
        "the overhead is quoted without its spread. p50 varies 2.4x across identical runs "
        "(EXP-007), so a single number reads as precision the measurement does not have."
    )
    assert "no tokens" in text


def test_refusing_engines_are_named_in_the_comparison():
    text = matrix._fmt_compare(
        [cell(governed=False, ok=True, llm_cost_usd=0.001),
         cell(governed=True, ok=True, llm_cost_usd=0.001, decisions=3, refused=1,
              engines=["treasury"])]
    )
    assert "treasury" in text


def test_a_cell_serialises_to_plain_data():
    import json

    json.dumps(cell(governed=True, decisions=2, engines=["policy"]).as_dict())


def test_a_ceiling_stop_is_carried_on_the_cell():
    assert cell(governed=True, ceiling_stopped=True).as_dict()["ceilingStopped"] is True


# --- the structural claim -------------------------------------------------


def test_the_sweep_imports_no_llm_sdk():
    """It drives agents; it must not know how any of them talks to a model."""
    import ast

    banned = {"openai", "anthropic", "groq", "langchain_openai", "google.adk"}
    source = MATRIX
    offenders = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            if name.split(".")[0] in {b.split(".")[0] for b in banned}:
                offenders.append(f"matrix.py:{node.lineno} imports {name}")
    assert not offenders, "\n  ".join(offenders)


def test_every_framework_in_the_sweep_can_actually_be_loaded():
    for framework in matrix.FRAMEWORKS:
        module = matrix._load(framework)
        assert hasattr(module, "run"), f"{framework} exposes no run()"


def test_every_framework_in_the_sweep_accepts_governance():
    """`--compare` is meaningless against an agent that cannot be governed."""
    for framework in matrix.FRAMEWORKS:
        module = matrix._load(framework)
        params = set(module.run.__code__.co_varnames[: module.run.__code__.co_argcount])
        assert {"governor", "budget_usd"} <= params, f"{framework} cannot be governed"
