# Installing

How to install `evennia-llm-service` into an Evennia game: the package, the one `INSTALLED_APPS`
entry, the three required settings and two optional ones, where prompt templates live, and where the
library writes its log.

## 1. Install the package

Not published to PyPI. From a checkout:

```bash
pip install -e /path/to/evennia-logging-extension
pip install -e /path/to/evennia-llm-service
```

`evennia` and `openai` come with it. `evennia-logging-extension` does not — it is a hard dependency
and is not on PyPI either, so it is installed by path first. Skipping it fails the server boot with
`ModuleNotFoundError` from `at_server_start`.

## 2. Add it to `INSTALLED_APPS`

In the gamedir's `server/conf/settings.py`:

```python
INSTALLED_APPS = INSTALLED_APPS + [
    "evennia_llm_service",
]
```

**Required.** The library declares no Django models and needs no migrations, so the entry exists for
one reason: it is what makes `AppConfig.ready()` fire, and `ready()` is where your settings are
checked. Without it a misconfigured game starts cleanly and fails later, in front of a player.

## 3. Required settings

**The server will not start without these.** `ready()` refuses the boot with `ImproperlyConfigured`,
and the same message goes to `llm_service.log` as well as the console — Evennia wraps the console
traceback in advice about syntax errors and wrong directories, none of which applies here.

```python
LLM_PROMPT_FOLDER_PATH = os.path.join(GAME_DIR, "llm_service", "prompts")

# Not needed while LLM_ENABLED is False.
LLM_API_KEY = "..."
LLM_API_BASE_URL = "https://openrouter.ai/api/v1"
```

| Setting | Required when | What is checked |
|---|---|---|
| `LLM_PROMPT_FOLDER_PATH` | always | Declared, exists, and is a folder rather than a file |
| `LLM_API_KEY` | `LLM_ENABLED` is on | Declared and not blank |
| `LLM_API_BASE_URL` | `LLM_ENABLED` is on | Declared, and an `http`/`https` URL with a host |

**The prompts folder is yours.** Point it anywhere. The library ships no prompt text and creates no
folder, so there is none it could pick for you — make it before you start the server.

**The key and the endpoint are required only while the library is switched on.** A game still being
set up has no provider account yet, and `LLM_ENABLED = False` is the supported way to run without one.
Enabled without them is refused, because every call would fail and the game would start clean and go
quiet.

**The library names no provider for you.** Any OpenAI-compatible endpoint works, and which one your
traffic and your credential go to is your decision — a default here would have sent an OpenAI key to
whatever the default named.

Put the key in secret settings or the environment, not in a file you commit.

## 4. Optional settings

Each is read with a default, so declaring none of these still starts.

| Setting | Default | What it does |
|---|---|---|
| `LLM_ENABLED` | `True` | Master switch. False makes every call return `None` without contacting the provider, and neither the key nor the endpoint is needed. |
| `LLM_MODEL_TIERS` | `("openai/gpt-4o-mini",)` | The models a call can use, cheapest first. Tier 0 is where every call starts; a call escalates only as far as its `max_escalation_tier`. Refused at boot, while enabled, if empty or holding anything but model names. |

### Spending and rate limits

The library enforces neither, deliberately. Set a daily budget and a rate limit **on the API key**, at
the provider — OpenRouter and most others support both. A limit set there applies to what you actually
spend; a limit set in the library applies to one process, and a game running a router and two shards
has three of those.

Throttling a single NPC is a different problem and a game rule: do it on the NPC.

## 5. Write your prompt templates

Templates are the game's, not the library's. The library ships none.

They live wherever `LLM_PROMPT_FOLDER_PATH` points. Organise the folder however you like — a template
is named by its path relative to it, so subfolders work:

```python
from evennia_llm_service import render_prompt

prompt = render_prompt("npc/bartender.md", {"name": "Torben", "mood": "wary"})
```

A placeholder with no matching variable is left in the text as `{name}` rather than raising, so a
missing variable degrades to a visible gap rather than a failed call.

**A template that is missing, unreadable or empty all return `None`** — one thing for your caller to
handle, not three. Each logs what happened and where: a missing file at WARN, an unreadable one at
ERROR with the reason, an empty one at WARN. An empty prompt is a non-prompt, and whitespace counts
as empty.

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

**It logs what went wrong, not what went right.** One line on a working boot and nothing else until
something needs your attention, so anything in this file is worth reading.

| Line | Level | When |
|---|---|---|
| `started — prompts: …, enabled: …` | INFO | Once per process at boot. Three per `evennia start` — launcher, portal, server |
| `LLM_… is not set …` | ERROR | A refused boot, the same text the console gets |
| `prompt file not found: …` | WARN | A template an NPC named is not there |
| `prompt file could not be read: …` | ERROR | Permissions, a folder, or not UTF-8 — with the reason |
| `prompt file is empty: …` | WARN | A template that exists but says nothing |
| `error rendering prompt …` | ERROR | `format_map` failed; the unrendered template is sent anyway |
| `provider returned no content: …` | WARN | The provider answered with nothing usable |
| `call failed: …` | ERROR | The call itself failed, with a traceback |

Delivery belongs to `evennia-logging-extension`, which owns the file, the timestamp and the
pre-reactor window. See [interoperability.md](interoperability.md).

## What is not checked for you

The boot check sees the folder, never what is in it, and sees that the key is present, never that it
works. These are yours to get right:

- **That the folder you named is the right one.** A real but wrong folder passes every check and then
  misses every template. The folder it resolved to is in the startup line, which is what that line is
  for.
- **That a template an NPC names is actually there.** Templates are added and renamed long after boot.
  A missing one logs and returns `None` — your caller decides what to say instead.
- **That a placeholder has a matching variable.** An unmatched `{name}` stays in the text.
- **That the key is valid.** Boot checks it is not blank. A wrong, expired or revoked key is a failed
  call at ERROR, not a refused boot.
- **That the endpoint answers, or is the one you meant.** Boot checks the URL parses. It makes no
  network call — a provider outage must not stop your server starting — so a well-formed URL pointing
  at the wrong host fails at the first call, not at boot.
- **That the provider gives you something usable.** A content filter or a refusal returns no content;
  that logs a WARN and returns `None`.
- **That you are off the reactor thread.** `chat_completion` blocks; wrapping it is yours.

## Verifying the install

From the library checkout:

```bash
python runtests.py
```

89 tests, no gamedir required. In a consuming game, the server starting at all confirms `ready()` ran
and your settings passed — and the startup line in `llm_service.log` tells you which folder it
resolved to and whether the library is switched on.
