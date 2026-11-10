"""Random small trade areas through every output path: none may raise (owner request).

A scenario is 1-4 ZIPs with random populations (including zero and unknown), random shares, a
published median that may be missing or top/bottom coded, random registry cells knocked out
(all-null and partly-null metrics), wide and zero margins of error, an optional Zipcator overlap,
restricted mode on or off, a random lens, optional filter rules and an optional map. Every output
function the app and CLI use is then run on it. ``ALL_OUTPUTS`` is the one list to extend when a
new output path (the Phase 6 KPI, chart and map data functions) appears.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import geopandas as gpd
import numpy as np
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from shapely.geometry import box
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import charts, export, filters, lenses, metrics, report, table, ui, verticals
from zipographics.models import ParsedInput, Rule, UsePolicy
from zipographics.review import review_lines

NOW = datetime(2026, 11, 10, 14, 30, tzinfo=UTC)
POLICIES = [
    verticals.make_policy("Retail (general & specialty)", False),
    verticals.make_policy("Home services (HVAC, plumbing, roofing, pest, remodeling)", False),
    verticals.make_policy("Automotive sales", True),
    verticals.make_policy("Mortgage & lending", None),
]
VARS = list(metrics.VARIABLES)
FILTERABLE = ["owner", "hh_kids", "median_hh_income", "pop", "hh", "inc_75p", "median_age"]
ZIPS = ["33602", "33606", "02108", "00601", "59001", "10001", "94110"]


@dataclass(repr=False)
class Scenario:
    analysis: an.Analysis
    result: filters.FilterResult | None
    geo: gpd.GeoDataFrame | None
    entered: tuple[str, ...]

    def __repr__(self) -> str:  # a failing example must print small, not two dataframes
        a = self.analysis
        return (
            f"Scenario(zips={a.zips}, policy={a.policy.answer!r}, mode={a.mode}, lens={a.lens.name}, "
            f"rules={None if self.result is None else self.result.rules}, geo={self.geo is not None})"
        )


@st.composite
def scenarios(draw: st.DrawFn) -> Scenario:
    n = draw(st.integers(1, 4))
    zips = draw(st.permutations(ZIPS))[:n]
    world: dict[str, Z] = {}
    for z in zips:
        pop = draw(st.one_of(st.none(), st.integers(0, 60_000)))
        hh = draw(st.one_of(st.none(), st.integers(0, 25_000)))
        income = draw(st.one_of(st.none(), st.floats(2_499, 250_001, allow_nan=False)))
        code = draw(st.sampled_from(["none", "none", "top", "bottom"])) if income else "none"
        world[z] = Z(
            pop, hh,
            owner=draw(st.floats(0, 1)), kids=draw(st.floats(0, 1)),
            income=income, code=code,
            state="FL", county=("12057", "Hillsborough County"),
            rel_moe=draw(st.sampled_from([0.0, 0.05, 0.3, 1.5])),
        )  # fmt: skip
    art = make_artifacts(world)
    # knock out random registry cells: all-null and partly-null metrics
    holes = draw(st.lists(st.sampled_from(VARS), max_size=40, unique=True))
    for key in holes:
        rows = draw(st.lists(st.sampled_from(list(world)), max_size=len(world), unique=True))
        for z in rows:
            art.profile.loc[z, f"{key}_e"] = np.nan
            art.profile.loc[z, f"{key}_m"] = np.nan
    if draw(st.booleans()):  # and sometimes a null margin next to a real estimate
        key = draw(st.sampled_from(VARS))
        art.profile[f"{key}_m"] = np.nan

    policy: UsePolicy = draw(st.sampled_from(POLICIES))
    typed = list(world) + draw(st.lists(st.sampled_from(["99999", "12345", "abc"]), max_size=2))
    text = " ".join(typed)
    from zipographics.zips import parse_paste

    parsed = parse_paste(text)
    if draw(st.booleans()):  # a Zipcator-style overlap on some of the ZIPs
        overlaps = {z: draw(st.floats(0.5, 100.0)) for z in world if draw(st.booleans())}
        parsed = ParsedInput(
            zips=parsed.zips, overlaps=overlaps,
            blank_overlap=tuple(z for z in parsed.zips if z not in overlaps), source="zipcator",
        )  # fmt: skip
    lens = draw(st.sampled_from([lens.name for lens in lenses.LENSES if not lens.restricted_only]))
    try:
        a = an.analyze(
            art, parsed, policy,
            project_name=draw(st.sampled_from(["", "Acme", "=x"])), lens=lens,
        )  # fmt: skip
    except ValueError as exc:
        # the review's blocking conditions are not bugs: nothing to profile, no ZIP recognized
        blocked = "residential population" in str(exc) or "No ZIPs were recognized" in str(exc)
        assume(not blocked)  # discard blocked scenarios; any other ValueError is a real failure
        raise

    result = None
    if not a.restricted and draw(st.booleans()):
        rules = [
            Rule(
                draw(st.sampled_from(FILTERABLE)), draw(st.sampled_from([">=", "<="])),
                draw(st.floats(0, 1)), "value",
            )
            for _ in range(draw(st.integers(0, 3)))
        ]  # fmt: skip
        rules = [r for r in rules if metrics.BY_ID[r.metric].unit == "percent"]
        result = filters.apply(a, rules, exclude_unreliable=draw(st.booleans()))
    geo = None
    if draw(st.booleans()):
        shown = [z for z in world if draw(st.booleans())]
        geo = gpd.GeoDataFrame(
            {"zip": shown},
            geometry=[box(-82.5 + i, 27.9, -82.4 + i, 28.0) for i in range(len(shown))],
            crs="EPSG:4326",
        )  # fmt: skip
    return Scenario(a, result, geo, parsed.zips)


# ------------------------------------------------------------------ the output paths
def out_csv(s: Scenario) -> None:
    for excel in (False, True):
        text = export.csv_bytes(s.analysis, s.result, excel=excel, now=NOW, version="1").decode(
            "utf-8-sig"
        )
        rows = list(csv.reader(io.StringIO(text, newline="")))
        assert rows and rows[0][0] == "Row type"
        zips = [r[1].strip('="') for r in rows[1:] if r and r[0] == "ZIP"]
        assert zips == list(s.analysis.zips)  # one row per recognized ZIP, input order
        if s.analysis.restricted:
            assert "Qualifies" not in rows[0] and not any("index" in h for h in rows[0])


def out_csv_all_metrics(s: Scenario) -> None:
    export.csv_text(s.analysis, s.result, metric_ids=[m.id for m in metrics.REGISTRY],
                    now=NOW, version="1")  # fmt: skip


def out_report(s: Scenario) -> None:
    page = report.render(s.analysis, s.result, geo=s.geo, now=NOW, version="1")
    assert page.startswith("<!doctype html>") and "<script" not in page
    assert ("Restricted mode is on." in page) == s.analysis.restricted


def out_zip_list(s: Scenario) -> None:
    a = s.analysis
    for style in ("comma", "newline"):
        text = export.zip_list(
            a, qualifying=None if s.result is None else s.result.qualifying, style=style
        )  # type: ignore[arg-type]
        assert text == "" or all(len(z) == 5 for z in text.replace(",", " ").split())
        if a.restricted:
            assert text == (", " if style == "comma" else "\n").join(a.parsed.zips)
    export.attestation(a, s.result, now=NOW, version="1")


def out_review(s: Scenario) -> None:
    assert review_lines(s.analysis.summary)


def out_tables(s: Scenario) -> None:
    a = s.analysis
    assert table.order(a, "input") == a.zips and table.order(a, "zip")
    if not a.restricted:
        for m in metrics.REGISTRY:
            table.order(a, m.id)
            if m.indexable:
                table.order(a, m.id, index=True, descending=True)


def out_kpis_and_formatting(s: Scenario) -> None:
    a = s.analysis
    for mid in a.lens.all_kpis:
        m = metrics.BY_ID[mid]
        v = a.trade.values[mid]
        ui.fmt_value(m, v), ui.fmt_moe(m, v), ui.fmt_index(a.index.get(mid))
        a.share_of_benchmark(mid) if not m.indexable else None
    for z in a.zips:
        for m in metrics.REGISTRY:
            ui.fmt_value(m, a.value(z, m.id))
    for m in metrics.REGISTRY:
        if m.indexable:
            a.zip_index(m.id)


def out_charts(s: Scenario) -> None:
    for d in (*charts.charts_for(s.analysis), *charts.more_demographics(s.analysis)):
        assert d.rows


ALL_OUTPUTS: list[Callable[[Scenario], None]] = [
    out_csv, out_csv_all_metrics, out_report, out_zip_list, out_review, out_tables,
    out_kpis_and_formatting, out_charts,
]  # fmt: skip


@settings(max_examples=40, deadline=None, suppress_health_check=list(HealthCheck))
@given(s=scenarios())
def test_no_output_path_raises_on_a_random_trade_area(s: Scenario) -> None:
    for fn in ALL_OUTPUTS:
        fn(s)


def test_the_property_covers_a_single_zip_and_every_policy_kind() -> None:
    # a cheap guard that the generator is not silently narrower than it looks
    assert len({p.restricted for p in POLICIES}) == 2 and len(ZIPS) >= 4
