# Test plan

Every test case the library commits to covering, and the test function that covers it. The library is
built test-first: cases are agreed here, tests are written against them, then the implementation is
written to pass. The **Test function** column is the auditable trail — it is filled in as each test is
written, so an empty cell means the case is agreed but not yet covered.

Case IDs are stable and referenceable. Do not renumber; retire an ID rather than reuse it.

## Scope — stage one

Stage one lifts FCM's `src/game/llm/` into this library unchanged: same settings, same method names,
same signatures, same return values. Completion is reached when FCM can delete its LLM service code,
install this library, and the game still works.

These cases therefore describe **what the code does today**, not what it should do. Where current
behaviour is questionable — a bare `except` that returns `None`, a render failure that returns the
unrendered template — the case pins the current behaviour. Changing any of it is a later stage.

In scope: `service.py` and `prompt_loader.py`.

**Three things are not lifted.** Each belongs to someone better placed to do it.

- **Rate limiting and the daily cost cap** — enforced on the provider's API key, where the limit
  applies to actual spend rather than to one process. FCM runs a router and two shards, so a
  per-process cap was three times the budget it claimed. Retires `RL`, `DC`, `CC-10` to `CC-12`.
- **Cost tracking** — it existed to feed the cap, has no caller in FCM, and estimated from five
  hardcoded prices. Retires `CT`, `CC-15` to `CC-17`, and `LLM_GLOBAL_MAX_CALLS_PER_MINUTE`,
  `LLM_PER_NPC_MAX_CALLS_PER_MINUTE`, `LLM_DAILY_COST_LIMIT_CENTS`.
- **Per-NPC throttling** — a game rule, and FCM's mixin already does it with
  `llm_cooldown_seconds` before it ever calls the service.

`chat_completion` keeps `npc_key`: it identifies the caller in the log and carries no accounting.

**`create_embedding` is not lifted either.** `evennia-ai-memory` now owns embedding end to end, so the
method has no future caller. The `CE` block and the second-client cases are retired, along with
`LLM_EMBEDDING_API_KEY`, `LLM_EMBEDDING_API_BASE_URL` and `LLM_EMBEDDING_MODEL`.

Out of scope for stage one, and deliberately absent from this plan: `LLMMixin` (stays in FCM),
`name_generator.py` (a crafting feature, stays in FCM), and every redesign discussed but not yet
scheduled — the single exception type, the library's own log file, prompt `defaults` blocks, the
prompt validator, memory integration, and Django wiring.

**One approved change from current behaviour.** `prompt_loader` resolves its prompts directory from
its own `__file__`, which would point at the library once moved. The library instead owns a fixed,
expected prompts location and looks there; FCM's templates move into it at migration. Covered by `PD`.

**Logging follows the library convention, not the substrate's.** FCM's modules use stdlib
`logging.getLogger`; every library under `libraries/` emits through a `log.py` shim to a file of
its own. This one writes to `llm_service.log`. Covered by `XC-07`.

No FCM test exercises `LLMService` or `prompt_loader` directly — the two test modules that mention
them patch them out to test their callers. This suite is the first coverage of this code.

| Prefix | Covers |
|---|---|
| `CC` | `chat_completion` |
| `CL` | Provider client construction |
| `PD` | The prompts directory |
| `PL` | `load_prompt` and the cache |
| `PR` | `render_prompt` |
| `XC` | Cross-cutting |

## Fixtures

The client is cached on the class, so a fake provider needs no production code change — a test
assigns the fake and clears it afterwards.

| Fixture | Purpose |
|---|---|
| `FakeClient` | Stands in for the OpenAI client; `chat.completions.create` returns a scripted response and records its kwargs |
| `make_response(content, prompt_tokens, completion_tokens)` | Builds a response shaped like the SDK's, with a `usage` that can be `None` |
| `RaisingClient` | Raises a chosen exception from `create` |
| `reset_state()` | Clears the cached client and the template cache between tests |
| `tmp_prompts_dir` | A temporary directory used as the library's prompts location |
| `write_prompt(name, text)` | Writes a template into that directory, including subfolders |
| `capture_logs` | Captures the module's log records so a test can assert on them |

## CC — `chat_completion`

`chat_completion(messages, model=None, max_tokens=150, temperature=0.8, npc_key=None)`

| ID | Case | Test function |
|---|---|---|
| CC-01 | A successful call returns `response.choices[0].message.content` | `ChatCompletionTests.test_cc_01_returns_content` |
| CC-02 | `messages` reaches the provider unchanged | `ChatCompletionTests.test_cc_02_messages_reach_provider_unchanged` |
| CC-03 | With `LLM_ENABLED` false, returns `None` without building a client | `ChatCompletionTests.test_cc_03_disabled_returns_none_without_client` |
| CC-04 | With `LLM_ENABLED` unset, the call proceeds — the default is enabled | `ChatCompletionTests.test_cc_04_enabled_by_default` |
| CC-05 | With no `model` argument, `LLM_DEFAULT_MODEL` is used | `ChatCompletionTests.test_cc_05_model_from_setting` |
| CC-06 | With neither argument nor setting, `openai/gpt-4o-mini` is used | `ChatCompletionTests.test_cc_06_model_falls_back_to_hardcoded_default` |
| CC-07 | An explicit `model` argument overrides the setting | `ChatCompletionTests.test_cc_07_explicit_model_overrides_setting` |
| CC-08 | `max_tokens` and `temperature` reach the provider | `ChatCompletionTests.test_cc_08_max_tokens_and_temperature_reach_provider` |
| CC-09 | Their defaults are 150 and 0.8 | `ChatCompletionTests.test_cc_09_max_tokens_and_temperature_defaults` |
| CC-13 | A provider exception returns `None` rather than propagating | `ChatCompletionTests.test_cc_13_provider_exception_returns_none` |
| CC-14 | A provider exception is logged with the npc key | `ChatCompletionTests.test_cc_14_provider_exception_is_logged_with_npc_key` |
| CC-19 | A response carrying no `usage` data still returns its content | `ChatCompletionTests.test_cc_19_response_without_usage_returns_content` |
| CC-18 | The call is synchronous — it returns rather than dispatching, so a consumer can put retrieval, rendering and the completion in one `deferToThread` | `ChatCompletionTests.test_cc_18_call_is_synchronous` |

## CL — client construction

Retired: CL-05 to CL-10 covered a second client for embeddings. `evennia-ai-memory` owns embedding end to end — its own settings, client and error taxonomy — so this library has no embedding surface and no second client.

| ID | Case | Test function |
|---|---|---|
| CL-01 | The completion client is built from `LLM_API_KEY` and `LLM_API_BASE_URL` | `ClientConstructionTests.test_cl_01_completion_client_uses_key_and_base_url` |
| CL-02 | With no `LLM_API_BASE_URL`, the OpenRouter URL is used | `ClientConstructionTests.test_cl_02_completion_base_url_defaults_to_openrouter` |
| CL-03 | With no `LLM_API_KEY`, the client is built with an empty key rather than raising | `ClientConstructionTests.test_cl_03_missing_key_builds_with_empty_string` |
| CL-04 | The completion client is built once and reused across calls | `ClientConstructionTests.test_cl_04_completion_client_built_once` |




## PD — the prompts directory

The one approved change from current behaviour.

| ID | Case | Test function |
|---|---|---|
| PD-01 | The library resolves prompts from its fixed expected location, not from its own package directory | `PromptsDirTests.test_pd_01_resolves_configured_location_not_package_dir` |
| PD-02 | `ensure_prompts_dir()` creates the location when it is absent | `PromptsDirTests.test_pd_02_location_exists_after_startup` |
| PD-03 | An existing location is left alone — its contents survive startup | `PromptsDirTests.test_pd_03_existing_location_left_alone` |
| PD-06 | Creating the directory is logged, naming the path | `PromptsDirTests.test_pd_06_creation_is_logged` |
| PD-07 | `AppConfig.ready()` is what ensures the directory exists | `PromptsDirTests.test_pd_07_app_ready_ensures_the_directory` |
| PD-04 | A template in the location is found by bare filename, as `render_prompt("roleplay_npc.md", ...)` does today | `PromptsDirTests.test_pd_04_template_found_by_bare_filename` |
| PD-05 | A template in a subfolder is found by relative path | `PromptsDirTests.test_pd_05_template_found_by_relative_subfolder_path` |

## PL — `load_prompt` and the cache

| ID | Case | Test function |
|---|---|---|
| PL-01 | An existing template returns its full raw text | `LoadPromptTests.test_pl_01_existing_template_returns_full_text` |
| PL-02 | A missing template returns `None` | `LoadPromptTests.test_pl_02_missing_template_returns_none` |
| PL-03 | A missing template logs a warning naming the path | `LoadPromptTests.test_pl_03_missing_template_logs_warning_with_path` |
| PL-04 | A template is read from disk once and served from cache after | `LoadPromptTests.test_pl_04_read_from_disk_once_then_cached` |
| PL-05 | A file edited on disk without a flush still serves the cached text | `LoadPromptTests.test_pl_05_edit_without_flush_serves_cached_text` |
| PL-06 | `clear_cache()` clears it; the next load reads from disk | `LoadPromptTests.test_pl_06_clear_cache_forces_reread` |
| PL-07 | `clear_cache()` on an empty cache is a no-op | `LoadPromptTests.test_pl_07_clear_cache_on_empty_cache_is_noop` |
| PL-08 | The cache is keyed by filename — two templates do not collide | `LoadPromptTests.test_pl_08_cache_keyed_by_filename` |
| PL-09 | A missing template is cached as `None` and not re-read | `LoadPromptTests.test_pl_09_missing_template_is_cached_as_none` |
| PL-10 | An empty template file returns an empty string, not `None` | `LoadPromptTests.test_pl_10_empty_file_returns_empty_string` |

## PR — `render_prompt`

| ID | Case | Test function |
|---|---|---|
| PR-01 | Placeholders present in `variables` are substituted | `RenderPromptTests.test_pr_01_placeholders_substituted` |
| PR-02 | A placeholder absent from `variables` is left in the text as `{name}` | `RenderPromptTests.test_pr_02_missing_variable_left_in_place` |
| PR-03 | A missing template returns `None` without attempting to render | `RenderPromptTests.test_pr_03_missing_template_returns_none` |
| PR-04 | A template with no placeholders renders unchanged | `RenderPromptTests.test_pr_04_template_without_placeholders_unchanged` |
| PR-05 | An empty `variables` dict leaves every placeholder in place | `RenderPromptTests.test_pr_05_empty_variables_leaves_every_placeholder` |
| PR-06 | Keys in `variables` that no placeholder uses are ignored | `RenderPromptTests.test_pr_06_unused_keys_ignored` |
| PR-07 | A non-string value is substituted as its string form | `RenderPromptTests.test_pr_07_non_string_value_substituted_as_string` |
| PR-08 | A template that raises during `format_map` returns the unrendered template, not `None` | `RenderPromptTests.test_pr_08_format_failure_returns_unrendered_template` |
| PR-09 | That failure is logged | `RenderPromptTests.test_pr_09_format_failure_is_logged` |
| PR-10 | A substituted value containing braces is not substituted a second time | `RenderPromptTests.test_pr_10_substituted_braces_not_expanded_again` |
| PR-11 | Rendering the same template twice with the same variables gives the same string | `RenderPromptTests.test_pr_11_rendering_is_deterministic` |
| PR-12 | Rendering does not mutate the cached template | `RenderPromptTests.test_pr_12_rendering_does_not_mutate_cached_template` |

## XC — cross-cutting

| ID | Case | Test function |
|---|---|---|
| XC-01 | `chat_completion` returns `None` on failure rather than raising — the current contract | `CrossCuttingTests.test_xc_01_public_functions_return_none_on_failure` |
| XC-02 | Settings are read through `getattr` with defaults, so a consumer declaring none still works | `CrossCuttingTests.test_xc_02_settings_read_with_defaults` |
| XC-03 | The library imports no FCM module and reads no FCM-specific setting | `CrossCuttingTests.test_xc_03_no_fcm_imports_or_settings` |
| XC-07 | The library logs through its own shim — no stdlib `logging.getLogger` in the package | `CrossCuttingTests.test_xc_07_no_stdlib_logging_in_the_package` |
| XC-08 | The library never dispatches off the calling thread — no Twisted import anywhere in the package, asserted statically | `CrossCuttingTests.test_xc_08_package_never_dispatches_off_the_calling_thread` |
| XC-04 | The package installs and the suite runs with no consumer gamedir | `CrossCuttingTests.test_xc_04_suite_runs_without_a_gamedir` |
| XC-05 | The installed package reports its version | `SmokeTest.test_version` |
| XC-06 | The library is in `INSTALLED_APPS` under the test settings | `SmokeTest.test_app_installed` |
