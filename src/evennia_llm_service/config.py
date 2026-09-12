# SPDX-License-Identifier: BSD-3-Clause
"""The settings this library reads, their accessors, and the boot check.

Every module-level constant the library declares lives here, and every other
module imports it from here — one file to check before minting a second name
for a value that already has one.

Four of the five settings have a library default, so absence is the case the
default exists for and none of them is checked at boot. The prompts folder is
the exception: the library ships no prompt text, so there is no folder it
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

from django.core.exceptions import ImproperlyConfigured

SETTING_PROMPT_FOLDER_PATH = "LLM_PROMPT_FOLDER_PATH"
SETTING_ENABLED = "LLM_ENABLED"
SETTING_API_KEY = "LLM_API_KEY"
SETTING_API_BASE_URL = "LLM_API_BASE_URL"
SETTING_DEFAULT_MODEL = "LLM_DEFAULT_MODEL"

#: Used when neither the caller nor the consumer names a model.
DEFAULT_MODEL = "openai/gpt-4o-mini"

#: Used when the consumer names no endpoint.
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

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
        raise ImproperlyConfigured(
            f"{SETTING_PROMPT_FOLDER_PATH} is not set. Point it at the folder "
            f"holding your prompt templates, e.g. '/path/to/game/prompts'. The "
            f"library ships no prompt text, so there is no folder it can pick "
            f"for you."
        )

    if not os.path.exists(path):
        raise ImproperlyConfigured(
            f"{SETTING_PROMPT_FOLDER_PATH} names {path!r}, which does not "
            f"exist. Create the folder and put your prompt templates in it."
        )

    if not os.path.isdir(path):
        raise ImproperlyConfigured(
            f"{SETTING_PROMPT_FOLDER_PATH} names {path!r}, which is a file. "
            f"Point it at the folder holding your templates, not at one of them."
        )


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


def get_default_model() -> str:
    """Return ``LLM_DEFAULT_MODEL``, defaulting to ``DEFAULT_MODEL``."""
    from django.conf import settings

    return getattr(settings, SETTING_DEFAULT_MODEL, DEFAULT_MODEL)
