# SPDX-License-Identifier: BSD-3-Clause
"""Django AppConfig for evennia-llm-service.

Only loaded when the consumer adds ``evennia_llm_service`` to
``INSTALLED_APPS``. The library declares no models — the entry exists so
``ready()`` fires, which is where the prompts directory is settled.

``ready()`` runs during ``django.setup()``, before the game serves anything,
so a consumer starting with no prompts directory gets one rather than a
stream of missing-template warnings at the first NPC conversation.
"""

from django.apps import AppConfig

from .log import llm_service_log


class EvenniaLLMServiceConfig(AppConfig):
    name = "evennia_llm_service"

    def ready(self):
        """Settle the prompts directory, and say in the log what happened."""
        from .prompt_loader import ensure_prompts_dir, get_prompts_dir

        path = get_prompts_dir()
        created = ensure_prompts_dir()
        if created:
            llm_service_log(f"created the prompts directory at {path}")
        else:
            llm_service_log(f"prompts directory: {path}")
