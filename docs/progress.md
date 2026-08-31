# Progress

Running log of milestones with links to evidence. Reverse chronological — newest first.

## 2026-08-31 (latest)

- **Live-tested in a running Evennia game.** A demo gamedir at `examples/demo-game/` installed the
  library, booted, and made a real call to OpenRouter that came back in character. Everything the unit
  suite cannot reach was exercised: `AppConfig.ready()` fired, the prompts directory was created and
  resolved to `examples/demo-game/llm_service/prompts` rather than the package, a template loaded and
  rendered with its placeholders filled, and the completion returned content. Only `LLM_API_KEY` was
  set — the other four defaults carried the rest.

  Not exercised, and worth knowing before FCM: the off-thread dispatch (the test called
  `chat_completion` straight from `py`, which blocked the server for the duration) and anything under
  shards.

- **Stage one implemented — 54 tests, all green.** `LLMService.chat_completion` and `_get_client` in
  `service.py`; the prompts directory, loading, rendering and cache in `prompt_loader.py`; the logging
  shim in `log.py`; and an `AppConfig` whose `ready()` settles the prompts directory and logs where it
  is. `library-standards-linter` reports no errors and no warnings.

  `service.py` is 60 lines against the substrate's 302, because three of its four responsibilities
  were handed to whoever does them better. See [stages.md](stages.md).

- **Test plan written and covered.** 53 cases across `CC` (the call), `CL` (client construction), `PD`
  (the prompts directory), `PL` (loading and cache), `PR` (rendering) and `XC` (cross-cutting). Every
  case names its test; every test traces to a case. The plan describes what the substrate *does*, not
  what it should do — the questionable behaviours are pinned, not fixed.

- **Scope narrowed four times, each time by handing work to whoever does it better.**

  - The prompts directory moves out of the package and into the gamedir, because resolving it from
    `__file__` would point at the library once moved.
  - `create_embedding` is not lifted: `evennia-ai-memory` owns embedding end to end.
  - Rate limiting and the daily cost cap are not lifted: they belong on the provider's API key, where
    a limit applies to actual spend rather than to one process.
  - Cost tracking is not lifted: it existed to feed the cap, had no caller, and estimated from five
    hardcoded prices.

  Between them these removed 61 test cases, five settings and roughly 240 lines.

- **Logging brought into line with the other libraries.** The substrate used stdlib
  `logging.getLogger`; every library under `libraries/` emits through a `log.py` shim to a file of its
  own. This one writes to `llm_service.log`. `XC-07` asserts no stdlib logging remains in the package.

## 2026-08-30

- **Repository bootstrapped.** Library-standards scaffold: `pyproject.toml`, `runtests.py`, `src/`
  layout, `tests/` infrastructure on Evennia's settings defaults, `CLAUDE.md`, `README.md` and the
  `docs/` set. Evennia is the runtime dependency and the test runner bootstraps it, matching
  `evennia-message-bus`.

- **Extraction scope agreed.** The library takes FCM's `src/game/llm/` in stages. Stage one is a
  lift-and-shift of `service.py` and `prompt_loader.py`, complete when FCM can delete its LLM service
  code, install the library, and the game still works. `LLMMixin` and `name_generator.py` stay in FCM
  — the mixin until stage two, the name generator permanently, being a crafting feature rather than
  infrastructure.
