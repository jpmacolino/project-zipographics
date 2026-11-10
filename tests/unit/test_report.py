"""The self-contained HTML summary report (SPEC 5.6 item 3, 5.7, 9.2)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html.parser import HTMLParser

import geopandas as gpd
import pytest
from shapely.geometry import box
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import filters, report, restricted, verticals
from zipographics.models import ParsedInput, Rule, UsePolicy
from zipographics.zips import parse_paste

OFF = verticals.make_policy("Home services (HVAC, plumbing, roofing, pest, remodeling)", False)
ANSWERED = verticals.make_policy("Automotive sales", True)
FORCED = verticals.make_policy("Mortgage & lending", None)
NOW = datetime(2026, 11, 10, 14, 30, tzinfo=UTC)

WORLD = {
    "33602": Z(5000, 2000, owner=0.40, kids=0.20),
    "33606": Z(8000, 3500, owner=0.70, kids=0.35),
    "33603": Z(900, 280, owner=0.55, kids=0.30, income=250_001, code="top",
               extra={"B25003_002": (154.0, 200.0)}),
}  # fmt: skip
ART = make_artifacts(WORLD)
GEO = gpd.GeoDataFrame(
    {"zip": ["33602", "33606", "33603"]},
    geometry=[box(-82.5, 27.9, -82.4, 28.0), box(-82.4, 27.9, -82.3, 28.0),
              box(-82.5, 28.0, -82.4, 28.1)],
    crs="EPSG:4326",
)  # fmt: skip


def render(policy: UsePolicy = OFF, rules=None, geo=GEO, name: str = "Acme HVAC", **kw) -> str:  # type: ignore[no-untyped-def]
    a = an.analyze(ART, parse_paste("33602 99999 33606 33603"), policy, project_name=name, **kw)
    result = filters.apply(a, rules or [], policy)
    return report.render(a, result, geo=geo, now=NOW, version="1.2.3")


class Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attrs: list[tuple[str, str, str | None]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):  # type: ignore[no-untyped-def]
        self.tags.append(tag)
        for k, v in attrs:
            self.attrs.append((tag, k, v))

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def parse(html: str) -> Tags:
    p = Tags()
    p.feed(html)
    p.close()
    return p


def test_the_report_is_one_well_formed_html_document() -> None:
    html = render()
    assert html.startswith("<!doctype html>") and html.rstrip().endswith("</html>")
    p = parse(html)
    assert {"html", "head", "body", "title", "h1", "table", "svg", "footer"} <= set(p.tags)
    assert html.count("<html") == 1


def test_it_has_no_scripts_no_external_resources_and_no_fonts() -> None:
    html = render()
    p = parse(html)
    assert "script" not in p.tags and "iframe" not in p.tags and "link" not in p.tags
    assert "@import" not in html and "@font-face" not in html
    assert not re.search(r"url\((?!#)", html)  # only local fragment references
    resource_attrs = [
        (t, k, v) for t, k, v in p.attrs if k in ("src", "href", "data", "srcset", "xlink:href")
    ]
    for tag, attr, value in resource_attrs:
        assert tag == "a" or (value or "").startswith("#"), (tag, attr, value)
    # the only http(s) text is in the sources links
    outside = re.sub(r'<section id="sources".*?</section>', "", html, flags=re.S)
    assert "http://" not in outside and "https://" not in outside


def test_a_print_stylesheet_is_included() -> None:
    html = render()
    assert ("@media print" in html and "page-break" in html) or "break-before" in html


def test_title_date_industry_benchmark_and_mode() -> None:
    p = parse(render())
    text = " ".join(p.text)
    assert "Acme HVAC" in text and "2026-11-10" in text
    assert "Home services (HVAC, plumbing, roofing, pest, remodeling)" in text
    assert "Florida" in text and "Full ZIPs" in text and "ACS 2020-2024 5-year estimates" in text
    assert "<title>Acme HVAC" in render()


def test_an_untitled_project_says_so_in_the_title() -> None:
    assert "<title>Untitled project" in render(name="")


def test_the_project_name_is_escaped() -> None:
    html = render(name="<script>alert(1)</script> & Co")
    assert "<script>" not in html and "&lt;script&gt;" in html and "&amp; Co" in html


def test_kpi_cards_show_value_moe_index_and_a_reliability_marker() -> None:
    html = render()
    assert 'class="kpi' in html
    for label in ("Households", "Population", "Median household income", "Homeowners",
                  "Households with children", "Single-family"):  # fmt: skip
        assert label in html
    assert "Index " in html and "vs Florida" in html
    assert "of Florida" in html  # counts show their share of the benchmark total
    assert "\N{PLUS-MINUS SIGN}" in html


def test_the_report_has_the_core_charts_and_the_lens_chart_as_inline_svg() -> None:
    html = render()
    assert html.count("<svg") >= 6  # four core + units in structure + map
    for title in (
        "Household income",
        "Age",
        "Owner vs renter",
        "Age of housing",
        "Units in structure",
    ):
        assert title in html
    assert "Trade area" in html and "Florida" in html


def test_the_zip_table_has_every_recognized_zip_and_the_summary_rows() -> None:
    html = render()
    for z in ("33602", "33606", "33603"):
        assert f">{z}<" in html
    assert ">99999<" not in html.split('id="table"')[1].split("</table>")[0]
    assert "Trade area" in html and "Benchmark" in html
    assert "$250,000+" in html  # a coded median from its bound
    assert "\N{DAGGER}" in html  # an unreliable cell


def test_the_map_is_inline_svg_or_an_explained_placeholder() -> None:
    assert '<section id="map"' in render()
    placeholder = render(geo=None)
    assert "map is unavailable" in placeholder.lower()


def test_unrestricted_filters_are_listed_and_matching_zips_are_marked() -> None:
    html = render(rules=[Rule("owner", ">=", 0.5)])
    assert 'id="filters"' in html
    assert "Homeowners ≥ 50 %" in html
    assert "2 of 3 ZIPs match" in html and "households:" in html
    assert 'class="match"' in html


def test_without_filters_the_filter_section_is_absent() -> None:
    assert 'id="filters"' not in render()


@pytest.mark.parametrize("policy", [ANSWERED, FORCED])
def test_restricted_report_has_the_banner_and_no_filter_state(policy: UsePolicy) -> None:
    a = an.analyze(ART, parse_paste("33602 33606 33603"), policy, project_name="Acme")
    html = report.render(a, filters.apply(a, [], policy), geo=GEO, now=NOW, version="1.2.3")
    assert restricted.BANNER_TITLE in html and "can't be ranked, filtered or selected" in html
    assert 'id="filters"' not in html and 'class="match"' not in html
    assert "Qualifies" not in html and "\N{CHECK MARK}" not in html
    assert html.index("33602") < html.index("33606") < html.index("33603")  # input order
    assert "Restricted mode: on" in html


def test_restricted_report_cannot_be_given_filters() -> None:
    a = an.analyze(ART, parse_paste("33602 33606"), OFF, project_name="x")
    result = filters.apply(a, [Rule("owner", ">=", 0.5)], OFF)
    restricted_a = an.analyze(ART, parse_paste("33602 33606"), ANSWERED, project_name="x")
    with pytest.raises(restricted.RestrictedUseError):
        report.render(restricted_a, result, geo=GEO, now=NOW, version="1.2.3")


def test_the_unrestricted_banner_is_absent() -> None:
    assert restricted.BANNER_TITLE not in render()


def test_the_footer_carries_the_whole_attestation() -> None:
    html = render()
    foot = html.split("<footer")[1]
    needles = [
        "Project: Acme HVAC", "Answer: No", "Restricted mode: off", "Benchmark: Florida (state)",
        "Filters applied: none", "Generated: 2026-11-10 14:30 UTC by Zipographics 1.2.3",
        "not endorsed or certified by the Census Bureau", "GeoNames",
    ]  # fmt: skip
    for needle in needles:
        assert needle in foot, needle


def test_the_restricted_report_footer_records_forced_and_answered() -> None:
    assert "Answer: Yes (set by industry)" in render(FORCED)
    assert "Answer: Yes" in render(ANSWERED) and "Answer: Yes (set by" not in render(ANSWERED)


def test_data_notes_cover_reliability_coding_and_the_input_summary() -> None:
    html = render()
    section = html.split('id="notes"')[1]
    assert "margin of error" in section.lower() and "\N{DAGGER}" in section
    assert "ending in +" in section or "top-coded" in section.lower()
    assert "1 not found" in html  # the input summary from the review lines
    assert "ZIP = Census ZCTA" in html


def test_in_radius_columns_appear_for_zipcator_input() -> None:
    parsed = ParsedInput(
        zips=("33602", "33606"), overlaps={"33602": 50.0, "33606": 100.0}, source="zipcator"
    )
    a = an.analyze(ART, parsed, OFF, project_name="Z")
    html = report.render(a, filters.apply(a, [], OFF), geo=GEO, now=NOW, version="1.2.3")
    assert "In-radius estimate" in html and "In-radius households" in html and ">1,000<" in html


def test_the_report_is_deterministic_for_a_given_time() -> None:
    assert render() == render()


def test_a_large_input_renders_every_row_quickly() -> None:
    world = {
        f"{10000 + i:05d}": Z(1000 + i, 400 + i, owner=0.3 + (i % 50) / 100) for i in range(400)
    }
    art = make_artifacts(world)
    a = an.analyze(art, ParsedInput(zips=tuple(world)), OFF, project_name="Big")
    html = report.render(a, filters.apply(a, [], OFF), geo=None, now=NOW, version="1")
    assert html.count("<tr") >= 400
