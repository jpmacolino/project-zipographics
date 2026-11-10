"""Tests for zipographics.importer: CSV reading and the Zipcator contract (SPEC §5.2, §5.3).

Expected ZIPs and overlaps for the Zipcator fixtures come from Zipcator's own CLI output (its
printed table shows overlap to 1 decimal, hence the 0.05 tolerance), not from this parser.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from zipographics.importer import (
    ColumnChoiceRequired,
    ImportFileError,
    decode_bytes,
    import_csv,
    is_zipcator_header,
    sniff_delimiter,
)

from zipographics.config import MAX_UPLOAD_BYTES

FX = Path(__file__).resolve().parents[1] / "fixtures" / "zipcator"

# `uv run zipcator "27.9506, -82.4572" --radius 5`  (rows in the CLI's order)
TAMPA = {
    "33602": 100.0,
    "33606": 100.0,
    "33605": 100.0,
    "33607": 76.2,
    "33603": 100.0,
    "33609": 96.1,
    "33629": 94.4,
    "33610": 37.9,
    "33619": 42.0,
    "33614": 52.1,
    "33604": 58.4,
    "33611": 38.3,
}

# `uv run zipcator "42.3588, -71.0578" --radius 3 --zips`  (33 ZIPs, all with a leading zero)
BOSTON_ZIPS = [
    "02108",
    "02109",
    "02110",
    "02203",
    "02114",
    "02133",
    "02111",
    "02113",
    "02210",
    "02205",
    "02116",
    "02129",
    "02141",
    "02127",
    "02118",
    "02142",
    "02128",
    "02143",
    "02199",
    "02139",
    "02115",
    "02215",
    "02150",
    "02120",
    "02119",
    "02149",
    "02125",
    "02145",
    "02446",
    "02138",
    "02134",
    "02155",
    "02445",
]
BOSTON_PARTIAL = {  # the rows of the CLI table that are not 100.0 %
    "02128": 71.5,
    "02143": 74.2,
    "02139": 99.0,
    "02115": 89.7,
    "02215": 85.9,
    "02150": 56.7,
    "02120": 70.8,
    "02119": 66.4,
    "02149": 32.9,
    "02125": 45.0,
    "02145": 63.4,
    "02446": 14.8,
    "02138": 6.8,
    "02134": 1.5,
    "02155": 0.4,
    "02445": 0.1,
}


def read(name: str) -> bytes:
    return (FX / name).read_bytes()


def csv_bytes(text: str, encoding: str = "utf-8") -> bytes:
    return text.replace("\n", "\r\n").encode(encoding)


# ----------------------------------------------------------------- Zipcator fixtures (§5.3)
TAMPA_FILES = ["tampa_5mi.csv", "tampa_5mi_excel.csv", "tampa_5mi_semicolon.csv"]
BOSTON_REAL = ["boston_3mi.csv", "boston_3mi_excel.csv"]
BOSTON_RESAVED = [
    "boston_3mi_resave_zeros_stripped.csv",
    "boston_3mi_resave_utf8_bom.csv",
    "boston_3mi_excel_resave_plain_zips.csv",
    "boston_3mi_snake_case.csv",
]


@pytest.mark.parametrize("name", TAMPA_FILES)
def test_tampa_exports_parse_to_the_cli_zips_and_overlaps(name: str) -> None:
    p = import_csv(read(name))
    assert p.zips == tuple(TAMPA)
    assert p.source == "zipcator"
    assert p.is_zipcator
    assert p.detected_by == "zipcator"
    assert p.zip_column == "ZIP"
    assert set(p.overlaps) == set(TAMPA)
    for z, pct in TAMPA.items():
        assert p.overlaps[z] == pytest.approx(pct, abs=0.05), z
    assert p.repaired == ()
    assert p.invalid == ()
    assert p.duplicates == 0
    assert p.blank_overlap == ()


@pytest.mark.parametrize("name", [*BOSTON_REAL, *BOSTON_RESAVED])
def test_boston_variants_all_give_the_same_zips_and_overlaps(name: str) -> None:
    p = import_csv(read(name))
    assert p.zips == tuple(BOSTON_ZIPS)
    assert p.is_zipcator
    for z in BOSTON_ZIPS:
        assert p.overlaps[z] == pytest.approx(BOSTON_PARTIAL.get(z, 100.0), abs=0.05), z


@pytest.mark.parametrize("name", BOSTON_REAL)
def test_real_exports_need_no_repair(name: str) -> None:
    assert import_csv(read(name)).repaired == ()


@pytest.mark.parametrize(
    "name", ["boston_3mi_resave_zeros_stripped.csv", "boston_3mi_resave_utf8_bom.csv"]
)
def test_excel_stripped_zeros_are_repaired_and_reported(name: str) -> None:
    p = import_csv(read(name))
    assert len(p.repaired) == 33  # every Boston ZIP lost its leading zero
    assert (p.repaired[0].raw, p.repaired[0].zip) == ("2108", "02108")
    assert [t.zip for t in p.repaired] == BOSTON_ZIPS


def test_excel_resave_of_the_excel_safe_file_needs_no_repair() -> None:
    assert import_csv(read("boston_3mi_excel_resave_plain_zips.csv")).repaired == ()


def test_snake_case_headers_are_a_zipcator_export() -> None:
    p = import_csv(read("boston_3mi_snake_case.csv"))
    assert p.is_zipcator
    assert p.zip_column == "zip"


def test_population_columns_do_not_matter() -> None:
    p = import_csv(read("synthetic_population.csv"))
    assert p.zips == ("02108", "00501", "33602")
    assert p.overlaps["02108"] == 100.0
    assert p.overlaps["00501"] == 100.0
    assert p.overlaps["33602"] == pytest.approx(2.806595)
    assert import_csv(read("synthetic_population_excel.csv")).zips == p.zips


def test_cp1252_resave_with_an_accent_and_stripped_zeros() -> None:
    p = import_csv(read("synthetic_population_resave_cp1252.csv"))
    assert p.zips == ("02108", "00501", "33602")
    assert [(t.raw, t.zip) for t in p.repaired] == [("2108", "02108"), ("501", "00501")]
    assert p.overlaps["33602"] == pytest.approx(2.806595)


# ----------------------------------------------------------------- detection (§5.3)
@pytest.mark.parametrize(
    "headers",
    [
        [
            "ZIP",
            "City",
            "County",
            "State",
            "Overlap %",
            "Area in radius (sq mi)",
            "Contains address",
        ],
        ["ZIP", "Overlap %", "Contains address"],
        ["ZIP", "Overlap %", "Area in radius (sq mi)"],
        ["ZIP", "Overlap %", "Nearest distance (mi)"],
        ["﻿ZIP", "Overlap %", "Contains address"],  # BOM left on the first header
        ["  zip ", " OVERLAP % ", " contains ADDRESS "],  # whitespace and case
        ["zip", "overlap_pct"],  # snake_case fallback
        ["ZIP", "overlap_pct", "city"],
        ["Overlap %", "ZIP", "Contains address"],  # column order does not matter
    ],
)
def test_zipcator_header_detection_true(headers: list[str]) -> None:
    assert is_zipcator_header(headers)


@pytest.mark.parametrize(
    "headers",
    [
        ["ZIP", "City", "State"],  # a generic CSV with a ZIP column
        ["ZIP", "Overlap %"],  # not enough: needs one of the Zipcator-only columns
        ["ZIP", "Contains address"],  # no overlap column
        ["Overlap %", "Contains address"],  # no ZIP
        ["zipcode", "overlap_pct"],  # snake_case needs exactly zip + overlap_pct
        ["ZIP", "Overlap"],
        [],
    ],
)
def test_zipcator_header_detection_false(headers: list[str]) -> None:
    assert not is_zipcator_header(headers)


def test_a_generic_csv_with_a_zip_column_is_not_a_zipcator_export() -> None:
    p = import_csv(csv_bytes("Name,ZIP,Sales\nAcme,02108,10\nBeta,33602,20\n"))
    assert p.source == "csv"
    assert not p.is_zipcator
    assert p.overlaps == {}
    assert p.zips == ("02108", "33602")


def test_a_generic_csv_with_an_overlap_column_but_no_zipcator_columns_is_generic() -> None:
    p = import_csv(csv_bytes("ZIP,Overlap %\n02108,50\n"))
    assert p.source == "csv"
    assert p.overlaps == {}


# ----------------------------------------------------------------- Zipcator row rules (§5.3)
ZC_HEAD = "ZIP,Overlap %,Contains address\n"


def zc(rows: str) -> bytes:
    return csv_bytes(ZC_HEAD + rows)


def test_overlap_with_a_percent_sign_is_accepted() -> None:
    p = import_csv(zc('02108,12.5%,No\n02109," 100 %",No\n'))
    assert p.overlaps == {"02108": 12.5, "02109": 100.0}


def test_comma_decimal_in_a_quoted_cell_is_accepted() -> None:
    assert import_csv(zc('02108,"12,5",No\n')).overlaps == {"02108": 12.5}


def test_blank_overlap_keeps_the_zip_as_a_full_zip_and_lists_it() -> None:
    p = import_csv(zc("02108,50,No\n02109,,No\n02110, ,No\n"))
    assert p.zips == ("02108", "02109", "02110")
    assert p.blank_overlap == ("02109", "02110")
    assert p.overlaps == {"02108": 50.0}


@pytest.mark.parametrize(
    "bad", ["0", "0.0", "-5", "100.5", "101", "abc", "nan", "inf", "1e2", "--1"]
)
def test_out_of_range_or_unparseable_overlap_rejects_the_row(bad: str) -> None:
    p = import_csv(zc(f"02108,50,No\n02109,{bad},No\n"))
    assert p.zips == ("02108",)
    assert len(p.rejected_rows) == 1
    row = p.rejected_rows[0]
    assert (row.zip, row.raw_overlap) == ("02109", bad)
    assert row.reason


@pytest.mark.parametrize("good", ["100", "100.0", "0.000001", "0.1", "99.999999"])
def test_boundary_overlaps_are_accepted(good: str) -> None:
    p = import_csv(zc(f"02108,{good},No\n"))
    assert p.zips == ("02108",)
    assert p.overlaps["02108"] == pytest.approx(float(good))
    assert p.rejected_rows == ()


def test_repeated_zip_with_the_same_overlap_is_just_a_duplicate() -> None:
    p = import_csv(zc("02108,50,No\n02108,50,No\n"))
    assert p.zips == ("02108",)
    assert p.duplicates == 1
    assert p.overlap_conflicts == ()


def test_repeated_zip_with_a_different_overlap_keeps_the_first_and_warns() -> None:
    p = import_csv(zc("02108,50,No\n02108,60,No\n"))
    assert p.zips == ("02108",)
    assert p.overlaps == {"02108": 50.0}
    assert p.duplicates == 1
    assert p.overlap_conflicts == ("02108",)


def test_a_repeat_after_repair_is_matched_too() -> None:
    p = import_csv(zc("02108,50,No\n2108,60,No\n"))
    assert p.zips == ("02108",)
    assert p.overlap_conflicts == ("02108",)


def test_invalid_zip_in_a_zipcator_file_is_listed_not_imported() -> None:
    p = import_csv(zc("02108,50,No\nabc,50,No\n"))
    assert p.zips == ("02108",)
    assert p.invalid == ("abc",)
    assert "abc" not in p.overlaps


def test_zipcator_rows_with_blank_zip_cells_and_blank_lines_are_ignored() -> None:
    p = import_csv(zc("02108,50,No\n,50,No\n\n02109,60,No\n"))
    assert p.zips == ("02108", "02109")
    assert p.invalid == ()


def test_excel_text_formula_cells_are_unwrapped() -> None:
    p = import_csv(zc('"=""02108""",50,No\n'))
    assert p.zips == ("02108",)
    assert p.repaired == ()


# ----------------------------------------------------------------- generic ZIP column (§5.2)
@pytest.mark.parametrize(
    "header",
    ["zip", "ZIP", "Zip", "zipcode", "ZipCode", "Zip Code", "zip_code", "zip5", "Postal Code",
     "postalcode", "ZCTA", "zcta5", "  ZIP  ", "zip-code"],
)  # fmt: skip
def test_zip_column_found_by_header_name(header: str) -> None:
    p = import_csv(csv_bytes(f"Name,{header},Sales\nAcme,02108,10\nBeta,33602,20\n"))
    assert p.zips == ("02108", "33602")
    assert p.detected_by == "header"
    assert p.zip_column == header.strip()
    assert p.source == "csv"


def test_two_header_name_matches_need_a_choice() -> None:
    data = csv_bytes("ZIP,Zip Code,Name\n02108,33602,Acme\n02109,33606,Beta\n")
    with pytest.raises(ColumnChoiceRequired) as exc:
        import_csv(data)
    assert exc.value.candidates == ("ZIP", "Zip Code")
    p = import_csv(data, zip_column="Zip Code")
    assert p.zips == ("33602", "33606")
    assert p.detected_by == "choice"
    assert p.zip_column == "Zip Code"


def test_zip_column_found_by_content_when_no_header_matches() -> None:
    p = import_csv(csv_bytes("Name,Where,Notes\nAcme,02108,hello\nBeta,33602,world\n"))
    assert p.zips == ("02108", "33602")
    assert p.detected_by == "content"
    assert p.zip_column == "Where"


def test_content_detection_needs_80_percent_valid_values() -> None:
    rows = "\n".join(["Acme,02108", "B,33602", "C,02110", "D,02111", "E,junk"])  # 4 of 5 = 80 %
    assert import_csv(csv_bytes("Name,Where\n" + rows + "\n")).zips == (
        "02108",
        "33602",
        "02110",
        "02111",
    )
    rows = "\n".join(["Acme,02108", "B,33602", "C,02110", "D,junk", "E,junk"])  # 3 of 5 = 60 %
    with pytest.raises(ImportFileError, match="ZIP"):
        import_csv(csv_bytes("Name,Where\n" + rows + "\n"))


def test_several_content_candidates_need_a_choice() -> None:
    data = csv_bytes("Home,Work\n02108,33602\n02109,33606\n")
    with pytest.raises(ColumnChoiceRequired) as exc:
        import_csv(data)
    assert exc.value.candidates == ("Home", "Work")
    assert import_csv(data, zip_column="Work").zips == ("33602", "33606")


def test_unknown_chosen_column_is_an_error() -> None:
    with pytest.raises(ImportFileError, match="Nope"):
        import_csv(csv_bytes("ZIP,Name\n02108,x\n"), zip_column="Nope")


def test_no_zip_column_is_an_error() -> None:
    with pytest.raises(ImportFileError, match="ZIP column"):
        import_csv(csv_bytes("Name,City\nAcme,Boston\nBeta,Tampa\n"))


def test_header_less_single_column() -> None:
    p = import_csv(csv_bytes("02108\n02109\n33602\n"))
    assert p.zips == ("02108", "02109", "33602")
    assert p.detected_by == "single"
    assert p.zip_column is None


def test_header_less_single_column_with_a_repairable_first_value() -> None:
    p = import_csv(csv_bytes("2108\n02109\n"))  # 2108 is data (a valid token), not a header
    assert p.zips == ("02108", "02109")
    assert [t.raw for t in p.repaired] == ["2108"]


@pytest.mark.parametrize("header", ["ZIP", "Zip Code", "my zips", "Customer ZIPs"])
def test_single_column_with_a_header_cell(header: str) -> None:
    p = import_csv(csv_bytes(f"{header}\n02108\n02109\n"))
    assert p.zips == ("02108", "02109")
    assert p.invalid == ()
    assert p.zip_column == header


def test_single_column_of_mostly_junk_is_data_not_a_header() -> None:
    p = import_csv(csv_bytes("abc\ndef\nghi\n02108\n"))
    assert p.zips == ("02108",)
    assert p.invalid == ("abc", "def", "ghi")


def test_token_rules_apply_to_csv_values() -> None:
    p = import_csv(csv_bytes('ZIP\n2108\n601\n02109-1234\n021101234\n3360.0\n="02111"\nabc\n'))
    assert p.zips == ("02108", "00601", "02109", "02110", "03360", "02111")
    assert [t.raw for t in p.repaired] == ["2108", "601", "3360.0"]
    assert [t.raw for t in p.truncated] == ["02109-1234", "021101234"]
    assert p.invalid == ("abc",)
    assert p.duplicates == 0


def test_plus_four_of_an_already_seen_zip_is_a_duplicate() -> None:
    p = import_csv(csv_bytes("ZIP\n02108\n02108-1234\n2108\n"))
    assert p.zips == ("02108",)
    assert p.duplicates == 2


def test_zip_values_are_never_numbers() -> None:
    p = import_csv(csv_bytes("ZIP,N\n01234,1\n00501,2\n"))
    assert p.zips == ("01234", "00501")
    assert all(isinstance(z, str) for z in p.zips)


def test_header_only_file_gives_an_empty_input() -> None:
    p = import_csv(csv_bytes("ZIP,Name\n"))
    assert p.zips == ()
    assert p.zip_column == "ZIP"


def test_ragged_rows_and_blank_lines() -> None:
    p = import_csv(csv_bytes("Name,ZIP,Notes\nAcme,02108\n\nBeta\nGamma,33602,x,y\n"))
    assert p.zips == ("02108", "33602")


# ----------------------------------------------------------------- encodings and delimiters
def test_utf8_bom_is_stripped_from_the_first_header() -> None:
    p = import_csv(csv_bytes("ZIP,Name\n02108,x\n", "utf-8-sig"))
    assert p.zip_column == "ZIP"
    assert p.zips == ("02108",)


def test_utf8_with_accents() -> None:
    p = import_csv(csv_bytes("ZIP,City\n00601,Adjuntas\n00602,Aguada\n00603,Aguadilla\n"))
    assert p.zips == ("00601", "00602", "00603")
    assert import_csv(csv_bytes("ZIP,City\n00667,Mayagüez\n")).zips == ("00667",)


def test_cp1252_is_the_fallback_encoding() -> None:
    data = csv_bytes("ZIP,City\n00667,Mayagüez\n", "cp1252")
    with pytest.raises(UnicodeDecodeError):
        data.decode("utf-8")
    assert import_csv(data).zips == ("00667",)
    assert decode_bytes(data) == "ZIP,City\r\n00667,Mayagüez\r\n"


def test_undefined_cp1252_bytes_do_not_crash() -> None:
    data = b"ZIP,Name\r\n02108,caf\x81\r\n"  # 0x81 is undefined in cp1252
    assert import_csv(data).zips == ("02108",)


def test_utf16_with_bom_excel_unicode_text() -> None:
    data = csv_bytes("ZIP\tCity\n02108\tBoston\n33602\tTampa\n", "utf-16")
    assert import_csv(data).zips == ("02108", "33602")


@pytest.mark.parametrize("delim", [",", ";", "\t"])
def test_delimiters_comma_semicolon_tab(delim: str) -> None:
    text = delim.join(["Name", "ZIP", "Sales"]) + "\n" + delim.join(["Acme", "02108", "1"]) + "\n"
    p = import_csv(csv_bytes(text + delim.join(["Beta", "33602", "2"]) + "\n"))
    assert p.zips == ("02108", "33602")


def test_quoted_fields_containing_the_delimiter() -> None:
    p = import_csv(csv_bytes('Name,ZIP\n"Smith, John",02108\n"Doe; Jane",33602\n'))
    assert p.zips == ("02108", "33602")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a,b,c\n1,2,3\n", ","),
        ("a;b;c\n1;2;3\n", ";"),
        ("a\tb\tc\n1\t2\t3\n", "\t"),
        ("a\n1\n2\n", ","),  # single column: default
        ('"a,x";"b"\n"1,2";"3"\n', ";"),  # commas inside quotes must not win
        ("", ","),
    ],
)
def test_sniff_delimiter(text: str, expected: str) -> None:
    assert sniff_delimiter(text) == expected


# ----------------------------------------------------------------- limits and errors
def test_file_at_the_size_limit_is_accepted_and_one_byte_over_is_not() -> None:
    base = b"ZIP\n02108\n"
    at_limit = base + b" " * (MAX_UPLOAD_BYTES - len(base))
    assert len(at_limit) == MAX_UPLOAD_BYTES
    assert import_csv(at_limit).zips == ("02108",)
    with pytest.raises(ImportFileError, match="5 MB"):
        import_csv(at_limit + b" ")


@pytest.mark.parametrize("data", [b"", b"\n\n", b"   \r\n  "])
def test_empty_file_is_an_error(data: bytes) -> None:
    with pytest.raises(ImportFileError, match="empty"):
        import_csv(data)


def test_import_errors_are_value_errors() -> None:
    assert issubclass(ImportFileError, ValueError)
    assert issubclass(ColumnChoiceRequired, ImportFileError)


# ----------------------------------------------------------------- properties
@given(st.lists(st.from_regex(r"[0-9]{5}", fullmatch=True), min_size=1, max_size=50))
def test_single_column_csv_roundtrip_preserves_zips(zs: list[str]) -> None:
    # a header-less column whose first value is a valid ZIP is all data
    p = import_csv(csv_bytes("\n".join(zs) + "\n"))
    assert list(p.zips) == list(dict.fromkeys(zs))
    assert p.duplicates == len(zs) - len(set(zs))
    assert all(isinstance(z, str) and len(z) == 5 for z in p.zips)
