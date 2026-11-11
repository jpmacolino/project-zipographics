"""KPI card data shared by the app, the report and the CLI (SPEC 5.5)."""

from __future__ import annotations

from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import kpis, ui, verticals
from zipographics.zips import parse_paste

OFF = verticals.make_policy("Home services (HVAC, plumbing, roofing, pest, remodeling)", False)
FORCED = verticals.make_policy("Insurance", None)
WORLD = {
    "33602": Z(5000, 2000, owner=0.40, kids=0.20),
    "33606": Z(8000, 3500, owner=0.70, kids=0.35),
    "33603": Z(900, 280, owner=0.55, kids=0.30, extra={"B25003_002": (154.0, 200.0)}),
}
ART = make_artifacts(WORLD)


def run(policy=OFF, text="33602 33606", **kw):  # type: ignore[no-untyped-def]
    return an.analyze(ART, parse_paste(text), policy, **kw)


def card(a: an.Analysis, metric: str) -> kpis.KpiCard:
    return next(c for c in kpis.cards(a) if c.metric_id == metric)


def test_there_is_one_card_per_lens_kpi_in_order() -> None:
    a = run()
    assert [c.metric_id for c in kpis.cards(a)] == list(a.lens.all_kpis)
    assert [c.metric_id for c in kpis.cards(a)][:5] == [
        "hh",
        "pop",
        "median_hh_income",
        "owner",
        "hh_kids",
    ]


def test_a_count_shows_its_share_of_the_benchmark_and_no_index() -> None:
    c = card(run(), "hh")
    assert c.value == "5,500" and c.index is None and c.index_text is None
    assert c.share_text == "0.1 % of Florida's households"
    assert card(run(), "pop").share_text == "0.1 % of Florida's population"


def test_a_share_shows_its_index_against_the_benchmark() -> None:
    c = card(run(), "owner")
    assert c.value.endswith("%") and c.index == round(100 * c.estimate / 0.66)
    assert c.index_text == f"Index {c.index} vs Florida" and c.share_text is None
    assert c.moe.startswith(ui.PLUS_MINUS)


def test_a_median_uses_the_published_value_and_its_index() -> None:
    c = card(run(text="33602"), "median_hh_income")
    assert c.value == "$60,000" and c.index is not None


def test_a_top_coded_median_has_no_index_and_says_why() -> None:
    art = make_artifacts({"99001": Z(4000, 1500, income=250_001, code="top")})
    a = an.analyze(art, parse_paste("99001"), OFF)
    c = next(c for c in kpis.cards(a) if c.metric_id == "median_hh_income")
    assert c.value == "$250,000+" and c.index is None
    assert "above the published range" in (c.index_text or "")


def test_reliability_marker_and_tooltip_for_an_unreliable_card() -> None:
    a = run(text="33603")
    c = card(a, "owner")
    assert c.tier == "unreliable" and c.marker == ui.DAGGER
    assert "Unreliable" in c.tier_label and "30" in c.tooltip
    good = card(run(), "hh")
    assert good.marker == "" and good.tooltip == ""


def test_the_card_tier_is_the_worse_of_the_value_and_the_index() -> None:
    a = run(text="33603")
    assert card(a, "owner").tier == "unreliable"
    assert card(run(), "owner").tier == "good"


def test_restricted_mode_still_has_cards_with_their_context_index() -> None:
    a = run(FORCED)
    assert [c.metric_id for c in kpis.cards(a)] == list(a.lens.all_kpis)
    assert card(a, "owner").index_text


def test_unknown_values_show_a_dash_and_no_index() -> None:
    art = make_artifacts({"33602": Z(5000, 2000, income=None)})
    a = an.analyze(art, parse_paste("33602"), OFF)
    c = next(c for c in kpis.cards(a) if c.metric_id == "median_hh_income")
    assert c.value == ui.DASH and c.index is None and c.moe == ""


def test_the_text_lines_match_the_cards() -> None:
    lines = kpis.text_lines(run())
    assert len(lines) == len(kpis.cards(run())) and any(
        "Households" in x and "5,500" in x for x in lines
    )


def test_a_tiny_share_of_a_big_benchmark_reads_less_than_a_tenth_of_a_percent() -> None:
    # Phase 7 final review L4: "0.0 % of United States's households"
    us = an.analyze(
        ART,
        parse_paste("33602 33606"),
        OFF,
        benchmark=an.analyze(ART, parse_paste("33602"), OFF).options.us,
    )
    text = card(us, "hh").share_text
    assert text == "<0.1 % of the United States' households"


def test_a_possessive_after_an_s_has_no_second_s() -> None:
    a = run()
    assert card(a, "hh").share_text == "0.1 % of Florida's households"
    assert (
        kpis.possessive("United States") == "the United States'"
        and kpis.possessive("Florida") == "Florida's"
    )
    assert kpis.possessive("Massachusetts") == "Massachusetts'"
