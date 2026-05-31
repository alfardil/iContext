from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from imsg.constants import GroupEvent


class Service(StrEnum):
    IMESSAGE = "iMessage"
    SMS = "SMS"
    RCS = "RCS"
    UNKNOWN = "unknown"


class TapbackType(IntEnum):
    LOVED = 2000
    LIKED = 2001
    DISLIKED = 2002
    LAUGHED = 2003
    EMPHASIZED = 2004
    QUESTIONED = 2005
    STICKER = 2006

    @classmethod
    def from_raw(cls, raw: int) -> "TapbackType | None":
        base = raw - 1000 if raw >= 3000 else raw
        try:
            return cls(base)
        except ValueError:
            return None


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Handle(_Frozen):
    rowid: int
    contact_id: str
    country: str | None
    service: Service


class Attachment(_Frozen):
    rowid: int
    guid: str
    filename: str | None
    mime_type: str | None
    total_bytes: int | None
    is_sticker: bool
    transfer_name: str | None


class EditEntry(_Frozen):
    text: str
    edited_at: datetime | None


class AppPayload(_Frozen):
    bundle_id: str
    url: str | None = None
    title: str | None = None
    summary: str | None = None


class Reaction(_Frozen):
    type: TapbackType
    is_removal: bool
    from_handle: str | None
    from_handle_name: str | None = None
    target_guid: str
    target_part: int | None
    sent_at: datetime
    emoji: str | None


class Chat(_Frozen):
    rowid: int
    guid: str
    identifier: str
    display_name: str | None
    style: Literal["group", "direct", "unknown"]
    service: Service
    participants: tuple[str, ...]


class Message(_Frozen):
    rowid: int
    guid: str
    chat_guid: str
    sender: str | None
    sender_name: str | None = None
    is_from_me: bool
    service: Service
    sent_at: datetime
    delivered_at: datetime | None
    read_at: datetime | None
    text: str
    attachments: tuple[Attachment, ...] = ()
    reactions: tuple[Reaction, ...] = ()
    reply_to_guid: str | None = None
    thread_originator_guid: str | None = None
    thread_originator_part: str | None = None
    edit_history: tuple[EditEntry, ...] = ()
    retracted_at: datetime | None = None
    retracted_parts: tuple[int, ...] = ()
    app_payload: AppPayload | None = None
    group_event: GroupEvent = GroupEvent.NONE
    group_title: str | None = None
    item_type: int = 0
    decoded_from_attributed_body: bool = False


__all__ = [
    "AppPayload",
    "Attachment",
    "Chat",
    "EditEntry",
    "GroupEvent",
    "Handle",
    "Message",
    "Reaction",
    "Service",
    "TapbackType",
]
