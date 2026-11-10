"""SPEC 7 performance budgets on the real data (markers ``slow`` and data): run with
``uv run pytest -m slow -s`` (the timings are printed and copied into docs/QA_REPORT.md)."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pandas as pd
import pytest

from zipographics import analysis, config, data, export, filters, mapview, report, review, verticals
from zipographics.zips import parse_paste

pytestmark = pytest.mark.slow
HOME = verticals.make_policy("Home services (HVAC, plumbing, roofing, pest, remodeling)", False)
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

if not (config.data_dir() / "zcta_profile.parquet").exists():  # pragma: no cover
    pytest.skip("data/ has not been built", allow_module_level=True)


@pytest.fixture(scope="module")
def art() -> data.Artifacts:
    return data.load(config.data_dir())


@pytest.fixture(scope="module")
def thousand(art: data.Artifacts) -> list[str]:
    pop = art.profile["B01003_001_e"]
    return list(pop[pop > 0].sample(1000, random_state=11).index)


def timed(fn):  # type: ignore[no-untyped-def]
    start = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - start


def test_data_load_is_within_three_seconds(capsys: pytest.CaptureFixture[str]) -> None:
    _, secs = timed(lambda: data.load(config.data_dir()))
    with capsys.disabled():
        print(f"\n  data load {secs:.2f} s (budget 3 s)")
    assert secs <= 3.0


def test_parsing_and_reviewing_a_thousand_real_zips_is_within_half_a_second(
    art: data.Artifacts, thousand: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    facts = data.facts_from_profile(art.profile)
    text = ", ".join(
        z.lstrip("0") for z in thousand
    )  # Excel-mangled: every leading-zero ZIP repaired

    def run() -> int:
        s = review.summarize(parse_paste(text), facts, policy=HOME)
        return len(review.review_lines(s))

    _, secs = timed(run)
    with capsys.disabled():
        print(f"\n  parse + review of 1,000 ZIPs {secs:.3f} s (budget 0.5 s)")
    assert secs <= 0.5


def test_profile_indexes_and_table_for_a_thousand_zips_are_within_a_second(
    art: data.Artifacts, thousand: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    parsed = parse_paste(" ".join(thousand))
    a, secs = timed(lambda: analysis.analyze(art, parsed, HOME))
    with capsys.disabled():
        print(f"  analysis (trade area, indexes, table), 1,000 ZIPs {secs:.2f} s (budget 1 s)")
    assert len(a.zips) == 1000 and secs <= 1.0


def test_map_preparation_for_a_thousand_zips_is_within_a_second(
    art: data.Artifacts, thousand: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    a = analysis.analyze(art, parse_paste(" ".join(thousand)), HOME)
    layer, secs = timed(lambda: mapview.layer(a, "owner", None, art.geo))
    assert layer is not None
    size = len(str(layer.geojson)) / 1e6
    with capsys.disabled():
        print(f"\n  map layer (GeoJSON, {size:.1f} MB), 1,000 ZIPs {secs:.2f} s (budget 1 s)")
    assert secs <= 1.0


def test_the_summary_report_for_a_thousand_zips_is_within_five_seconds(
    art: data.Artifacts, thousand: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    a = analysis.analyze(art, parse_paste(" ".join(thousand)), HOME)
    result = filters.apply(a, [])
    html, secs = timed(lambda: report.render(a, result, geo=art.geo, now=NOW, version="1"))
    with capsys.disabled():
        print(f"\n  summary report, 1,000 ZIPs {secs:.2f} s, {len(html) / 1e6:.1f} MB (budget 5 s)")
    assert secs <= 5.0


def test_csv_exports_for_a_thousand_zips_are_quick(
    art: data.Artifacts, thousand: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    a = analysis.analyze(art, parse_paste(" ".join(thousand)), HOME)
    ids = [m for m in pd.Series(a.lens.columns)]
    _, secs = timed(lambda: export.csv_bytes(a, None, metric_ids=ids, now=NOW, version="1"))
    with capsys.disabled():
        print(f"\n  CSV for 1,000 ZIPs {secs:.2f} s")
    assert secs <= 2.0
