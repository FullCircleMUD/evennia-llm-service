# SPDX-License-Identifier: BSD-3-Clause
"""The settings this library reads, their accessors, and the boot check.

Every module-level constant the library declares lives here, and every other
module imports it from here — one file to check before minting a second name
for a value that already has one.

Four of the five settings have a library default. The prompts folder is the
exception: the library ships no prompt text, so there is no folder it
could pick that would be correct. A guessed location is an empty one, and an
empty one fails silently — every ``render_prompt`` returns ``None``, every NPC
drops to the consumer's own fallback, and the game runs with every character
sounding the same. Refusing the boot is the honest answer::

    LLM_PROMPT_FOLDER_PATH = "/path/to/game/prompts"

The check sees the folder, never its contents. Templates are added and renamed
long after boot, and a template named by an NPC but not present is already
handled where it is noticed — ``load_prompt`` logs a WARN naming the path and
returns ``None``.
"""

import os
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

SETTING_PROMPT_FOLDER_PATH = "LLM_PROMPT_FOLDER_PATH"
SETTING_ENABLED = "LLM_ENABLED"
SETTING_API_KEY = "LLM_API_KEY"
SETTING_API_BASE_URL = "LLM_API_BASE_URL"
SETTING_MODEL_TIERS = "LLM_MODEL_TIERS"

#: Used when the consumer declares no tiers: one, which every call goes to.
DEFAULT_MODEL_TIERS = ("openai/gpt-4o-mini",)

#: No endpoint the library could pick would be right: which provider a game
#: sends its traffic and its credential to is the consumer's choice. A default
#: here would have sent an OpenAI key to whoever the default named. Blank, and
#: refused at boot while the library is enabled.
DEFAULT_BASE_URL = ""

#: Schemes a provider endpoint can use.
URL_SCHEMES = ("http", "https")

#: Used when the consumer declares no key. The provider rejects the call and
#: the failure is logged, which is the same path any other bad key takes.
DEFAULT_API_KEY = ""

#: The library runs unless the consumer turns it off.
DEFAULT_ENABLED = True


def check_settings() -> None:
    """Refuse to start when the prompts folder is missing or unusable.

    Called from ``AppConfig.ready()``. Raises ``ImproperlyConfigured``.

    The checks are sequential rather than collected: there is one setting, and
    each answer makes the next question worth asking.
    """
    from django.conf import settings

    path = getattr(settings, SETTING_PROMPT_FOLDER_PATH, None)

    # `not path` covers undeclared and empty together. From the library's side
    # they are the same mistake: nothing to load a template from.
    if not path:
        _refuse(
            f"{SETTING_PROMPT_FOLDER_PATH} is not set. Point it at the folder "
            f"holding your prompt templates, e.g. '/path/to/game/prompts'. The "
            f"library ships no prompt text, so there is no folder it can pick "
            f"for you."
        )

    if not os.path.exists(path):
        _refuse(
            f"{SETTING_PROMPT_FOLDER_PATH} names {path!r}, which does not "
            f"exist. Create the folder and put your prompt templates in it."
        )

    if not os.path.isdir(path):
        _refuse(
            f"{SETTING_PROMPT_FOLDER_PATH} names {path!r}, which is a file. "
            f"Point it at the folder holding your templates, not at one of them."
        )

    # Required only while the library is switched on. A game still being set
    # up has no provider account yet, and turning the library off is the
    # supported way to run without one — so the default empty key is only ever
    # reachable on a path that makes no calls.
    if not get_enabled():
        return

    if not get_api_key().strip():
        _refuse(
            f"{SETTING_API_KEY} is not set, and {SETTING_ENABLED} is on. Every "
            f"call would be rejected by the provider. Set the key, or set "
            f"{SETTING_ENABLED} = False to run without one."
        )

    base_url = get_api_base_url().strip()

    if not base_url:
        _refuse(
            f"{SETTING_API_BASE_URL} is not set, and {SETTING_ENABLED} is on. "
            f"Name the provider endpoint your key belongs to, e.g. "
            f"'https://openrouter.ai/api/v1'. The library picks no provider for "
            f"you — a default would send your key somewhere you did not choose."
        )

    parsed = urlparse(base_url)
    if parsed.scheme not in URL_SCHEMES or not parsed.netloc:
        _refuse(
            f"{SETTING_API_BASE_URL} is {base_url!r}, which is not an "
            f"http or https URL with a host. A missing 'https://' is the usual "
            f"cause, e.g. 'https://openrouter.ai/api/v1'."
        )

    tiers = getattr(settings, SETTING_MODEL_TIERS, DEFAULT_MODEL_TIERS)
    if (
        not isinstance(tiers, (list, tuple))
        or not tiers
        or any(not isinstance(tier, str) or not tier.strip() for tier in tiers)
    ):
        _refuse(
            f"{SETTING_MODEL_TIERS} is {tiers!r}. It must be a list of model names, "
            f"cheapest first, e.g. ['openai/gpt-4o-mini', 'anthropic/claude-haiku-4.5']. "
            f"Tier 0 is the model every call starts on."
        )


def _refuse(message: str) -> None:
    """Log the refusal, then raise it — one message, both channels.

    A consumer whose server will not start reads the console or the log, and
    must get the same answer from either. Evennia wraps the console traceback
    in advice about syntax errors and wrong directories, none of which applies
    here, so the log is often the clearer of the two.

    The log import is lazy by rule: ``log.py`` and ``config.py`` importing each
    other at module scope resolve or crash on declaration order.
    """
    from .log import llm_service_log

    llm_service_log(message, level="ERROR")
    raise ImproperlyConfigured(message)


def get_prompt_folder_path() -> str:
    """Return the consumer's prompts folder.

    Required, so there is no default to fall back on — ``check_settings()``
    has already refused the boot if it is not usable, which is what makes the
    plain read safe here.
    """
    from django.conf import settings

    return getattr(settings, SETTING_PROMPT_FOLDER_PATH)


def get_enabled() -> bool:
    """Return ``LLM_ENABLED``, defaulting to ``DEFAULT_ENABLED``."""
    from django.conf import settings

    return bool(getattr(settings, SETTING_ENABLED, DEFAULT_ENABLED))


def get_api_key() -> str:
    """Return ``LLM_API_KEY``, defaulting to ``DEFAULT_API_KEY``."""
    from django.conf import settings

    return getattr(settings, SETTING_API_KEY, DEFAULT_API_KEY)


def get_api_base_url() -> str:
    """Return ``LLM_API_BASE_URL``, defaulting to ``DEFAULT_BASE_URL``."""
    from django.conf import settings

    return getattr(settings, SETTING_API_BASE_URL, DEFAULT_BASE_URL)


def get_model_tiers() -> tuple:
    """Return ``LLM_MODEL_TIERS``, cheapest first, defaulting to ``DEFAULT_MODEL_TIERS``.

    Tier 0 is the default model: a call that names no tier goes there. The boot
    check has already refused tiers a call could not use.
    """
    from django.conf import settings

    return tuple(getattr(settings, SETTING_MODEL_TIERS, DEFAULT_MODEL_TIERS))
