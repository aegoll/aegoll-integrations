# The cockpit

A Streamlit demo and development surface for `tesoro`.

**This is not the supported UI.** It is here to be read, run locally, and copied from. The
supported visual output ships in the package itself:

| | |
|---|---|
| `tesoro report --html -o spend.html` | one self-contained file, four panels, no server — **available now** |
| `tesoro serve` | the same renderer behind a localhost read-only API — 0.2 |

If you want a governed agent's spending on a screen, use one of those. If you want to see what a
richer surface *could* look like, or to hack on one, this is that.

```bash
pip install streamlit tesoro
streamlit run cockpit/app.py
```

## Why it lives here and not in the package

Streamlit is fine for a demo and wrong for a library. 2,534 lines and 58 tests left `tesoro` at
[A2](https://github.com/aegoll/tesoro/blob/main/PLAN.md) for one reason: **nobody installing a
spend cap should get a web framework as a side effect.** A governance layer that drags a web
stack into every install gets declined by exactly the teams worth having, and
`tesoro`'s own test suite now fails if `streamlit` appears anywhere in its dependencies —
including as an extra.

Here it costs a slower CI job and nothing else. That is the whole trade.

## What it demonstrates

- **BYOK key entry**, with `masked()` as the only path a key value takes to the screen. Invariant
  9 says keys are never stored, logged or journalled; `test_ui_keys.py` asserts that no raw key
  reaches the page, and it is the load-bearing test in this directory.
- **The cross-framework comparison view** (`crossview.py`) — the same task run under different
  frameworks and providers, side by side, which is how you see that governance is not coupled to
  any of them.
- **Policy inspection and live decisions**, against real policy packs.

48 tests, in their own CI job. Deliberately separate from the governance gates so a Streamlit
release cannot turn them red.

## What it reaches for that it should not

Stated here rather than quietly worked around, because
[C4.3](https://github.com/aegoll/tesoro-integrations/blob/main/PLAN.md) says so: *if the cockpit
needs a private symbol, that is a gap in the public API* — raise it, do not reach inside.

It needs nine symbols that
[`api-surface.md`](https://github.com/aegoll/tesoro/blob/main/docs/api-surface.md) does not make
public:

| Symbol | For |
|---|---|
| `tesoro.advisors.keys` | BYOK storage and `masked()` |
| `tesoro.advisors.providers` · `test_key` | the key-entry screen |
| `tesoro.advisors.available_models` · `estimate_call_cost_usd` | showing what a model costs before you pick it |
| `tesoro.advisors.advisor_catalogue_safe` | the catalogue, without keys in it |
| `tesoro.config.available_bundles` | listing installed policy packs |
| `tesoro.plugin.NOT_RECOMMENDED` | warning about a model choice |
| `tesoro.plugin.Governor` | the four-call run surface (`authorize_run` / `check_spend` / `settle_run` / `wrap`) |

That last one is worth care: it is **not** `tesoro.Governor`. Same name, different class — the
facade in `tesoro.governor` is the documented Tier 1 surface, while `tesoro.plugin.Governor` is
the prototype's 838-line run surface that the api-surface document explicitly supersedes. A
name-based check reports it as public and is wrong.

Two of these are real API gaps rather than cockpit conveniences, and are the ones worth acting on:

- **listing what is installed** — `available_bundles()` for packs, `available_models()` for
  advisor models. Any host that lets a user *choose* needs to enumerate, and every host will
  write the same private import until this is public.
- **cost before commitment** — `estimate_call_cost_usd()`. The whole economic-gate argument
  depends on knowing what a call costs before making it, so a surface that cannot ask is missing
  the input the design turns on.

The rest are advisor-internal and arguably belong behind the `advisors` extra's own surface
rather than the core's. Raised against
[A0.6](https://github.com/aegoll/tesoro/blob/main/docs/api-surface.md) and recorded in that
document's open-questions list.

## Retire or keep?

Open, and deliberately not decided yet ([C4.8](../PLAN.md)). `tesoro report --html` covers the
read-only case already; `tesoro serve` will cover the live one. Once it does, the question is
whether this remains as the richer demo — key entry, provider comparison, framework matrix — or
is retired. The decision gets recorded either way rather than the directory quietly rotting.
