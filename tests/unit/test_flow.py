"""Wiring helpers the Streamlit app uses; the app file itself stays layout only (SPEC 8)."""

from __future__ import annotations

import pytest
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import flow, metrics, verticals
from zipographics.models import Rule
from zipographics.zips import parse_paste

OFF = verticals.make_policy("Retail (general & specialty)", False)
WORLD = {
    "33602": Z(5000, 2000),
    "30301": Z(3000, 1200, state="GA", county=("13121", "Fulton County"), city="Atlanta"),
}
ART = make_artifacts(WORLD)


def test_the_continue_button_needs_an_industry_and_an_answer() -> None:
    assert not flow.step1_ready(None, None)
    assert not flow.step1_ready("Retail (general & specialty)", None)
    assert flow.step1_ready("Retail (general & specialty)", "No")
    assert flow.step1_ready("Retail (general & specialty)", "Yes")
    assert flow.step1_ready("Mortgage & lending", None)  # locked: no answer needed
    assert not flow.step1_ready("Astrology", "No")


def test_step1_builds_the_policy() -> None:
    assert flow.policy_for("Mortgage & lending", None).answer == "Yes (set by industry)"
    assert flow.policy_for("Automotive sales", "Yes").restricted
    assert not flow.policy_for("Automotive sales", "No").restricted
    with pytest.raises(ValueError, match="answer"):
        flow.policy_for("Automotive sales", None)


def test_benchmark_choices_are_labelled_and_the_default_comes_first() -> None:
    a = an.analyze(ART, parse_paste("33602 30301"), OFF)
    choices = flow.benchmark_choices(a.options)
    labels = [c.label for c in choices]
    assert labels[0] == "Florida (state)" and "Georgia (state)" in labels
    assert "Hillsborough County (county)" in labels and labels[-1] == "United States (national)"
    assert len(set(labels)) == len(labels)
    assert flow.find_choice(choices, "Georgia (state)").ref.geo_id == "13"
    assert flow.find_choice(choices, "nope") is choices[0]  # falls back to the default


def test_spanning_states_gets_the_review_sentence() -> None:
    msg = flow.span_message(an.analyze(ART, parse_paste("33602 30301"), OFF))
    assert msg is not None and "FL and GA" in msg and "Benchmark: Florida" in msg
    assert flow.span_message(an.analyze(ART, parse_paste("33602"), OFF)) is None


def test_rule_inputs_are_converted_between_display_units_and_rule_values() -> None:
    assert flow.rule_from_inputs("owner", ">=", 60, "value") == Rule("owner", ">=", 0.6, "value")
    assert flow.rule_from_inputs("median_hh_income", "<=", 75_000, "value").value == 75_000
    assert flow.rule_from_inputs("hh_kids", ">=", 115, "index") == Rule(
        "hh_kids", ">=", 115, "index"
    )
    assert flow.rule_to_inputs(Rule("owner", ">=", 0.6, "value")) == ("owner", ">=", 60.0, "value")
    assert flow.rule_to_inputs(Rule("hh_kids", ">=", 115, "index"))[2] == 115
    r = flow.rule_from_inputs("owner", ">=", 0.07 * 100, "value")
    assert flow.rule_to_inputs(r)[2] == pytest.approx(7.0)


def test_rule_value_hints_name_the_unit() -> None:
    assert flow.value_unit("owner", "value") == "%"
    assert flow.value_unit("owner", "index") == "index"
    assert flow.value_unit("median_hh_income", "value") == "$"
    assert flow.value_unit("pop", "value") == ""


def test_metric_choices_are_every_registry_metric_with_a_unique_label() -> None:
    names = flow.metric_labels()
    assert len(names) == len(metrics.REGISTRY) and len(set(names.values())) == len(names)
    assert names["owner"] == "Homeowners"


def test_index_is_offered_only_for_indexable_metrics() -> None:
    assert flow.bases_for("owner") == ["value", "index"]
    assert flow.bases_for("pop") == ["value"]


def test_sort_choices_depend_on_restricted_mode() -> None:
    open_ = flow.sort_choices(restricted=False)
    assert open_[0] == ("input", "Input order") and ("owner", "Homeowners") in open_
    locked = flow.sort_choices(restricted=True)
    assert locked == [("input", "As entered"), ("zip", "By ZIP")]


def test_a_sensible_default_number_for_each_unit_and_basis() -> None:
    assert flow.default_number("owner", "value") == 50.0  # percent, as typed
    assert flow.default_number("owner", "index") == 100.0
    assert flow.default_number("median_hh_income", "value") == 50_000.0
    assert flow.default_number("median_age", "value") == 40.0
    assert flow.default_number("pop", "value") == 1000.0
    for m in metrics.REGISTRY:  # every default converts to a valid rule value
        for basis in flow.bases_for(m.id):
            rule = flow.rule_from_inputs(m.id, ">=", flow.default_number(m.id, basis), basis)
            if m.unit == "percent" and basis == "value":
                assert 0 <= rule.value <= 1
