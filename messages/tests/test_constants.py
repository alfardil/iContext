import pytest

from imsg.constants import is_tapback_type
from imsg.models import TapbackType


@pytest.mark.parametrize("raw", [2000, 2001, 2002, 2003, 2004, 2005, 2006])
def test_is_tapback_type_add(raw: int) -> None:
    assert is_tapback_type(raw)


@pytest.mark.parametrize("raw", [3000, 3001, 3002, 3003, 3004, 3005, 3006])
def test_is_tapback_type_remove(raw: int) -> None:
    assert is_tapback_type(raw)


@pytest.mark.parametrize("raw", [0, 1, 1999, 2007, 2999, 3007, 9999])
def test_is_tapback_type_negatives(raw: int) -> None:
    assert not is_tapback_type(raw)


def test_tapback_from_raw_add() -> None:
    assert TapbackType.from_raw(2000) is TapbackType.LOVED
    assert TapbackType.from_raw(2003) is TapbackType.LAUGHED
    assert TapbackType.from_raw(2006) is TapbackType.STICKER


def test_tapback_from_raw_remove() -> None:
    assert TapbackType.from_raw(3000) is TapbackType.LOVED
    assert TapbackType.from_raw(3003) is TapbackType.LAUGHED


def test_tapback_from_raw_unknown() -> None:
    assert TapbackType.from_raw(9999) is None
    assert TapbackType.from_raw(2099) is None
