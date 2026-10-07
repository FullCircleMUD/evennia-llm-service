# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for evennia-llm-service, run via ``python runtests.py``.

Stage one: these cover the behaviour lifted from FullCircleMUD's
``src/game/llm/``. Every case traces to an ID in docs/test-plan.md.
"""

import ast
import contextlib
import dataclasses
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

import evennia_llm_service
from evennia_llm_service import apps, config, log, prompt_loader, service
from evennia_llm_service.config import (
    DEFAULT_MODEL_TIERS,
    SETTING_PROMPT_FOLDER_PATH,
    check_settings,
)
from evennia_llm_service.service import LLMService, ToolChoice

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


class SequenceClient(FakeClient):
    """A completion client answering each call with the next of ``answers``.

    An answer that is an exception is raised; anything else is returned.
    """

    def __init__(self, *answers):
        super().__init__()
        self._answers = list(answers)
        self.completions.create = self._create

    def _create(self, **kwargs):
        self.completions.calls.append(kwargs)
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def models(self):
        return [call["model"] for call in self.calls]


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


def clear_logs():
    """Empty LOG_DIR's files so a line read back was written by this test.

    Truncated, never removed: Evennia's ``_open_log_file`` caches the handle
    after the first write, and removing the file leaves that handle appending
    to an unlinked inode — every later line silently vanishes. An append-mode
    handle seeks to the end on each write, so a truncated file stays live.
    """
    for name in os.listdir(settings.LOG_DIR):
        if name.endswith(".log"):
            with open(os.path.join(settings.LOG_DIR, name), "w"):
                pass


def read_back_logs():
    """Every line in LOG_DIR's files, as one string."""
    text = []
    for name in sorted(os.listdir(settings.LOG_DIR)):
        if name.endswith(".log"):
            with open(os.path.join(settings.LOG_DIR, name)) as handle:
                text.append(handle.read())
    return "\n".join(text)


@contextlib.contextmanager
def undeclared(*names):
    """Run the block with ``names`` absent from settings entirely.

    The test settings must declare whatever the boot check requires, or the
    suite cannot bootstrap. A case about an *undeclared* setting therefore
    removes it for itself rather than relying on the file staying empty —
    which also keeps the case honest if the test settings change again.
    """
    with override_settings():
        for name in names:
            delattr(settings, name)
        yield


def folder(value):
    """Point ``LLM_PROMPT_FOLDER_PATH`` at ``value`` for the block.

    ``None`` stands in for a setting the consumer never declared: the library
    reads it with ``getattr(settings, name, None)``, so an undeclared setting
    and one set to ``None`` reach the check as the same thing.
    """
    return override_settings(**{SETTING_PROMPT_FOLDER_PATH: value})


# ── CF — the settings accessors and the boot check ────────────────────


class CheckSettingsTests(SimpleTestCase):
    """CF-01 to CF-07 and CF-17 to CF-19 — what the boot check refuses, what
    calls it, and what a boot puts in the log."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="llm_folder_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def refusal(self, value):
        """Run the check against one value and return the refusal message."""
        with folder(value):
            with self.assertRaises(ImproperlyConfigured) as caught:
                check_settings()
        return str(caught.exception)

    def test_cf_01_undeclared_folder_refuses_boot(self):
        """CF-01"""
        self.assertIn(SETTING_PROMPT_FOLDER_PATH, self.refusal(None))

    def test_cf_02_empty_folder_refuses_boot(self):
        """CF-02"""
        self.assertIn(SETTING_PROMPT_FOLDER_PATH, self.refusal(""))

    def test_cf_03_missing_folder_refuses_boot(self):
        """CF-03"""
        missing = os.path.join(self.dir, "not_there")
        self.assertIn(missing, self.refusal(missing))

    def test_cf_04_file_instead_of_folder_refuses_boot(self):
        """CF-04"""
        path = os.path.join(self.dir, "prompts.md")
        with open(path, "w") as handle:
            handle.write("a template, where a folder was meant to be")
        self.assertIn(path, self.refusal(path))

    def test_cf_05_existing_folder_boots(self):
        """CF-05"""
        with open(os.path.join(self.dir, "roleplay_npc.md"), "w") as handle:
            handle.write("You are {name}.")
        with folder(self.dir):
            self.assertIsNone(check_settings())

    def test_cf_06_empty_folder_is_accepted(self):
        """CF-06"""
        self.assertEqual(os.listdir(self.dir), [])
        with folder(self.dir):
            self.assertIsNone(check_settings())

    def test_cf_07_app_ready_calls_check_settings(self):
        """CF-07"""
        with mock.patch.object(config, "check_settings") as checked:
            apps.EvenniaLLMServiceConfig.ready(mock.Mock())
        checked.assert_called_once_with()

    def boot(self):
        """Boot against the temporary folder and return what was logged."""
        with folder(self.dir):
            with mock.patch.object(apps, "llm_service_log") as log:
                apps.EvenniaLLMServiceConfig.ready(mock.Mock())
        return log

    def test_cf_17_successful_boot_logs_one_line(self):
        """CF-17"""
        log = self.boot()
        self.assertEqual(log.call_count, 1)
        self.assertIn(self.dir, str(log.call_args))
        # INFO is the shim's default, so a boot line names no level at all.
        # Asserting the resolved level keeps the case true either way.
        self.assertEqual(log.call_args.kwargs.get("level", "INFO"), "INFO")

    def test_cf_18_boot_line_reports_enabled_state(self):
        """CF-18"""
        self.assertIn("True", str(self.boot().call_args))
        with override_settings(LLM_ENABLED=False):
            self.assertIn("False", str(self.boot().call_args))

    def assertLoggedBeforeRaising(self, value):
        """One ERROR on disk, carrying the same text the caller is raised.

        Read back from the file rather than mocked. A mock proves the library
        called the log function; only the file proves a line landed — and the
        refusal fires during ``django.setup()``, the one window where the
        extension is known to drop lines silently.
        """
        clear_logs()
        with folder(value):
            with self.assertRaises(ImproperlyConfigured) as caught:
                check_settings()
        written = read_back_logs()
        self.assertIn(str(caught.exception), written)
        self.assertIn("[ERROR]", written)

    def test_cf_20_undeclared_folder_logs_before_raising(self):
        """CF-20"""
        self.assertLoggedBeforeRaising(None)
        self.assertLoggedBeforeRaising("")

    def test_cf_21_missing_folder_logs_before_raising(self):
        """CF-21"""
        self.assertLoggedBeforeRaising(os.path.join(self.dir, "not_there"))

    def test_cf_22_file_instead_of_folder_logs_before_raising(self):
        """CF-22"""
        path = os.path.join(self.dir, "prompts.md")
        with open(path, "w") as handle:
            handle.write("a template, where a folder was meant to be")
        self.assertLoggedBeforeRaising(path)

    def test_cf_23_enabled_without_api_key_refuses_boot(self):
        """CF-23"""
        with folder(self.dir), override_settings(LLM_ENABLED=True, LLM_API_KEY=""):
            with self.assertRaises(ImproperlyConfigured) as caught:
                check_settings()
        self.assertIn("LLM_API_KEY", str(caught.exception))

    def test_cf_24_disabled_without_api_key_boots(self):
        """CF-24"""
        with folder(self.dir), override_settings(LLM_ENABLED=False, LLM_API_KEY=""):
            self.assertIsNone(check_settings())

    def test_cf_25_enabled_with_api_key_boots(self):
        """CF-25"""
        with folder(self.dir), override_settings(LLM_ENABLED=True, LLM_API_KEY="key-123"):
            self.assertIsNone(check_settings())

    def test_cf_26_missing_api_key_logs_before_raising(self):
        """CF-26"""
        clear_logs()
        with folder(self.dir), override_settings(LLM_ENABLED=True, LLM_API_KEY=""):
            with self.assertRaises(ImproperlyConfigured) as caught:
                check_settings()
        written = read_back_logs()
        self.assertIn(str(caught.exception), written)
        self.assertIn("[ERROR]", written)

    def test_cf_27_enabled_without_base_url_refuses_boot(self):
        """CF-27"""
        with folder(self.dir), override_settings(
            LLM_ENABLED=True, LLM_API_KEY="key-123", LLM_API_BASE_URL=""
        ):
            with self.assertRaises(ImproperlyConfigured) as caught:
                check_settings()
        self.assertIn("LLM_API_BASE_URL", str(caught.exception))

    def test_cf_28_malformed_base_url_refuses_boot(self):
        """CF-28"""
        for bad in ("openrouter.ai/api/v1", "https://", "ftp://example.test", "not a url"):
            with self.subTest(url=bad):
                with folder(self.dir), override_settings(
                    LLM_ENABLED=True, LLM_API_KEY="key-123", LLM_API_BASE_URL=bad
                ):
                    with self.assertRaises(ImproperlyConfigured) as caught:
                        check_settings()
                self.assertIn(bad, str(caught.exception))

    def test_cf_29_disabled_without_base_url_boots(self):
        """CF-29"""
        with folder(self.dir), override_settings(
            LLM_ENABLED=False, LLM_API_KEY="", LLM_API_BASE_URL=""
        ):
            self.assertIsNone(check_settings())

    def test_cf_30_missing_base_url_logs_before_raising(self):
        """CF-30"""
        clear_logs()
        with folder(self.dir), override_settings(
            LLM_ENABLED=True, LLM_API_KEY="key-123", LLM_API_BASE_URL=""
        ):
            with self.assertRaises(ImproperlyConfigured) as caught:
                check_settings()
        written = read_back_logs()
        self.assertIn(str(caught.exception), written)
        self.assertIn("[ERROR]", written)

    def test_cf_33_unusable_model_tiers_refuse_boot(self):
        """CF-33"""
        for bad in ([], (), "openai/gpt-4o-mini", ["cheap/model", ""], ["cheap/model", 3]):
            with self.subTest(tiers=bad):
                with folder(self.dir), override_settings(LLM_ENABLED=True, LLM_MODEL_TIERS=bad):
                    with self.assertRaises(ImproperlyConfigured) as caught:
                        check_settings()
                self.assertIn("LLM_MODEL_TIERS", str(caught.exception))

    def test_cf_34_unusable_model_tiers_log_before_raising(self):
        """CF-34"""
        clear_logs()
        with folder(self.dir), override_settings(LLM_ENABLED=True, LLM_MODEL_TIERS=[]):
            with self.assertRaises(ImproperlyConfigured) as caught:
                check_settings()
        written = read_back_logs()
        self.assertIn(str(caught.exception), written)
        self.assertIn("[ERROR]", written)

    def test_cf_19_refused_boot_logs_no_start_line(self):
        """CF-19"""
        with folder(None):
            with mock.patch.object(apps, "llm_service_log") as log:
                with self.assertRaises(ImproperlyConfigured):
                    apps.EvenniaLLMServiceConfig.ready(mock.Mock())
        log.assert_not_called()


class AccessorTests(SimpleTestCase):
    """CF-08 to CF-14, CF-31 and CF-32 — every setting reaches the library through config.py."""

    def assertUndeclared(self, name):
        """Guard the default cases: they only mean something while it is unset."""
        self.assertFalse(hasattr(settings, name), name)

    def test_cf_08_prompt_folder_path_returns_declared_value(self):
        """CF-08"""
        with folder("/somewhere/the/consumer/chose"):
            self.assertEqual(
                config.get_prompt_folder_path(), "/somewhere/the/consumer/chose"
            )

    def test_cf_09_enabled_defaults_true(self):
        """CF-09"""
        self.assertUndeclared("LLM_ENABLED")
        self.assertIs(config.get_enabled(), True)

    def test_cf_10_enabled_returns_declared_value(self):
        """CF-10"""
        with override_settings(LLM_ENABLED=False):
            self.assertIs(config.get_enabled(), False)

    def test_cf_11_api_key_defaults_empty(self):
        """CF-11"""
        with undeclared("LLM_API_KEY"):
            self.assertEqual(config.get_api_key(), "")

    def test_cf_12_api_key_returns_declared_value(self):
        """CF-12"""
        with override_settings(LLM_API_KEY="key-123"):
            self.assertEqual(config.get_api_key(), "key-123")

    def test_cf_13_base_url_defaults_empty(self):
        """CF-13"""
        with undeclared("LLM_API_BASE_URL"):
            self.assertEqual(config.get_api_base_url(), "")

    def test_cf_14_base_url_returns_declared_value(self):
        """CF-14"""
        with override_settings(LLM_API_BASE_URL="https://example.test/v1"):
            self.assertEqual(config.get_api_base_url(), "https://example.test/v1")

    def test_cf_31_model_tiers_default_to_the_one_default_model(self):
        """CF-31"""
        self.assertUndeclared("LLM_MODEL_TIERS")
        self.assertEqual(config.get_model_tiers(), DEFAULT_MODEL_TIERS)
        self.assertEqual(len(DEFAULT_MODEL_TIERS), 1)

    def test_cf_32_model_tiers_return_the_declared_tiers_in_order(self):
        """CF-32"""
        with override_settings(LLM_MODEL_TIERS=["cheap/model", "dear/model"]):
            self.assertEqual(tuple(config.get_model_tiers()), ("cheap/model", "dear/model"))


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

    @override_settings(LLM_MODEL_TIERS=["openai/gpt-4o"])
    def test_cc_20_none_content_logs_warning(self):
        self.install_client(make_response(None))
        with mock.patch.object(service, "llm_service_log") as log:
            LLMService.chat_completion(MESSAGES, npc_key="npc#7")
        logged = " ".join(str(c) for c in log.call_args_list)
        self.assertIn("WARN", logged)
        self.assertIn("openai/gpt-4o", logged)
        self.assertIn("npc#7", logged)

    def test_cc_21_none_content_returns_none(self):
        self.install_client(make_response(None))
        self.assertIsNone(LLMService.chat_completion(MESSAGES))

    def test_cc_22_empty_content_treated_as_no_reply(self):
        for content in ("", "   \n"):
            with self.subTest(content=content):
                reset_state()
                self.install_client(make_response(content))
                with mock.patch.object(service, "llm_service_log") as log:
                    self.assertIsNone(LLMService.chat_completion(MESSAGES))
                self.assertIn("WARN", " ".join(str(c) for c in log.call_args_list))


# ── CL — client construction ──────────────────────────────────────────


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "say",
            "description": "Say something aloud.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stay_silent",
            "description": "Say nothing.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def make_tool_response(*calls):
    """A response choosing `calls`, each a `(name, arguments_json)` pair."""
    tool_calls = [
        SimpleNamespace(type="function", function=SimpleNamespace(name=name, arguments=arguments))
        for name, arguments in calls
    ]
    message = SimpleNamespace(content=None, tool_calls=tool_calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


class ChooseToolTests(ServiceCase):
    def test_tc_01_returns_the_chosen_tool_and_its_arguments(self):
        self.install_client(make_tool_response(("say", '{"text": "Well met."}')))
        self.assertEqual(
            LLMService.choose_tool(MESSAGES, TOOLS), ToolChoice("say", {"text": "Well met."})
        )

    def test_tc_02_messages_and_tools_reach_the_provider_with_a_tool_required(self):
        client = self.install_client(make_tool_response(("stay_silent", "{}")))
        LLMService.choose_tool(MESSAGES, TOOLS)
        call = client.calls[0]
        self.assertEqual(call["messages"], MESSAGES)
        self.assertEqual(call["tools"], TOOLS)
        self.assertEqual(call["tool_choice"], "required")

    @override_settings(LLM_ENABLED=False)
    def test_tc_03_disabled_returns_none_without_client(self):
        client = self.install_client(make_tool_response(("stay_silent", "{}")))
        self.assertIsNone(LLMService.choose_tool(MESSAGES, TOOLS))
        self.assertEqual(client.calls, [])

    def test_tc_04_model_tokens_and_temperature_work_as_for_chat_completion(self):
        client = self.install_client(make_tool_response(("stay_silent", "{}")))
        LLMService.choose_tool(MESSAGES, TOOLS)
        LLMService.choose_tool(MESSAGES, TOOLS, max_tokens=40, temperature=0.2)
        defaults, given = client.calls
        self.assertEqual((defaults["max_tokens"], defaults["temperature"]), (150, 0.8))
        self.assertEqual((given["max_tokens"], given["temperature"]), (40, 0.2))

    def test_tc_05_a_provider_exception_returns_none_logged_at_error(self):
        self.install_client(exc=RuntimeError("boom"))
        with mock.patch.object(service, "llm_service_log") as log:
            self.assertIsNone(LLMService.choose_tool(MESSAGES, TOOLS, npc_key="npc#7"))
        logged = " ".join(str(c) for c in log.call_args_list)
        self.assertIn("ERROR", logged)
        self.assertIn("npc#7", logged)

    @override_settings(LLM_MODEL_TIERS=["openai/gpt-4o"])
    def test_tc_06_no_tool_chosen_returns_none_logged_at_warn(self):
        self.install_client(make_tool_response())
        with mock.patch.object(service, "llm_service_log") as log:
            self.assertIsNone(LLMService.choose_tool(MESSAGES, TOOLS, npc_key="npc#7"))
        logged = " ".join(str(c) for c in log.call_args_list)
        self.assertIn("WARN", logged)
        self.assertIn("openai/gpt-4o", logged)
        self.assertIn("npc#7", logged)

    def test_tc_07_a_tool_not_offered_returns_none_logged_at_warn(self):
        self.install_client(make_tool_response(("fly_away", "{}")))
        with mock.patch.object(service, "llm_service_log") as log:
            self.assertIsNone(LLMService.choose_tool(MESSAGES, TOOLS))
        logged = " ".join(str(c) for c in log.call_args_list)
        self.assertIn("WARN", logged)
        self.assertIn("fly_away", logged)

    def test_tc_08_arguments_that_are_not_a_json_object_return_none(self):
        for arguments in ("{not json", '["a", "list"]'):
            with self.subTest(arguments=arguments):
                self.install_client(make_tool_response(("say", arguments)))
                with mock.patch.object(service, "llm_service_log") as log:
                    self.assertIsNone(LLMService.choose_tool(MESSAGES, TOOLS))
                logged = " ".join(str(c) for c in log.call_args_list)
                self.assertIn("WARN", logged)
                self.assertIn("say", logged)

    def test_tc_09_several_tools_chosen_returns_the_first(self):
        self.install_client(
            make_tool_response(("say", '{"text": "First."}'), ("stay_silent", "{}"))
        )
        self.assertEqual(
            LLMService.choose_tool(MESSAGES, TOOLS), ToolChoice("say", {"text": "First."})
        )

    def test_tc_10_tool_choice_is_exported_and_frozen(self):
        import evennia_llm_service

        self.assertIs(evennia_llm_service.ToolChoice, ToolChoice)
        self.assertIn("ToolChoice", evennia_llm_service.__all__)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ToolChoice("say", {}).name = "shout"


# ── ES — escalation ───────────────────────────────────────────────────


TIERS = ["tier/zero", "tier/one", "tier/two"]


@override_settings(LLM_MODEL_TIERS=TIERS)
class EscalationTests(ServiceCase):
    """ES — which tier each attempt goes to, and when a call moves up."""

    def install_answers(self, *answers):
        client = SequenceClient(*answers)
        LLMService._client = client
        return client

    def test_es_01_a_call_naming_no_tier_goes_to_tier_zero_once(self):
        """ES-01"""
        client = self.install_answers(make_response("ok"))
        LLMService.chat_completion(MESSAGES)
        self.assertEqual(client.models, ["tier/zero"])

    def test_es_02_start_tier_names_the_first_attempts_tier(self):
        """ES-02"""
        client = self.install_answers(make_response("ok"))
        LLMService.chat_completion(MESSAGES, start_tier=1)
        self.assertEqual(client.models, ["tier/one"])

    def test_es_03_with_no_max_an_empty_answer_is_not_retried(self):
        """ES-03"""
        client = self.install_answers(make_response(None), make_response("ok"))
        self.assertIsNone(LLMService.chat_completion(MESSAGES))
        self.assertEqual(client.models, ["tier/zero"])

    def test_es_04_an_empty_answer_moves_the_same_request_up_a_tier(self):
        """ES-04"""
        client = self.install_answers(make_response(None), make_response("ok"))
        answer = LLMService.chat_completion(
            MESSAGES, max_tokens=12, temperature=0.9, max_escalation_tier=1
        )
        self.assertEqual(answer, "ok")
        self.assertEqual(client.models, ["tier/zero", "tier/one"])
        first, second = client.calls
        self.assertEqual(
            {k: v for k, v in first.items() if k != "model"},
            {k: v for k, v in second.items() if k != "model"},
        )

    def test_es_05_a_provider_exception_moves_up_a_tier(self):
        """ES-05"""
        client = self.install_answers(RuntimeError("boom"), make_response("ok"))
        self.assertEqual(LLMService.chat_completion(MESSAGES, max_escalation_tier=1), "ok")
        self.assertEqual(client.models, ["tier/zero", "tier/one"])

    def test_es_06_the_first_usable_answer_is_returned(self):
        """ES-06"""
        client = self.install_answers(make_response("ok"), make_response("dearer"))
        self.assertEqual(LLMService.chat_completion(MESSAGES, max_escalation_tier=2), "ok")
        self.assertEqual(client.models, ["tier/zero"])

    def test_es_07_empty_through_the_max_returns_none(self):
        """ES-07"""
        client = self.install_answers(
            make_response(None), make_response(None), make_response("too far")
        )
        self.assertIsNone(LLMService.chat_completion(MESSAGES, max_escalation_tier=1))
        self.assertEqual(client.models, ["tier/zero", "tier/one"])

    def test_es_08_an_answer_accept_rejects_moves_up_a_tier(self):
        """ES-08"""
        client = self.install_answers(make_response("bad"), make_response("good"))
        answer = LLMService.chat_completion(
            MESSAGES, max_escalation_tier=1, accept=lambda text: text == "good"
        )
        self.assertEqual(answer, "good")
        self.assertEqual(client.models, ["tier/zero", "tier/one"])

    def test_es_09_an_answer_rejected_at_the_max_returns_none(self):
        """ES-09"""
        self.install_answers(make_response("bad"))
        self.assertIsNone(LLMService.chat_completion(MESSAGES, accept=lambda text: False))

    def test_es_10_accept_is_never_handed_none(self):
        """ES-10"""
        seen = []
        self.install_answers(make_response(None), make_response("ok"))
        LLMService.chat_completion(
            MESSAGES, max_escalation_tier=1, accept=lambda answer: seen.append(answer) or True
        )
        self.assertEqual(seen, ["ok"])

    def test_es_11_a_max_below_the_start_raises_before_any_call(self):
        """ES-11"""
        client = self.install_answers(make_response("ok"))
        with self.assertRaises(ValueError):
            LLMService.chat_completion(MESSAGES, start_tier=2, max_escalation_tier=1)
        self.assertEqual(client.calls, [])

    def test_es_12_a_tier_past_the_last_stops_at_the_last(self):
        """ES-12"""
        client = self.install_answers(make_response("ok"))
        LLMService.chat_completion(MESSAGES, start_tier=9)
        self.assertEqual(client.models, ["tier/two"])

        client = self.install_answers(
            make_response(None), make_response(None), make_response(None)
        )
        self.assertIsNone(LLMService.chat_completion(MESSAGES, max_escalation_tier=9))
        self.assertEqual(client.models, TIERS)

    def test_es_13_choose_tool_escalates_by_the_same_rule(self):
        """ES-13"""
        client = self.install_answers(
            make_tool_response(), make_tool_response(("stay_silent", "{}"))
        )
        answer = LLMService.choose_tool(MESSAGES, TOOLS, max_escalation_tier=1)
        self.assertEqual(answer, ToolChoice("stay_silent", {}))
        self.assertEqual(client.models, ["tier/zero", "tier/one"])

    def test_es_14_choose_tools_accept_is_handed_the_tool_choice(self):
        """ES-14"""
        seen = []
        self.install_answers(make_tool_response(("say", '{"text": "hi"}')))
        LLMService.choose_tool(
            MESSAGES, TOOLS, accept=lambda choice: seen.append(choice) or True
        )
        self.assertEqual(seen, [ToolChoice("say", {"text": "hi"})])


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
    def test_cl_03_missing_key_builds_with_empty_string(self):
        # Reachable only with the library disabled — check_settings refuses a
        # boot that is enabled without a key (CF-23). _get_client still has to
        # behave rather than raise, since nothing guards it directly.
        with undeclared("LLM_API_KEY"):
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
        override = folder(self.dir)
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
    def test_pd_01_resolves_declared_folder_not_package_dir(self):
        package_dir = os.path.dirname(prompt_loader.__file__)
        self.write_prompt("here.md", "in the declared folder")
        self.assertEqual(prompt_loader.load_prompt("here.md"), "in the declared folder")
        self.assertFalse(os.path.exists(os.path.join(package_dir, "here.md")))

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

    def test_pl_16_empty_template_logs_warning_with_path(self):
        path = self.write_prompt("empty.md", "")
        with mock.patch.object(prompt_loader, "llm_service_log") as log:
            prompt_loader.load_prompt("empty.md")
        logged = " ".join(str(c) for c in log.call_args_list)
        self.assertIn(path, logged)
        self.assertIn("WARN", logged)

    def test_pl_17_empty_template_returns_none(self):
        self.write_prompt("empty.md", "")
        self.assertIsNone(prompt_loader.load_prompt("empty.md"))

    def unreadable_prompt(self, name):
        """A template that exists but the process cannot read."""
        path = self.write_prompt(name, "you will never read me")
        os.chmod(path, 0o000)
        # Restored so the temporary directory can be removed afterwards.
        self.addCleanup(os.chmod, path, 0o600)
        return path

    @unittest.skipIf(os.geteuid() == 0, "root reads a 0o000 file regardless")
    def test_pl_11_unreadable_template_logs_error_with_path(self):
        path = self.unreadable_prompt("locked.md")
        with mock.patch.object(prompt_loader, "llm_service_log") as log:
            prompt_loader.load_prompt("locked.md")
        logged = " ".join(str(c) for c in log.call_args_list)
        self.assertIn(path, logged)
        self.assertIn("ERROR", logged)
        # The reason, so permissions and encoding are told apart in the log
        # without needing a traceback.
        self.assertIn("Permission denied", logged)

    @unittest.skipIf(os.geteuid() == 0, "root reads a 0o000 file regardless")
    def test_pl_12_unreadable_template_returns_none(self):
        self.unreadable_prompt("locked.md")
        self.assertIsNone(prompt_loader.load_prompt("locked.md"))

    @unittest.skipIf(os.geteuid() == 0, "root reads a 0o000 file regardless")
    def test_pl_13_unreadable_template_is_cached_as_none(self):
        path = self.unreadable_prompt("locked.md")
        with mock.patch.object(prompt_loader, "llm_service_log") as log:
            self.assertIsNone(prompt_loader.load_prompt("locked.md"))
            os.chmod(path, 0o600)
            # Readable now, but the cached None stands — proof the second
            # call never reached the disk.
            self.assertIsNone(prompt_loader.load_prompt("locked.md"))
        self.assertEqual(log.call_count, 1)

    def test_pl_14_directory_treated_as_unreadable(self):
        os.makedirs(os.path.join(self.dir, "bartender.md"))
        with mock.patch.object(prompt_loader, "llm_service_log") as log:
            self.assertIsNone(prompt_loader.load_prompt("bartender.md"))
        self.assertIn("bartender.md", " ".join(str(c) for c in log.call_args_list))

    def test_pl_15_undecodable_template_treated_as_unreadable(self):
        path = os.path.join(self.dir, "cp1252.md")
        with open(path, "wb") as handle:
            handle.write(b"You are \xff\xfe not valid utf-8")
        with mock.patch.object(prompt_loader, "llm_service_log") as log:
            self.assertIsNone(prompt_loader.load_prompt("cp1252.md"))
        self.assertIn("cp1252.md", " ".join(str(c) for c in log.call_args_list))


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

    def test_xc_09_settings_read_only_through_config(self):
        # config.py is the one place a setting name is written down. A second
        # module reading django.conf.settings is how a library ends up
        # validating one setting at boot and reading a different one at
        # runtime — which is exactly what this catches.
        package_dir = os.path.dirname(evennia_llm_service.__file__)
        offenders = []
        for root, _dirs, files in os.walk(package_dir):
            for name in files:
                if not name.endswith(".py") or name in ("tests.py", "config.py"):
                    continue
                tree = ast.parse(open(os.path.join(root, name)).read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module == "django.conf":
                        if any(a.name == "settings" for a in node.names):
                            offenders.append(f"{name}:{node.lineno}")
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
