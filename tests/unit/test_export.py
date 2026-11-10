"""Exports: ZIP lists, CSV (plain and Excel), attestation, file names (SPEC 5.6, 5.7, 9.2)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime

import pandas as pd
import pytest
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import export, filters, restricted, verticals
from zipographics.models import ParsedInput, Rule, UsePolicy
from zipographics.zips import parse_paste

OFF = verticals.make_policy("Retail (general & specialty)", False)
ANSWERED = verticals.make_policy("Automotive sales", True)
FORCED = verticals.make_policy("Mortgage & lending", None)
BOM = chr(0xFEFF)  # a UTF-8 byte order mark, as Excel-safe CSVs start with
NOW = datetime(2026, 11, 10, 14, 30, tzinfo=UTC)

WORLD = {
    "02108": Z(3794, 1973, owner=0.51, kids=0.10, state="MA", county=("25025", "Suffolk County"),
              city="Boston", income=212_928),
    "33602": Z(5000, 2000, owner=0.40, kids=0.20),
    "33606": Z(8000, 3500, owner=0.70, kids=0.35, city="=HYPERLINK(\"http://x\")"),
    "33603": Z(900, 280, owner=0.55, kids=0.30, income=250_001, code="top",
               extra={"B25003_002": (154.0, 200.0)}),
}  # fmt: skip
ART = make_artifacts(WORLD)
NOT_FOUND_TEXT = "33602 99999 33606 2108 33603"  # 99999 is not in the data; 2108 repairs to 02108


def run(text: str = NOT_FOUND_TEXT, policy: UsePolicy = OFF, **kw):  # type: ignore[no-untyped-def]
    return an.analyze(
        ART, parse_paste(text), policy, project_name=kw.pop("name", "Acme HVAC"), **kw
    )


def table_of(text: str) -> list[list[str]]:
    """The rows of the CSV table part (up to the blank line)."""
    rows = list(csv.reader(io.StringIO(text.lstrip(BOM), newline="")))
    out = []
    for r in rows:
        if not r:
            break
        out.append(r)
    return out


def footer_of(text: str) -> list[str]:
    rows = list(csv.reader(io.StringIO(text.lstrip(BOM), newline="")))
    i = rows.index([])
    return [r[0] for r in rows[i + 1 :]]


# --------------------------------------------------------------------- file names
@pytest.mark.parametrize(
    ("project", "expected"),
    [
        ("Acme HVAC", "Acme HVAC"),
        ("  Acme / HVAC: Q4?  ", "Acme _ HVAC_ Q4_"),
        ("CON", "CON"),
        ("a" * 200, "a" * 60),
        ("", "zipographics"),
        (None, "zipographics"),
        ("...", "zipographics"),
        ('<>:"/\\|?*', "zipographics"),
        ("tab\tand\nnewline", "tab and newline"),
        ("Café Müller", "Café Müller"),
    ],
)
def test_project_names_become_safe_file_stems(project: str | None, expected: str) -> None:
    assert export.file_stem(project) == expected


def test_file_names_follow_the_spec_pattern() -> None:
    names = export.filenames("Acme HVAC", date(2026, 11, 10))
    assert names == {
        "csv": "Acme HVAC_2026-11-10_zips.csv",
        "csv_excel": "Acme HVAC_2026-11-10_zips_excel.csv",
        "ziplist": "Acme HVAC_2026-11-10_ziplist.txt",
        "report": "Acme HVAC_2026-11-10_report.html",
    }
    assert export.filenames(None, date(2026, 1, 2))["csv"] == "zipographics_2026-01-02_zips.csv"


def test_a_reserved_windows_name_never_appears_as_a_whole_file_name() -> None:
    for name in export.filenames("NUL", date(2026, 1, 1)).values():
        assert name.split(".")[0].upper() != "NUL"


# --------------------------------------------------------------------- ZIP lists
def test_the_zip_list_has_every_valid_input_zip_in_input_order() -> None:
    a = run()
    assert a.parsed.zips == ("33602", "99999", "33606", "02108", "33603")
    assert export.zip_list(a) == "33602, 99999, 33606, 02108, 33603"
    assert export.zip_list(a, style="newline") == "33602\n99999\n33606\n02108\n33603"


def test_not_found_zips_can_be_dropped_with_the_checkbox() -> None:
    a = run()
    assert export.zip_list(a, include_not_found=False) == "33602, 33606, 02108, 33603"


def test_a_filter_exports_the_qualifying_zips_in_input_order() -> None:
    a = run()
    r = filters.apply(a, [Rule("owner", ">=", 0.5)])
    assert r.qualifying == ("33606", "02108", "33603")
    assert export.zip_list(a, qualifying=r.qualifying) == "33606, 02108, 33603"
    assert export.zip_list(a, qualifying=()) == ""
    # "export all instead" is simply not passing the subset
    assert export.zip_list(a) == "33602, 99999, 33606, 02108, 33603"


def test_a_qualifying_subset_must_come_from_the_recognized_zips() -> None:
    with pytest.raises(ValueError, match="99999"):
        export.zip_list(run(), qualifying=("99999",))


@pytest.mark.parametrize("policy", [ANSWERED, FORCED, None])
def test_restricted_mode_exports_exactly_the_input_zips_whatever_is_passed(
    policy: UsePolicy | None,
) -> None:
    a = run(policy=ANSWERED)
    for qualifying in (None, ("33606",), ()):
        for style, sep in (("comma", ", "), ("newline", "\n")):
            got = export.zip_list(a, qualifying=qualifying, include_not_found=False, style=style)  # type: ignore[arg-type]
            assert got == sep.join(a.parsed.zips)


def test_the_zip_list_has_no_footer_or_header() -> None:
    text = export.zip_list(run())
    assert "Note" not in text and "ZIP" not in text and "\r" not in text


def test_an_empty_input_gives_an_empty_list() -> None:
    a = an.analyze(ART, ParsedInput(zips=("33602",)), OFF)
    assert export.zip_list(a, qualifying=()) == ""


def test_zip_list_styles_are_validated() -> None:
    with pytest.raises(ValueError, match="style"):
        export.zip_list(run(), style="tabs")  # type: ignore[arg-type]


def test_the_ad_platform_notice_appears_only_in_restricted_mode() -> None:
    assert export.ad_platform_notice(ANSWERED) == restricted.AD_PLATFORM_NOTICE
    assert export.ad_platform_notice(FORCED) == restricted.AD_PLATFORM_NOTICE
    assert export.ad_platform_notice(OFF) is None
    assert export.ad_platform_notice(None) == restricted.AD_PLATFORM_NOTICE  # fail closed


# --------------------------------------------------------------------- attestation
def lines(a: an.Analysis, result=None) -> str:  # type: ignore[no-untyped-def]
    return "\n".join(export.attestation(a, result, now=NOW, version="1.2.3"))


@pytest.mark.parametrize(
    ("policy", "answer", "mode"),
    [(OFF, "No", "off"), (ANSWERED, "Yes", "on"), (FORCED, "Yes (set by industry)", "on")],
)
def test_the_attestation_records_every_field(policy: UsePolicy, answer: str, mode: str) -> None:
    a = run(policy=policy, name="Acme HVAC")
    text = lines(a)
    assert "Project: Acme HVAC" in text
    assert f"Industry: {policy.vertical}" in text
    assert verticals.RESTRICTED_QUESTION in text and f"Answer: {answer}" in text
    assert f"Restricted mode: {mode}" in text
    assert "Benchmark: Florida (state)" in text
    assert "Estimate mode: Full ZIPs" in text
    assert "Filters applied: none" in text
    assert "Data: ACS 2020-2024 5-year estimates" in text
    assert "ZIP = Census ZCTA; PO-box-only and single-organization ZIPs aren't included." in text
    assert "90 % confidence level" in text and "approximations" in text
    assert "Generated: 2026-11-10 14:30 UTC by Zipographics 1.2.3" in text
    assert "This product uses the Census Bureau Data API but is not endorsed or certified" in text
    assert "GeoNames" in text and "CC BY 4.0" in text
    assert (restricted.NOT_LEGAL_ADVICE in text) == (mode == "on")


def test_an_untitled_project_says_so() -> None:
    assert "Project: Untitled project" in lines(run(name=""))


def test_the_attestation_lists_the_filters_applied() -> None:
    a = run()
    r = filters.apply(a, [Rule("owner", ">=", 0.5), Rule("hh_kids", ">=", 115, "index")])
    text = lines(a, r)
    assert "Filters applied: Homeowners ≥ 50 %; Households with children, index ≥ 115" in text
    assert f"ZIPs matching: {len(r.qualifying)} of {len(r.matches)}" in text


def test_the_attestation_names_in_radius_mode() -> None:
    parsed = ParsedInput(
        zips=("33602", "33606"), overlaps={"33602": 50.0, "33606": 100.0}, source="zipcator"
    )
    a = an.analyze(ART, parsed, OFF)
    assert "Estimate mode: In-radius estimate (Zipcator overlap)" in lines(a)


def test_restricted_attestation_never_claims_a_filter() -> None:
    a = run(policy=ANSWERED)
    r = filters.apply(a, [])
    assert "Filters applied: none" in lines(a, r)


# --------------------------------------------------------------------- CSV
def csv_text(a: an.Analysis, result=None, **kw) -> str:  # type: ignore[no-untyped-def]
    return export.csv_text(a, result, now=NOW, version="1.2.3", **kw)


def test_the_plain_csv_quotes_zips_as_text_and_uses_crlf() -> None:
    text = csv_text(run())
    assert text.startswith('"Row type","ZIP","City","County","State"')
    assert '"02108"' in text and '"33602"' in text
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    assert not text.startswith(BOM)
    assert export.csv_bytes(run(), None, now=NOW, version="1.2.3")[:3] != b"\xef\xbb\xbf"


def test_the_excel_csv_has_a_bom_and_formula_wrapped_zips() -> None:
    a = run()
    raw = export.csv_bytes(a, None, excel=True, now=NOW, version="1.2.3")
    assert raw[:3] == b"\xef\xbb\xbf"
    text = raw.decode("utf-8-sig")
    assert '"=""02108"""' in text and '"=""33602"""' in text
    rows = table_of(text)
    assert rows[1][1] == '="33602"' or rows[1][1] == '="33602"'


def test_zips_keep_their_leading_zeros_in_both_variants_when_read_as_text() -> None:
    for excel in (False, True):
        text = csv_text(run(), excel=excel)
        skip = len(footer_of(text)) + 1  # the footer notes and the blank line before them
        frame = pd.read_csv(
            io.StringIO(text.lstrip(BOM)), dtype=str, skipfooter=skip, engine="python",
            keep_default_na=False,
        )  # fmt: skip
        zips = [z.strip('="') for z in frame["ZIP"] if z]
        assert zips == ["33602", "33606", "02108", "33603"]  # recognized, input order


def test_rows_are_zips_then_a_trade_area_row_then_a_benchmark_row() -> None:
    rows = table_of(csv_text(run()))
    types = [r[0] for r in rows[1:]]
    assert types == ["ZIP", "ZIP", "ZIP", "ZIP", "Trade area", "Benchmark"]
    assert rows[5][1] == "" and rows[6][1] == ""  # the ZIP column stays pure ZIPs
    assert "4 ZIPs" in rows[5][2] and "Florida" in rows[6][2]


def test_each_metric_has_value_moe_reliability_and_index_columns() -> None:
    a = run()
    rows = table_of(csv_text(a, metric_ids=["owner", "pop"]))
    head = rows[0]
    assert head[5:] == [
        "Homeowners (%)", "Homeowners MOE (pts)", "Homeowners reliability", "Homeowners index",
        "Population", "Population MOE", "Population reliability", "Population index",
    ]  # fmt: skip
    first = rows[1]
    assert first[5] == "40" and first[7] == "Reliable"
    assert first[9] == "5000" and first[11] == "Reliable"
    assert first[8] == "61" and first[12] == ""  # index 40 / 66 = 61; counts have none


def test_a_coded_median_is_written_from_its_bound_without_an_index() -> None:
    rows = table_of(csv_text(run(), metric_ids=["median_hh_income"]))
    coded = next(r for r in rows if r[1] == "33603")
    assert coded[5] == "250000+" and coded[6] == "" and coded[8] == ""
    assert coded[7] == "Use with caution"


def test_unknown_values_are_blank_not_zero() -> None:
    a = an.analyze(make_artifacts({"11111": Z(100, 50, income=None)}), parse_paste("11111"), OFF)
    rows = table_of(csv_text(a, metric_ids=["median_hh_income"]))
    assert rows[1][5:9] == ["", "", "Unreliable", ""]


def test_text_cells_are_defused_against_formula_injection() -> None:
    text = csv_text(run())
    assert "\"'=HYPERLINK(" in text
    for row in table_of(text)[1:]:
        for cell in row[2:5]:
            assert not cell.startswith(("=", "+", "-", "@"))


def test_defuse_handles_each_leading_character() -> None:
    for lead in "=+-@\t\r":
        assert export.defuse(f"{lead}x").startswith("'")
    assert export.defuse("Boston") == "Boston" and export.defuse("") == ""


def test_the_footer_follows_a_blank_line_as_single_note_cells() -> None:
    text = csv_text(run())
    assert "\r\n\r\n" in text
    foot = footer_of(text)
    assert foot and all(line.startswith("Note: ") for line in foot)
    assert any("Restricted mode: off" in line for line in foot)
    assert all(len(r) == 1 for r in list(csv.reader(io.StringIO(text)))[len(table_of(text)) + 1 :])


def test_the_table_round_trips_through_csv_and_pandas() -> None:
    text = csv_text(run())
    n_foot = len(footer_of(text))
    via_pandas = pd.read_csv(io.StringIO(text), dtype=str, skipfooter=n_foot + 1, engine="python",
                             keep_default_na=False)  # fmt: skip
    assert list(via_pandas.columns) == table_of(text)[0]
    assert len(via_pandas) == len(table_of(text)) - 1


def test_overlap_columns_appear_for_zipcator_input() -> None:
    parsed = ParsedInput(
        zips=("33602", "33606"), overlaps={"33602": 50.0, "33606": 100.0}, source="zipcator"
    )
    a = an.analyze(ART, parsed, OFF)
    rows = table_of(csv_text(a, metric_ids=["owner"]))
    head = rows[0]
    assert head[5:8] == ["Overlap %", "In-radius households", "In-radius population"]
    assert rows[1][5:8] == ["50", "1000", "2500"]
    assert rows[2][5:8] == ["100", "3500", "8000"]


def test_a_qualifies_column_appears_when_filters_are_active() -> None:
    a = run()
    r = filters.apply(a, [Rule("owner", ">=", 0.5)])
    rows = table_of(csv_text(a, r, metric_ids=["owner"]))
    assert rows[0][-1] == "Qualifies"
    got = {row[1]: row[-1] for row in rows[1:5]}
    assert got == {
        "33602": "No",
        "33606": "Yes",
        "02108": "Yes",
        "33603": "Yes (unreliable estimate)",
    }  # 33603: owner share is unreliable
    assert rows[5][-1] == "" and rows[6][-1] == ""
    assert "Qualifies" not in table_of(csv_text(a, None, metric_ids=["owner"]))[0]


def test_an_unreliable_qualifier_is_marked_in_the_qualifies_column() -> None:
    a = run()
    r = filters.apply(a, [Rule("owner", "<=", 0.6)])
    rows = table_of(csv_text(a, r, metric_ids=["owner"]))
    got = {row[1]: row[-1] for row in rows[1:5]}
    assert got["33603"] == "Yes (unreliable estimate)"


def test_restricted_csv_ignores_a_requested_order() -> None:
    a = run(policy=ANSWERED)
    rows = table_of(csv_text(a, order=("33603", "33602", "33606", "02108"), metric_ids=["pop"]))
    assert [r[1] for r in rows[1:5]] == ["33602", "33606", "02108", "33603"]


def test_an_unrestricted_csv_follows_a_requested_order() -> None:
    a = run()
    rows = table_of(csv_text(a, order=("33603", "33602", "33606", "02108"), metric_ids=["pop"]))
    assert [r[1] for r in rows[1:5]] == ["33603", "33602", "33606", "02108"]
    with pytest.raises(ValueError, match="order"):
        csv_text(a, order=("33603", "99999"))


def test_default_columns_follow_the_lens() -> None:
    a = run(policy=OFF, lens="Home services")
    head = table_of(csv_text(a))[0]
    assert "Population" in head and "Households" in head and "Median household income ($)" in head
    assert "Single-family homes (%)" in head or any("ingle" in h for h in head)


def test_coded_values_and_columns_are_explained_in_the_footer() -> None:
    foot = "\n".join(footer_of(csv_text(run())))
    assert "ending in +" in foot and "top-coded" in foot.lower()
