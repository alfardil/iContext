# Deployment

This is the production plan, optimized for one goal you stated: **cheapest possible, and the
bot must still answer when my Mac is off — just from the latest snapshot it had.**

> Status: the cloud-replica pieces are now **implemented** (see "What's built" below). What's left
> is operational, not code: stand up a host (Oracle free ARM or Hetzner), run Postgres+pgvector and
> ghostwriter on it with `SPRING_PROFILES_ACTIVE=prod`, point the Mac's push job at it over
> Tailscale, and move the Telegram webhook to the box's URL.

## The one idea that makes this work

Today (dev) the request path runs *through* your Mac:

```
Telegram → ghostwriter → MCP over HTTP → imsg_mcp (Mac) → chat.db + sqlite-vec
```

If the Mac sleeps, that path is broken — the bot goes down. You can't fix that by "trying the
snapshot," because the snapshot, the vector index, and the MCP server all live on the Mac.

So in prod we **take the Mac out of the request path** and make it a *publisher* instead:

```
        ┌─ when awake ──────────────────────────────────────────────┐
Mac:    imsg_mcp embeddings + indexer  ──push new vectors+text──►  Cloud Postgres (pgvector)
        (launchd, every ~10 min)                                        ▲
                                                                        │ SQL KNN (no Mac involved)
Telegram → ghostwriter (always-on cloud) ── embeds query in-process ────┘
                         └── answers from whatever the Mac last pushed ──► Telegram
```

- ghostwriter does semantic search with a plain SQL query against the cloud pgvector table
  (`ORDER BY embedding <=> :query_vec LIMIT k`). It never calls the Mac.
- The Mac, **whenever it happens to be awake**, embeds any new messages and upserts them into
  that same cloud table. When the Mac is asleep, nothing pushes — and ghostwriter simply answers
  from the rows already there. **Staleness == time since the Mac last synced**, which is exactly
  "query the latest snapshot if my Mac is not on."

Why this is also the *cheapest* path: it reuses infrastructure that already exists on both ends.

- **ghostwriter already runs the embedding model in-process.** `QuestionCacheService` uses Spring
  AI's `TransformersEmbeddingModel` = `all-MiniLM-L6-v2`, 384-dim — the *same* model
  `imsg_mcp/embeddings.py` uses for messages. Query vectors and message vectors land in the same
  space for free, no embedding API, no extra service. (Keep both pinned to all-MiniLM-L6-v2.)
- **You already run Postgres with pgvector** for `QuestionCache`. The message vectors go in the
  same database — one DB, not a second system.

## Recommended stack (cheapest first)

**Option A — $0/mo: one always-free Oracle VM runs everything.** Two shapes of the free tier:
- **Ampere A1 (ARM), up to 4 vCPU / 24 GB** — the roomy one; the whole stack incl. Kafka fits with
  no diet. Often capacity-constrained at signup ("out of capacity").
- **VM.Standard.E2.1.Micro (x86), 1 vCPU / 1 GB** — the always-available fallback. **This is what's
  deployed.** 1 GB does *not* hold a second JVM, so **Kafka is dropped in `prod`** (inline path) and
  the box runs ghostwriter + Postgres + Caddy with a swap file as a shock absorber. Tight but works.
- On that one box: ghostwriter + Postgres (with `pgvector`) + Caddy (TLS). That's it.
- Mac → VM sync travels over **Tailscale** (free) so Postgres is never exposed to the public
  internet — the Mac dials the VM's Tailscale IP.
- Telegram webhook (HTTPS-only) terminates at **Caddy** on the box, which auto-provisions a
  Let's Encrypt cert for your domain and proxies to ghostwriter. **ngrok is gone in prod.**
- Fixed infra cost: **$0.** You pay only Anthropic per query — and only on a cache miss, since
  `QuestionCache` short-circuits repeats.

**Option B — ~$4–5/mo, less fiddly: a tiny paid VPS.**
- A **Hetzner CX22** (~€3.79/mo, 2 vCPU / 4 GB) running the same single-box layout. More reliable
  to provision than Oracle's free ARM (which can be capacity-constrained at signup) and dead
  simple. Same Tailscale + drop-ngrok story.

**Avoid for this workload:** Render/Railway free web tiers (they sleep on idle → cold starts on a
webhook bot = dropped/slow replies), and managed Postgres-as-a-separate-service (Neon/Supabase are
fine and have free pgvector, but a separate DB only adds moving parts when one box already has
room — use them only if you deliberately want serverless Postgres).

## What changes from dev → prod

| | Dev (today) | Prod (this plan) |
|---|---|---|
| Postgres | on your Mac (host) | on the cloud box, with pgvector |
| Message search | MCP → imsg_mcp on Mac, sqlite-vec | SQL KNN on cloud pgvector, in ghostwriter |
| Mac's role | serves live queries | async publisher (push embeddings when awake) |
| Mac asleep | bot is down | bot answers from last sync (stale, by design) |
| Kafka | in compose | **dropped** — inline path instead (see below) |
| Ingress | webhook → Kafka `task` → AgentService | webhook → 200 + background thread → reply (`InlineMessageIntake`) |
| ngrok | in compose (`--profile public`) | drop it; use the box's real URL |
| Embeddings | MiniLM on Mac (messages) + ghostwriter (queries) | unchanged — same model both ends |

**Dropping Kafka in prod.** Kafka earns its keep under bursty multi-user load and for retry/credit
control. For a single Telegram user it's an always-on JVM broker — and on a 1 GB box it's the one
process that doesn't fit (a second JVM next to ghostwriter's). So in `prod` it's gone: the webhook
returns 200 immediately and a small background pool (`InlineMessageIntake`) runs
`QuestionCache lookup → (miss) LLM → reply → Telegram`. The two things Kafka gave us that actually
matter are preserved: the **QuestionCache** (cache hits never hit Anthropic) and **no retry storms**
— the inline path logs-and-drops on failure rather than re-calling Anthropic, so a bad request can't
burn credits in a loop. The `dev` profile is unchanged and still runs the full two-topic Kafka flow.

## What's built

1. **Flyway `V0004__Create_message_vectors_table.sql`** (`ghostwriter/src/main/resources/db/migration/`)
   — the `MessageVector` pgvector table storing the text *alongside* the vector, so reads need
   nothing from the Mac. HNSW cosine index on the embedding, plus btree indexes on `chatGuid`,
   `senderName`, and `sentAt` for the filters below. Runs automatically on ghostwriter boot.

2. **Mac-side push job** — `messages/imsg_mcp/push.py` (`just push`, or `python -m imsg_mcp.push`).
   Reuses `imsg.MessageStore` (same snapshot + "real message" stream) and `imsg_mcp.embeddings`
   (same MiniLM-L6), and swaps the sink: it `INSERT … ON CONFLICT ("msgGuid") DO UPDATE`s into the
   cloud `MessageVector`. Incremental + idempotent — per chat it reads `MAX("sentAt")` already in
   Postgres and only embeds messages after that. Connect over Tailscale via `GHOSTWRITER_PG_DSN`.
   Schedule with the launchd plist at `messages/scripts/com.icontext.imsg-push.plist` (`StartInterval`
   fires only while the Mac is awake — no cron-on-a-sleeping-Mac problem). Needs the `push` extra:
   `uv pip install --python .venv/bin/python -e ".[mcp,push]"`.

3. **ghostwriter search** — `MessageVectorSearchService` (`common/service/search/`) exposes a
   `search_messages` `@Tool` that embeds the query with the existing `EmbeddingModel` (the same
   MiniLM the question cache uses) and runs the pgvector KNN via `MessageVectorSqlRepository`,
   optionally filtered by `senderName` (ILIKE) and a `since`/`until` date range. Profile wiring lives
   in `ToolConfig`: the default/dev profile bridges the Mac's MCP tools (`AgentToolset` from
   `SyncMcpToolCallbackProvider`); the **`prod`** profile uses this in-process pgvector tool instead.
   `application-prod.yaml` turns the MCP client off so prod never reaches for the Mac. Switch with
   `SPRING_PROFILES_ACTIVE=prod`.

4. **Staleness hint** — `MessageVectorSearchService` reads `MAX("sentAt")` and, when the freshest
   synced message is older than ~1h, returns a `freshnessNote` alongside the hits; the `prod` system
   prompt instructs the model to surface it ("messages were last synced ~N ago — my Mac may be
   asleep"), so freshness is honest without faking live data.

5. **Inline ingress (no Kafka)** — `MessageIntake` abstracts how a webhook message is handed off.
   `dev` uses `KafkaMessageIntake` (publishes to the `task` topic, full two-topic flow). `prod` uses
   `InlineMessageIntake`: the webhook returns 200 immediately and a 2-thread pool runs
   `ConversationService.respond` (cache → LLM → persist) then delivers to Telegram directly. The
   cache/LLM/persist core lives in `ConversationService` so both paths share it. `application-prod.yaml`
   excludes `KafkaAutoConfiguration`, and the Kafka beans are `@Profile("!prod")`, so prod loads no
   Kafka at all. `docker-compose.prod.yml` parks the Kafka container behind a compose profile.

The MCP server (`imsg_mcp`) stays exactly as-is for **local use** (Claude Desktop, dev, ad-hoc
queries) and remains the dev request path. Prod just doesn't sit in its request path.

## Prod cutover runbook (Oracle E2.1.Micro, 1 GB)

Replace `BOX_PUBLIC_IP`, `BOX_TAILSCALE_IP`, `bot.example.com`, and the DB password as you go.

**1. Swap (the 1 GB box needs it).** On the 100 GB volume:
```bash
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo sysctl vm.swappiness=10   # prefer RAM; swap is the shock absorber, not the home
```

**2. Open ports — both layers.** Oracle's instances block almost everything by default in *two*
places, and people forget the second:
- **Oracle console** → VCN → Security List (or NSG): add ingress for TCP **80** and **443** from
  `0.0.0.0/0`. Do **not** open 5432 or 8080.
- **On the box** (Oracle Ubuntu ships locked-down iptables):
  ```bash
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
  sudo netfilter-persistent save
  ```

**3. Tailscale on both ends.** `curl -fsSL https://tailscale.com/install.sh | sh` then
`sudo tailscale up` on the box and the Mac. Note the box's `100.x.y.z` (`tailscale ip -4`).

**4. Docker + the stack.** Install Docker Engine + compose plugin. Clone the repo, then:
```bash
cp .env.example .env   # set ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, DB creds,
                       # and POSTGRES_BIND=BOX_TAILSCALE_IP
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
This starts only **postgres** + **ghostwriter** (Kafka is parked, ngrok is dev-only). Flyway runs
V0001–V0004 and creates `MessageVector`. Postgres is published on `BOX_TAILSCALE_IP:5432` only.
Verify: `curl -s localhost:8080/actuator/health` → `{"status":"UP"}`.

**5. Caddy for HTTPS.** Point a DNS A record `bot.example.com → BOX_PUBLIC_IP`, then on the box:
```bash
sudo apt install -y caddy
printf 'bot.example.com {\n\treverse_proxy localhost:8080\n}\n' | sudo tee /etc/caddy/Caddyfile
sudo systemctl restart caddy   # auto-provisions a Let's Encrypt cert
```

**6. Telegram webhook.**
```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook?url=https://bot.example.com/api/webhook"
```

**7. Mac publisher.** Install the push extra and load the launchd job:
```bash
cd messages && uv pip install --python .venv/bin/python -e ".[mcp,push]"
cp scripts/com.icontext.imsg-push.plist ~/Library/LaunchAgents/
# edit the plist: paths + GHOSTWRITER_PG_DSN=postgresql://USER:PW@BOX_TAILSCALE_IP:5432/ghostwriter
launchctl load ~/Library/LaunchAgents/com.icontext.imsg-push.plist
tail -f /tmp/imsg-push.log   # watch the first back-fill
```
The interpreter needs **Full Disk Access** (System Settings → Privacy & Security), same as
`just serve`. First run back-fills; thereafter it pushes incrementally every 10 min while awake.

**8. Verify end-to-end.** Text the bot from your phone. If you ask about messages and the Mac has
synced, you get hits; if the last sync is >1h old the reply will note it may be stale.
