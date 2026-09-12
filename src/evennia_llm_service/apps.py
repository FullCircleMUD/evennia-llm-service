# SPDX-License-Identifier: BSD-3-Clause
"""Django AppConfig for evennia-llm-service.

Only loaded when the consumer adds ``evennia_llm_service`` to
``INSTALLED_APPS``. The library declares no models — the entry exists so
``ready()`` fires, which is where the consumer's configuration is validated.

``ready()`` runs during ``django.setup()``, before the game serves anything.
Checking here rather than at first use is the point: validation deferred to
the first NPC conversation means a misconfigured instance starts cleanly,
runs, and then answers a player in a voice nobody wrote.
"""

from django.apps import AppConfig

from .log import llm_service_log


class EvenniaLLMServiceConfig(AppConfig):
    """Refuses the boot when the declared prompts folder is unusable."""

    name = "evennia_llm_service"

    def ready(self):
        from .config import check_settings, get_enabled, get_prompt_folder_path

        check_settings()

        # The one line this library writes on a working boot. It carries the
        # two things a consumer cannot otherwise see: which folder the
        # templates actually resolved to — a real but wrong folder passes
        # every check and then misses every template — and whether the
        # library is switched on, which is the first question behind "why
        # has every NPC gone quiet". Evennia stamps the timestamp.
        llm_service_log(
            f"started — prompts: {get_prompt_folder_path()}, "
            f"enabled: {get_enabled()}"
        )
