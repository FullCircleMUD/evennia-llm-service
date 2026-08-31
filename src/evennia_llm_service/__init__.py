# SPDX-License-Identifier: BSD-3-Clause
"""The LLM provider layer for Evennia games.

Stage one lifts FullCircleMUD's ``src/game/llm/`` into this library
unchanged — same settings, same method names, same signatures. See
docs/INDEX.md for the design wiki and docs/test-plan.md for the behaviour
the library is committed to reproducing.
"""

from .prompt_loader import (
    clear_cache,
    ensure_prompts_dir,
    get_prompts_dir,
    load_prompt,
    render_prompt,
)
from .service import LLMService

__version__ = "0.0.1"

__all__ = [
    "LLMService",
    "clear_cache",
    "ensure_prompts_dir",
    "get_prompts_dir",
    "load_prompt",
    "render_prompt",
    "__version__",
]
