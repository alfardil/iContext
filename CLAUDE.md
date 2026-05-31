# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`icontext/` is a two-project workspace. Each subdirectory has its own `CLAUDE.md` with project-specific commands and architecture — read those first when you go in. This file documents what's only true at the integration layer.

- **`ghostwriter/`** — Spring Boot 4 / Java 25 Telegram chatbot, model via Spring AI's Anthropic starter (Claude Haiku 4.5). See `ghostwriter/CLAUDE.md`.
- **`messages/`** — Python library `imsg` that reads `~/Library/Messages/chat.db`, plus an MCP server `imsg_mcp` that exposes its data as tools. See `messages/CLAUDE.md`.

## How the two glue together

```
Telegram → ghostwriter (:8080) → Kafka task → AgentService ─► QuestionCacheService (pgvector)
                                                       │ miss
                                                       ▼
                                                    LLMClient
                                                       │
                                                       ▼ Spring AI ChatClient
                                                    Anthropic Claude
                                                       │ MCP tool callbacks
                                                       ▼
                                                imsg_mcp (:5050/mcp)
                                                       │
                                                       ▼
                                              ~/Library/Messages/chat.db
                                              + ~/.imsg-mcp/vectors.db (sqlite-vec)
```

Each Telegram message first hits a **semantic cache**: `AgentService` calls `QuestionCacheService.lookup(userId, question)`, which embeds the question in-process via Spring AI's `TransformersEmbeddingModel` (MiniLM-L6, 384-dim) and does a pgvector cosine-distance lookup in the `QuestionCache` table. Hit (cosine sim ≥ `app.cache.similarity-threshold`, default 0.85, TTL `app.cache.ttl`, default 1h) → short-circuit, skip Anthropic + MCP entirely. Miss → run the LLM, write the result back to the cache.

`ghostwriter` uses `spring-ai-starter-mcp-client` to auto-discover tools from the imsg MCP server. The starter is wired at `spring.ai.mcp.client.streamable-http.connections.imsg.url` in `ghostwriter/src/main/resources/application.yaml`, defaulting to `${IMSG_MCP_URL:http://localhost:5050}` (port 5050, not 5000 — macOS's AirPlay Receiver squats on 5000). `LLMClient` (in `common/service/llm/`) injects `SyncMcpToolCallbackProvider` and hands the tool callbacks to every `ChatClient.prompt()` call — adding a new tool on the Python side requires zero Java changes.

The five MCP tools exposed by `imsg_mcp`: `find_contacts`, `list_chats`, `semantic_search_messages`, `index_chat`, `index_status`. Search is semantic-only (MiniLM embeddings in sqlite-vec) — there is intentionally no keyword/substring search tool.

## Dev workflow for the whole stack

`imsg_mcp` has to run on the macOS host — the iMessage `chat.db` needs Full Disk Access, which Docker Desktop containers can't get. Everything else is in the root `docker-compose.yml`.

```bash
# 1) imsg MCP server (host)
cd messages && just serve            # → :5050/mcp

# 2) Kafka + ghostwriter (compose). Postgres runs on your Mac, not in compose.
cp .env.example .env && $EDITOR .env  # first time only
docker compose up -d                  # → ghostwriter on :8080

# 3) Real Telegram round-trips (adds ngrok)
docker compose --profile public up -d
```

Inside the compose network, ghostwriter reaches both the host MCP server (`host.docker.internal:5050`) and the host Postgres (`host.docker.internal`, port/credentials from `.env`) via the host gateway — both set in the `ghostwriter.environment` block, which overrides whatever's in `.env`. Kafka uses service DNS (`kafka:9092`). **Postgres runs on your Mac in dev** (no DB container, no volume): it must have the `pgvector` extension available — Flyway runs all three migrations (message table, `CREATE EXTENSION vector`, question cache) against it on ghostwriter boot — and must listen beyond `127.0.0.1` (`listen_addresses='*'` + a matching `pg_hba.conf` line) so the container can reach it. Health probe at `GET /actuator/health`. See `DEPLOYMENT.md` for the production topology (where the Mac becomes an async indexer and the cloud holds a queryable replica, so the bot answers even while the Mac is asleep).

## Operational gotchas worth knowing before debugging

- **Spring AI's MCP client caches the session ID across requests; it does NOT re-handshake when the MCP server restarts.** If you restart `imsg_mcp/server.py`, you must also restart ghostwriter or every tool call returns `McpTransportSessionNotFoundException`. The reverse is fine.

- **`messages/.venv` exists because pyenv builds Python without `--enable-loadable-sqlite-extensions`**, which `sqlite-vec` requires. The venv was created from a uv-managed Python that has the flag. Always invoke `.venv/bin/python` / `.venv/bin/fastmcp` — never bare `python`. To rebuild: `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[mcp,dev]"` (`dev` adds pytest/mypy/ruff so the suite runs in the same venv).

- **Snapshot isolation matters.** `Cache.snapshot()` in `imsg_mcp/store_cache.py` writes each refresh to a unique `/tmp/imsg-mcp/snap-<ts>/` dir and cleans the old one only after a 120s grace window. Reusing a single path corrupts sqlite for any in-flight reader (manifests as `database disk image is malformed`).

- **`MessageStore.message_by_guid` does a full table scan per call** — never use it inside a loop. For semantic search hit assembly we go straight to the snapshot SQLite with `WHERE m.guid IN (?, ?, …)`; see `fetch_messages_by_guids` in `imsg_mcp/snapshot_queries.py` (rows are turned into hits by `_fetch_hits_by_guids` in `tools.py`).

- **All ad-hoc snapshot SQL lives in `imsg_mcp/snapshot_queries.py`.** The `message → chat_message_join → chat` join and the "real message" filter (`COALESCE(associated_message_type,0)=0 AND COALESCE(item_type,0)=0`, which drops tapbacks and group/system events) are defined exactly once there. `tools.py` (list_chats, hit assembly) and `indexer.py` (warm-start ranking, per-chat counts) call those helpers — add new aggregates to `snapshot_queries`, never hand-roll the join inline again. Covered by `tests/test_snapshot_queries.py` (runs in CI; needs only `imsg`, no MCP extras).

- **Tool JSON schemas are post-processed** to strip `"default": null` from optional-with-default Pydantic fields. Google's GenAI SDK NPEs on null defaults (`Optional.of(null)`). The Anthropic path doesn't strictly need this, but the sanitizer (`_sanitize_tool_schemas` in `imsg_mcp/server.py`) stays so any future provider swap doesn't regress. `fastmcp run` boots inside a running event loop, so the sanitizer reaches the components dict directly rather than via `asyncio.run(mcp.list_tools())`.

- **Telegram delivery uses `parse_mode=HTML`** with an automatic plain-text retry on 400. The system prompt in `LLMClient.java` instructs Claude to emit `<b>`/`<i>` tags only — never Markdown asterisks. Telegram HTML only requires escaping `<`, `>`, `&` outside tags, which Claude handles via the prompt instruction.

- **Per-chat semantic indexing**: a chat is embedded on first `semantic_search_messages` / `index_chat` call. The server also warm-starts the top 10 recent chats on boot. Status lives in `~/.imsg-mcp/vectors.db.chat_meta`; `index_status()` reads it.

- **Spring Kafka retry storm is mitigated, not eliminated.** `kafka/config/KafkaErrorHandlerConfig.java` registers a `DefaultErrorHandler` with `NonTransientAiException` + `HttpClientErrorException` flagged non-retryable and a 2-attempt `FixedBackOff(1s)` for everything else. A 4xx from Anthropic still costs one extra retry, not ten. Transient 5xx still retry.

- **Cache hits never reach the LLM.** A `QuestionCache` row stores the original `question`, its embedding, and the prior `aiResponse` per `userId` with a 1h TTL (`app.cache.ttl`). If you've changed iMessages and want fresh results within that window, currently the only options are: wait, lower the TTL, or `DELETE FROM "QuestionCache" WHERE "userId" = '...'` directly.
