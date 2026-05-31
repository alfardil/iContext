import logging
import plistlib
from datetime import datetime
from typing import Any

import typedstream

from imsg.time_utils import apple_to_dt

log = logging.getLogger(__name__)


def decode_attributed_body(blob: bytes | None) -> tuple[str, bool]:
    if not blob:
        return "", False
    try:
        obj = typedstream.unarchive_from_data(blob)
        for item in getattr(obj, "contents", []):
            if getattr(item, "encoding", None) == b"@":
                value = getattr(item, "value", None)
                inner = getattr(value, "value", None)
                if isinstance(inner, str):
                    return inner, True
    except Exception as exc:  # pytypedstream may throw on malformed/new layouts
        log.debug("typedstream parse failed (%s); falling back to byte scan", exc)
    return _byte_scan_nsstring(blob), False


def _byte_scan_nsstring(blob: bytes) -> str:
    try:
        idx = blob.find(b"NSString")
        if idx < 0:
            return ""
        # 5-byte preamble after b"NSString": b"\x01\x94\x84\x01+"
        content = blob[idx + len(b"NSString") + 5 :]
        if not content:
            return ""
        first = content[0]
        if first == 0x81:
            if len(content) < 3:
                return ""
            length = int.from_bytes(content[1:3], "little")
            start = 3
        else:
            length = first
            start = 1
        return content[start : start + length].decode("utf-8", errors="ignore")
    except Exception as exc:
        log.warning("byte-scan fallback failed: %s", exc)
        return ""


def decode_edit_summary(
    blob: bytes | None,
) -> tuple[list[tuple[str, datetime | None]], list[int]]:
    if not blob:
        return [], []
    try:
        plist = plistlib.loads(blob)
    except Exception as exc:
        log.warning("message_summary_info plist parse failed: %s", exc)
        return [], []

    edits: list[tuple[str, datetime | None]] = []
    ec = plist.get("ec", {})
    # ec is dict[str part_index -> list[entry]]; entries have keys "t" (typedstream blob) and "d" (ns ts)
    if isinstance(ec, dict):
        for _part_key, entries in ec.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                raw_text = entry.get("t")
                raw_ts = entry.get("d")
                text = ""
                if isinstance(raw_text, (bytes, bytearray)):
                    text, _ = decode_attributed_body(bytes(raw_text))
                edited_at = apple_to_dt(raw_ts) if isinstance(raw_ts, (int, float)) else None
                edits.append((text, edited_at))

    retracted_raw = plist.get("rp", []) or []
    retracted: list[int] = [int(x) for x in retracted_raw if isinstance(x, int)]
    return edits, retracted


def decode_balloon_payload(bundle_id: str | None, payload: bytes | None) -> dict[str, Any] | None:
    if not bundle_id or not payload:
        return None
    try:
        plist = plistlib.loads(payload)
    except Exception as exc:
        log.debug("balloon payload parse failed for %s: %s", bundle_id, exc)
        return None

    result: dict[str, Any] = {"bundle_id": bundle_id, "raw": plist}
    if bundle_id == "com.apple.messages.URLBalloonProvider":
        # Newer versions stash a nested bplist under various keys; best-effort extract.
        if isinstance(plist, dict):
            ns_keyed = plist.get("$objects")
            if isinstance(ns_keyed, list):
                for obj in ns_keyed:
                    if isinstance(obj, str) and obj.startswith(("http://", "https://")):
                        result.setdefault("url", obj)
                        break
            for key in ("URL", "url", "originalURL"):
                v = plist.get(key)
                if isinstance(v, str):
                    result.setdefault("url", v)
            for key in ("title", "siteName", "subject"):
                v = plist.get(key)
                if isinstance(v, str):
                    result.setdefault("title", v)
            for key in ("summary", "selectedText"):
                v = plist.get(key)
                if isinstance(v, str):
                    result.setdefault("summary", v)
    return result
