# evennia-llm-service

The LLM call, and the prompt that goes into it — for games in the
[Evennia](https://www.evennia.com/) ecosystem.

That is the whole library: a provider client and a template loader. It deliberately does not manage
your spending, throttle your NPCs, or hold any prompt text, because each of those is done better
somewhere else.

## Status

**Stage one complete.** The provider call and the prompt loader are implemented, with 53 tests
covering them. Not yet published, and not yet installed into a consuming game. See
[docs/progress.md](https://github.com/FullCircleMUD/evennia-llm-service/blob/main/docs/progress.md).

## What it does

| Surface | What it gives you |
|---|---|
| `LLMService.chat_completion` | One synchronous call to any OpenAI-compatible provider. Returns the reply, or `None` with the reason in the log. |
| `render_prompt` | Loads a template from your game's prompts directory and fills in its placeholders. |
| `load_prompt` / `clear_cache` | The raw template, cached; and the flush when you have edited one. |
| `get_prompts_dir` / `ensure_prompts_dir` | The fixed location templates live in, created for you at startup. |

Five settings, all optional: `LLM_ENABLED`, `LLM_API_KEY`, `LLM_API_BASE_URL`, `LLM_DEFAULT_MODEL`,
`LLM_PROMPTS_DIR`.

## What it deliberately does not do

- **Manage your spending.** Set a daily budget and a rate limit on the API key, at your provider. That
  applies to what you actually spend; a limit inside the library applies to one process, and a sharded
  game runs several.
- **Throttle an NPC.** How often a character will answer is a game rule. It belongs on the character.
- **Embed anything.** [`evennia-ai-memory`](https://github.com/FullCircleMUD/evennia-ai-memory) owns
  embedding and semantic memory, with its own provider configuration.
- **Ship prompts.** The templates are your game's writing. The library owns the folder and the
  rendering, and nothing about what they say.

## Is this for me?

If you want NPCs that talk, and you would rather not write the provider client, the retry-free failure
path, and a template loader yourself — yes.

If you want memory as well, install `evennia-ai-memory` alongside it. If you want a working NPC mixin
rather than the primitives, not yet: that is stage two, and until then the wiring is yours.

## Install

Not published. From a checkout:

```bash
git clone https://github.com/FullCircleMUD/evennia-llm-service.git
cd evennia-llm-service
python -m venv venv
# Activate the venv (platform-specific)
pip install -e .
python runtests.py
```

Then add `evennia_llm_service` to your gamedir's `INSTALLED_APPS` and set `LLM_API_KEY`. Full
instructions, including where prompt templates go:
**[docs/installation.md](https://github.com/FullCircleMUD/evennia-llm-service/blob/main/docs/installation.md)**.

## Learn more

- **[docs/INDEX.md](https://github.com/FullCircleMUD/evennia-llm-service/blob/main/docs/INDEX.md)** —
  index of design documents.
- **[docs/stages.md](https://github.com/FullCircleMUD/evennia-llm-service/blob/main/docs/stages.md)** —
  what is built, what is coming, and what was decided for later.
- **[docs/test-plan.md](https://github.com/FullCircleMUD/evennia-llm-service/blob/main/docs/test-plan.md)**
  — every behaviour the library commits to.
- **[CLAUDE.md](https://github.com/FullCircleMUD/evennia-llm-service/blob/main/CLAUDE.md)** —
  principles and orientation for working in the repository.

## License

BSD 3-Clause. See [LICENSE](https://github.com/FullCircleMUD/evennia-llm-service/blob/main/LICENSE).
