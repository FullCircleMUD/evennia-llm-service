# Interoperability

This library against every sibling library in `libraries/`.

What this library does that could constrain a sibling is short, because the library is short. It makes
one **outbound network call** on the calling thread, holds a **provider API key** read from Django
settings, creates a **directory under `GAME_DIR`** at `AppConfig.ready()`, and writes to its own log
file. It declares no Django models, registers no router, touches no `ObjectDB` row, and dispatches
nothing off the thread it is called on.

The blocking call is the one thing worth knowing about. `chat_completion` waits on a network round
trip, so a consumer that calls it on Evennia's reactor thread stalls every connected player. The
dispatch is the consumer's, and so is the requirement.

## evennia-ai-memory

**No coupling today; the closest sibling by subject.** Neither library imports the other, and neither
needs the other installed.

The boundary was drawn deliberately. `evennia-ai-memory` owns embedding end to end — its own
`AI_MEMORY_EMBEDDING_*` settings, its own client, and its own `EmbeddingError` taxonomy with retries.
This library therefore ships no embedding call at all, and the two hold **separate provider
credentials**, which is worth knowing when a key is rotated: there are two places to change it, and a
consumer may legitimately point them at different endpoints, since a completion provider does not
always serve embeddings.

A consumer wiring both together does so in its own code: retrieve from ai-memory, put the result in a
prompt variable, call this library. Because both are synchronous by contract, all of it fits in one
`deferToThread` — see [stages.md](stages.md) for the shape.

Keeping them independent is the working position, not an accident of sequencing.

## evennia-archive

**No coupling.** Neither library imports the other. Archive installs a database router and writes to a
second alias; this library declares no models, registers no router and issues no ORM query, so nothing
it does is visible to that layer.

## evennia-llm-service

This library.

## evennia-message-bus

**No coupling.** Neither library imports the other. Message-bus is a transport between Evennia
instances with its own models and polling loop; this library has neither persistence nor a loop, and
holds no state that would need to reach another instance.

## evennia-mob-spawner

**No coupling.** Neither library imports the other. Mob-spawner creates and despawns game objects;
this library resolves no game object and holds no reference to one. `npc_key` is an opaque string used
in a log line — this library never looks up what it refers to, so a despawn cannot invalidate anything
it holds.

## evennia-shards

**No coupling, with one constraint that lands on the consumer.** Neither library imports the other,
and neither of shards' recurring constraints is this library's to satisfy.

Tenancy is installed on `ObjectDB`. This library issues no ORM query at all, so there is no `shard_id`
to scope and no auto-stamp to lose.

The off-thread constraint is the one to watch, and it is sharpened here rather than avoided.
`chat_completion` blocks on a network call, so a consumer running under shards will dispatch it with
`deferToThread` — and shards requires `preserve_tenant_context` **at the dispatch site**. Since the
dispatch site is the consumer's, so is the wrap. It is needed whenever the same worker also touches
`ObjectDB`, which a consumer assembling a prompt from NPC state generally will. The constraint is
documented on shards' side; see `../../evennia-shards/docs/interoperability.md`.

One thing shards makes concrete: a per-process limit is not a global one. That is part of why this
library enforces no rate limit or spend cap — a game running a router and two shards would have three
of each. See [stages.md](stages.md).

## evennia-targeting

**No coupling.** Neither library imports the other. Targeting filters candidate lists already in hand
and issues no call this library would serve.

## evennia-world-builder

**No coupling.** Neither library imports the other.

Both write under `GAME_DIR` — world-builder builds from a content repo, this library creates
`llm_service/prompts/`. The paths do not overlap and neither reads the other's, but a consumer moving
either with a setting should keep them distinct.

## evennia-yaml-reader

**No coupling.** Neither library imports the other. Prompt templates are plain text rendered with
`str.format_map`; nothing in this library parses YAML.
