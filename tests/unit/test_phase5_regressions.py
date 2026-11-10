"""Regression tests from the independent Phase 5 QA review (docs/QA_REPORT.md, Phase 5)."""

from __future__ import annotations

import dataclasses
import io
from datetime import UTC, datetime

import geopandas as gpd
import pytest
from shapely.geometry import box
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import cli, export, filters, lenses, report, restricted, table, verticals
from zipographics.errors import RestrictedUseError
from zipographics.models import ParsedInput, Rule, UsePolicy
from zipographics.zips import parse_paste

OFF = verticals.make_policy("Retail (general & specialty)", False)
ANSWERED = verticals.make_policy("Automotive sales", True)
FORCED = verticals.make_policy("Insurance", None)
#: an unrestricted-looking policy for a restricted vertical (a caller that forgot the lock)
LIAR = UsePolicy(False, "Insurance", "No")
NOW = datetime(2026, 11, 10, 14, 30, tzinfo=UTC)

WORLD = {
    "33602": Z(5000, 2000, owner=0.40, kids=0.20),
    "33606": Z(8000, 3500, owner=0.70, kids=0.35),
    "33603": Z(900, 280, owner=0.55, kids=0.30, extra={"B25003_002": (154.0, 200.0)}),
}
ART = make_artifacts(WORLD)
GEO = gpd.GeoDataFrame(
    {"zip": list(WORLD)},
    geometry=[box(-82.5, 27.9, -82.4, 28.0), box(-82.4, 27.9, -82.3, 28.0),
              box(-82.5, 28.0, -82.4, 28.1)],
    crs="EPSG:4326",
)  # fmt: skip


def run(policy: UsePolicy = OFF, text: str = "33602 33606 33603", **kw):  # type: ignore[no-untyped-def]
    return an.analyze(ART, parse_paste(text), policy, project_name="Acme", **kw)


# ------------------------------------------------------------ 3: the Analysis's own policy counts
def test_a_policy_that_disagrees_with_a_restricted_analysis_cannot_unlock_filters() -> None:
    a = run(FORCED)
    with pytest.raises(RestrictedUseError):
        filters.apply(a, [Rule("owner", ">=", 0.6)], OFF)


def test_a_policy_that_disagrees_with_a_restricted_analysis_cannot_unlock_ordering() -> None:
    a = run(ANSWERED)
    with pytest.raises(RestrictedUseError):
        table.order(a, "owner", OFF)
    assert table.order(a, "input", OFF) == a.zips


def test_a_policy_that_disagrees_with_a_restricted_analysis_cannot_unlock_the_zip_list() -> None:
    a = run(FORCED)
    assert export.zip_list(a, OFF, qualifying=("33606",)) == "33602, 33606, 33603"


def test_a_policy_that_disagrees_with_a_restricted_analysis_cannot_unlock_the_csv() -> None:
    a = run(FORCED)
    unrestricted = run(OFF)
    result = filters.apply(unrestricted, [Rule("owner", ">=", 0.6)], OFF)
    with pytest.raises(RestrictedUseError):
        export.csv_text(a, OFF, result, now=NOW, version="1")
    text = export.csv_text(a, OFF, None, order=("33603", "33602", "33606"), now=NOW, version="1")
    header = text.splitlines()[0]
    assert "index" not in header and "Qualifies" not in header  # still the locked layout
    assert text.index("33602") < text.index("33606") < text.index("33603")  # input order kept


def test_a_restricted_vertical_cannot_be_given_an_unrestricted_policy() -> None:
    # UsePolicy(False, "Insurance", "No") is a caller bug; every guard treats it as restricted
    assert restricted.is_restricted(LIAR)
    assert restricted.is_restricted(None)
    assert not restricted.is_restricted(OFF)
    assert restricted.is_restricted(OFF, FORCED)  # any restricted policy wins
    assert [lens.name for lens in lenses.available(LIAR)] == ["Context"]
    assert lenses.presets_for("Retail", LIAR) == []
    assert lenses.resolve("Retail", LIAR).name == "Context"
    with pytest.raises(RestrictedUseError):
        lenses.preset("Renters", LIAR)
    with pytest.raises(RestrictedUseError):
        filters.apply(run(OFF), [Rule("owner", ">=", 0.6)], LIAR)
    assert export.zip_list(run(OFF), LIAR, qualifying=("33606",)) == "33602, 33606, 33603"


def test_an_unknown_vertical_is_not_assumed_restricted_by_name() -> None:
    assert not restricted.is_restricted(UsePolicy(False, "Something else", "No"))
    assert not restricted.is_restricted(UsePolicy(False, None, "No"))


# ------------------------------------------------------------ restricted survivors (mutants)
def test_the_restricted_attestation_never_lists_filters_even_if_handed_a_result() -> None:
    result = filters.apply(run(OFF), [Rule("owner", ">=", 0.6)], OFF)
    lines = export.attestation(run(ANSWERED), result, now=NOW, version="1")
    assert "Filters applied: none" in lines
    assert not any(line.startswith("ZIPs matching") for line in lines)


def test_the_zip_list_keeps_input_order_even_when_the_subset_is_given_out_of_order() -> None:
    a = run()
    assert export.zip_list(a, OFF, qualifying=("33603", "33602")) == "33602, 33603"


def test_the_restricted_report_ignores_a_requested_order_and_draws_a_neutral_map() -> None:
    a = run(ANSWERED)
    page = report.render(a, None, geo=GEO, now=NOW, version="1", order=("33603", "33606", "33602"))
    assert page.index(">33602<") < page.index(">33606<") < page.index(">33603<")
    assert "one neutral fill" in page
    assert "Blues" not in page and "#08306b" not in page.lower()
    # no legend title (the metric name) is drawn on a neutral map
    svg = page.split('id="map"')[1].split("</section>")[0]
    assert "Median age" not in svg and "Homeowners" not in svg and " to " not in svg


def test_the_unrestricted_report_honours_a_requested_order() -> None:
    a = run(OFF)
    page = report.render(a, None, geo=None, now=NOW, version="1", order=("33603", "33606", "33602"))
    assert page.index(">33603<") < page.index(">33606<") < page.index(">33602<")


# ------------------------------------------------------------ 7: filter boundaries
def test_a_value_exactly_at_the_threshold_qualifies_for_both_comparisons() -> None:
    a = run(OFF)
    at = float(a.value("33602", "pop").estimate)  # exactly 5,000
    assert "33602" in filters.apply(a, [Rule("pop", ">=", at)], OFF).qualifying
    assert "33602" in filters.apply(a, [Rule("pop", "<=", at)], OFF).qualifying
    assert "33602" not in filters.apply(a, [Rule("pop", ">=", at + 1)], OFF).qualifying
    assert "33602" not in filters.apply(a, [Rule("pop", "<=", at - 1)], OFF).qualifying


def test_an_index_exactly_at_the_threshold_qualifies() -> None:
    a = run(OFF)
    idx = a.zip_index("owner")[0].value  # 33602: round(100 * 0.40 / 0.66) = 61
    assert idx == 61
    assert "33602" in filters.apply(a, [Rule("owner", ">=", 61, "index")], OFF).qualifying
    assert "33602" in filters.apply(a, [Rule("owner", "<=", 61, "index")], OFF).qualifying
    assert "33602" not in filters.apply(a, [Rule("owner", ">=", 62, "index")], OFF).qualifying


CODED = make_artifacts({"99001": Z(4000, 1500, income=250_001, code="top"),
                        "99002": Z(3000, 1000, income=2_499, code="bottom")})  # fmt: skip


def run_coded():  # type: ignore[no-untyped-def]
    return an.analyze(CODED, parse_paste("99001 99002"), OFF)


@pytest.mark.parametrize(
    ("op", "value", "qualifies"),
    [(">=", 250_000, True), (">=", 250_001, False), (">=", 249_999, True)],
)
def test_a_top_coded_median_is_compared_from_its_bound_not_its_stored_value(
    op: str, value: float, qualifies: bool
) -> None:
    a = run_coded()
    got = filters.apply(a, [Rule("median_hh_income", op, value)], OFF)  # type: ignore[arg-type]
    assert ("99001" in got.qualifying) is qualifies


@pytest.mark.parametrize(
    ("op", "value", "qualifies"), [("<=", 2_500, True), ("<=", 2_499, False), ("<=", 2_501, True)]
)
def test_a_bottom_coded_median_is_compared_from_its_bound_not_its_stored_value(
    op: str, value: float, qualifies: bool
) -> None:
    got = filters.apply(run_coded(), [Rule("median_hh_income", op, value)], OFF)  # type: ignore[arg-type]
    assert ("99002" in got.qualifying) is qualifies


def test_a_coded_median_that_cannot_be_decided_is_uncertain_in_both_directions() -> None:
    a = run_coded()
    # "$250,000+" might be 300,000 or more: not a miss, uncertain
    r = filters.apply(a, [Rule("median_hh_income", ">=", 300_000)], OFF)
    assert "99001" not in r.qualifying and r.matches["99001"].uncertain == ("median_hh_income",)
    # "$250,000+" is certainly not at or below 200,000
    r = filters.apply(a, [Rule("median_hh_income", "<=", 200_000)], OFF)
    assert r.matches["99001"].uncertain == ()
    # "$2,500 or less" may be under 1,000: uncertain for ">= 1,000", a certain miss for ">= 3,000"
    r = filters.apply(a, [Rule("median_hh_income", ">=", 1_000)], OFF)
    assert r.matches["99002"].uncertain == ("median_hh_income",)
    r = filters.apply(a, [Rule("median_hh_income", ">=", 3_000)], OFF)
    assert r.matches["99002"].uncertain == ()
    r = filters.apply(a, [Rule("median_hh_income", "<=", 1_000)], OFF)
    assert "99002" not in r.qualifying and r.matches["99002"].uncertain == ("median_hh_income",)


def test_the_per_zip_index_tier_is_the_worse_of_the_zip_and_the_benchmark() -> None:
    a = run(OFF)
    good = a.zip_index("owner")[0]
    assert good.tier == "good"
    bad_bench = a.bench.values["owner"].__class__(
        "owner", 0.66, 0.60, "unreliable", "none", False, "published"
    )
    values = {**a.bench.values, "owner": bad_bench}
    worse = dataclasses.replace(a, bench=dataclasses.replace(a.bench, values=values))
    assert worse.zip_index("owner")[0].tier == "unreliable"


def test_an_index_rule_that_passes_on_an_unreliable_index_is_flagged() -> None:
    a = run(OFF)
    # 33603's owner share is unreliable, so its index is too
    r = filters.apply(a, [Rule("owner", ">=", 50, "index")], OFF)
    assert "33603" in r.qualifying and r.matches["33603"].on_unreliable
    r2 = filters.apply(a, [Rule("owner", ">=", 50, "index")], OFF, exclude_unreliable=True)
    assert "33603" not in r2.qualifying


# ------------------------------------------------------------ 4: performance (cached index columns)
def test_the_index_column_is_computed_once_per_metric() -> None:
    a = run(OFF)
    assert a.zip_index("owner") is a.zip_index("owner")


def test_a_thousand_zip_csv_and_filter_are_fast() -> None:
    import time

    world = {
        f"{10000 + i:05d}": Z(1000 + i, 400 + i, owner=0.3 + (i % 50) / 100) for i in range(1000)
    }
    a = an.analyze(make_artifacts(world), ParsedInput(zips=tuple(world)), OFF, project_name="Big")
    start = time.perf_counter()
    r = filters.apply(
        a, [Rule("owner", ">=", 100, "index"), Rule("hh_kids", ">=", 90, "index")], OFF
    )
    text = export.csv_text(a, OFF, r, now=NOW, version="1")
    assert time.perf_counter() - start < 3.0 and len(text) > 1000


# ---------------------------------------------------- 5: blank overlap = full ZIP everywhere
def test_a_blank_overlap_zip_is_shown_as_a_full_zip_in_the_columns_too() -> None:
    parsed = ParsedInput(zips=("33602", "33606"), overlaps={"33602": 50.0},
                         blank_overlap=("33606",), source="zipcator")  # fmt: skip
    a = an.analyze(ART, parsed, OFF, project_name="Z")
    assert a.in_radius("33606", "hh") == pytest.approx(3500)
    assert a.overlap_pct("33606") == 100.0 and a.overlap_pct("33602") == 50.0
    text = export.csv_text(a, OFF, None, metric_ids=["owner"], now=NOW, version="1")
    row = next(line for line in text.splitlines() if '"33606"' in line)
    assert '"ZIP","33606"' in row and ",100,3500,8000," in row
    page = report.render(a, None, geo=None, now=NOW, version="1")
    assert ">3,500<" in page
    total = sum(a.in_radius(z, "hh") or 0 for z in a.zips)
    assert total == pytest.approx(a.trade.values["hh"].estimate)


def test_an_unknown_estimate_mode_is_an_error() -> None:
    with pytest.raises(ValueError, match="mode"):
        run(mode="typo")  # type: ignore[arg-type]


# ------------------------------------------------------------ 1-2: the report map
def render_map(art, text: str, geo=GEO, policy: UsePolicy = OFF, **kw) -> str:  # type: ignore[no-untyped-def]
    a = an.analyze(art, parse_paste(text), policy, project_name="Map")
    return report.render(a, None, geo=geo, now=NOW, version="1", **kw)


def has_map(page: str) -> bool:
    section = page.split('id="map"')[1].split("</section>")[0]
    return "<svg" in section and "map is unavailable" not in section


def test_a_single_zip_report_with_a_map_does_not_crash() -> None:
    page = render_map(ART, "33602", map_metric="owner")
    assert has_map(page)


def test_zips_that_all_have_the_same_map_value_render() -> None:
    world = {z: Z(1000, 400, owner=0.5) for z in ("33602", "33606", "33603")}
    page = render_map(make_artifacts(world), "33602 33606 33603", map_metric="owner")
    assert has_map(page)


def test_a_zip_with_no_value_for_the_map_metric_is_drawn_neutral_not_a_crash() -> None:
    world = {"33602": Z(5000, 2000, owner=0.4), "33606": Z(None, None), "33603": Z(900, 280)}
    page = render_map(make_artifacts(world), "33602 33606 33603", map_metric="owner")
    assert has_map(page)


def test_every_zip_without_a_value_renders_a_neutral_map() -> None:
    world = {"33602": Z(None, None), "33606": Z(None, None), "33603": Z(None, None)}
    page = render_map(make_artifacts(world), "33602 33606 33603", map_metric="owner")
    assert "<svg" in page


def test_the_map_never_shades_by_a_top_coded_value_as_if_it_were_exact() -> None:
    world = {"33602": Z(5000, 2000, income=250_001, code="top"),
             "33606": Z(8000, 3500, income=80_000),
             "33603": Z(900, 280, income=60_000)}  # fmt: skip
    page = render_map(make_artifacts(world), "33602 33606 33603", map_metric="median_hh_income")
    svg = page.split('id="map"')[1].split("</section>")[0]
    assert "250,001" not in svg and "250001" not in svg


def test_dollar_legend_labels_are_not_eaten_by_mathtext() -> None:
    world = {"33602": Z(5000, 2000, income=40_000), "33606": Z(8000, 3500, income=80_000),
             "33603": Z(900, 280, income=60_000)}  # fmt: skip
    page = render_map(make_artifacts(world), "33602 33606 33603", map_metric="median_hh_income")
    svg = page.split('id="map"')[1].split("</section>")[0]
    assert "$40,000" in svg and "$80,000" in svg


def test_the_map_caption_has_no_double_period() -> None:
    assert ".." not in render_map(ART, "33602 33606", policy=ANSWERED)
    assert ".." not in render_map(ART, "33602 33606")


# ------------------------------------------------------------ low items fixed
def test_the_project_name_is_cleaned_in_the_library() -> None:
    a = run(OFF)
    messy = an.analyze(ART, parse_paste("33602"), OFF, project_name="Line one\nLine\ttwo ‮ x")
    assert messy.project_name == "Line one Line two x"
    long = an.analyze(ART, parse_paste("33602"), OFF, project_name="a" * 200)
    assert long.project_name == "a" * 80
    assert a.project_name == "Acme"
    assert an.analyze(ART, parse_paste("33602"), OFF, project_name=" \n ").project_name is None
    text = export.csv_text(messy, OFF, None, now=NOW, version="1")
    assert "Note: Project: Line one Line two x" in text


def test_file_names_drop_bidi_override_characters() -> None:
    assert export.file_stem("abc‮def") == "abcdef"


def test_csv_metric_ids_are_validated() -> None:
    a = run(OFF)
    with pytest.raises(ValueError, match="Unknown metric"):
        export.csv_text(a, OFF, None, metric_ids=["nope"], now=NOW, version="1")
    with pytest.raises(ValueError, match="twice"):
        export.csv_text(a, OFF, None, metric_ids=["owner", "owner"], now=NOW, version="1")


def test_share_moe_columns_say_they_are_percentage_points() -> None:
    a = run(OFF)
    header = export.csv_text(a, OFF, None, metric_ids=["owner", "pop"], now=NOW, version="1")
    head = header.splitlines()[0]
    assert '"Homeowners MOE (pts)"' in head and '"Population MOE"' in head


# ------------------------------------------------------------ CLI low items
def cli_run(argv, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli, "_load", lambda data_dir: ART)
    out, err = io.StringIO(), io.StringIO()
    return cli.main(argv, out=out, err=err, now=NOW), out.getvalue(), err.getvalue()


def test_an_unknown_lens_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    base = ["profile", "33602", "--vertical", "Retail (general & specialty)", "--restricted", "no"]
    code, _, err = cli_run([*base, "--lens", "Astrology"], monkeypatch)
    assert code == 2 and "lens" in err.lower()
    code, _, err = cli_run([*base, "--lens", "Context"], monkeypatch)
    assert code == 2 and "restricted" in err.lower()


def test_a_no_answer_for_a_restricted_vertical_is_noted(monkeypatch: pytest.MonkeyPatch) -> None:
    code, out, _ = cli_run(
        ["profile", "33602", "--vertical", "Insurance", "--restricted", "no"], monkeypatch
    )
    assert code == 0 and "always counts as restricted use" in out


def test_positional_zips_missing_from_a_zipcator_file_are_listed_as_full_zips(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    f = tmp_path / "z.csv"
    crlf = chr(13) + chr(10)
    f.write_bytes(
        crlf.join(['"ZIP","Overlap %","Contains address"', '"33602",50.0,"Yes"']).encode()
    )
    code, out, _ = cli_run(
        ["profile", "33606", "--file", str(f), "--vertical", "Retail (general & specialty)",
         "--restricted", "no"], monkeypatch)  # fmt: skip
    assert code == 0 and "1 ZIP has no overlap value" in out and "33606" in out
