import shutil
import sqlite3
from pathlib import Path

DEFAULT_SRC: Path = Path.home() / "Library" / "Messages"
DEFAULT_WORKDIR: Path = Path("/tmp/imsg")

_SIDECAR_NAMES: tuple[str, ...] = ("chat.db", "chat.db-wal", "chat.db-shm")


class FullDiskAccessRequired(RuntimeError):
    pass


def safe_copy_chatdb(
    src_dir: Path = DEFAULT_SRC,
    dst_dir: Path = DEFAULT_WORKDIR,
) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    src_db = src_dir / "chat.db"
    if not src_db.exists():
        raise FileNotFoundError(f"chat.db not found at {src_db}")

    try:
        for name in _SIDECAR_NAMES:
            src = src_dir / name
            if src.exists():
                shutil.copy2(src, dst_dir / name)
    except PermissionError as exc:
        raise FullDiskAccessRequired(
            "Permission denied reading ~/Library/Messages. macOS requires Full Disk Access for "
            "the binary running this code (Terminal, iTerm, your Python interpreter, etc.). "
            "Open System Settings → Privacy & Security → Full Disk Access → add it and retry."
        ) from exc

    snapshot = dst_dir / "chat.db"
    conn = sqlite3.connect(str(snapshot))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.commit()
    finally:
        conn.close()
    return snapshot


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


MESSAGE_SQL: str = """
SELECT m.ROWID            AS msg_rowid,
       m.guid             AS msg_guid,
       m.text             AS msg_text,
       m.attributedBody   AS msg_attributed_body,
       m.handle_id        AS msg_handle_id,
       m.service          AS msg_service,
       m.date             AS msg_date,
       m.date_read        AS msg_date_read,
       m.date_delivered   AS msg_date_delivered,
       m.is_from_me       AS msg_is_from_me,
       m.cache_has_attachments AS msg_has_attachments,
       m.associated_message_guid  AS msg_assoc_guid,
       m.associated_message_type  AS msg_assoc_type,
       m.balloon_bundle_id        AS msg_bundle,
       m.payload_data             AS msg_payload,
       m.reply_to_guid            AS msg_reply_to,
       m.thread_originator_guid   AS msg_thread_guid,
       m.thread_originator_part   AS msg_thread_part,
       m.date_edited              AS msg_date_edited,
       m.date_retracted           AS msg_date_retracted,
       m.message_summary_info     AS msg_summary,
       m.item_type                AS msg_item_type,
       m.group_action_type        AS msg_group_action,
       m.group_title              AS msg_group_title,
       c.ROWID                    AS chat_rowid,
       c.guid                     AS chat_guid
FROM   message m
JOIN   chat_message_join cmj ON cmj.message_id = m.ROWID
JOIN   chat               c   ON c.ROWID       = cmj.chat_id
WHERE  (:chat_rowid IS NULL OR c.ROWID = :chat_rowid)
  AND  (:since_ns   IS NULL OR m.date  >= :since_ns)
  AND  (:until_ns   IS NULL OR m.date  <  :until_ns)
ORDER BY m.date ASC, m.ROWID ASC;
"""

ATTACHMENT_SQL_TEMPLATE: str = """
SELECT mj.message_id AS msg_rowid,
       a.ROWID       AS att_rowid,
       a.guid        AS att_guid,
       a.filename    AS att_filename,
       a.mime_type   AS att_mime,
       a.total_bytes AS att_bytes,
       a.is_sticker  AS att_is_sticker,
       a.transfer_name AS att_transfer
FROM   message_attachment_join mj
JOIN   attachment a ON a.ROWID = mj.attachment_id
WHERE  mj.message_id IN ({placeholders});
"""
