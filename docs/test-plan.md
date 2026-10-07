# Test plan

Every test case the library commits to covering, and the test function that covers it. The library is
built test-first: cases are agreed here, tests are written against them, then the implementation is
written to pass. The **Test function** column is the auditable trail — it is filled in as each test is
written, so an empty cell means the case is agreed but not yet covered.

Case IDs are stable and referenceable. Do not renumber; retire an ID rather than reuse it.

## Scope — stage one

Stage one lifts FCM's `src/game/llm/` into this library with one approved change, recorded below:
same method names, same signatures, same return values. FCM's code is the source material, not a
destination — the game is being rebuilt once the libraries are ready, and the rebuilt game is what
consumes this one.

These cases therefore describe **what the code does today**, not what it should do. Where current
behaviour is questionable — a bare `except` that returns `None`, a render failure that returns the
unrendered template — the case pins the current behaviour. Changing any of it is a later stage.

In scope: `service.py`, `prompt_loader.py`, `config.py` and `apps.py`.

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

Out of scope for stage one, and deliberately absent from this plan: `LLMMixin` (stage two),
`name_generator.py` (a crafting feature, never the library's), and every redesign discussed but not yet
scheduled — the single exception type, the library's own log file, prompt `defaults` blocks, the
prompt validator, memory integration, and Django wiring.

**One approved change from current behaviour.** `prompt_loader` resolves its prompts directory from
its own `__file__`, which would point at the library once moved. Templates are the consumer's, so the
folder holding them is the consumer's too: `LLM_PROMPT_FOLDER_PATH` names it, `check_settings()`
refuses a boot without a usable one, and the library creates nothing. FCM declares the setting and
moves its templates there at migration. Covered by `CF` and `PD`.

**Logging follows the library convention, not the substrate's.** FCM's modules use stdlib
`logging.getLogger`; every library under `libraries/` emits through a `log.py` shim to a file of
its own. This one writes to `llm_service.log`. Covered by `XC-07`.

**The log records what went wrong, not what went right.** One INFO line per process at boot, and
after that only the paths a consumer would be troubleshooting. No case asserts a success is logged,
and that absence is deliberate — see CLAUDE.md principle 6. The refusal cases assert delivery by
reading the file back rather than mocking the shim, because a mock cannot see a line that was never
written.

No FCM test exercises `LLMService` or `prompt_loader` directly — the two test modules that mention
them patch them out to test their callers. This suite is the first coverage of this code.

| Prefix | Covers |
|---|---|
| `CF` | The settings accessors and the boot check |
| `CC` | `chat_completion` |
| `TC` | `choose_tool` — a completion that must answer by choosing one of the caller's tools |
| `ES` | Escalation — which model tier each attempt uses, and when a call moves up a tier |
| `CL` | Provider client construction |
| `PD` | The prompts folder |
| `PL` | `load_prompt` and the cache |
| `PR` | `render_prompt` |
| `XC` | Cross-cutting |

## Fixtures

The client is cached on the class, so a fake provider needs no production code change — a test
assigns the fake and clears it afterwards.

| Fixture | Purpose |
|---|---|
| `FakeClient` | Stands in for the OpenAI client; `chat.completions.create` returns a scripted response and records its kwargs |
| `SequenceClient(*answers)` | A client answering each call with the next answer, raising any that is an exception — what `ES` scripts a climb with |
| `make_response(content, prompt_tokens, completion_tokens)` | Builds a response shaped like the SDK's, with a `usage` that can be `None` |
| `RaisingClient` | Raises a chosen exception from `create` |
| `reset_state()` | Clears the cached client and the template cache between tests |
| `folder(value)` | Points `LLM_PROMPT_FOLDER_PATH` at `value` for a block; `None` stands in for a setting the consumer never declared |
| `PromptCase.dir` | A temporary directory, declared as the prompts folder for the life of the test |
| `write_prompt(name, text)` | Writes a template into that directory, including subfolders |

## CF — the settings accessors and the boot check

Every setting is read through a named accessor in `config.py`, so a consumer who declared nothing
gets the default rather than an `AttributeError`. Four settings have a library default and are never
checked at boot — absence is the case the default exists for. The prompts folder has none: the
library ships no prompt text, so there is no location it could pick that would be correct.

`check_settings()` sees the folder, never its contents. A template named by an NPC but absent is
handled where it is noticed — `PL-03` covers it.

| ID | Case | Test function |
|---|---|---|
| CF-01 | `check_settings()` refuses a boot where `LLM_PROMPT_FOLDER_PATH` is not declared, naming the setting | `CheckSettingsTests.test_cf_01_undeclared_folder_refuses_boot` |
| CF-02 | It refuses a declared but empty value — the same mistake as undeclared, from the library's side | `CheckSettingsTests.test_cf_02_empty_folder_refuses_boot` |
| CF-03 | It refuses a path that does not exist, naming the path | `CheckSettingsTests.test_cf_03_missing_folder_refuses_boot` |
| CF-04 | It refuses a path that exists but is a file rather than a directory | `CheckSettingsTests.test_cf_04_file_instead_of_folder_refuses_boot` |
| CF-05 | It returns without raising when the path names an existing directory | `CheckSettingsTests.test_cf_05_existing_folder_boots` |
| CF-06 | An empty directory is accepted — templates arrive after boot | `CheckSettingsTests.test_cf_06_empty_folder_is_accepted` |
| CF-07 | `AppConfig.ready()` is what calls `check_settings()` | `CheckSettingsTests.test_cf_07_app_ready_calls_check_settings` |
| CF-08 | `get_prompt_folder_path()` returns the declared path, with no fallback — the boot check has already refused an unusable one | `AccessorTests.test_cf_08_prompt_folder_path_returns_declared_value` |
| CF-09 | `get_enabled()` returns `True` when `LLM_ENABLED` is undeclared | `AccessorTests.test_cf_09_enabled_defaults_true` |
| CF-10 | `get_enabled()` returns the consumer's value when declared | `AccessorTests.test_cf_10_enabled_returns_declared_value` |
| CF-11 | `get_api_key()` returns `""` when `LLM_API_KEY` is undeclared | `AccessorTests.test_cf_11_api_key_defaults_empty` |
| CF-12 | `get_api_key()` returns the consumer's value when declared | `AccessorTests.test_cf_12_api_key_returns_declared_value` |
| CF-13 | `get_api_base_url()` returns `""` when `LLM_API_BASE_URL` is undeclared — reachable only with the library disabled, since the boot check refuses a blank one while it is on | `AccessorTests.test_cf_13_base_url_defaults_empty` |
| CF-14 | `get_api_base_url()` returns the consumer's value when declared | `AccessorTests.test_cf_14_base_url_returns_declared_value` |
| CF-17 | A boot that passes the check logs one INFO line naming the resolved prompts folder — the anchor for "which run was this", and the one place a wrong-but-valid folder shows up | `CheckSettingsTests.test_cf_17_successful_boot_logs_one_line` |
| CF-18 | That line reports whether `LLM_ENABLED` is on, so a consumer chasing silent NPCs can see it was switched off without reading the settings file | `CheckSettingsTests.test_cf_18_boot_line_reports_enabled_state` |
| CF-19 | A refused boot logs no start line — the refusal is the message | `CheckSettingsTests.test_cf_19_refused_boot_logs_no_start_line` |
| CF-20 | An undeclared or empty folder logs an ERROR before it raises, carrying the same text as the exception | `CheckSettingsTests.test_cf_20_undeclared_folder_logs_before_raising` |
| CF-21 | A path that does not exist logs an ERROR before it raises, carrying the same text | `CheckSettingsTests.test_cf_21_missing_folder_logs_before_raising` |
| CF-22 | A path that is a file logs an ERROR before it raises, carrying the same text | `CheckSettingsTests.test_cf_22_file_instead_of_folder_logs_before_raising` |
| CF-23 | With `LLM_ENABLED` on and no `LLM_API_KEY`, the boot is refused naming the setting — every call would 401, and the game would start clean and go quiet | `CheckSettingsTests.test_cf_23_enabled_without_api_key_refuses_boot` |
| CF-24 | With `LLM_ENABLED` off, no key is needed and the boot passes — the setup phase, before a provider account exists | `CheckSettingsTests.test_cf_24_disabled_without_api_key_boots` |
| CF-25 | With `LLM_ENABLED` on and a key declared, the boot passes | `CheckSettingsTests.test_cf_25_enabled_with_api_key_boots` |
| CF-26 | That refusal logs an ERROR before it raises, carrying the same text | `CheckSettingsTests.test_cf_26_missing_api_key_logs_before_raising` |
| CF-27 | With `LLM_ENABLED` on and no `LLM_API_BASE_URL`, the boot is refused naming the setting — the library picks no provider, so there is nowhere to send the call | `CheckSettingsTests.test_cf_27_enabled_without_base_url_refuses_boot` |
| CF-28 | A base URL that is not `http`/`https` with a host is refused, naming the value — `openrouter.ai/api/v1` with the scheme missing is the realistic typo | `CheckSettingsTests.test_cf_28_malformed_base_url_refuses_boot` |
| CF-29 | With `LLM_ENABLED` off, no base URL is needed and the boot passes | `CheckSettingsTests.test_cf_29_disabled_without_base_url_boots` |
| CF-30 | That refusal logs an ERROR before it raises, carrying the same text | `CheckSettingsTests.test_cf_30_missing_base_url_logs_before_raising` |
| CF-31 | `get_model_tiers()` returns `("openai/gpt-4o-mini",)` when `LLM_MODEL_TIERS` is undeclared | `AccessorTests.test_cf_31_model_tiers_default_to_the_one_default_model` |
| CF-32 | `get_model_tiers()` returns the consumer's tiers, in order, when declared | `AccessorTests.test_cf_32_model_tiers_return_the_declared_tiers_in_order` |
| CF-33 | With `LLM_ENABLED` on, `LLM_MODEL_TIERS` that is empty, not a list or tuple, or holds an entry that is not a non-blank string is refused, naming the setting — a call would have no model to go to | `CheckSettingsTests.test_cf_33_unusable_model_tiers_refuse_boot` |
| CF-34 | That refusal logs an ERROR before it raises, carrying the same text | `CheckSettingsTests.test_cf_34_unusable_model_tiers_log_before_raising` |

Retired: CF-15 and CF-16 covered `get_default_model()` and `LLM_DEFAULT_MODEL`. The default model is
tier 0 of `LLM_MODEL_TIERS`; see `ES`.

## CC — `chat_completion`

`chat_completion(messages, max_tokens=150, temperature=0.8, npc_key=None, start_tier=0, max_escalation_tier=None, accept=None)`

| ID | Case | Test function |
|---|---|---|
| CC-01 | A successful call returns `response.choices[0].message.content` | `ChatCompletionTests.test_cc_01_returns_content` |
| CC-02 | `messages` reaches the provider unchanged | `ChatCompletionTests.test_cc_02_messages_reach_provider_unchanged` |
| CC-03 | With `LLM_ENABLED` false, returns `None` without building a client | `ChatCompletionTests.test_cc_03_disabled_returns_none_without_client` |
| CC-04 | With `LLM_ENABLED` unset, the call proceeds — the default is enabled | `ChatCompletionTests.test_cc_04_enabled_by_default` |
| CC-08 | `max_tokens` and `temperature` reach the provider | `ChatCompletionTests.test_cc_08_max_tokens_and_temperature_reach_provider` |
| CC-09 | Their defaults are 150 and 0.8 | `ChatCompletionTests.test_cc_09_max_tokens_and_temperature_defaults` |
| CC-13 | A provider exception returns `None` rather than propagating | `ChatCompletionTests.test_cc_13_provider_exception_returns_none` |
| CC-14 | A provider exception is logged with the npc key | `ChatCompletionTests.test_cc_14_provider_exception_is_logged_with_npc_key` |
| CC-19 | A response carrying no `usage` data still returns its content | `ChatCompletionTests.test_cc_19_response_without_usage_returns_content` |
| CC-18 | The call is synchronous — it returns rather than dispatching, so a consumer can put retrieval, rendering and the completion in one `deferToThread` | `ChatCompletionTests.test_cc_18_call_is_synchronous` |
| CC-20 | A response whose content is `None` logs a WARN naming the model and the npc key — the provider answered, but with nothing usable, and nothing else in the library would say so | `ChatCompletionTests.test_cc_20_none_content_logs_warning` |
| CC-21 | It still returns `None`. The caller's action is unchanged; only the log is new | `ChatCompletionTests.test_cc_21_none_content_returns_none` |
| CC-22 | A response whose content is empty or only whitespace is treated the same way — an empty reply is a non-reply, as an empty template is a non-prompt | `ChatCompletionTests.test_cc_22_empty_content_treated_as_no_reply` |

Retired: CC-05 to CC-07 covered the `model` argument and `LLM_DEFAULT_MODEL`. Which model a call uses
is its tier; see `ES`.

## TC — `choose_tool`

`choose_tool(messages, tools, max_tokens=150, temperature=0.8, npc_key=None, start_tier=0, max_escalation_tier=None, accept=None)`

A completion that must answer by choosing one of the tools the caller offers, for a consumer that wants
a decision rather than prose. `tools` is a list in the OpenAI tool format — each a name, a description
and a JSON schema for its arguments — and the request carries `tool_choice="required"`. The answer is a
`ToolChoice(name, arguments)`, frozen, with `arguments` parsed from the call's JSON into a dict.

Added beside `chat_completion`, which is unchanged. Like it, every failure returns `None` with the reason
in the log: the call failing is an ERROR; an answer that cannot be used — no tool chosen, a tool not
offered, arguments that are not a JSON object — is a WARN, as an empty reply is for `chat_completion`.
The library knows nothing of what the tools mean.

| ID | Case | Test function |
|---|---|---|
| TC-01 | A response choosing a tool returns `ToolChoice(name, arguments)`, the arguments parsed from the call's JSON into a dict | `ChooseToolTests.test_tc_01_returns_the_chosen_tool_and_its_arguments` |
| TC-02 | `messages` and `tools` reach the provider unchanged, with `tool_choice="required"` | `ChooseToolTests.test_tc_02_messages_and_tools_reach_the_provider_with_a_tool_required` |
| TC-03 | With `LLM_ENABLED` false, returns `None` without building a client | `ChooseToolTests.test_tc_03_disabled_returns_none_without_client` |
| TC-04 | `max_tokens` and `temperature` reach the provider as they do for `chat_completion`, with the same defaults | `ChooseToolTests.test_tc_04_model_tokens_and_temperature_work_as_for_chat_completion` |
| TC-05 | A provider exception returns `None`, logged at ERROR with the npc key | `ChooseToolTests.test_tc_05_a_provider_exception_returns_none_logged_at_error` |
| TC-06 | A response choosing no tool returns `None`, logged at WARN naming the model and the npc key | `ChooseToolTests.test_tc_06_no_tool_chosen_returns_none_logged_at_warn` |
| TC-07 | A response choosing a tool that was not offered returns `None`, logged at WARN naming the tool | `ChooseToolTests.test_tc_07_a_tool_not_offered_returns_none_logged_at_warn` |
| TC-08 | Arguments that are not valid JSON, or not a JSON object, return `None`, logged at WARN naming the tool | `ChooseToolTests.test_tc_08_arguments_that_are_not_a_json_object_return_none` |
| TC-09 | A response choosing several tools returns the first | `ChooseToolTests.test_tc_09_several_tools_chosen_returns_the_first` |
| TC-10 | `ToolChoice` is exported from the package root, and cannot be changed once made | `ChooseToolTests.test_tc_10_tool_choice_is_exported_and_frozen` |

## ES — escalation

`LLM_MODEL_TIERS` is the consumer's models, cheapest first. Tier 0 is the default: a call that names no
tier goes there and nowhere else.

| Argument | Means | Default |
|---|---|---|
| `start_tier` | the tier the first attempt uses | `0` |
| `max_escalation_tier` | the highest tier the call may move up to | `start_tier` — no escalation |
| `accept` | `accept(answer) -> bool`, the caller's own test of an answer | every non-`None` answer is usable |

An attempt that comes back `None` — the call failed, or the answer could not be used — moves up one tier
and sends the same request again. So does an answer `accept` rejects. The call stops at the first usable
answer, or after `max_escalation_tier`, returning `None`. The answer `accept` sees is what the method would have
returned: the text for `chat_completion`, the `ToolChoice` for `choose_tool`.

Escalation is opt-in per call, because the cost is per call: a line of NPC conversation stays on tier 0,
and a rare one-off can pay to climb. Each failed attempt is already logged, naming its model, so the log
shows every tier a call tried.

A tier past the last one stops at the last one. A game may declare fewer tiers than a caller asks for,
and the call still works. `max_escalation_tier` below `start_tier` is a caller's mistake, whatever the game
declared, and raises.

| ID | Case | Test function |
|---|---|---|
| ES-01 | A call naming no tier goes to tier 0, once | `EscalationTests.test_es_01_a_call_naming_no_tier_goes_to_tier_zero_once` |
| ES-02 | `start_tier` names the tier the first attempt goes to | `EscalationTests.test_es_02_start_tier_names_the_first_attempts_tier` |
| ES-03 | With `max_escalation_tier` left out, an empty answer is not retried — the call returns `None` after one attempt | `EscalationTests.test_es_03_with_no_max_an_empty_answer_is_not_retried` |
| ES-04 | An empty answer below `max_escalation_tier` sends the same request to the next tier up | `EscalationTests.test_es_04_an_empty_answer_moves_the_same_request_up_a_tier` |
| ES-05 | A provider exception below `max_escalation_tier` moves up a tier as an empty answer does | `EscalationTests.test_es_05_a_provider_exception_moves_up_a_tier` |
| ES-06 | The first usable answer is returned, and no tier above it is called | `EscalationTests.test_es_06_the_first_usable_answer_is_returned` |
| ES-07 | Empty answers through `max_escalation_tier` return `None`, and no tier above it is called | `EscalationTests.test_es_07_empty_through_the_max_returns_none` |
| ES-08 | An answer `accept` rejects moves up a tier as an empty answer does | `EscalationTests.test_es_08_an_answer_accept_rejects_moves_up_a_tier` |
| ES-09 | An answer rejected at `max_escalation_tier` returns `None`, not the rejected answer | `EscalationTests.test_es_09_an_answer_rejected_at_the_max_returns_none` |
| ES-10 | `accept` is never handed `None` | `EscalationTests.test_es_10_accept_is_never_handed_none` |
| ES-11 | `max_escalation_tier` below `start_tier` raises `ValueError` before any call is made | `EscalationTests.test_es_11_a_max_below_the_start_raises_before_any_call` |
| ES-12 | A `start_tier` or `max_escalation_tier` past the last tier stops at the last tier | `EscalationTests.test_es_12_a_tier_past_the_last_stops_at_the_last` |
| ES-13 | `choose_tool` escalates by the same rule — an unusable answer below `max_escalation_tier` moves up a tier | `EscalationTests.test_es_13_choose_tool_escalates_by_the_same_rule` |
| ES-14 | `choose_tool`'s `accept` is handed the `ToolChoice` | `EscalationTests.test_es_14_choose_tools_accept_is_handed_the_tool_choice` |

What each guards, where it is not obvious:

- **ES-03** is the default that keeps every existing caller on one call. A default `max_escalation_tier` of the
  last tier would quietly multiply the cost of every NPC line that came back empty.
- **ES-05** is the second way an attempt fails. A provider exception returns from a different branch
  than an empty reply, and escalation written against one alone misses the other.
- **ES-10** is what lets a caller write `accept=lambda choice: choice.arguments["name"]`. Handed `None`,
  that raises in the middle of the retry.
- **ES-13 and ES-14** are the second method. One rule, so the `ES` cases run against `chat_completion`
  and these two show `choose_tool` is wired to it.

## CL — client construction

Retired: CL-05 to CL-10 covered a second client for embeddings. `evennia-ai-memory` owns embedding end to end — its own settings, client and error taxonomy — so this library has no embedding surface and no second client.

Retired: CL-02 had the client fall back to OpenRouter when no base URL was declared. Which provider a
game sends its traffic and its credential to is the consumer's choice, not a default the library makes
quietly — a game holding an OpenAI key and no base URL would have sent it to a third party it never
named. The setting is required while the library is enabled; see `CF-27`.

| ID | Case | Test function |
|---|---|---|
| CL-01 | The completion client is built from `LLM_API_KEY` and `LLM_API_BASE_URL` | `ClientConstructionTests.test_cl_01_completion_client_uses_key_and_base_url` |
| CL-03 | With no `LLM_API_KEY`, the client is built with an empty key rather than raising | `ClientConstructionTests.test_cl_03_missing_key_builds_with_empty_string` |
| CL-04 | The completion client is built once and reused across calls | `ClientConstructionTests.test_cl_04_completion_client_built_once` |




## PD — the prompts folder

Where a template is looked for. The folder itself is the `CF` block's business.

Retired: PD-02, PD-03, PD-06 and PD-07 covered `ensure_prompts_dir()` creating the folder at boot and
logging that it had. The consumer owns the folder and declares where it is, so the library creates
nothing — `check_settings()` refuses a boot that names an unusable one. See the `CF` block.

| ID | Case | Test function |
|---|---|---|
| PD-01 | Templates are loaded from the folder the consumer declared, not from the library's own package directory | `PromptsDirTests.test_pd_01_resolves_declared_folder_not_package_dir` |
| PD-04 | A template in the location is found by bare filename, as `render_prompt("roleplay_npc.md", ...)` does today | `PromptsDirTests.test_pd_04_template_found_by_bare_filename` |
| PD-05 | A template in a subfolder is found by relative path | `PromptsDirTests.test_pd_05_template_found_by_relative_subfolder_path` |

## PL — `load_prompt` and the cache

Retired: PL-10 had an empty template file return `""` rather than `None`. An empty prompt is a
non-prompt, so it takes the same path as a missing or unreadable one — one way for the caller to
handle "no usable template", not two. Replaced by PL-16 and PL-17.

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
| PL-11 | A template that exists but cannot be read logs an ERROR naming the path and the reason | `LoadPromptTests.test_pl_11_unreadable_template_logs_error_with_path` |
| PL-12 | It returns `None`, the same as a missing template — the caller cannot tell the two apart and does not need to | `LoadPromptTests.test_pl_12_unreadable_template_returns_none` |
| PL-13 | That `None` is cached: a second call neither re-reads the file nor logs again | `LoadPromptTests.test_pl_13_unreadable_template_is_cached_as_none` |
| PL-14 | A folder where a template was expected is treated as unreadable | `LoadPromptTests.test_pl_14_directory_treated_as_unreadable` |
| PL-15 | A template that is not valid UTF-8 is treated as unreadable | `LoadPromptTests.test_pl_15_undecodable_template_treated_as_unreadable` |
| PL-16 | An empty template file logs a WARN naming the path — an unfinished template is the kind of thing a consumer is trying to find | `LoadPromptTests.test_pl_16_empty_template_logs_warning_with_path` |
| PL-17 | An empty template file returns `None`, the same as missing or unreadable — one way for a caller to handle "no usable template" | `LoadPromptTests.test_pl_17_empty_template_returns_none` |

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
| XC-02 | Beyond the three the boot check requires, every setting defaults — a consumer declaring nothing else still gets a working call | `CrossCuttingTests.test_xc_02_settings_read_with_defaults` |
| XC-09 | Every setting is read through `config.py` — no other module in the package touches `django.conf.settings`, asserted statically. This is what stops a second name for a setting that already has one | `CrossCuttingTests.test_xc_09_settings_read_only_through_config` |
| XC-03 | The library imports no FCM module and reads no FCM-specific setting | `CrossCuttingTests.test_xc_03_no_fcm_imports_or_settings` |
| XC-07 | The library logs through its own shim — no stdlib `logging.getLogger` in the package | `CrossCuttingTests.test_xc_07_no_stdlib_logging_in_the_package` |
| XC-08 | The library never dispatches off the calling thread — no Twisted import anywhere in the package, asserted statically | `CrossCuttingTests.test_xc_08_package_never_dispatches_off_the_calling_thread` |
| XC-04 | The package installs and the suite runs with no consumer gamedir | `CrossCuttingTests.test_xc_04_suite_runs_without_a_gamedir` |
| XC-05 | The installed package reports its version | `SmokeTest.test_version` |
| XC-06 | The library is in `INSTALLED_APPS` under the test settings | `SmokeTest.test_app_installed` |
