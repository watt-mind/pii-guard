"""Check-digit algorithms. Values are generated or hand-computed; none is a real identifier."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.checksums import (
    IBAN_LENGTHS,
    giro_check_digit,
    hu_tax_id_check_digit,
    hu_tax_number_check_digit,
    iban_check_digits,
    is_valid_giro,
    is_valid_hu_tax_id,
    is_valid_hu_tax_number,
    is_valid_iban,
    is_valid_taj,
    taj_check_digit,
)


def digits(n: int) -> st.SearchStrategy[str]:
    return st.text(alphabet="0123456789", min_size=n, max_size=n)


def _replace_digit(value: str, index: int, offset: int) -> str:
    """``value`` with the digit at ``index`` changed by ``offset`` (1-9) mod 10."""
    new = (int(value[index]) + offset) % 10
    return value[:index] + str(new) + value[index + 1 :]


# --- Hand-computed vectors --------------------------------------------------


def test_known_vectors() -> None:
    # 8*1 + 1*2 + 2*3 + 3*4 + 4*5 + 5*6 + 6*7 + 7*8 + 8*9 = 248; 248 mod 11 = 6
    assert hu_tax_id_check_digit("812345678") == 6
    assert is_valid_hu_tax_id("8123456786")
    # 3*1 + 7*1 + 3*1 + 7*2 + 3*2 + 7*2 + 3*3 + 7*3 = 77 -> 7
    assert taj_check_digit("11122233") == 7
    assert is_valid_taj("111222337")
    # 9*1 + 7*1 + 3*7 + 1*7 + 9*3 + 7*0 + 3*1 = 74 -> (10 - 4) mod 10 = 6
    assert giro_check_digit("1177301") == 6
    assert hu_tax_number_check_digit("1177301") == 6
    # The worked example from the IBAN standard (a fictional account).
    assert is_valid_iban("GB82WEST12345698765432")
    assert iban_check_digits("GB", "WEST12345698765432") == "82"


def test_tax_id_remainder_ten_is_never_valid() -> None:
    # Some payloads have a weighted sum of 10 mod 11: no check digit can make them valid.
    payload = next(f"8{n:08d}" for n in range(10**8) if hu_tax_id_check_digit(f"8{n:08d}") is None)
    assert not any(is_valid_hu_tax_id(payload + str(d)) for d in range(10))


@pytest.mark.parametrize(
    "value",
    ["", "812345678", "81234567860", "7123456786", "812345678a", "\uff18123456786"],
)
def test_tax_id_rejects_malformed(value: str) -> None:
    assert not is_valid_hu_tax_id(value)


def test_malformed_payloads_raise() -> None:
    with pytest.raises(ValueError):
        hu_tax_id_check_digit("123")
    with pytest.raises(ValueError):
        taj_check_digit("1234567a")
    with pytest.raises(ValueError):
        giro_check_digit("")
    with pytest.raises(ValueError):
        hu_tax_number_check_digit("12345678")
    with pytest.raises(ValueError):
        iban_check_digits("hu", "1234")
    with pytest.raises(ValueError):
        iban_check_digits("HU", "abc")


def test_iban_rejects_malformed() -> None:
    bban = "WEST12345698765432"
    good = "GB" + iban_check_digits("GB", bban) + bban
    assert is_valid_iban(good)
    assert not is_valid_iban(good.lower())
    assert not is_valid_iban(good + "0")  # wrong length for GB
    assert not is_valid_iban("ZZ" + good[2:])  # unknown country
    assert not is_valid_iban("GBXX" + bban)  # non-digit check digits
    assert not is_valid_iban(good[:6] + " " + good[7:])


def test_giro_rejects_wrong_length() -> None:
    assert not is_valid_giro("1177301")
    assert not is_valid_giro("1" * 20)


def test_tax_number_codes() -> None:
    base = "1234567" + str(hu_tax_number_check_digit("1234567"))
    assert is_valid_hu_tax_number(base, "2", "42")
    assert not is_valid_hu_tax_number(base, "6", "42")  # VAT code 1-5 only
    assert not is_valid_hu_tax_number(base, "2", "99")  # unknown area code
    assert not is_valid_hu_tax_number(_replace_digit(base, 7, 1), "2", "42")


# --- Properties -------------------------------------------------------------


@given(payload=digits(8), index=st.integers(0, 9), offset=st.integers(1, 9))
def test_tax_id_detects_any_single_digit_error(payload: str, index: int, offset: int) -> None:
    check = hu_tax_id_check_digit("8" + payload)
    if check is None:
        return
    value = f"8{payload}{check}"
    assert is_valid_hu_tax_id(value)
    assert not is_valid_hu_tax_id(_replace_digit(value, index, offset))


@given(payload=digits(8), index=st.integers(0, 8), offset=st.integers(1, 9))
def test_taj_detects_any_single_digit_error(payload: str, index: int, offset: int) -> None:
    value = payload + str(taj_check_digit(payload))
    assert is_valid_taj(value)
    assert not is_valid_taj(_replace_digit(value, index, offset))


@given(
    bank=digits(7),
    account=st.one_of(digits(7), digits(15)),
    data=st.data(),
)
def test_giro_detects_any_single_digit_error(bank: str, account: str, data: st.DataObject) -> None:
    value = bank + str(giro_check_digit(bank)) + account + str(giro_check_digit(account))
    assert is_valid_giro(value)
    index = data.draw(st.integers(0, len(value) - 1))
    offset = data.draw(st.integers(1, 9))
    assert not is_valid_giro(_replace_digit(value, index, offset))


@given(country=st.sampled_from(sorted(IBAN_LENGTHS)), data=st.data())
def test_iban_round_trip_and_single_error(country: str, data: st.DataObject) -> None:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    size = IBAN_LENGTHS[country] - 4
    bban = data.draw(st.text(alphabet=alphabet, min_size=size, max_size=size))
    value = country + iban_check_digits(country, bban) + bban
    assert is_valid_iban(value)
    # Mod 97 catches every single-digit substitution (97 is prime, so 97 never divides
    # delta * 10**k). Letters expand to two digits, so only digits are substituted here.
    positions = [i for i, ch in enumerate(value) if ch.isdigit()]
    index = data.draw(st.sampled_from(positions))
    replacement = data.draw(st.sampled_from("0123456789").filter(lambda ch: ch != value[index]))
    assert not is_valid_iban(value[:index] + replacement + value[index + 1 :])
