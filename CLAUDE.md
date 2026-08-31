# CLAUDE.md

> **Project-wide working rules and cross-repo context live in the FCM umbrella repo's `CLAUDE.md`**,
> loaded automatically when you work from the umbrella root. If you opened this repo directly instead
> of via the umbrella, relaunch from the umbrella root for the full context. This file holds only this
> repo's specific instructions.

Instructions for Claude (and other LLM agents) working in this repository.

## What this project is

`evennia-llm-service` makes the LLM call, and loads the prompt that goes into it. That is the whole of
it: a provider client and a template loader, for games in the [Evennia](https://www.evennia.com/)
ecosystem. Tagline: **"The LLM call, and the prompt that goes into it."**

The library is deliberately small. Rate limiting and spend caps belong on the provider's API key,
embedding belongs to `evennia-ai-memory`, per-NPC throttling is a game rule, and prompt *text* belongs
to the consumer. What is left is the call.

For the big-picture overview, read [README.md](README.md).
For the design wiki, read [docs/INDEX.md](docs/INDEX.md).

## Project status

**Stage one complete.** `LLMService.chat_completion` and the prompt loader are implemented and covered
— 53 cases, all green. The library has not yet been installed into FCM.

For what each stage covers and what is decided but not built, read [docs/stages.md](docs/stages.md).
For the running milestone log, read [docs/progress.md](docs/progress.md).

## Where to read first

1. [README.md](README.md) — what the library is and its status.
2. [docs/stages.md](docs/stages.md) — what is in this stage, what is deferred, and why.
3. [docs/test-plan.md](docs/test-plan.md) — every behaviour the library commits to, and the test
   covering it. The scope section lists each deviation from the substrate.
4. [docs/installation.md](docs/installation.md) — settings, `INSTALLED_APPS`, prompts, logging.

## Load-bearing architectural principles

1. **The library does not own game concepts.** NPCs, rooms, factions, quests and the words a character
   says belong to the consumer game. This library provides the call.
2. **No FCM-specific assumptions.** This library is extracted from FullCircleMUD (FCM). FCM prompt
   content, NPC names, zone vocabularies and typeclass names all stay in FCM. Default to "consumer
   concern" when uncertain. `XC-03` asserts it statically.
3. **The library ships no prompt text.** Templates are the game's. The library owns the directory they
   live in and the mechanism that renders them, and nothing about what they say.
4. **Do not enforce what the provider enforces better.** Spend caps and rate limits go on the API key,
   where they apply to actual spend rather than to one process. A limit the library holds is one that
   multiplies by however many processes the consumer runs. `XC-02` and the retired `RL`/`DC`/`CT`
   blocks record this.
5. **Every failure returns `None`, and the reason goes to the log.** The caller's action is the same
   whichever failure it was: use your fallback. This is the substrate's contract, kept for stage one —
   see [docs/stages.md](docs/stages.md) for the agreed replacement.
6. **The library logs to its own file.** Everything goes through `log.py` to `llm_service.log`. Stdlib
   `logging.getLogger` is not used anywhere in the package; `XC-07` asserts it.
7. **The library never dispatches off the calling thread.** Every function is synchronous and returns;
   wrapping the call is the consumer's, and the docs say so. This is what lets a consumer put a memory
   lookup, a prompt render and the completion in *one* `deferToThread` — a library that deferred
   internally would force a hop inside a hop and make the siblings awkward to compose. `XC-08` asserts
   that nothing in the package imports Twisted.

## Out of scope

Decided as questions arise. Rulings so far:

- **Embedding.** `evennia-ai-memory` owns it end to end — its own settings, client and error taxonomy.
- **Rate limiting, spend caps, cost tracking.** The provider's, on the key. See principle 4.
- **Per-NPC throttling.** A game rule. FCM's mixin does it before it reaches the service.
- **Prompt text.** The consumer's. See principle 3.
- **Wiring up a sibling library.** ai-memory is independently installable and documents its own
  `INSTALLED_APPS` line.

## Working conventions

- **Test-first.** Cases are agreed in [docs/test-plan.md](docs/test-plan.md) before a test is written,
  and the implementation is written to pass them. Every test traces to a case ID; the
  `library-standards-linter` enforces both directions.
- **Editing design docs.** Update or add design documents whenever an architectural decision is made
  or refined. Capture the *why*, not just the *what*. Index new docs in [docs/INDEX.md](docs/INDEX.md).
- **Don't put implementation detail in this file or README.** Link out to `docs/` instead.
- **License.** BSD 3-Clause. Source files carry an SPDX header on the first line
  (`# SPDX-License-Identifier: BSD-3-Clause`).

## Documentation discipline (load-bearing)

Design documents in `docs/` must reflect decisions **actually discussed and agreed on with the project
owner**. They are not a place to forward-design the system from first principles or extrapolate
"reasonable defaults" from a starting point.

**Rules:**

1. **Only capture what was discussed and agreed.** If the conversation establishes a principle, do not
   extrapolate it into specifics that were not raised — API shapes, retry policies, naming conventions.
2. **Flag open questions explicitly.** Write `[TBD — needs discussion: <what is open>]` so a future
   session picks the topic up deliberately rather than inheriting an unagreed assumption.
3. **Smaller is better.** Three discussed points captured faithfully beat three discussed points plus
   seven invented ones.

The tempting source of unasked-for answers here is FCM's `src/game/llm/` substrate. Carrying one of its
decisions across is an invention unless it has been discussed.

## Repository layout

```
evennia-llm-service/
├── CLAUDE.md                  # this file
├── README.md
├── LICENSE                    # BSD 3-Clause
├── pyproject.toml
├── runtests.py                # standalone test runner (no consumer gamedir needed)
├── docs/                      # design wiki (humans + LLMs)
├── src/
│   └── evennia_llm_service/   # library code (src layout)
│       ├── __init__.py        # the public surface
│       ├── apps.py            # AppConfig — ready() settles the prompts directory
│       ├── log.py             # logging shim → llm_service.log
│       ├── service.py         # LLMService.chat_completion
│       ├── prompt_loader.py   # the prompts directory, loading, rendering, cache
│       └── tests.py           # unit tests (run via runtests.py)
└── tests/                     # standalone test settings (test_settings.py, urls.py)
```

No `examples/` (nothing to demonstrate that the suite does not cover) and no `contrib/` (nothing opt-in
exists yet; the standards forbid scaffolding one empty).

## Tools and environment

- Python 3.10+ (pinned via `pyproject.toml`).
- Runtime dependencies: `evennia` and `openai`. The client is OpenAI-compatible, so the provider is
  whatever `LLM_API_BASE_URL` points at — OpenRouter by default.
- Tests run through Django's test runner via `python runtests.py` — not pytest. No gamedir required.
- The provider is faked by assigning `LLMService._client`; the class caches it, so no production code
  changes for testability.
- Development uses a dedicated venv at `venv/` (gitignored), independent of any consumer game.

## Sibling libraries to reference

- **[../evennia-ai-memory/](../evennia-ai-memory/)** — owns embedding and NPC memory. The library this
  one sits closest to; see [docs/interoperability.md](docs/interoperability.md).
- **[../evennia-shards/](../evennia-shards/)** — the `log.py` shim this library's copies, and the
  reference for the test-runner pattern.
- **[../evennia-message-bus/](../evennia-message-bus/)** — the `AppConfig` shape.
