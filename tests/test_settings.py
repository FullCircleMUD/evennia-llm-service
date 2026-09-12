# SPDX-License-Identifier: BSD-3-Clause
"""Minimal Django settings for evennia-llm-service unit tests.

Imports Evennia's defaults, adds the library to INSTALLED_APPS, and uses an
in-memory sqlite test database. No gamedir required.
"""
import os
import sys
import tempfile

import evennia

# Evennia 6.0.0+ ships migrations that import ``typeclasses.objects``
# (a gamedir module). Put Evennia's game_template on sys.path so the
# import resolves without requiring a real gamedir.
_game_template = os.path.join(os.path.dirname(evennia.__file__), "game_template")
if _game_template not in sys.path:
    sys.path.insert(0, _game_template)

from evennia.settings_default import *  # noqa: F401, F403, E402

# Evennia path bits — point at safe scratch locations so settings_default's
# path-derived defaults resolve without needing a real gamedir.
GAME_DIR = tempfile.gettempdir()
LOG_DIR = os.path.join(tempfile.gettempdir(), "evennia_llm_service_test_logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Library under test
INSTALLED_APPS = list(INSTALLED_APPS) + ["evennia_llm_service"]  # noqa: F405

# The library refuses to boot without a prompts folder, so the suite declares
# one for AppConfig.ready(). Tests that care about the value override it with
# a temporary directory of their own; this one only has to exist.
LLM_PROMPT_FOLDER_PATH = os.path.join(tempfile.gettempdir(), "evennia_llm_service_test_prompts")
os.makedirs(LLM_PROMPT_FOLDER_PATH, exist_ok=True)

# The library refuses to boot enabled without a key and an endpoint. Neither is
# ever used to reach a provider — every test installs a fake client.
LLM_API_KEY = "test-only-not-a-real-key"
LLM_API_BASE_URL = "https://provider.test/v1"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

# Required Django bits
SECRET_KEY = "test-only-secret"
TEST_ENVIRONMENT = True
ROOT_URLCONF = "tests.urls"
