from pathlib import Path

from imsg.contacts import ContactBook, _build_name, _normalize_email, _normalize_phone


def test_normalize_phone_e164() -> None:
    assert _normalize_phone("+19995550101") == "+19995550101"


def test_normalize_phone_us_with_parens() -> None:
    assert _normalize_phone("(999) 555-0101") == "+9995550101"


def test_normalize_phone_with_spaces_and_dashes() -> None:
    assert _normalize_phone("999-555 0101") == "+9995550101"


def test_normalize_phone_empty() -> None:
    assert _normalize_phone("") == ""
    assert _normalize_phone("---") == ""


def test_normalize_email_lowercase_and_strip() -> None:
    assert _normalize_email("  Foo@Example.COM ") == "foo@example.com"


def test_build_name_prefers_nickname() -> None:
    assert _build_name("Test", "User", "T-Dawg", None) == "T-Dawg"


def test_build_name_full_name() -> None:
    assert _build_name("Test", "User", None, None) == "Test User"


def test_build_name_falls_back_to_org() -> None:
    assert _build_name(None, None, None, "Acme") == "Acme"


def test_build_name_returns_none_when_empty() -> None:
    assert _build_name(None, None, None, None) is None


def test_lookup_phone_direct_hit() -> None:
    cb = ContactBook(phones={"+19995550101": "Test User"}, emails={})
    assert cb.lookup("+19995550101") == "Test User"


def test_lookup_phone_us_10_digit_fallback() -> None:
    cb = ContactBook(phones={"+19995550101": "Test User"}, emails={})
    assert cb.lookup("9995550101") == "Test User"


def test_lookup_phone_unknown() -> None:
    cb = ContactBook(phones={"+19995550101": "Test User"}, emails={})
    assert cb.lookup("+19999999999") is None


def test_lookup_email() -> None:
    cb = ContactBook(phones={}, emails={"foo@example.com": "Foo Bar"})
    assert cb.lookup("Foo@Example.com") == "Foo Bar"


def test_lookup_empty_input() -> None:
    cb = ContactBook(phones={"+1": "x"}, emails={"a@b": "y"})
    assert cb.lookup("") is None


def test_from_default_sources_missing_root_returns_empty(tmp_path: Path) -> None:
    cb = ContactBook.from_default_sources(src_root=tmp_path / "nope", dst_root=tmp_path / "out")
    assert cb.size == 0
    assert cb.lookup("+15555550100") is None
