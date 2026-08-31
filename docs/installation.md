# Installation

How to install `evennia-llm-service` into an Evennia game: the package, the one `INSTALLED_APPS`
entry, the five settings, where prompt templates live, and where the library writes its log.

## Install the package

Not published to PyPI. From a checkout:

```bash
pip install -e /path/to/evennia-llm-service
```

`evennia` and `openai` come with it.

## Add it to `INSTALLED_APPS`

In the gamedir's `server/conf/settings.py`:

```python
INSTALLED_APPS = INSTALLED_APPS + [
    "evennia_llm_service",
]
```

**Required.** The library declares no Django models and needs no migrations, so the entry exists for
one reason: it is what makes `AppConfig.ready()` fire, and `ready()` is where the prompts directory is
settled. Without it the directory is never created and every template lookup logs a miss.

## Settings

All five are optional — each is read with a default, so a game that declares none still starts. In
practice you will set at least `LLM_API_KEY`.

| Setting | Default | What it does |
|---|---|---|
| `LLM_ENABLED` | `True` | Master switch. False makes every call return `None` without contacting the provider. |
| `LLM_API_KEY` | `""` | Provider API key. |
| `LLM_API_BASE_URL` | `https://openrouter.ai/api/v1` | Provider endpoint. Anything OpenAI-compatible works. |
| `LLM_DEFAULT_MODEL` | `openai/gpt-4o-mini` | Used when a caller names no model. |
| `LLM_PROMPTS_DIR` | `<GAME_DIR>/llm_service/prompts` | Where prompt templates are loaded from. |

Put the key in secret settings or the environment, not in a file you commit.

### Spending and rate limits

The library enforces neither, deliberately. Set a daily budget and a rate limit **on the API key**, at
the provider — OpenRouter and most others support both. A limit set there applies to what you actually
spend; a limit set in the library applies to one process, and a game running a router and two shards
has three of those.

Throttling a single NPC is a different problem and a game rule: do it on the NPC.

## Prompt templates

Templates are the game's, not the library's. The library ships none.

They live in `<GAME_DIR>/llm_service/prompts/` unless `LLM_PROMPTS_DIR` says otherwise. The directory
is created at startup if it is missing. Organise it however you like — a template is named by its path
relative to that directory, so subfolders work:

```python
from evennia_llm_service import render_prompt

prompt = render_prompt("npc/bartender.md", {"name": "Torben", "mood": "wary"})
```

A placeholder with no matching variable is left in the text as `{name}` rather than raising, so a
missing variable degrades to a visible gap rather than a failed call.

**Templates are cached after first read.** Editing one has no effect until the server restarts or
something calls `clear_cache()`.

## Using it

```python
from evennia_llm_service import LLMService, render_prompt

prompt = render_prompt("npc/bartender.md", {"name": "Torben"})
reply = LLMService.chat_completion(
    messages=[{"role": "system", "content": prompt},
              {"role": "user", "content": "What's the news?"}],
    npc_key="npc#42",
)
if reply is None:
    ...  # the provider gave nothing usable — say something else
```

`chat_completion` is **synchronous and makes a network call**. Wrap it in `deferToThread` or the
equivalent, or it blocks Evennia's reactor and with it every connected player.

It returns `None` rather than raising, for every failure: disabled in settings, a network error, a bad
key, an unknown model. The reason goes to the log.

`npc_key` identifies the caller in the log and does nothing else.

## Where it logs

`llm_service.log`, alongside Evennia's own logs under `settings.LOG_DIR`. Provider failures and prompt
problems go there, not into `server.log`.

Outside a running Evennia engine the log call is a silent no-op — the library will not fall back to
stderr or a file of its own choosing.

## Verifying the install

From the library checkout:

```bash
python runtests.py
```

53 tests, no gamedir required. In a consuming game, the startup line in `llm_service.log` naming the
prompts directory is the confirmation that `ready()` ran.
