"""Read-only aggregate / bulk SQL over a chat.db snapshot.

`MessageStore` covers per-message reads, but the MCP layer also needs a few cheap
whole-snapshot aggregates (recent-chat ranking, per-chat counts) and one bulk
"fetch exactly these GUIDs" query for assembling search hits. They live here so the
message↔chat JOIN and the definition of a "real message" exist in exactly one place
instead of being copy-pasted across tools.py and indexer.py.

Every function opens its own short-lived read-only connection and returns a plain
value; a malformed or locked snapshot yields an empty result rather than raising, so
one bad read never takes down a tool call.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection
from pathlib import Path
from typing import NamedTuple

from imsg.db import connect_readonly
from imsg.time_utils import apple_to_dt

log = logging.getLogger(__name__)

_REAL_MESSAGE = (
    "COALESCE(m.associated_message_type, 0) = 0 AND COALESCE(m.item_type, 0) = 0"
)

_CHAT_JOIN = (
    "FROM message m "
    "JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
    "JOIN chat               c   ON c.ROWID       = cmj.chat_id"
)


class ChatSummary(NamedTuple):
    last_message_at: str | None
    message_count: int


def chat_summaries(snapshot: Path) -> dict[str, ChatSummary]:
    """Map chat GUID → (last real-message time, real-message count) in a single scan.

    Powers list_chats and warm-start ranking. Tapbacks and group-event rows are excluded
    so both "last activity" and the count reflect actual messages.
    """
    sql = (
        f"SELECT c.guid AS guid, MAX(m.date) AS last_date, COUNT(*) AS cnt "
        f"{_CHAT_JOIN} WHERE {_REAL_MESSAGE} GROUP BY c.guid"
    )
    try:
        conn = connect_readonly(snapshot)
    except sqlite3.Error as exc:
        log.warning("chat_summaries: cannot open snapshot: %s", exc)
        return {}
    try:
        rows = conn.execute(sql).fetchall()
    except sqlite3.Error as exc:
        log.warning("chat_summaries: query failed: %s", exc)
        return {}
    finally:
        conn.close()

    out: dict[str, ChatSummary] = {}
    for r in rows:
        dt = apple_to_dt(r["last_date"])
        out[str(r["guid"])] = ChatSummary(
            last_message_at=dt.isoformat() if dt is not None else None,
            message_count=int(r["cnt"]),
        )
    return out


def recent_chat_guids(snapshot: Path, min_messages: int, limit: int) -> list[str]:
    """GUIDs of the `limit` most-recently-active chats with ≥ `min_messages` messages.

    ISO-8601 UTC strings sort chronologically as plain text, so we rank on the cached
    summaries rather than issuing a second SQL pass.
    """
    eligible = [
        (guid, s)
        for guid, s in chat_summaries(snapshot).items()
        if s.message_count >= min_messages
    ]
    eligible.sort(key=lambda item: item[1].last_message_at or "", reverse=True)
    return [guid for guid, _ in eligible[:limit]]


def message_count_for_chat(snapshot: Path, chat_guid: str) -> int:
    """Count real, text-bearing messages in one chat (used to size an index job)."""
    sql = (
        f"SELECT COUNT(*) AS cnt {_CHAT_JOIN} "
        f"WHERE c.guid = ? AND {_REAL_MESSAGE} "
        f"AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL)"
    )
    try:
        conn = connect_readonly(snapshot)
        try:
            row = conn.execute(sql, (chat_guid,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return 0
    return int(row["cnt"]) if row else 0


def fetch_messages_by_guids(
    snapshot: Path, chat_guid: str, guids: Collection[str]
) -> list[sqlite3.Row]:
    """Bulk-fetch raw rows for specific message GUIDs within one chat — one query, not N.

    `MessageStore.message_by_guid` re-scans the entire message table per call; for the
    hundreds of candidates a semantic search produces that blows past the MCP client's
    60s timeout. The caller decodes attributedBody and resolves sender names from these
    rows. Columns are aliased to match what tools._fetch_hits_by_guids expects.
    """
    if not guids:
        return []
    placeholders = ",".join("?" * len(guids))
    sql = (
        f"SELECT m.guid           AS msg_guid, "
        f"       m.text           AS msg_text, "
        f"       m.attributedBody AS msg_body, "
        f"       m.is_from_me     AS msg_is_from_me, "
        f"       m.date           AS msg_date, "
        f"       h.id             AS handle_contact_id "
        f"{_CHAT_JOIN} "
        f"LEFT JOIN handle h ON h.ROWID = m.handle_id "
        f"WHERE c.guid = ? AND m.guid IN ({placeholders})"
    )
    try:
        conn = connect_readonly(snapshot)
        try:
            return conn.execute(sql, (chat_guid, *guids)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("fetch_messages_by_guids: query failed: %s", exc)
        return []
