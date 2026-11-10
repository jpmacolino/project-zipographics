"""Verticals, the restricted-use question and the restricted data module (SPEC 5.1, 5.7, App. B)."""

from __future__ import annotations

import pytest

from zipographics import errors, metrics, restricted, verticals
from zipographics.models import UsePolicy

RESTRICTED = {
    "Real estate (brokerage, rentals, property management)",
    "Home builders & developers",
    "Senior living (communities are housing)",
    "Mortgage & lending",
    "Banking & credit unions",
    "Insurance",
    "Financial planning & investments",
    "Staffing & recruiting",
}


# ------------------------------------------------------------------ verticals
def test_the_vertical_table_matches_the_spec() -> None:
    names = [v.name for v in verticals.VERTICALS]
    assert len(names) == len(set(names)) == 29
    assert names[-1] == "Other"
    assert {v.name for v in verticals.VERTICALS if v.restricted} == RESTRICTED


def test_every_restricted_vertical_has_the_context_lens_and_every_other_has_its_own() -> None:
    for v in verticals.VERTICALS:
        assert (v.lens == "Context") == v.restricted, v.name
    assert verticals.get("Solar & home energy").lens == "Lawn & outdoor"
    assert verticals.get("Moving & storage").lens == "Movers"
    assert verticals.get("Legal services").lens == "General"
    assert verticals.get("Nonprofit & community organizations").lens == "General"
    assert verticals.get("Other").lens == "General"
    assert verticals.get("Hospitality, entertainment & events").lens == "Hospitality"


def test_the_question_is_worded_exactly() -> None:
    assert verticals.RESTRICTED_QUESTION == (
        "Will this be used for ads, mailers, or any other marketing for housing, jobs, "
        "credit or financing, or insurance?"
    )
    assert verticals.LOCKED_NOTE == ("Marketing for this industry always counts as restricted use.")


@pytest.mark.parametrize("name", sorted(RESTRICTED))
@pytest.mark.parametrize("answer", [True, False, None])
def test_a_restricted_vertical_is_locked_yes_whatever_is_passed(
    name: str, answer: bool | None
) -> None:
    p = verticals.make_policy(name, answer)
    assert p == UsePolicy(True, name, "Yes (set by industry)")
    assert verticals.is_locked(name)


@pytest.mark.parametrize("v", [v.name for v in verticals.VERTICALS if not v.restricted])
def test_every_other_vertical_needs_an_answer(v: str) -> None:
    assert not verticals.is_locked(v)
    with pytest.raises(ValueError, match="answer"):
        verticals.make_policy(v, None)
    assert verticals.make_policy(v, True) == UsePolicy(True, v, "Yes")
    assert verticals.make_policy(v, False) == UsePolicy(False, v, "No")


def test_a_car_dealer_advertising_financing_turns_restricted_mode_on() -> None:
    p = verticals.make_policy("Automotive sales", True)
    assert p.restricted and p.answer == "Yes"  # answered, not forced (golden scenario 6)


def test_other_follows_the_answer() -> None:
    assert verticals.make_policy("Other", True).restricted
    assert not verticals.make_policy("Other", False).restricted


def test_an_unknown_vertical_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown industry"):
        verticals.make_policy("Astrology", False)
    with pytest.raises(ValueError, match="Unknown industry"):
        verticals.get("")


def test_the_default_lens_is_context_whenever_restricted_mode_is_on() -> None:
    assert verticals.default_lens(verticals.make_policy("Automotive sales", True)) == "Context"
    assert verticals.default_lens(verticals.make_policy("Automotive sales", False)) == "Auto sales"
    assert verticals.default_lens(verticals.make_policy("Mortgage & lending", None)) == "Context"


def test_notes_name_the_answer_to_give() -> None:
    assert "answer Yes" in (
        verticals.get("Home services (HVAC, plumbing, roofing, pest, remodeling)").note or ""
    )
    assert "answer Yes" in (verticals.get("Solar & home energy").note or "")
    assert verticals.get("Legal services").note is None


def test_search_finds_a_vertical_by_a_fragment() -> None:
    assert [v.name for v in verticals.search("dent")] == ["Dental & orthodontics"]
    assert len(verticals.search("")) == 29


# ------------------------------------------------------------------ restricted data
def test_every_metric_has_a_tag_decision() -> None:
    # a metric added without deciding its characteristic tag fails here (SPEC §9.2)
    untagged = {"pop", "hh", "units", "vacancy"}
    for metric in metrics.REGISTRY:
        if metric.characteristic is None:
            assert metric.id in untagged, f"{metric.id} has no characteristic tag decision"
        else:
            assert metric.characteristic in restricted.TAGS


def test_the_tag_table_is_appendix_b_exactly() -> None:
    assert set(restricted.TAGS) == {
        "race_color", "national_origin", "religion", "sex", "familial_status", "age",
        "disability", "marital_status", "public_assistance", "military", "genetic",
        "income", "proxy_other",
    }  # fmt: skip
    expected = {
        "race_color": {"race_white", "race_black", "race_aian", "race_asian", "race_nhpi",
                       "race_other", "race_two_plus"},
        "national_origin": {"hispanic", "spanish_home", "limited_english"},
        "familial_status": {"hh_kids", "age_0_4", "age_5_17", "working_parents_u6"},
    }  # fmt: skip
    for tag, ids in expected.items():
        assert {m.id for m in metrics.REGISTRY if m.characteristic == tag} == ids
    for tag in ("religion", "sex", "disability", "marital_status", "public_assistance",
                "military", "genetic"):  # fmt: skip
        assert not [m for m in metrics.REGISTRY if m.characteristic == tag]
    age = {m.id for m in metrics.REGISTRY if m.characteristic == "age"}
    assert {"median_age", "age_65p", "age_0_17", "age_75p"} <= age
    assert all(
        m.id.startswith("age_") or m.id == "median_age"
        for m in metrics.REGISTRY
        if m.characteristic == "age"
    )
    income = {m.id for m in metrics.REGISTRY if m.characteristic == "income"}
    assert {
        "median_hh_income",
        "mean_hh_income",
        "per_capita_income",
        "poverty",
        "inc_100p",
    } <= income


def test_each_tag_says_what_it_covers() -> None:
    for tag, text in restricted.TAGS.items():
        assert text.strip() and tag in restricted.TAG_LABELS
    assert restricted.label_of(metrics.BY_ID["hh_kids"]) == restricted.TAG_LABELS["familial_status"]
    assert restricted.label_of(metrics.BY_ID["pop"]) is None


def test_the_texts_are_the_spec_wording() -> None:
    assert restricted.BANNER_TITLE == "Restricted mode is on."
    assert "ZIPs can't be ranked, filtered or selected by it" in restricted.BANNER
    assert restricted.BANNER.startswith("Restricted mode is on. You said this will be used")
    assert "Meta also requires at least a 15-mile radius" in restricted.AD_PLATFORM_NOTICE
    assert "Google Ads and Meta don't allow ZIP-code targeting" in restricted.AD_PLATFORM_NOTICE
    assert restricted.NOT_LEGAL_ADVICE.startswith(
        "Restricted mode is a guardrail, not legal advice."
    )
    assert "agency's counsel" in restricted.NOT_LEGAL_ADVICE


def test_the_guard_refuses_every_action_when_restricted_and_allows_them_otherwise() -> None:
    on = UsePolicy(True, "Insurance", "Yes (set by industry)")
    off = UsePolicy(False, "Retail", "No")
    for action in ("filter", "rank", "select"):
        with pytest.raises(restricted.RestrictedUseError, match=action):
            restricted.require_unrestricted(on, action)
        restricted.require_unrestricted(off, action)  # no error
    assert restricted.RestrictedUseError is errors.RestrictedUseError


def test_a_missing_policy_is_treated_as_restricted() -> None:
    # fail closed: a caller that forgot the policy must not be able to select by demographics
    with pytest.raises(restricted.RestrictedUseError):
        restricted.require_unrestricted(None, "filter")
