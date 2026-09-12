# SPDX-License-Identifier: BSD-3-Clause
"""Prompt loader — loads and caches prompt templates from files.

Stage one: lifted from FullCircleMUD's ``src/game/llm/prompt_loader.py``
with one approved change. The original resolved its prompts directory from
its own ``__file__``, which would point inside this package once moved.
Templates are the consumer's, so the folder holding them is the consumer's
too — named by ``LLM_PROMPT_FOLDER_PATH`` and read through
``config.get_prompt_folder_path()``.

Templates use ``str.format_map()`` with named placeholders. Files are
cached in memory after first load.

See docs/test-plan.md for the behaviour this reproduces.
"""

import os
from functools import lru_cache

from .config import get_prompt_folder_path
from .log import llm_service_log


@lru_cache(maxsize=32)
def load_prompt(filename):
    """Load a prompt template from the consumer's prompts folder.

    Cached after first read.

    Returns:
        str: the raw template text, or None if the file is not found.
    """
    path = os.path.join(get_prompt_folder_path(), filename)
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
