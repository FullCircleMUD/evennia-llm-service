# SPDX-License-Identifier: BSD-3-Clause
"""LLMService — the provider client.

Stage one: lifted from FullCircleMUD's ``src/game/llm/service.py`` with the
same settings, method names, signatures and return values. See
docs/test-plan.md for the behaviour this is committed to reproducing.

Three things in the substrate are deliberately **not** lifted, because each
belongs to someone better placed to do it:

- ``create_embedding`` — ``evennia-ai-memory`` owns embedding end to end.
- **Rate limiting and the daily cost cap** — enforced on the provider's API
  key, where the limit applies to actual spend rather than to one process.
- **Cost tracking** — it existed to feed the cap, and the provider reports
  usage more accurately than an estimate from a hardcoded price table.

What remains is the call itself. Per-NPC throttling is a game rule and lives
on the consumer's NPC.

Defaults live here rather than in the consumer's settings, so a game that
declares nothing still runs.
"""

import json
from dataclasses import dataclass

from .config import (
    get_api_base_url,
    get_api_key,
    get_enabled,
    get_model_tiers,
)
from .log import llm_service_log


@dataclass(frozen=True)
class ToolChoice:
    """The tool a completion chose, and its arguments.

    Attributes:
        name: the chosen tool's name, one of those offered.
        arguments: its arguments, parsed from the call's JSON into a dict.
    """

    name: str
    arguments: dict


class LLMService:
    """Centralized service for all LLM API calls."""

    _client = None

    # ── Public API ────────────────────────────────────────────────────

    @classmethod
    def chat_completion(
        cls,
        messages,
        max_tokens=150,
        temperature=0.8,
        npc_key=None,
        start_tier=0,
        max_escalation_tier=None,
        accept=None,
    ):
        """Send a chat completion request.

        Synchronous. The caller is responsible for wrapping it in
        ``deferToThread`` so it does not block the Twisted reactor.

        ``npc_key`` identifies the caller in the log. It carries no
        throttling or accounting.

        ``start_tier``, ``max_escalation_tier`` and ``accept`` choose the model
        and when to move up a tier — see ``_escalate``.

        Returns:
            str: the assistant's response text, or None if disabled or no
                tier gave a usable answer.
        """
        return cls._escalate(
            lambda model: cls._complete_once(
                model, messages, max_tokens, temperature, npc_key
            ),
            start_tier,
            max_escalation_tier,
            accept,
        )

    @classmethod
    def choose_tool(
        cls,
        messages,
        tools,
        max_tokens=150,
        temperature=0.8,
        npc_key=None,
        start_tier=0,
        max_escalation_tier=None,
        accept=None,
    ):
        """Send a completion that must answer by choosing one of ``tools``.

        Synchronous, like ``chat_completion``: the caller wraps it in
        ``deferToThread``. ``tools`` is a list in the OpenAI tool format —
        each a name, a description and a JSON schema for its arguments.
        Tiers escalate as for ``chat_completion``; ``accept`` is handed the
        ``ToolChoice``.

        Returns:
            ToolChoice: the tool chosen and its arguments, or None if disabled
                or no tier gave a usable answer.
        """
        return cls._escalate(
            lambda model: cls._choose_once(
                model, messages, tools, max_tokens, temperature, npc_key
            ),
            start_tier,
            max_escalation_tier,
            accept,
        )

    # ── Internal ──────────────────────────────────────────────────────

    @classmethod
    def _escalate(cls, attempt, start_tier, max_escalation_tier, accept):
        """Run ``attempt(model)`` from ``start_tier`` up, until one is usable.

        An attempt is unusable when it answers ``None`` or ``accept`` rejects
        it. ``max_escalation_tier`` is the highest tier tried, and defaults to
        ``start_tier`` — no escalation. Either past the last tier stops at the
        last tier, so a caller works against a game that declared fewer.

        Raises:
            ValueError: ``max_escalation_tier`` is below ``start_tier`` — the
                caller's mistake, whatever tiers the game declared.
        """
        if max_escalation_tier is None:
            max_escalation_tier = start_tier
        if max_escalation_tier < start_tier:
            raise ValueError(
                f"max_escalation_tier {max_escalation_tier} is below "
                f"start_tier {start_tier}"
            )

        if not get_enabled():
            return None

        tiers = get_model_tiers()
        last = len(tiers) - 1
        for model in tiers[min(start_tier, last) : min(max_escalation_tier, last) + 1]:
            answer = attempt(model)
            if answer is not None and (accept is None or accept(answer)):
                return answer
        return None

    @classmethod
    def _complete_once(cls, model, messages, max_tokens, temperature, npc_key):
        """One chat completion against ``model``: the text, or None, logged."""
        try:
            client = cls._get_client()
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            content = response.choices[0].message.content
        except Exception:
            llm_service_log(
                f"call failed: model={model} npc={npc_key}",
                level="ERROR",
                trace=True,
            )
            return None

        # The provider answered, but with nothing to say — a content filter,
        # a refusal, or an empty completion. Without this the caller gets the
        # same None as a disabled library or a failed call, and nothing
        # anywhere says which of the three it was.
        if content is None or not content.strip():
            llm_service_log(
                f"provider returned no content: model={model} npc={npc_key}",
                level="WARN",
            )
            return None

        return content

    @classmethod
    def _choose_once(cls, model, messages, tools, max_tokens, temperature, npc_key):
        """One tool-choosing completion against ``model``: the choice, or None, logged."""
        try:
            client = cls._get_client()
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="required",
                max_tokens=max_tokens,
                temperature=temperature,
            )
            message = response.choices[0].message
        except Exception:
            llm_service_log(
                f"call failed: model={model} npc={npc_key}",
                level="ERROR",
                trace=True,
            )
            return None

        # The provider answered, but not with a choice this caller can act on.
        # Each is logged by what was wrong, since all of them return None.
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            llm_service_log(
                f"provider chose no tool: model={model} npc={npc_key}",
                level="WARN",
            )
            return None

        chosen = tool_calls[0].function
        offered = {tool["function"]["name"] for tool in tools}
        if chosen.name not in offered:
            llm_service_log(
                f"provider chose {chosen.name!r}, which was not offered: "
                f"model={model} npc={npc_key}",
                level="WARN",
            )
            return None

        try:
            arguments = json.loads(chosen.arguments or "{}")
        except (TypeError, ValueError):
            arguments = None
        if not isinstance(arguments, dict):
            llm_service_log(
                f"provider chose {chosen.name!r} with arguments that are not a JSON "
                f"object: model={model} npc={npc_key}",
                level="WARN",
            )
            return None

        return ToolChoice(chosen.name, arguments)

    @classmethod
    def _get_client(cls):
        """Lazy-init the completion client."""
        if cls._client is None:
            from openai import OpenAI

            cls._client = OpenAI(
                base_url=get_api_base_url(),
                api_key=get_api_key(),
            )
        return cls._client
