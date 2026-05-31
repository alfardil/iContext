"""Push message embeddings to a cloud Postgres (pgvector) so ghostwriter can search
without the Mac in the request path.

This is the production "publisher" half of DEPLOYMENT.md. It reuses exactly what the local
indexer uses — `imsg.MessageStore` for the same snapshot + "real message" stream, and
`imsg_mcp.embeddings` for the same MiniLM-L6 (384-dim) model ghostwriter embeds queries with —
but swaps the sink: instead of sqlite-vec it upserts into the cloud `MessageVector` table.

Run it from launchd while the Mac is awake (see scripts/com.icontext.imsg-push.plist). Each run
is incremental and idempotent: per chat it asks Postgres for the newest `sentAt` already there
and only embeds messages after that, upserting on `msgGuid`. When the Mac is asleep nothing
pushes and ghostwriter simply answers from the rows already present (staleness by design).

Connection: set GHOSTWRITER_PG_DSN, e.g.
    postgresql://postgres:postgres@100.x.y.z:5432/ghostwriter
where the host is the cloud box's Tailscale IP. Postgres is never exposed publicly.

    .venv/bin/python -m imsg_mcp.push                 # all chats with >= --min-messages
    .venv/bin/python -m imsg_mcp.push --chat <guid>   # one chat
    .venv/bin/python -m imsg_mcp.push --limit 20      # top-N most-recently-active chats
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from imsg import MessageStore, safe_copy_chatdb
from imsg.contacts import ContactBook
from imsg.models import Message
from imsg_mcp import embeddings, snapshot_queries

if TYPE_CHECKING:
    import psycopg

log = logging.getLogger("imsg-push")

BATCH = 256
DSN_ENV = "GHOSTWRITER_PG_DSN"

_UPSERT_SQL = """
INSERT INTO "MessageVector"
  ("msgGuid", "chatGuid", "sentAt", "sender", "senderName", "isFromMe", "text", "embedding")
VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
ON CONFLICT ("msgGuid") DO UPDATE SET
  "chatGuid"   = EXCLUDED."chatGuid",
  "sentAt"     = EXCLUDED."sentAt",
  "sender"     = EXCLUDED."sender",
  "senderName" = EXCLUDED."senderName",
  "isFromMe"   = EXCLUDED."isFromMe",
  "text"       = EXCLUDED."text",
  "embedding"  = EXCLUDED."embedding"
"""


def _vector_literal(vec: object) -> str:
    """pgvector text form: '[f1,f2,...]'. Matches QuestionCacheSqlRepository.toVectorLiteral."""
    import numpy as np

    arr = np.asarray(vec, dtype=np.float32)
    return "[" + ",".join(repr(float(x)) for x in arr) + "]"


def _last_synced_at(conn: "psycopg.Connection", chat_guid: str) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            'SELECT MAX("sentAt") FROM "MessageVector" WHERE "chatGuid" = %s',
            (chat_guid,),
        )
        row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


def push_chat(conn: "psycopg.Connection", store: MessageStore, chat_guid: str) -> int:
    """Embed and upsert every message in `chat_guid` newer than what's already in Postgres.

    Returns the number of messages pushed.
    """
    since = _last_synced_at(conn, chat_guid)
    pushed = 0
    batch_msgs: list[Message] = []

    def flush() -> None:
        nonlocal pushed
        if not batch_msgs:
            return
        vectors = embeddings.embed([(m.text or "").strip() for m in batch_msgs])
        rows = [
            (
                m.guid,
                m.chat_guid,
                m.sent_at,
                m.sender,
                m.sender_name,
                m.is_from_me,
                m.text,
                _vector_literal(vectors[i]),
            )
            for i, m in enumerate(batch_msgs)
        ]
        with conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL, rows)
        conn.commit()
        pushed += len(rows)
        batch_msgs.clear()

    for msg in store.messages(chat_guid=chat_guid, since=since):
        if not (msg.text and msg.text.strip()):
            continue
        batch_msgs.append(msg)
        if len(batch_msgs) >= BATCH:
            flush()
    flush()
    return pushed


def push_all(dsn: str, *, min_messages: int, limit: int | None, chat_guids: list[str] | None) -> None:
    import psycopg

    snap = safe_copy_chatdb()
    if chat_guids:
        targets = chat_guids
    else:
        summaries = snapshot_queries.chat_summaries(snap)
        eligible = [g for g, s in summaries.items() if s.message_count >= min_messages]
        eligible.sort(key=lambda g: summaries[g].last_message_at or "", reverse=True)
        targets = eligible[:limit] if limit else eligible

    log.info("pushing %d chat(s) → %s", len(targets), _redacted(dsn))
    embeddings.warmup()
    contacts = ContactBook.from_default_sources()

    conn = psycopg.connect(dsn)
    try:
        with MessageStore(snap, contacts=contacts) as store:
            total = 0
            for guid in targets:
                start = time.monotonic()
                try:
                    n = push_chat(conn, store, guid)
                except Exception:
                    conn.rollback()
                    log.exception("push failed for chat %s", guid)
                    continue
                total += n
                if n:
                    log.info("chat %s: +%d msgs in %.1fs", guid, n, time.monotonic() - start)
            log.info("done: %d new messages pushed across %d chat(s)", total, len(targets))
    finally:
        conn.close()


def _redacted(dsn: str) -> str:
    """Hide credentials when logging the DSN."""
    if "@" in dsn:
        return dsn[: dsn.index("//") + 2] + "***@" + dsn.rsplit("@", 1)[1]
    return dsn


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Push iMessage embeddings to cloud pgvector.")
    parser.add_argument("--dsn", default=os.environ.get(DSN_ENV), help=f"Postgres DSN (or ${DSN_ENV}).")
    parser.add_argument("--chat", action="append", dest="chats", help="Push only this chat GUID (repeatable).")
    parser.add_argument("--min-messages", type=int, default=1, help="Skip chats with fewer messages.")
    parser.add_argument("--limit", type=int, default=None, help="Only the N most-recently-active chats.")
    args = parser.parse_args(argv)

    if not args.dsn:
        print(f"error: provide --dsn or set ${DSN_ENV}", file=sys.stderr)
        return 2

    start = datetime.now(timezone.utc)
    push_all(args.dsn, min_messages=args.min_messages, limit=args.limit, chat_guids=args.chats)
    log.info("elapsed %.1fs", (datetime.now(timezone.utc) - start).total_seconds())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
