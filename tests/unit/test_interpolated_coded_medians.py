"""An interpolated median in an open-ended bracket displays the same bound as a published one.

Phase 7 final review (M1): the API stores a coded median shifted by one from its bound (250,001 for
"$250,000+"), and ``stats.coded_bound`` undoes that. The interpolated median in the top bracket
returned the bound itself (200,000), so it displayed "$199,999+". It now stores bound + 1, the same
convention, so every coded value is shown and compared from its published bound.
"""

from __future__ import annotations

import pytest
from synth_frame import empty_frame

from zipographics import metrics, profile, ui

CASES = [
    ("median_hh_income", "$200,000+"),
    ("median_value", "$2,000,000+"),
    ("median_rent", "$3,500+"),
]


def frame_in_top_bracket(metric_id: str, zips: list[str]):  # type: ignore[no-untyped-def]
    spec = metrics.BY_ID[metric_id].spec
    assert isinstance(spec, metrics.MedianSpec)
    frame = empty_frame(zips)
    for bracket in spec.brackets:
        top = bracket is spec.brackets[-1]
        for key in bracket.keys:
            frame[f"{key}_e"] = 500.0 if top else 0.0
            frame[f"{key}_m"] = 50.0
    return frame


@pytest.mark.parametrize(("metric_id", "shown"), CASES)
def test_a_trade_area_median_in_the_top_bracket_displays_its_published_bound(
    metric_id: str, shown: str
) -> None:
    zips = ["10001", "10002"]
    trade = profile.build_profile(
        frame_in_top_bracket(metric_id, zips), zips, metric_ids=[metric_id]
    )
    v = trade.values[metric_id]
    assert v.code == "top" and v.source == "interpolated" and v.moe is None
    assert ui.fmt_value(metrics.BY_ID[metric_id], v) == shown


@pytest.mark.parametrize(("metric_id", "shown"), CASES)
def test_the_interpolated_and_the_published_coded_value_use_one_convention(
    metric_id: str, shown: str
) -> None:
    published = {"median_hh_income": 250_001.0, "median_value": 2_000_001.0, "median_rent": 3_501.0}
    zips = ["10001", "10002"]
    v = profile.build_profile(
        frame_in_top_bracket(metric_id, zips), zips, metric_ids=[metric_id]
    ).values[metric_id]
    spec = metrics.BY_ID[metric_id].spec
    assert isinstance(spec, metrics.MedianSpec)
    assert v.estimate == spec.brackets[-1].lo + 1  # stored like the API stores a coded median
    assert v.estimate - 1 == {"median_hh_income": 200_000, "median_value": 2_000_000,
                              "median_rent": 3_500}[metric_id]  # fmt: skip
    assert published[metric_id] - 1 >= v.estimate - 1  # the published bound is never below this one


def test_a_median_that_is_not_in_the_top_bracket_is_unchanged() -> None:
    zips = ["10001", "10002"]
    frame = frame_in_top_bracket("median_hh_income", zips)
    spec = metrics.BY_ID["median_hh_income"].spec
    assert isinstance(spec, metrics.MedianSpec)
    for bracket in spec.brackets:  # all households in the $50-60k bracket instead
        for key in bracket.keys:
            frame[f"{key}_e"] = 500.0 if (bracket.lo, bracket.hi) == (50_000, 60_000) else 0.0
    v = profile.build_profile(frame, zips, metric_ids=["median_hh_income"]).values[
        "median_hh_income"
    ]
    assert v.code == "none" and v.estimate == pytest.approx(55_000)


def test_the_trade_area_card_and_csv_show_the_bound(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from synth_art import Z, make_artifacts

    from zipographics import analysis, export, kpis, verticals
    from zipographics.zips import parse_paste

    top = {f"B19001_{k:03d}": (0.0, 0.0) for k in range(2, 17)} | {"B19001_017": (1000.0, 80.0)}
    art = make_artifacts({"33602": Z(5000, 1000, extra=top), "33606": Z(8000, 1000, extra=top)})
    a = analysis.analyze(
        art,
        parse_paste("33602 33606"),
        verticals.make_policy("Retail (general & specialty)", False),
    )
    card = next(c for c in kpis.cards(a) if c.metric_id == "median_hh_income")
    assert card.value == "$200,000+" and card.index is None
    text = export.csv_text(
        a, None, metric_ids=["median_hh_income"], now=datetime(2026, 1, 1, tzinfo=UTC), version="1"
    )
    trade_row = next(line for line in text.splitlines() if line.startswith('"Trade area"'))
    assert '"200000+"' in trade_row
