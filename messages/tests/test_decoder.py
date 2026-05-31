from pathlib import Path

from imsg.decoder import (
    _byte_scan_nsstring,
    decode_attributed_body,
    decode_balloon_payload,
    decode_edit_summary,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_decode_attributed_body_typedstream_path() -> None:
    blob = (FIXTURES / "sample_attributed_body.bin").read_bytes()
    text, via_typedstream = decode_attributed_body(blob)
    assert text == "test message"
    assert via_typedstream is True


def test_decode_attributed_body_none_and_empty() -> None:
    assert decode_attributed_body(None) == ("", False)
    assert decode_attributed_body(b"") == ("", False)


def test_decode_attributed_body_garbage_falls_back_to_empty() -> None:
    text, via_typedstream = decode_attributed_body(b"\x00\x01\x02 not a typedstream")
    assert text == ""
    assert via_typedstream is False


def test_byte_scan_short_string() -> None:
    blob = b"prefix-junk" + b"NSString" + b"\x01\x94\x84\x01+" + b"\x05hello-suffix"
    assert _byte_scan_nsstring(blob) == "hello"


def test_byte_scan_long_string_with_0x81_length() -> None:
    payload = b"x" * 300
    length_bytes = len(payload).to_bytes(2, "little")
    blob = b"NSString" + b"\x01\x94\x84\x01+" + b"\x81" + length_bytes + payload
    assert _byte_scan_nsstring(blob) == payload.decode()


def test_byte_scan_no_nsstring_marker() -> None:
    assert _byte_scan_nsstring(b"completely unrelated bytes") == ""


def test_decode_attributed_body_falls_back_when_typedstream_fails() -> None:
    blob = b"NSString" + b"\x01\x94\x84\x01+" + b"\x02hi"
    text, via = decode_attributed_body(blob)
    assert text == "hi"
    assert via is False


def test_decode_edit_summary_real_blob() -> None:
    blob = (FIXTURES / "sample_edit_summary.bin").read_bytes()
    edits, retracted = decode_edit_summary(blob)
    assert len(edits) >= 1
    text, ts = edits[-1]
    assert text != ""
    assert ts is not None
    assert retracted == []


def test_decode_edit_summary_none() -> None:
    assert decode_edit_summary(None) == ([], [])


def test_decode_edit_summary_invalid_plist() -> None:
    assert decode_edit_summary(b"not a plist") == ([], [])


def test_decode_balloon_payload_no_args() -> None:
    assert decode_balloon_payload(None, None) is None
    assert decode_balloon_payload("com.x", None) is None
    assert decode_balloon_payload(None, b"data") is None
