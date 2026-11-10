"""Tests for zipographics.zips: token rules and paste parsing (SPEC §5.2, §9.2 zips)."""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from zipographics.models import ParsedInput
from zipographics.zips import normalize_token, parse_paste

FIVE = re.compile(r"[0-9]{5}")


# --------------------------------------------------------------------------- normalize_token
@pytest.mark.parametrize(
    ("raw", "expected", "status"),
    [
        ("02108", "02108", "ok"),
        ("33602", "33602", "ok"),
        ("00000", "00000", "ok"),  # valid format; "not found" is the review's job
        ("  02108\t", "02108", "ok"),
        ('"02108"', "02108", "ok"),
        ("'02108", "02108", "ok"),  # Excel's text prefix
        ("“02108”", "02108", "ok"),  # smart quotes
        ('="02108"', "02108", "ok"),  # Zipcator Excel-safe, after CSV decoding
        ('"=""02108"""', "02108", "ok"),  # the same, raw from the file
        ("\N{ZERO WIDTH NO-BREAK SPACE}02108", "02108", "ok"),  # stray BOM
        ("\N{NO-BREAK SPACE}02108\N{NO-BREAK SPACE}", "02108", "ok"),  # non-breaking spaces
        ("02108.0", "02108", "ok"),  # Excel float
        ("33602.00", "33602", "ok"),
        # 3-4 digits: left-padded and counted as repaired
        ("2108", "02108", "repaired"),
        ("601", "00601", "repaired"),
        ("501", "00501", "repaired"),
        ("000", "00000", "repaired"),
        ("2108.0", "02108", "repaired"),
        ('="2108"', "02108", "repaired"),
        # ZIP+4: truncated
        ("02108-1234", "02108", "truncated"),
        ("021081234", "02108", "truncated"),
        ("33602-0000", "33602", "truncated"),
        # Excel-mangled ZIP+4: repaired and truncated
        ("2108-1234", "02108", "repaired_truncated"),
        ("601-1234", "00601", "repaired_truncated"),
        ("21081234", "02108", "repaired_truncated"),  # 8 digits: 02108-1234 minus the zero
        ("6011234", "00601", "repaired_truncated"),  # 7 digits: 00601-1234 minus two zeros
    ],
)
def test_token_rules(raw: str, expected: str, status: str) -> None:
    tok = normalize_token(raw)
    assert tok.zip == expected
    assert tok.status == status
    assert tok.raw == raw
    assert tok.valid
    assert tok.repaired == status.startswith("repaired")
    assert tok.truncated == status.endswith("truncated")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "1",
        "12",  # 1-2 digits
        "123456",  # 6 digits
        "abc",
        "ABC12",
        "12-34",
        "1e5",
        "33602.5",
        "02108-12",  # short plus-four
        "02108-12345",
        "1234567890",  # 10 digits
        "02108-",
        "-02108",
        "02 108",
        "zip",
        "🙂",
        "٠٢١٠٨",  # Arabic-Indic digits: str.isdigit() accepts them, we must not
        (  # full-width digits
            "\N{FULLWIDTH DIGIT ZERO}\N{FULLWIDTH DIGIT TWO}\N{FULLWIDTH DIGIT ONE}"
            "\N{FULLWIDTH DIGIT ZERO}\N{FULLWIDTH DIGIT EIGHT}"
        ),
        "²¹⁰⁸",
    ],
)
def test_invalid_tokens(raw: str) -> None:
    tok = normalize_token(raw)
    assert tok.zip is None
    assert tok.status == "invalid"
    assert not tok.valid
    assert tok.raw == raw


def test_the_zip_is_text_never_a_number() -> None:
    assert isinstance(normalize_token("601").zip, str)
    assert normalize_token("601").zip == "00601"


# --------------------------------------------------------------------------- parse_paste
def test_separators_commas_spaces_tabs_semicolons_pipes_newlines() -> None:
    text = "02108,02109 02110\t02111;02113|02114\n02115\r\n02116"
    p = parse_paste(text)
    assert p.zips == (
        "02108",
        "02109",
        "02110",
        "02111",
        "02113",
        "02114",
        "02115",
        "02116",
    )
    assert p.source == "paste"
    assert p.invalid == ()
    assert p.duplicates == 0


def test_runs_of_separators_collapse() -> None:
    assert parse_paste(",, ;; 02108 ,\n\n  | 02109 ,,").zips == ("02108", "02109")


def test_excel_column_with_a_header_cell() -> None:
    p = parse_paste("ZIP\r\n02108\r\n02109\r\n")
    assert p.zips == ("02108", "02109")
    assert p.invalid == ()


@pytest.mark.parametrize(
    "header",
    ["zip", "ZIP", "Zip", "zipcode", "ZipCode", "zip code", "Zip Code", "postal code", "ZCTA"],
)
def test_first_token_header_words_are_ignored(header: str) -> None:
    p = parse_paste(f"{header}\n02108\n02109")
    assert p.zips == ("02108", "02109")
    assert p.invalid == ()


def test_header_word_on_the_same_line_is_ignored() -> None:
    assert parse_paste("zip, 02108, 02109").zips == ("02108", "02109")


def test_quoted_header_is_ignored() -> None:
    assert parse_paste('"ZIP"\n"02108"').zips == ("02108",)


def test_a_header_word_that_is_not_first_is_invalid() -> None:
    p = parse_paste("02108 zip")
    assert p.zips == ("02108",)
    assert p.invalid == ("zip",)


def test_quoted_tokens_and_excel_text_formula_and_float() -> None:
    p = parse_paste('"02108", "02109"\n="02110"\n2111.0')
    assert p.zips == ("02108", "02109", "02110", "02111")
    assert [t.raw for t in p.repaired] == ["2111.0"]


def test_zipcator_excel_safe_lines_pasted_raw() -> None:
    p = parse_paste('"=""02108"""\n"=""02109"""')
    assert p.zips == ("02108", "02109")
    assert p.repaired == ()


def test_leading_zero_repair_is_reported_in_order() -> None:
    p = parse_paste("2108, 02109, 601, 501")
    assert p.zips == ("02108", "02109", "00601", "00501")
    assert [(t.raw, t.zip) for t in p.repaired] == [
        ("2108", "02108"),
        ("601", "00601"),
        ("501", "00501"),
    ]


def test_zip_plus_four_is_truncated_and_counted() -> None:
    p = parse_paste("02108-1234 021091234 21101234 2111-1234 6011234")
    assert p.zips == ("02108", "02109", "02110", "02111", "00601")
    assert [t.raw for t in p.truncated] == [
        "02108-1234",
        "021091234",
        "21101234",
        "2111-1234",
        "6011234",
    ]
    # the Excel-mangled ones are also repaired
    assert [t.raw for t in p.repaired] == ["21101234", "2111-1234", "6011234"]


def test_invalid_tokens_are_listed_verbatim_in_order() -> None:
    p = parse_paste("abc 02108 1e5 12-34 🙂 123456 7")
    assert p.zips == ("02108",)
    assert p.invalid == ("abc", "1e5", "12-34", "🙂", "123456", "7")


def test_duplicates_are_dropped_first_occurrence_keeps_its_position() -> None:
    p = parse_paste("33602 02108 33602 10001 02108")
    assert p.zips == ("33602", "02108", "10001")
    assert p.duplicates == 2


def test_duplicates_are_detected_after_repair() -> None:
    p = parse_paste("2108 02108 2108")
    assert p.zips == ("02108",)
    assert p.duplicates == 2
    # only the retained occurrence is reported as repaired
    assert [t.raw for t in p.repaired] == ["2108"]


def test_repair_of_a_dropped_duplicate_is_not_reported() -> None:
    p = parse_paste("02108 2108")
    assert p.zips == ("02108",)
    assert p.duplicates == 1
    assert p.repaired == ()


def test_zip_plus_four_duplicates_of_a_plain_zip() -> None:
    p = parse_paste("02108 02108-1234")
    assert p.zips == ("02108",)
    assert p.duplicates == 1
    assert p.truncated == ()


@pytest.mark.parametrize("text", ["", "   ", "\n\r\n\t", ",;|"])
def test_empty_input(text: str) -> None:
    p = parse_paste(text)
    assert p == ParsedInput(source="paste")
    assert p.zips == ()


def test_header_only_input_is_empty() -> None:
    assert parse_paste("ZIP").zips == ()


def test_the_parser_does_not_enforce_the_zip_limit() -> None:
    # the 1,000 limit is a review-screen blocking condition (SPEC §5.4), not a parse error
    text = " ".join(f"{n:05d}" for n in range(1001))
    assert len(parse_paste(text).zips) == 1001


def test_parse_paste_is_not_a_zipcator_input() -> None:
    p = parse_paste("02108")
    assert not p.is_zipcator
    assert p.overlaps == {}


# --------------------------------------------------------------------------- properties
@given(st.text())
def test_normalize_never_raises_and_only_yields_five_digit_strings(raw: str) -> None:
    tok = normalize_token(raw)
    if tok.zip is None:
        assert tok.status == "invalid"
    else:
        assert isinstance(tok.zip, str)
        assert FIVE.fullmatch(tok.zip)
        assert tok.status != "invalid"


@given(st.text())
def test_parse_output_zips_are_always_five_digit_strings(text: str) -> None:
    for z in parse_paste(text).zips:
        assert isinstance(z, str)
        assert FIVE.fullmatch(z)


@given(st.text())
def test_parse_then_reparse_is_idempotent(text: str) -> None:
    first = parse_paste(text).zips
    again = parse_paste(", ".join(first))
    assert again.zips == first
    assert again.duplicates == 0
    assert again.repaired == ()
    assert again.invalid == ()


@given(st.from_regex(r"[0-9]{5}", fullmatch=True))
def test_padding_never_changes_a_five_digit_token(z: str) -> None:
    tok = normalize_token(z)
    assert tok.zip == z
    assert tok.status == "ok"


@given(st.lists(st.from_regex(r"[0-9]{5}", fullmatch=True), max_size=60))
def test_dedupe_preserves_first_occurrence_order(zs: list[str]) -> None:
    expected = list(dict.fromkeys(zs))
    p = parse_paste(" ".join(zs))
    assert list(p.zips) == expected
    assert p.duplicates == len(zs) - len(expected)


_POOL = ["02108", "2108", "601", "abc", "02108-1234", "1", "33602", "33602.0", "123456", "x9"]


@given(st.lists(st.sampled_from(_POOL), max_size=40))
def test_every_token_is_accounted_for(tokens: list[str]) -> None:
    p = parse_paste(" ".join(tokens))
    assert len(p.zips) + p.duplicates + len(p.invalid) == len(tokens)
