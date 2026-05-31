import logging
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from imsg.constants import GroupEvent, is_tapback_type
from imsg.contacts import ContactBook
from imsg.db import (
    ATTACHMENT_SQL_TEMPLATE,
    MESSAGE_SQL,
    connect_readonly,
)
from imsg.decoder import (
    decode_attributed_body,
    decode_balloon_payload,
    decode_edit_summary,
)
from imsg.models import (
    AppPayload,
    Attachment,
    Chat,
    EditEntry,
    Handle,
    Message,
    Reaction,
    Service,
    TapbackType,
)
from imsg.time_utils import apple_to_dt, dt_to_apple_ns

log = logging.getLogger(__name__)

_BATCH = 500


def _service(raw: str | None) -> Service:
    if raw == "iMessage":
        return Service.IMESSAGE
    if raw == "SMS":
        return Service.SMS
    if raw == "RCS":
        return Service.RCS
    return Service.UNKNOWN


def _chat_style(raw: int | None) -> str:
    if raw == 43:
        return "group"
    if raw == 45:
        return "direct"
    return "unknown"


def _group_event(item_type: int | None, action_type: int | None) -> GroupEvent:
    if item_type in (1, 2, 3, 4, 5, 6):
        try:
            return GroupEvent(item_type)
        except ValueError:
            return GroupEvent.NONE
    _ = action_type
    return GroupEvent.NONE


class MessageStore:
    def __init__(self, db_path: Path, contacts: ContactBook | None = None) -> None:
        self._db_path = db_path
        self._conn = connect_readonly(db_path)
        self._contacts = contacts
        self._handles: dict[int, Handle] = self._load_handles()
        self._chat_participants: dict[int, tuple[str, ...]] = self._load_chat_handles()
        self._chats: dict[int, Chat] = self._load_chats()

    def _name_for(self, handle_id: str | None) -> str | None:
        if not handle_id or self._contacts is None:
            return None
        return self._contacts.lookup(handle_id)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "MessageStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _load_handles(self) -> dict[int, Handle]:
        rows = self._conn.execute(
            "SELECT ROWID, id, country, service FROM handle"
        ).fetchall()
        out: dict[int, Handle] = {}
        for r in rows:
            out[r["ROWID"]] = Handle(
                rowid=r["ROWID"],
                contact_id=r["id"],
                country=r["country"],
                service=_service(r["service"]),
            )
        return out

    def _load_chat_handles(self) -> dict[int, tuple[str, ...]]:
        rows = self._conn.execute(
            "SELECT chat_id, handle_id FROM chat_handle_join"
        ).fetchall()
        buf: dict[int, list[str]] = {}
        for r in rows:
            h = self._handles.get(r["handle_id"])
            if h is None:
                continue
            buf.setdefault(r["chat_id"], []).append(h.contact_id)
        return {k: tuple(sorted(set(v))) for k, v in buf.items()}

    def _load_chats(self) -> dict[int, Chat]:
        rows = self._conn.execute(
            "SELECT ROWID, guid, chat_identifier, display_name, style, service_name "
            "FROM chat"
        ).fetchall()
        out: dict[int, Chat] = {}
        for r in rows:
            out[r["ROWID"]] = Chat(
                rowid=r["ROWID"],
                guid=r["guid"],
                identifier=r["chat_identifier"],
                display_name=r["display_name"] or None,
                style=_chat_style(r["style"]),  # type: ignore[arg-type]
                service=_service(r["service_name"]),
                participants=self._chat_participants.get(r["ROWID"], ()),
            )
        return out

    def chats(self) -> list[Chat]:
        return list(self._chats.values())

    def contacts(self) -> list[Handle]:
        return list(self._handles.values())

    def message_by_guid(self, guid: str) -> Message | None:
        for m in self.messages(_guid=guid):
            return m
        return None

    def messages(
        self,
        *,
        chat_guid: str | None = None,
        chat_identifier: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        include_group_events: bool = False,
        _guid: str | None = None,
    ) -> Iterator[Message]:
        chat_rowid: int | None = None
        if chat_guid is not None:
            chat_rowid = next(
                (c.rowid for c in self._chats.values() if c.guid == chat_guid), None
            )
            if chat_rowid is None:
                return
        elif chat_identifier is not None:
            chat_rowid = next(
                (
                    c.rowid
                    for c in self._chats.values()
                    if c.identifier.lower() == chat_identifier.lower()
                ),
                None,
            )
            if chat_rowid is None:
                return

        params = {
            "chat_rowid": chat_rowid,
            "since_ns": dt_to_apple_ns(since) if since else None,
            "until_ns": dt_to_apple_ns(until) if until else None,
        }

        reactions_by_target: dict[str, list[Reaction]] = self._collect_reactions(params)

        cur = self._conn.execute(MESSAGE_SQL, params)
        batch: list[sqlite3.Row] = []
        for row in cur:
            if _guid is not None and row["msg_guid"] != _guid:
                continue
            assoc_type = row["msg_assoc_type"] or 0
            if is_tapback_type(assoc_type):
                continue  # already in reactions_by_target
            item_type = row["msg_item_type"] or 0
            if item_type != 0 and not include_group_events:
                continue
            batch.append(row)
            if len(batch) >= _BATCH:
                yield from self._yield_batch(batch, reactions_by_target)
                batch.clear()
        if batch:
            yield from self._yield_batch(batch, reactions_by_target)

    def _collect_reactions(self, params: dict[str, Any]) -> dict[str, list[Reaction]]:
        # We already iterate the same query in messages(); separate execution keeps logic clean.
        cur = self._conn.execute(MESSAGE_SQL, params)
        out: dict[str, list[Reaction]] = {}
        for row in cur:
            assoc_type = row["msg_assoc_type"] or 0
            if not is_tapback_type(assoc_type):
                continue
            target = row["msg_assoc_guid"]
            if not target:
                continue
            target_guid, target_part = _split_assoc_target(target)
            tb = TapbackType.from_raw(assoc_type)
            if tb is None:
                continue
            handle_id = row["msg_handle_id"] or 0
            handle = self._handles.get(handle_id)
            sent_at = apple_to_dt(row["msg_date"])
            if sent_at is None:
                continue
            from_handle = None if row["msg_is_from_me"] else (handle.contact_id if handle else None)
            reaction = Reaction(
                type=tb,
                is_removal=assoc_type >= 3000,
                from_handle=from_handle,
                from_handle_name=self._name_for(from_handle),
                target_guid=target_guid,
                target_part=target_part,
                sent_at=sent_at,
                emoji=None,
            )
            out.setdefault(target_guid, []).append(reaction)
        return out

    def _yield_batch(
        self,
        rows: list[sqlite3.Row],
        reactions_by_target: dict[str, list[Reaction]],
    ) -> Iterator[Message]:
        att_by_msg = self._fetch_attachments([r["msg_rowid"] for r in rows])
        for row in rows:
            msg = self._row_to_message(row, att_by_msg.get(row["msg_rowid"], ()), reactions_by_target)
            if msg is not None:
                yield msg

    def _fetch_attachments(self, msg_rowids: list[int]) -> dict[int, tuple[Attachment, ...]]:
        if not msg_rowids:
            return {}
        placeholders = ",".join("?" * len(msg_rowids))
        sql = ATTACHMENT_SQL_TEMPLATE.format(placeholders=placeholders)
        cur = self._conn.execute(sql, msg_rowids)
        buf: dict[int, list[Attachment]] = {}
        for r in cur:
            att = Attachment(
                rowid=r["att_rowid"],
                guid=r["att_guid"],
                filename=r["att_filename"],
                mime_type=r["att_mime"],
                total_bytes=r["att_bytes"] if (r["att_bytes"] is not None and r["att_bytes"] >= 0) else None,
                is_sticker=bool(r["att_is_sticker"]),
                transfer_name=r["att_transfer"],
            )
            buf.setdefault(r["msg_rowid"], []).append(att)
        return {k: tuple(v) for k, v in buf.items()}

    def _row_to_message(
        self,
        row: sqlite3.Row,
        attachments: tuple[Attachment, ...],
        reactions_by_target: dict[str, list[Reaction]],
    ) -> Message | None:
        sent_at = apple_to_dt(row["msg_date"])
        if sent_at is None:
            return None

        plain = row["msg_text"]
        decoded_via_ts = False
        if plain and plain.strip():
            text = plain
        else:
            text, decoded_via_ts = decode_attributed_body(row["msg_attributed_body"])

        edits_raw, retracted_parts = decode_edit_summary(row["msg_summary"])
        edit_history = tuple(
            EditEntry(text=t, edited_at=ts) for t, ts in edits_raw
        )

        payload_dict = decode_balloon_payload(row["msg_bundle"], row["msg_payload"])
        app_payload: AppPayload | None = None
        if payload_dict is not None:
            app_payload = AppPayload(
                bundle_id=payload_dict["bundle_id"],
                url=payload_dict.get("url"),
                title=payload_dict.get("title"),
                summary=payload_dict.get("summary"),
            )

        handle = self._handles.get(row["msg_handle_id"] or 0)
        sender = None if row["msg_is_from_me"] else (handle.contact_id if handle else None)
        sender_name = self._name_for(sender)

        reactions = tuple(
            sorted(reactions_by_target.get(row["msg_guid"], []), key=lambda r: r.sent_at)
        )

        return Message(
            rowid=row["msg_rowid"],
            guid=row["msg_guid"],
            chat_guid=row["chat_guid"],
            sender=sender,
            sender_name=sender_name,
            is_from_me=bool(row["msg_is_from_me"]),
            service=_service(row["msg_service"]),
            sent_at=sent_at,
            delivered_at=apple_to_dt(row["msg_date_delivered"]),
            read_at=apple_to_dt(row["msg_date_read"]),
            text=text,
            attachments=attachments,
            reactions=reactions,
            reply_to_guid=row["msg_reply_to"],
            thread_originator_guid=row["msg_thread_guid"],
            thread_originator_part=row["msg_thread_part"],
            edit_history=edit_history,
            retracted_at=apple_to_dt(row["msg_date_retracted"]),
            retracted_parts=tuple(retracted_parts),
            app_payload=app_payload,
            group_event=_group_event(row["msg_item_type"], row["msg_group_action"]),
            group_title=row["msg_group_title"],
            item_type=row["msg_item_type"] or 0,
            decoded_from_attributed_body=decoded_via_ts or (not (plain and plain.strip())),
        )


def _split_assoc_target(raw: str) -> tuple[str, int | None]:
    """`associated_message_guid` may be `p:N/<guid>` (part N) or just `<guid>`."""
    if raw.startswith("p:"):
        head, _, tail = raw.partition("/")
        try:
            part = int(head[2:])
        except ValueError:
            part = None
        return tail, part
    return raw, None
