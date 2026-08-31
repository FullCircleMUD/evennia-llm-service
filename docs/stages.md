# Stages

The library is being extracted from FullCircleMUD in stages. This records what each stage covers and
what was decided for the later ones, so a decision reached in conversation is not lost between them.

## Stage one — the lift (complete)

Take `src/game/llm/service.py` and `prompt_loader.py` out of FCM and into the library, keeping the
same settings, method names, signatures and return values. Complete when FCM can delete its LLM
service code, install the library, and the game still works.

Four deviations were agreed, each because the thing belongs to someone better placed to do it:

- **The prompts directory.** The substrate resolved it from its own `__file__`, which points inside
  the library once moved. The library owns a fixed location under the gamedir instead.
- **`create_embedding`.** `evennia-ai-memory` owns embedding end to end — its own settings, client and
  error taxonomy — so there is no caller for one here.
- **Rate limiting and the daily cost cap.** Enforced on the provider's API key, where the limit
  applies to actual spend. A per-process cap in a game running a router and two shards was three times
  the budget it claimed.
- **Cost tracking.** It existed to feed the cap, had no caller in FCM, and estimated from five
  hardcoded prices.

Per-NPC throttling stays a game rule: FCM's mixin already does it with `llm_cooldown_seconds` before
it ever reaches the service.

## Stage two — the mixin

`LLMMixin` moves out of FCM. It is 1,049 lines and most of it is game behaviour, not infrastructure —
of its 24 per-NPC attributes, roughly six are the library's (model, max tokens, temperature, prompt
file, cooldown, enabled) and the rest are FCM's: `llm_speech_mode`, `llm_engagement_timeout`,
`llm_thinking_emote`, `llm_snub_socials`, `llm_snub_comments`, `llm_blind_challenges` and the five
`llm_hook_*` switches.

So the library's mixin is not this file relocated. It is the thin part underneath, with FCM's mixin
sitting on top and keeping the behaviour.

`[TBD — needs discussion: whether the mixin ships in `contrib/` or in core. Proposed as contrib, on
the grounds that core stays ignorant of Evennia objects and a game whose NPCs work differently ignores
it. Not confirmed.]`

**The design problem to solve first.** FCM's `llm_respond()` does prompt assembly, memory retrieval and
the completion inside one `deferToThread` closure. That is not incidental: when only the final call was
wrapped, any NPC using lore or vector memory made synchronous embedding calls on the reactor thread,
blocking every connected player. If the library's mixin owns the thread hop, it needs a hook that runs
*inside* it so the consumer can do expensive preparation without a second hop.

## Agreed for a later stage, not yet scheduled

Decided in conversation and recorded so the reasoning survives. None of it is built.

- **One exception type.** Every failure means the same thing to a caller — no answer, use your
  fallback — so the library raises one exception rather than returning `None`, and the reason goes to
  the log. A broken key and a rate limit differ only in the log line.
- **No `LLM_ENABLED`.** A settings flag that turns the library off is the library second-guessing the
  consumer who installed it. Dropping it means the library needs to be stubbable another way for a
  consumer's test suite — injecting the client, most likely.
- **Prompt `defaults`.** Each template declares a JSON `defaults` object; a placeholder absent from the
  caller's variables falls back to it. A placeholder with neither is an authoring error and raises.
- **A prompt validator.** A public function checking that every placeholder in a template has a
  default, run over the whole directory at startup. It logs and names the file and the offending
  placeholders; it does not stop the boot, because a bad prompt has a fallback by design. The cache
  flush command re-runs it.
- **Memory integration.** The library takes `evennia-ai-memory` as a hard dependency, does the
  retrieval itself inside the same thread hop as the completion, and fills a reserved `{memory}`
  placeholder that the consumer never supplies. Retrieval happens only when the caller passes the
  arguments that need it, and a per-object attribute overrides a settings default. Every ai-memory
  import sits behind a single seam module.
- **The library does not wire ai-memory up.** ai-memory is independently installable and documents its
  own `INSTALLED_APPS` line. This library detects and errors at boot if it is missing or unmigrated,
  naming what to add — and checks nothing about ai-memory's alias or router, which ai-memory registers
  itself.

`[TBD — needs discussion: whether a missing provider key should also stop the boot. Same class of
misconfiguration, but the prompt validator logs rather than blocking, so the library is not uniformly
strict.]`
