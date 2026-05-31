import sqlite3
from pathlib import Path

import pytest

from imsg.queries import MessageStore

FIXTURES = Path(__file__).parent / "fixtures"

_SCHEMA = """
CREATE TABLE handle (
  ROWID INTEGER PRIMARY KEY, id TEXT, country TEXT, service TEXT,
  uncanonicalized_id TEXT, person_centric_id TEXT
);
CREATE TABLE chat (
  ROWID INTEGER PRIMARY KEY, guid TEXT, chat_identifier TEXT,
  display_name TEXT, style INTEGER, service_name TEXT
);
CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
CREATE TABLE message (
  ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, attributedBody BLOB,
  handle_id INTEGER, service TEXT, date INTEGER, date_read INTEGER, date_delivered INTEGER,
  is_from_me INTEGER, cache_has_attachments INTEGER,
  associated_message_guid TEXT, associated_message_type INTEGER,
  balloon_bundle_id TEXT, payload_data BLOB,
  reply_to_guid TEXT, thread_originator_guid TEXT, thread_originator_part TEXT,
  date_edited INTEGER, date_retracted INTEGER, message_summary_info BLOB,
  item_type INTEGER, group_action_type INTEGER, group_title TEXT
);
CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER, message_date INTEGER);
CREATE TABLE attachment (
  ROWID INTEGER PRIMARY KEY, guid TEXT, filename TEXT, mime_type TEXT,
  total_bytes INTEGER, is_sticker INTEGER, transfer_name TEXT
);
CREATE TABLE message_attachment_join (message_id INTEGER, attachment_id INTEGER);
"""

SENT_NS = 770_472_000_000_000_000
REACT_NS = SENT_NS + 60_000_000_000


@pytest.fixture()
def chat_db(tmp_path: Path) -> Path:
    db = tmp_path / "chat.db"
    blob = (FIXTURES / "sample_attributed_body.bin").read_bytes()

    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO handle (ROWID, id, country, service) VALUES (?, ?, ?, ?)",
            (1, "+15555550100", "us", "iMessage"),
        )
        conn.execute(
            "INSERT INTO chat (ROWID, guid, chat_identifier, display_name, style, service_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (1, "iMessage;-;+15555550100", "+15555550100", None, 45, "iMessage"),
        )
        conn.execute(
            "INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (?, ?)", (1, 1)
        )

        conn.execute(
            """INSERT INTO message
               (ROWID, guid, text, attributedBody, handle_id, service, date,
                is_from_me, cache_has_attachments, item_type)
               VALUES (?, ?, NULL, ?, 1, 'iMessage', ?, 0, 1, 0)""",
            (1, "MSG-1", blob, SENT_NS),
        )
        conn.execute(
            """INSERT INTO message
               (ROWID, guid, text, attributedBody, handle_id, service, date,
                is_from_me, associated_message_guid, associated_message_type, item_type)
               VALUES (?, ?, NULL, NULL, 1, 'iMessage', ?, 1, ?, ?, 0)""",
            (2, "TB-1", REACT_NS, "p:0/MSG-1", 2001),
        )
        conn.execute(
            """INSERT INTO message
               (ROWID, guid, text, handle_id, service, date, is_from_me, item_type)
               VALUES (?, ?, NULL, 1, 'iMessage', ?, 0, 2)""",
            (3, "GROUP-EVT", SENT_NS - 1, ),
        )

        for msg_id in (1, 2, 3):
            conn.execute(
                "INSERT INTO chat_message_join (chat_id, message_id, message_date) VALUES (?, ?, ?)",
                (1, msg_id, SENT_NS),
            )

        conn.execute(
            """INSERT INTO attachment
               (ROWID, guid, filename, mime_type, total_bytes, is_sticker, transfer_name)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (1, "ATT-1", "/tmp/x.jpg", "image/jpeg", 4096, 0, "x.jpg"),
        )
        conn.execute(
            "INSERT INTO message_attachment_join (message_id, attachment_id) VALUES (?, ?)",
            (1, 1),
        )
        conn.commit()
    finally:
        conn.close()
    return db


def test_messagestore_basic(chat_db: Path) -> None:
    with MessageStore(chat_db) as store:
        msgs = list(store.messages())
    assert len(msgs) == 1
    m = msgs[0]
    assert m.guid == "MSG-1"
    assert m.text == "test message"
    assert m.decoded_from_attributed_body is True
    assert m.sender == "+15555550100"
    assert m.is_from_me is False
    assert m.chat_guid == "iMessage;-;+15555550100"


def test_attachments_attached(chat_db: Path) -> None:
    with MessageStore(chat_db) as store:
        m = next(iter(store.messages()))
    assert len(m.attachments) == 1
    att = m.attachments[0]
    assert att.guid == "ATT-1"
    assert att.mime_type == "image/jpeg"
    assert att.total_bytes == 4096
    assert att.is_sticker is False


def test_tapback_folded_into_target(chat_db: Path) -> None:
    with MessageStore(chat_db) as store:
        m = next(iter(store.messages()))
    assert len(m.reactions) == 1
    r = m.reactions[0]
    assert r.type.name == "LIKED"
    assert r.is_removal is False
    assert r.from_handle is None
    assert r.target_guid == "MSG-1"
    assert r.target_part == 0


def test_group_events_excluded_by_default(chat_db: Path) -> None:
    with MessageStore(chat_db) as store:
        ids_default = {m.guid for m in store.messages()}
        ids_with = {m.guid for m in store.messages(include_group_events=True)}
    assert "GROUP-EVT" not in ids_default
    assert "GROUP-EVT" in ids_with


def test_chats_and_contacts(chat_db: Path) -> None:
    with MessageStore(chat_db) as store:
        chats = store.chats()
        contacts = store.contacts()
    assert len(chats) == 1
    assert chats[0].style == "direct"
    assert chats[0].participants == ("+15555550100",)
    assert len(contacts) == 1
    assert contacts[0].contact_id == "+15555550100"


def test_message_by_guid_returns_none_for_unknown(chat_db: Path) -> None:
    with MessageStore(chat_db) as store:
        assert store.message_by_guid("does-not-exist") is None


def test_message_by_guid_returns_message(chat_db: Path) -> None:
    with MessageStore(chat_db) as store:
        m = store.message_by_guid("MSG-1")
    assert m is not None
    assert m.text == "test message"
