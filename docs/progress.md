# Progress

Running log of milestones with links to evidence. Reverse chronological — newest first.

## 2026-09-12 (latest)

- **Diagnostic logging, and a second required setting.** The log now says why, everywhere a caller
  gets `None`: a template that is missing, unreadable or empty; a provider that answered with no
  content. A template that cannot be read no longer raises through `render_prompt` into the caller,
  and an empty template returns `None` rather than `""` — missing, unreadable and empty are one path
  for a caller to handle instead of three. `PL-10` retires with that change.

  `check_settings()` refuses a boot that is enabled with no `LLM_API_KEY` or no `LLM_API_BASE_URL`,
  and refuses a base URL that is not an `http`/`https` URL with a host. Both stay defaulted settings
  with a blank default, required only while `LLM_ENABLED` is on, so a game still being set up runs
  with the library switched off and no provider account. Every refusal logs at ERROR before it
  raises, with the same text in both channels.

  The OpenRouter default came off `LLM_API_BASE_URL` and `CL-02` retires with it. Which provider a
  game sends its traffic and its credential to is the consumer's choice: a game holding an OpenAI key
  and no base URL would have sent that key to a third party it never named. Nothing is checked over
  the network — a provider outage must not stop a server booting — so a well-formed URL pointing at
  the wrong host still fails at the first call.

  One INFO line per process at boot carries the resolved prompts folder and the `LLM_ENABLED` state
  — the two things that are invisible otherwise and that account for most silence. Nothing else logs
  a success; the library records what went wrong, not what went right, which is a deliberate
  divergence from the cascade recipe and is written up in CLAUDE.md principle 6.

  The refusal cases assert **delivery, read back from disk** rather than mocking the shim — the
  refusal fires during `django.setup()`, the one window where the extension is known to drop lines
  silently, and a mock cannot see that. Cascade's `clear_logs`/`read_back_logs` helpers port across
  unchanged. 89 tests, all green.

- **Settings moved behind `config.py`, and the prompts folder became the consumer's.** Five settings,
  five named accessors, and `XC-09` asserting statically that no other module reads
  `django.conf.settings`. `LLM_PROMPT_FOLDER_PATH` is required: the library ships no prompt text, so
  there is no folder it could pick, and `check_settings()` refuses the boot from `AppConfig.ready()`
  when the setting is missing or names something that is not a folder. `ensure_prompts_dir()` is gone
  — the library creates nothing. 67 tests, all green.

  Live-tested in the demo gamedir: all three refusals verified at a real `evennia start` with no
  process left running, then a clean boot, `get_prompt_folder_path()` resolving through the live
  accessor, `render_prompt("test_npc.md", …)` returning a filled template, and a missing template
  logging its WARN to `llm_service.log`.

- **Logging converted to `evennia-logging-extension`.** `log.py` binds `llm_service_log` from
  `make_logger("llm_service.log")` — same name, same file, same signature, so no call site moved.
  Validated live: the boot line landed once per process in Evennia's format, `WARN` and `ERROR` came
  through at their level, `trace=True` appended the active exception, and no `pre-startup.log`
  appeared.

  `ready()` no longer logs, because it no longer creates anything. Extending logging into the
  pre-reactor window is phase two and has not been done.

## 2026-08-31

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
  lift-and-shift of `service.py` and `prompt_loader.py`. `LLMMixin` follows in stage two;
  `name_generator.py` does not follow at all, being a crafting feature rather than infrastructure.
