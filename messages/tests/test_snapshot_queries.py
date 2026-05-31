"""Tests for the consolidated snapshot SQL (imsg_mcp.snapshot_queries).

Depends only on `imsg` (no sqlite-vec / numpy), so it runs in CI's python-tests job.
A tiny synthetic chat.db exercises the message↔chat join and the "real message" filter
that used to be copy-pasted across tools.py and indexer.py.
"""

import sqlite3
from pathlib import Path

import pytest

from imsg.time_utils import apple_to_dt
from imsg_mcp import snapshot_queries as sq

_SCHEMA = """
CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT, country TEXT, service TEXT);
CREATE TABLE chat (
  ROWID INTEGER PRIMARY KEY, guid TEXT, chat_identifier TEXT,
  display_name TEXT, style INTEGER, service_name TEXT
);
CREATE TABLE message (
  ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, attributedBody BLOB,
  handle_id INTEGER, date INTEGER, is_from_me INTEGER,
  associated_message_type INTEGER, item_type INTEGER
);
CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER, message_date INTEGER);
"""

# Apple-epoch values below the ns threshold → treated as seconds; ordering is all that matters.
M1, M2, TAPBACK, EVENT, M5 = 100, 200, 300, 50, 150


@pytest.fixture
def chat_db(tmp_path: Path) -> Path:
    db = tmp_path / "chat.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(_SCHEMA)
        conn.execute("INSERT INTO handle (ROWID, id) VALUES (1, '+15555550100')")
        conn.execute(
            "INSERT INTO chat (ROWID, guid, chat_identifier, style) VALUES (1, 'g1', '+15555550100', 45)"
        )
        conn.execute("INSERT INTO chat (ROWID, guid, chat_identifier, style) VALUES (2, 'g2', 'group', 43)")
        rows = [
            # ROWID, guid, text, handle_id, date, is_from_me, assoc_type, item_type
            (1, "m1", "hello", 1, M1, 0, 0, 0),  # real, received
            (2, "m2", "world", None, M2, 1, 0, 0),  # real, sent
            (3, "tb", None, 1, TAPBACK, 0, 2001, 0),  # tapback (later than m2) — must be excluded
            (4, "evt", None, 1, EVENT, 0, 0, 2),  # group event — must be excluded
            (5, "m5", "hey", 1, M5, 0, 0, 0),  # real, in chat g2
        ]
        conn.executemany(
            "INSERT INTO message (ROWID, guid, text, handle_id, date, is_from_me, "
            "associated_message_type, item_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        for chat_id, msg_id in [(1, 1), (1, 2), (1, 3), (1, 4), (2, 5)]:
            conn.execute(
                "INSERT INTO chat_message_join (chat_id, message_id) VALUES (?, ?)",
                (chat_id, msg_id),
            )
        conn.commit()
    finally:
        conn.close()
    return db


def test_chat_summaries_counts_only_real_messages(chat_db: Path) -> None:
    summaries = sq.chat_summaries(chat_db)
    assert summaries["g1"].message_count == 2  # m1, m2 — not the tapback or the event
    assert summaries["g2"].message_count == 1


def test_chat_summaries_last_activity_ignores_tapbacks(chat_db: Path) -> None:
    summaries = sq.chat_summaries(chat_db)
    # The tapback (date=300) is newer than m2 (date=200) but must not count as "last activity".
    assert summaries["g1"].last_message_at == apple_to_dt(M2).isoformat()


def test_recent_chat_guids_orders_by_recency(chat_db: Path) -> None:
    # g1's latest real message (200) is newer than g2's (150).
    assert sq.recent_chat_guids(chat_db, min_messages=1, limit=10) == ["g1", "g2"]


def test_recent_chat_guids_applies_min_messages(chat_db: Path) -> None:
    assert sq.recent_chat_guids(chat_db, min_messages=2, limit=10) == ["g1"]


def test_message_count_for_chat(chat_db: Path) -> None:
    assert sq.message_count_for_chat(chat_db, "g1") == 2
    assert sq.message_count_for_chat(chat_db, "g2") == 1
    assert sq.message_count_for_chat(chat_db, "nope") == 0


def test_fetch_messages_by_guids(chat_db: Path) -> None:
    rows = sq.fetch_messages_by_guids(chat_db, "g1", ["m1", "m2"])
    by_guid = {r["msg_guid"]: r for r in rows}
    assert set(by_guid) == {"m1", "m2"}
    assert by_guid["m1"]["handle_contact_id"] == "+15555550100"
    assert by_guid["m1"]["msg_is_from_me"] == 0
    assert by_guid["m2"]["msg_is_from_me"] == 1


def test_fetch_messages_by_guids_empty_returns_empty(chat_db: Path) -> None:
    assert sq.fetch_messages_by_guids(chat_db, "g1", []) == []
    assert sq.fetch_messages_by_guids(chat_db, "g1", ["does-not-exist"]) == []
