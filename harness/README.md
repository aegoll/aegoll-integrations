# The measurement harness

Three tools, and one rule that matters more than any of them: **every figure here is stamped with
what produced it, and every figure is a sample unless it says otherwise.**

```bash
python harness/matrix.py --dry-run      # what would run, and the cost estimate
python harness/matrix.py --json         # the sweep, with provenance
python harness/matrix.py --compare      # governed against ungoverned, side by side
```

| Tool | What it does |
|---|---|
| `matrix.py` | framework × provider × governance sweep |
| `scenarios.py` | scripted decision sequences, no provider needed |
| `evaluation.py` | scoring a run against what it was supposed to do |

## Every result carries its provenance

```json
{
  "provenance": {
    "aegoll": "0.1.1",
    "aegs": "0.1",
    "policy": {"name": "default", "hash": "a5a64aeb69dbc5f9206b31022064da26"},
    "measuredAt": "2026-08-18T13:56:47+00:00"
  },
  "cells": [...]
}
```

First key, on purpose: a reader should not be able to reach the numbers without passing what
produced them.

The **policy hash** rather than only its name is the load-bearing part. A label can be reused
across edited rules; a hash cannot. The prototype's plan records this as something it learned the
hard way — nothing had recorded which policy bundle a measurement ran against, so a rule change
would have silently invalidated every stored figure with no way to notice. That is a quiet
failure, which is the worst kind, and it is why `provenance()` **raises** rather than degrading
when a policy cannot be loaded. A stamp with a hole in it invites exactly the interpretation it
exists to prevent.

## What these measurements can show

- **That governance is in the path**, and what it refused. The `--compare` view runs the same
  task governed and ungoverned; a difference in outcome is the layer doing something.
- **The rough cost of a run**, on a given framework and provider, at the moment it was measured.
- **That the same task behaves comparably across frameworks** — which is the claim that
  governance is not coupled to any of them.

## What they cannot show

Stated at this length because a table of numbers invites more confidence than one run deserves.

**One run per cell is a sample, not an average.** Every figure from the prototype was one run or a
handful. `--repeat` averages, and the JSON records `runsPerCell` so a number lifted into a chart
arrives with its sample size attached. A single measurement of a model call tells you about that
call: providers vary by time of day, by region, by load, and by silent model updates.

**LLM cost is what the provider reported, not what it billed.** Token accounting and invoices are
reconciled by the provider, not here.

**Latency includes the network.** The layer's own decision latency is measured separately, and
is worth quoting carefully: ten runs of `aegoll bench -n 3000` against published `aegoll` 0.1.1
gave a p50 **median of ~170 µs** with a range of **139–330 µs** — a 2.4× spread from machine load
alone ([EXP-007](https://github.com/aegoll/aegs/tree/main/research/experiments/EXP-007)).

An earlier single run reported 128 µs, and that figure was repeated in this file, in `matrix.py`
and in a test as though it were a property of the system. It sits *below* the observed minimum of
ten later runs. So: **~200 µs, varying by 2× with load** is the honest short form, and any single
number is a sample. Anything measured in the sweep itself is dominated by a model call and says
nothing about the layer at all.

**A failed cell is reported, never dropped.** A provider error says something real about an
account or a rate limit, and hiding it makes the table look cleaner than the run was. Failures
appear in the output and in `limits.failedCells`.

**Nothing here is a benchmark against another product.** There is no comparison to a competing
governance layer, because no independent implementation of AEGS has been scored — which is the
project's largest open question and is
[W6.4](https://github.com/aegoll/aegoll-integrations/blob/main/PLAN.md), not something a sweep
can answer.

## Two things that were broken here

Recorded because both shipped, and both were the same shape.

**`matrix.py` was unimportable.** It resolved the agents under `harness/` — `HERE / "x402_core"`
and so on — which is where they sat in the prototype's single-repository layout and is nowhere in
this one. `import matrix` raised `ModuleNotFoundError`, and had done since the port, because
nothing imported it. The paths are now asserted at import: a stale entry appended to `sys.path` is
not an error, it is a no-op, which is precisely how the layout could change and nothing complain.

**Nothing was stamped.** C6.6 asked for it and it was not there.

`test_matrix_provenance.py` covers both, including the property that makes the stamp worth having
— editing one rule changes the hash — and the refusal to stamp a hole.

## Cost, before you run it

`--dry-run` prints an upper-bound estimate before anything spends. That exists because the
alternative is discovering the bill afterwards, which is the failure mode this whole project is
about.

Real settlement needs a funded **testnet** wallet. Never a mainnet key in a measurement script.
