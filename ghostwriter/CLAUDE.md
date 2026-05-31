# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Build / compile**
```bash
./mvnw compile
```

**Run**
```bash
mvn spring-boot:run
# or via just:
just dev
```

**Run tests**
```bash
./mvnw test
# single test class:
./mvnw test -Dtest=GhostwriterApplicationTests
```

**DB migrations** (requires `.env` loaded via `dotenvx`)
```bash
just migrate      # apply pending migrations
just drop         # wipe and reset (sets cleanDisabled=false)
```

Migrations live in `db/migration/` and follow the Flyway naming convention `V####__Description.sql`. They run automatically on app startup.

## Architecture

This is a Telegram chatbot backed by Gemini AI. The request/response flow is fully async through two Kafka topics:

```
Telegram webhook → [task topic] → AgentService (Gemini) → [reply topic] → TaskConsumer → Telegram
                                          ↓
                                     Message table (Postgres)
```

1. **`ApiController`** receives Telegram webhook POSTs at `/api/webhook`, extracts `userId` (Telegram chat ID) and message text, and publishes to the `task` Kafka topic with `userId` as the key.
2. **`AgentService`** consumes from `task`, calls Gemini, writes the exchange (userId + both sides) to the `Message` table, then publishes the AI reply to the `reply` topic. The two-topic design intentionally decouples AI calls from Telegram delivery — a Telegram send failure should not re-invoke Gemini.
3. **`TaskConsumer`** consumes from `reply` and calls `TelegramService.sendMessage()` to deliver the response.

## Key conventions

- **camelCase** for all variable names (including SQL column identifiers, which are quoted: `"telegramId"`, `"createdAt"`, etc.).
- DB models use `@NotNullColumn` / `@NullColumn` source-retention annotations to document nullability at a glance — they have no runtime effect.
- Repository layer uses Spring `JdbcClient` directly (no ORM). IDs are `UUID.randomUUID()` generated in Java before insert; `createdAt` is returned via `RETURNING`.
- All repository implementations follow the pattern: interface in `repos/<entity>/`, SQL impl in the same package.
- Kafka runs as a local plaintext broker (the `kafka` service in the root `docker-compose.yml`, reached via `${KAFKA_SERVER}`); there is no SSL/mTLS config. In the `prod` profile Kafka is dropped entirely — the webhook is handled inline (`MessageIntake` → `InlineMessageIntake`). See `DEPLOYMENT.md`.
- Environment variables are loaded from `.env` via Spring's `optional:file:.env[.properties]` import.
