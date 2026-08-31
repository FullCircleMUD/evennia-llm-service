# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for evennia-llm-service, run via ``python runtests.py``.

Stage one: these cover the behaviour lifted from FullCircleMUD's
``src/game/llm/``. Every case traces to an ID in docs/test-plan.md.
"""

import ast
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

import evennia_llm_service
from evennia_llm_service import apps, prompt_loader, service
from evennia_llm_service.service import LLMService

# ── Fixtures ──────────────────────────────────────────────────────────


def make_response(content="a reply", prompt_tokens=10, completion_tokens=5, usage=True):
    """A response shaped like the provider SDK's."""
    used = (
        SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        if usage
        else None
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=used,
    )


class _Recorder:
    """Records the kwargs of every call, then returns or raises."""

    def __init__(self, result=None, exc=None):
        self.calls = []
        self._result = result
        self._exc = exc

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._result


class FakeClient:
    """Stands in for the completion client."""

    def __init__(self, response=None, exc=None):
        self.completions = _Recorder(result=response, exc=exc)
        self.chat = SimpleNamespace(completions=self.completions)

    @property
    def calls(self):
        return self.completions.calls


class RaisingClient(FakeClient):
    """A completion client whose every call raises."""

    def __init__(self, exc=None):
        super().__init__(exc=exc or RuntimeError("provider exploded"))


def reset_state():
    """Clear the module-level singletons between tests."""
    LLMService._client = None
    try:
        prompt_loader.load_prompt.cache_clear()
    except AttributeError:
        pass


class ServiceCase(SimpleTestCase):
    """Base case — resets the module singletons around every test."""

    def setUp(self):
        reset_state()
        self.addCleanup(reset_state)

    def install_client(self, response=None, exc=None):
        client = RaisingClient(exc) if exc else FakeClient(response=response)
        LLMService._client = client
        return client

MESSAGES = [{"role": "user", "content": "hello"}]


# ── CC — chat_completion ──────────────────────────────────────────────


class ChatCompletionTests(ServiceCase):
    def test_cc_01_returns_content(self):
        self.install_client(make_response("Well met."))
        self.assertEqual(LLMService.chat_completion(MESSAGES), "Well met.")

    def test_cc_02_messages_reach_provider_unchanged(self):
        client = self.install_client(make_response())
        LLMService.chat_completion(MESSAGES)
        self.assertEqual(client.calls[0]["messages"], MESSAGES)

    @override_settings(LLM_ENABLED=False)
    def test_cc_03_disabled_returns_none_without_client(self):
        client = self.install_client(make_response())
        self.assertIsNone(LLMService.chat_completion(MESSAGES))
        self.assertEqual(client.calls, [])

    def test_cc_04_enabled_by_default(self):
        self.assertFalse(hasattr(settings, "LLM_ENABLED"))
        self.install_client(make_response())
        self.assertIsNotNone(LLMService.chat_completion(MESSAGES))

    @override_settings(LLM_DEFAULT_MODEL="anthropic/claude-haiku")
    def test_cc_05_model_from_setting(self):
        client = self.install_client(make_response())
        LLMService.chat_completion(MESSAGES)
        self.assertEqual(client.calls[0]["model"], "anthropic/claude-haiku")

    def test_cc_06_model_falls_back_to_hardcoded_default(self):
        client = self.install_client(make_response())
        LLMService.chat_completion(MESSAGES)
        self.assertEqual(client.calls[0]["model"], "openai/gpt-4o-mini")

    @override_settings(LLM_DEFAULT_MODEL="openai/gpt-4o")
    def test_cc_07_explicit_model_overrides_setting(self):
        client = self.install_client(make_response())
        LLMService.chat_completion(MESSAGES, model="google/gemini-2.0-flash")
        self.assertEqual(client.calls[0]["model"], "google/gemini-2.0-flash")

    def test_cc_08_max_tokens_and_temperature_reach_provider(self):
        client = self.install_client(make_response())
        LLMService.chat_completion(MESSAGES, max_tokens=12, temperature=0.1)
        self.assertEqual(client.calls[0]["max_tokens"], 12)
        self.assertEqual(client.calls[0]["temperature"], 0.1)

    def test_cc_09_max_tokens_and_temperature_defaults(self):
        client = self.install_client(make_response())
        LLMService.chat_completion(MESSAGES)
        self.assertEqual(client.calls[0]["max_tokens"], 150)
        self.assertEqual(client.calls[0]["temperature"], 0.8)

    def test_cc_13_provider_exception_returns_none(self):
        self.install_client(exc=RuntimeError("boom"))
        self.assertIsNone(LLMService.chat_completion(MESSAGES))

    def test_cc_14_provider_exception_is_logged_with_npc_key(self):
        self.install_client(exc=RuntimeError("boom"))
        with mock.patch.object(service, "llm_service_log") as log:
            LLMService.chat_completion(MESSAGES, npc_key="npc#7")
        self.assertIn("npc#7", " ".join(str(c) for c in log.call_args_list))

    def test_cc_19_response_without_usage_returns_content(self):
        self.install_client(make_response("still fine", usage=False))
        self.assertEqual(LLMService.chat_completion(MESSAGES), "still fine")

    def test_cc_18_call_is_synchronous(self):
        self.install_client(make_response("done"))
        result = LLMService.chat_completion(MESSAGES)
        self.assertIsInstance(result, str)


# ── CL — client construction ──────────────────────────────────────────


class ClientConstructionTests(ServiceCase):
    def patched_openai(self):
        return mock.patch("openai.OpenAI")

    @override_settings(LLM_API_KEY="key-123", LLM_API_BASE_URL="https://example.test/v1")
    def test_cl_01_completion_client_uses_key_and_base_url(self):
        with self.patched_openai() as ctor:
            LLMService._get_client()
        ctor.assert_called_once_with(
            base_url="https://example.test/v1", api_key="key-123"
        )

    @override_settings(LLM_API_KEY="key-123")
    def test_cl_02_completion_base_url_defaults_to_openrouter(self):
        with self.patched_openai() as ctor:
            LLMService._get_client()
        self.assertEqual(
            ctor.call_args.kwargs["base_url"], "https://openrouter.ai/api/v1"
        )

    def test_cl_03_missing_key_builds_with_empty_string(self):
        with self.patched_openai() as ctor:
            LLMService._get_client()
        self.assertEqual(ctor.call_args.kwargs["api_key"], "")

    def test_cl_04_completion_client_built_once(self):
        with self.patched_openai() as ctor:
            LLMService._get_client()
            LLMService._get_client()
        self.assertEqual(ctor.call_count, 1)


# ── Prompt cases ──────────────────────────────────────────────────────


class PromptCase(SimpleTestCase):
    """Base case — a temporary prompts directory, cleared cache."""

    def setUp(self):
        reset_state()
        self.addCleanup(reset_state)
        self.dir = tempfile.mkdtemp(prefix="llm_prompts_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        override = override_settings(LLM_PROMPTS_DIR=self.dir)
        override.enable()
        self.addCleanup(override.disable)

    def write_prompt(self, name, text):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)
        return path


# ── PD — the prompts directory ────────────────────────────────────────


class PromptsDirTests(PromptCase):
    def test_pd_01_resolves_configured_location_not_package_dir(self):
        package_dir = os.path.dirname(prompt_loader.__file__)
        resolved = prompt_loader.get_prompts_dir()
        self.assertEqual(os.path.realpath(resolved), os.path.realpath(self.dir))
        self.assertNotEqual(os.path.realpath(resolved), os.path.realpath(package_dir))

    def test_pd_02_location_exists_after_startup(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        prompt_loader.ensure_prompts_dir()
        self.assertTrue(os.path.isdir(self.dir))

    def test_pd_03_existing_location_left_alone(self):
        self.write_prompt("keep.md", "kept")
        prompt_loader.ensure_prompts_dir()
        with open(os.path.join(self.dir, "keep.md")) as handle:
            self.assertEqual(handle.read(), "kept")

    def test_pd_06_creation_is_logged(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        with mock.patch.object(apps, "llm_service_log") as log:
            apps.EvenniaLLMServiceConfig.ready(mock.Mock())
        self.assertIn(self.dir, " ".join(str(c) for c in log.call_args_list))

    def test_pd_07_app_ready_ensures_the_directory(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        with mock.patch.object(apps, "llm_service_log"):
            apps.EvenniaLLMServiceConfig.ready(mock.Mock())
        self.assertTrue(os.path.isdir(self.dir))

    def test_pd_04_template_found_by_bare_filename(self):
        self.write_prompt("roleplay_npc.md", "You are {name}.")
        self.assertEqual(prompt_loader.load_prompt("roleplay_npc.md"), "You are {name}.")

    def test_pd_05_template_found_by_relative_subfolder_path(self):
        self.write_prompt(os.path.join("npc", "bartender.md"), "Pour a drink.")
        self.assertEqual(
            prompt_loader.load_prompt(os.path.join("npc", "bartender.md")),
            "Pour a drink.",
        )


# ── PL — load_prompt and the cache ────────────────────────────────────


class LoadPromptTests(PromptCase):
    def test_pl_01_existing_template_returns_full_text(self):
        self.write_prompt("a.md", "line one\nline two\n")
        self.assertEqual(prompt_loader.load_prompt("a.md"), "line one\nline two\n")

    def test_pl_02_missing_template_returns_none(self):
        self.assertIsNone(prompt_loader.load_prompt("nope.md"))

    def test_pl_03_missing_template_logs_warning_with_path(self):
        with mock.patch.object(prompt_loader, "llm_service_log") as log:
            prompt_loader.load_prompt("nope.md")
        self.assertIn("nope.md", " ".join(str(c) for c in log.call_args_list))

    def test_pl_04_read_from_disk_once_then_cached(self):
        path = self.write_prompt("a.md", "original")
        prompt_loader.load_prompt("a.md")
        os.remove(path)
        self.assertEqual(prompt_loader.load_prompt("a.md"), "original")

    def test_pl_05_edit_without_flush_serves_cached_text(self):
        self.write_prompt("a.md", "original")
        prompt_loader.load_prompt("a.md")
        self.write_prompt("a.md", "edited")
        self.assertEqual(prompt_loader.load_prompt("a.md"), "original")

    def test_pl_06_clear_cache_forces_reread(self):
        self.write_prompt("a.md", "original")
        prompt_loader.load_prompt("a.md")
        self.write_prompt("a.md", "edited")
        prompt_loader.clear_cache()
        self.assertEqual(prompt_loader.load_prompt("a.md"), "edited")

    def test_pl_07_clear_cache_on_empty_cache_is_noop(self):
        prompt_loader.clear_cache()
        prompt_loader.clear_cache()

    def test_pl_08_cache_keyed_by_filename(self):
        self.write_prompt("a.md", "alpha")
        self.write_prompt("b.md", "beta")
        self.assertEqual(prompt_loader.load_prompt("a.md"), "alpha")
        self.assertEqual(prompt_loader.load_prompt("b.md"), "beta")

    def test_pl_09_missing_template_is_cached_as_none(self):
        self.assertIsNone(prompt_loader.load_prompt("later.md"))
        self.write_prompt("later.md", "now it exists")
        self.assertIsNone(prompt_loader.load_prompt("later.md"))

    def test_pl_10_empty_file_returns_empty_string(self):
        self.write_prompt("empty.md", "")
        self.assertEqual(prompt_loader.load_prompt("empty.md"), "")


# ── PR — render_prompt ────────────────────────────────────────────────


class RenderPromptTests(PromptCase):
    def test_pr_01_placeholders_substituted(self):
        self.write_prompt("a.md", "You are {name}.")
        self.assertEqual(
            prompt_loader.render_prompt("a.md", {"name": "Mara"}), "You are Mara."
        )

    def test_pr_02_missing_variable_left_in_place(self):
        self.write_prompt("a.md", "You are {name}.")
        self.assertEqual(prompt_loader.render_prompt("a.md", {}), "You are {name}.")

    def test_pr_03_missing_template_returns_none(self):
        self.assertIsNone(prompt_loader.render_prompt("nope.md", {"name": "Mara"}))

    def test_pr_04_template_without_placeholders_unchanged(self):
        self.write_prompt("a.md", "Just words.")
        self.assertEqual(prompt_loader.render_prompt("a.md", {}), "Just words.")

    def test_pr_05_empty_variables_leaves_every_placeholder(self):
        self.write_prompt("a.md", "{one} and {two}")
        self.assertEqual(prompt_loader.render_prompt("a.md", {}), "{one} and {two}")

    def test_pr_06_unused_keys_ignored(self):
        self.write_prompt("a.md", "You are {name}.")
        self.assertEqual(
            prompt_loader.render_prompt("a.md", {"name": "Mara", "spare": "x"}),
            "You are Mara.",
        )

    def test_pr_07_non_string_value_substituted_as_string(self):
        self.write_prompt("a.md", "You have {count} coins.")
        self.assertEqual(
            prompt_loader.render_prompt("a.md", {"count": 7}), "You have 7 coins."
        )

    def test_pr_08_format_failure_returns_unrendered_template(self):
        self.write_prompt("a.md", "Unbalanced {")
        self.assertEqual(prompt_loader.render_prompt("a.md", {}), "Unbalanced {")

    def test_pr_09_format_failure_is_logged(self):
        self.write_prompt("a.md", "Unbalanced {")
        with mock.patch.object(prompt_loader, "llm_service_log") as log:
            prompt_loader.render_prompt("a.md", {})
        self.assertTrue(log.called)

    def test_pr_10_substituted_braces_not_expanded_again(self):
        self.write_prompt("a.md", "Say {phrase}.")
        self.assertEqual(
            prompt_loader.render_prompt("a.md", {"phrase": "{name}"}), "Say {name}."
        )

    def test_pr_11_rendering_is_deterministic(self):
        self.write_prompt("a.md", "You are {name}.")
        first = prompt_loader.render_prompt("a.md", {"name": "Mara"})
        second = prompt_loader.render_prompt("a.md", {"name": "Mara"})
        self.assertEqual(first, second)

    def test_pr_12_rendering_does_not_mutate_cached_template(self):
        self.write_prompt("a.md", "You are {name}.")
        prompt_loader.render_prompt("a.md", {"name": "Mara"})
        self.assertEqual(prompt_loader.load_prompt("a.md"), "You are {name}.")


# ── XC — cross-cutting ────────────────────────────────────────────────


class CrossCuttingTests(ServiceCase):
    def test_xc_01_public_functions_return_none_on_failure(self):
        self.install_client(exc=RuntimeError("boom"))
        self.assertIsNone(LLMService.chat_completion(MESSAGES))

    def test_xc_02_settings_read_with_defaults(self):
        for name in (
            "LLM_ENABLED",
            "LLM_API_KEY",
            "LLM_API_BASE_URL",
            "LLM_DEFAULT_MODEL",
            "LLM_GLOBAL_MAX_CALLS_PER_MINUTE",
            "LLM_PER_NPC_MAX_CALLS_PER_MINUTE",
            "LLM_DAILY_COST_LIMIT_CENTS",
        ):
            self.assertFalse(hasattr(settings, name), name)
        self.install_client(make_response("fine"))
        self.assertEqual(LLMService.chat_completion(MESSAGES), "fine")

    def test_xc_03_no_fcm_imports_or_settings(self):
        package_dir = os.path.dirname(evennia_llm_service.__file__)
        offenders = []
        for root, _dirs, files in os.walk(package_dir):
            for name in files:
                if not name.endswith(".py") or name == "tests.py":
                    continue
                with open(os.path.join(root, name)) as handle:
                    source = handle.read()
                for token in ("typeclasses", "FCM", "fcm_", "combat", "xrpl"):
                    if token in source:
                        offenders.append((name, token))
        self.assertEqual(offenders, [])

    def test_xc_07_no_stdlib_logging_in_the_package(self):
        package_dir = os.path.dirname(evennia_llm_service.__file__)
        offenders = []
        for root, _dirs, files in os.walk(package_dir):
            for name in files:
                if not name.endswith(".py") or name == "tests.py":
                    continue
                with open(os.path.join(root, name)) as handle:
                    if "logging.getLogger" in handle.read():
                        offenders.append(name)
        self.assertEqual(offenders, [])

    def test_xc_08_package_never_dispatches_off_the_calling_thread(self):
        # Imports, not prose — the docstrings deliberately tell callers to
        # wrap these functions in deferToThread themselves.
        package_dir = os.path.dirname(evennia_llm_service.__file__)
        offenders = []
        for root, _dirs, files in os.walk(package_dir):
            for name in files:
                if not name.endswith(".py") or name == "tests.py":
                    continue
                tree = ast.parse(open(os.path.join(root, name)).read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        names = [node.module or ""]
                    else:
                        continue
                    for imported in names:
                        if imported.split(".")[0] == "twisted":
                            offenders.append((name, imported))
        self.assertEqual(offenders, [])

    def test_xc_04_suite_runs_without_a_gamedir(self):
        self.assertTrue(settings.configured)


class SmokeTest(unittest.TestCase):
    """Proves the package installs and the runner reaches it."""

    def test_version(self):
        self.assertEqual(evennia_llm_service.__version__, "0.0.1")

    def test_app_installed(self):
        self.assertIn("evennia_llm_service", settings.INSTALLED_APPS)
