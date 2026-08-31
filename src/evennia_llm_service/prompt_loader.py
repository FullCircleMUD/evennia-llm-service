# SPDX-License-Identifier: BSD-3-Clause
"""Prompt loader — loads and caches prompt templates from files.

Stage one: lifted from FullCircleMUD's ``src/game/llm/prompt_loader.py``
with one approved change. The original resolved its prompts directory from
its own ``__file__``, which would point inside this package once moved. The
library instead owns a fixed expected location under the consumer's game
directory, overridable by ``LLM_PROMPTS_DIR``.

Templates use ``str.format_map()`` with named placeholders. Files are
cached in memory after first load.

See docs/test-plan.md for the behaviour this reproduces.
"""

import os
from functools import lru_cache

from .log import llm_service_log

# Location under GAME_DIR when LLM_PROMPTS_DIR is not set.
DEFAULT_PROMPTS_SUBPATH = ("llm_service", "prompts")


def get_prompts_dir():
    """Return the directory prompt templates are loaded from.

    ``LLM_PROMPTS_DIR`` if the consumer set it, otherwise
    ``<GAME_DIR>/llm_service/prompts``.
    """
    from django.conf import settings

    configured = getattr(settings, "LLM_PROMPTS_DIR", None)
    if configured:
        return str(configured)
    return os.path.join(settings.GAME_DIR, *DEFAULT_PROMPTS_SUBPATH)


def ensure_prompts_dir():
    """Create the prompts directory if it does not exist.

    Leaves an existing directory and its contents untouched.

    Returns:
        bool: True if it had to be created, False if it was already there.
    """
    path = get_prompts_dir()
    if os.path.isdir(path):
        return False
    os.makedirs(path, exist_ok=True)
    return True


@lru_cache(maxsize=32)
def load_prompt(filename):
    """Load a prompt template from the prompts directory.

    Cached after first read.

    Returns:
        str: the raw template text, or None if the file is not found.
    """
    path = os.path.join(get_prompts_dir(), filename)
    if not os.path.exists(path):
        llm_service_log(f"prompt file not found: {path}", level="WARN")
        return None
    with open(path, "r") as handle:
        return handle.read()


def render_prompt(filename, variables):
    """Load a prompt template and fill in variables.

    Uses ``str.format_map()`` with a defaulting dict, so a missing
    variable produces ``{var_name}`` rather than raising.

    Returns:
        str: the rendered prompt, or None if the file is not found.
    """
    template = load_prompt(filename)
    if template is None:
        return None
    try:
        return template.format_map(_DefaultDict(variables))
    except Exception:
        # A template the loader cannot render is still better sent than
        # nothing — the substrate's behaviour, and the caller has no other
        # copy of it.
        llm_service_log(
            f"error rendering prompt {filename}", level="ERROR", trace=True
        )
        return template


def clear_cache():
    """Clear the prompt cache."""
    load_prompt.cache_clear()


class _DefaultDict(dict):
    """Dict returning ``{key}`` for missing keys instead of raising."""

    def __missing__(self, key):
        return "{" + key + "}"
