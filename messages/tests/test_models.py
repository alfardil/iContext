import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from imsg.models import (
    Attachment,
    Chat,
    Message,
    Reaction,
    Service,
    TapbackType,
)


def _msg(**overrides: object) -> Message:
    base: dict[str, object] = dict(
        rowid=1,
        guid="abc",
        chat_guid="chat-1",
        sender="+15555550100",
        is_from_me=False,
        service=Service.IMESSAGE,
        sent_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        delivered_at=None,
        read_at=None,
        text="hi",
    )
    base.update(overrides)
    return Message(**base)  # type: ignore[arg-type]


def test_message_is_frozen() -> None:
    m = _msg()
    with pytest.raises(ValidationError):
        m.text = "mutated"  # type: ignore[misc]


def test_message_json_round_trip() -> None:
    m = _msg(
        attachments=(
            Attachment(
                rowid=10,
                guid="att-1",
                filename="/tmp/x.jpg",
                mime_type="image/jpeg",
                total_bytes=1024,
                is_sticker=False,
                transfer_name="x.jpg",
            ),
        ),
        reactions=(
            Reaction(
                type=TapbackType.LIKED,
                is_removal=False,
                from_handle="+15555550101",
                target_guid="abc",
                target_part=0,
                sent_at=datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
                emoji=None,
            ),
        ),
    )
    payload = m.model_dump_json()
    parsed = json.loads(payload)
    assert parsed["text"] == "hi"
    assert parsed["attachments"][0]["mime_type"] == "image/jpeg"
    assert parsed["reactions"][0]["type"] == 2001


def test_chat_style_literal_enforced() -> None:
    with pytest.raises(ValidationError):
        Chat(
            rowid=1,
            guid="g",
            identifier="i",
            display_name=None,
            style="bogus",  # type: ignore[arg-type]
            service=Service.IMESSAGE,
            participants=(),
        )


def test_extra_fields_allowed_on_message() -> None:
    m = _msg()
    payload = m.model_dump()
    assert "rowid" in payload
