# Contributing to `aegoll-integrations`

Apache-2.0. By contributing you agree your work is licensed under it.

This repo's job is to make two claims checkable rather than asserted: that the layer is
**framework-neutral**, and that it is **not a dependency** of the agents it governs.

---

## Ground rules

- **Pin `aegoll` from PyPI.** Never `-e ../aegoll`, never a `file:` URL. An example that only
  works from a local checkout is not an example, and CI fails on path installs.
- **One virtual environment per framework directory.** Three agent frameworks in one
  environment resolve into a fight.
- **No agent imports the governor.** The governor wraps the agent, duck-typed. There is a test
  for this and it is the whole point of the repo — otherwise "plugin" and "dependency" are
  indistinguishable.
- **No agent imports another agent.** They share exactly one thing: the protocol layer that
  knows how to pay and nothing about how an agent decides to.
- **The protocol layer imports no framework and no model client.** Tested, not intended.
- **Keys from `.env`, never committed, never logged.** Copy `.env.example`. If you need a key
  displayed, use the masked path.
- **CI must never spend money or need a wallet.** Anything requiring real settlement or a real
  provider key goes in a separate, manually triggered workflow.

## Adding a framework

1. Read the framework's execution model first and write down where a tool call happens,
   whether a pre-call hook exists, and whether token spend is observable per step. That
   write-up is more valuable than the code.
2. Implement **the same behaviour** as the existing agents — same tools, same prompt. A
   comparison across frameworks is worthless if the agents are doing different work.
3. Anything the adapter contract could not express goes back to `aegoll` as a **finding**, not
   a workaround here. Working around a gap hides it.
4. Add a quickstart, and add the framework to the CI matrix.

## Adding a quickstart

- Five minutes, no prior knowledge, and **time it honestly**. If it is not five minutes,
  change the claim or change the quickstart.
- **It must end in a refusal.** A spend cap that has never refused anything has not been
  demonstrated.
- Mock seller first, no wallet and no testnet. The real-settlement variant comes second.
- The commands must run in CI against the mock, so a broken quickstart fails a build instead
  of a user.

## Adding a use case

Each one is a governance story: a beginning, a refusal, and evidence a reader can inspect
afterwards without running anything. Commit the Decision Records it emits.

If a use case demonstrates an **open gap** rather than a working control — `aml-structuring/`
is the current example — say so in its README, in the first paragraph. A demo that looks like
a defence but is a hole is the worst artifact in the repository.

## Two things live in the shared protocol layer on purpose

Do not move them into individual agents:

- **The tool descriptions**, because they carry the price signal a model reads before deciding
  to spend. If each agent wrote its own, the agents would no longer be measuring the same thing.
- **The telemetry shape**, because a comparison needs identical measurements and three
  incompatible reports are worthless.

## Measurements

Every harness run stamps the policy hash, the `aegoll` version and the AEGS version. A
measurement that does not record *which policy it ran against* is invalidated by the next rule
change with no way to notice — this is a real bug the prototype found, not a hypothetical.

New numbers get a sealed experiment record. Sealed records are superseded, never edited. Where
a ported measurement moves relative to the prototype's baseline, that is a **finding** to write
up, not a nuisance to smooth over.

## Documentation

Link **into** the specification and the package docs. Do not restate them — a copied
explanation drifts, and the copy is always the one someone reads.

## Commits

Present tense, imperative. No attribution trailers. Porting commits carry
`Ported-from: Jayzilva/x402@<sha> <path>` and copy faithfully first.
