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

from .config import (
    get_api_base_url,
    get_api_key,
    get_default_model,
    get_enabled,
)
from .log import llm_service_log


class LLMService:
    """Centralized service for all LLM API calls."""

    _client = None

    # ── Public API ────────────────────────────────────────────────────

    @classmethod
    def chat_completion(
        cls,
        messages,
        model=None,
        max_tokens=150,
        temperature=0.8,
        npc_key=None,
    ):
        """Send a chat completion request.

        Synchronous. The caller is responsible for wrapping it in
        ``deferToThread`` so it does not block the Twisted reactor.

        ``npc_key`` identifies the caller in the log. It carries no
        throttling or accounting.

        Returns:
            str: the assistant's response text, or None if disabled or
                the call failed.
        """
        if not get_enabled():
            return None

        model = model or get_default_model()

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

    # ── Internal ──────────────────────────────────────────────────────

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
