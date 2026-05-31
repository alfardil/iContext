from enum import IntEnum

APPLE_EPOCH: int = 978_307_200

TAPBACK_ADD: dict[int, str] = {
    2000: "loved",
    2001: "liked",
    2002: "disliked",
    2003: "laughed",
    2004: "emphasized",
    2005: "questioned",
    2006: "sticker",
}
TAPBACK_REMOVE_OFFSET: int = 1000

CHAT_STYLE_GROUP: int = 43
CHAT_STYLE_DIRECT: int = 45


class GroupEvent(IntEnum):
    NONE = 0
    PARTICIPANT_CHANGE = 1
    NAME_CHANGE = 2
    LEAVE = 3
    IMAGE_CHANGE = 4
    SHARE_LOCATION = 5
    STOP_SHARE_LOCATION = 6


def is_tapback_type(associated_message_type: int) -> bool:
    if associated_message_type == 0:
        return False
    base = (
        associated_message_type - TAPBACK_REMOVE_OFFSET
        if associated_message_type >= 3000
        else associated_message_type
    )
    return base in TAPBACK_ADD
