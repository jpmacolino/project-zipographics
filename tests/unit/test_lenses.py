"""Lenses and presets (SPEC 5.5, Appendix D) and their restricted-mode behavior (SPEC 5.7)."""

from __future__ import annotations

import pytest

from zipographics import lenses, metrics, verticals
from zipographics.models import Rule, UsePolicy

OFF = UsePolicy(False, "Retail (general & specialty)", "No")
ON = UsePolicy(True, "Insurance", "Yes (set by industry)")

EXPECTED = {  # lens: (extra KPI cards, extra charts, presets), straight from Appendix D
    "Home services": (("single_family", "built_pre1980", "median_value"), ("units_in_structure",),
                      ("Home services", "Affluent homeowners", "New movers")),
    "Lawn & outdoor": (("single_family", "median_value", "inc_100p"), ("units_in_structure",),
                       ("Affluent homeowners", "Home services")),
    "Movers": (("new_movers", "renter", "hh"), ("tenure_by_move_in",), ("New movers", "Renters")),
    "Restaurants": (("median_age", "age_18_34", "wfh", "commute_drive_alone"), ("commute_mode",),
                    ("Young adults", "Families", "Commuters", "Spanish-language households")),
    "Retail": (("median_age", "inc_75p", "mean_hh_income"), (),
               ("Families", "Premium", "Young adults", "Spanish-language households")),
    "Auto sales": (("veh_per_hh", "veh_2p", "commute_drive_alone"), ("vehicles_available",),
                   ("Commuters", "Premium")),
    "Auto service": (("veh_per_hh", "commute_drive_alone", "commute_30p"), ("commute_mode",),
                     ("Commuters",)),
    "Health": (("age_65p", "median_age", "uninsured"), (),
               ("Seniors", "Families", "Spanish-language households")),
    "Dental": (("hh_kids", "age_5_17", "inc_75p"), (), ("Families", "Premium")),
    "Pets": (("single_family", "inc_75p"), (), ("Affluent homeowners", "Home services")),
    "Fitness": (("age_18_44", "renter", "inc_75p"), (), ("Young adults", "Renters")),
    "Salon": (("median_age", "inc_75p", "hh"), (), ("Premium", "Young adults")),
    "Childcare": (("age_0_4", "working_parents_u6", "hh_kids"), (), ("Young children", "Families")),
    "Schools": (("age_5_17", "hh_kids", "inc_100p", "ba_plus"), (), ("Families", "Premium")),
    "Higher ed": (("age_18_34", "unemployment", "ba_plus"), ("education",), ("Young adults",)),
    "Hospitality": (("age_25_44", "inc_100p", "median_age"), (), ("Premium", "Young adults")),
    "B2B": (("wfh", "ba_plus", "lfpr"), ("commute_mode",), ()),
    "General": (("median_age", "mean_hh_income"), (),
                ("Families", "Premium", "Seniors", "Spanish-language households")),
    "Context": (("units", "vacancy", "renter"), (), ()),
}  # fmt: skip

PRESET_RULES = {  # Appendix D, shares as fractions
    "Home services": (Rule("owner", ">=", 0.60), Rule("built_pre1980", ">=", 0.40),
                      Rule("inc_75p", ">=", 0.40)),
    "Affluent homeowners": (Rule("owner", ">=", 0.70), Rule("median_value", ">=", 120, "index")),
    "New movers": (Rule("new_movers", ">=", 120, "index"),),
    "Renters": (Rule("renter", ">=", 0.50),),
    "Families": (Rule("hh_kids", ">=", 115, "index"),),
    "Young children": (Rule("age_0_4", ">=", 115, "index"),),
    "Premium": (Rule("inc_150p", ">=", 0.25),),
    "Young adults": (Rule("age_18_34", ">=", 120, "index"),),
    "Seniors": (Rule("age_65p", ">=", 120, "index"),),
    "Commuters": (Rule("commute_drive_alone", ">=", 0.75),
                  Rule("commute_30p", ">=", 110, "index")),
    "Spanish-language households": (Rule("spanish_home", ">=", 0.25),),
}  # fmt: skip


def test_the_lens_table_is_appendix_d() -> None:
    assert [lens.name for lens in lenses.LENSES] == list(EXPECTED)
    for name, (kpis, charts, presets) in EXPECTED.items():
        lens = lenses.get(name)
        assert (lens.kpis, lens.charts, lens.presets) == (kpis, charts, presets), name


def test_every_lens_starts_with_the_core_cards_and_charts() -> None:
    assert lenses.CORE_KPIS == ("hh", "pop", "median_hh_income", "owner", "hh_kids")
    assert lenses.CORE_CHARTS == ("income", "age", "tenure", "housing_age")
    for lens in lenses.LENSES:
        assert lens.core_kpis == lenses.CORE_KPIS
        assert lens.all_kpis[: len(lenses.CORE_KPIS)] == lenses.CORE_KPIS
        assert len(lens.kpis) <= 4  # 2-4 lens-specific cards (Context has 3, Schools 4)
        assert len(lens.all_charts) <= 6  # "about six charts"


def test_lens_cards_and_columns_are_registry_metrics_without_duplicates() -> None:
    for lens in lenses.LENSES:
        for mid in lens.all_kpis:
            assert mid in metrics.BY_ID, (lens.name, mid)
        assert len(set(lens.all_kpis)) == len(lens.all_kpis)  # a card shown once
        assert set(lens.columns) >= set(lens.kpis) - {"pop", "hh"}  # those two are always shown
        for mid in lens.columns:
            assert mid in metrics.BY_ID


def test_preset_rules_are_the_documented_thresholds() -> None:
    assert {p.name for p in lenses.PRESETS.values()} == set(PRESET_RULES)
    for name, rules in PRESET_RULES.items():
        assert lenses.PRESETS[name].rules == rules, name


def test_every_preset_rule_is_valid_against_the_registry() -> None:
    for preset in lenses.PRESETS.values():
        for rule in preset.rules:
            metric = metrics.BY_ID[rule.metric]
            assert rule.op in (">=", "<=")
            assert rule.basis in ("value", "index")
            if rule.basis == "index":
                assert metric.indexable
            if metric.unit == "percent" and rule.basis == "value":
                assert 0 < rule.value < 1  # shares are fractions


def test_no_preset_or_lens_card_uses_a_race_metric() -> None:
    for preset in lenses.PRESETS.values():
        for rule in preset.rules:
            assert metrics.BY_ID[rule.metric].characteristic != "race_color"
    for lens in lenses.LENSES:
        for mid in lens.all_kpis + lens.columns:
            assert metrics.BY_ID[mid].characteristic != "race_color", (lens.name, mid)


def test_every_vertical_points_at_a_lens() -> None:
    names = {lens.name for lens in lenses.LENSES}
    for v in verticals.VERTICALS:
        assert v.lens in names, v.name


def test_available_lenses_when_unrestricted_are_all_and_context_is_not_offered() -> None:
    names = [lens.name for lens in lenses.available(OFF)]
    assert "Context" not in names and len(names) == len(EXPECTED) - 1
    assert lenses.get("Context").restricted_only


def test_restricted_mode_offers_only_the_context_lens() -> None:
    assert [lens.name for lens in lenses.available(ON)] == ["Context"]
    assert [lens.name for lens in lenses.available(None)] == ["Context"]  # fail closed


@pytest.mark.parametrize("lens", [lens.name for lens in lenses.LENSES])
def test_presets_are_empty_when_restricted_for_every_lens(lens: str) -> None:
    assert lenses.presets_for(lens, ON) == []
    assert lenses.presets_for(lens, None) == []
    assert lenses.presets_for(lens, UsePolicy(True, "Other", "Yes")) == []


def test_presets_for_an_unrestricted_lens() -> None:
    got = lenses.presets_for("Home services", OFF)
    assert [p.name for p in got] == ["Home services", "Affluent homeowners", "New movers"]
    assert lenses.presets_for("B2B", OFF) == []  # none until business counts exist


def test_a_restricted_only_lens_cannot_be_chosen_when_unrestricted() -> None:
    with pytest.raises(ValueError, match="restricted"):
        lenses.resolve("Context", OFF)


def test_resolve_falls_back_to_context_when_restricted() -> None:
    assert lenses.resolve("Retail", ON).name == "Context"
    assert lenses.resolve("Retail", None).name == "Context"
    assert lenses.resolve("Retail", OFF).name == "Retail"
    with pytest.raises(ValueError, match="Unknown lens"):
        lenses.resolve("Astrology", OFF)


def test_unknown_lens_and_preset_names_are_errors() -> None:
    with pytest.raises(ValueError, match="Unknown lens"):
        lenses.get("nope")
    with pytest.raises(ValueError, match="Unknown preset"):
        lenses.preset("nope", OFF)


def test_applying_a_preset_returns_its_rules_only_when_unrestricted() -> None:
    assert lenses.preset("Renters", OFF).rules == (Rule("renter", ">=", 0.50),)
    with pytest.raises(lenses.RestrictedUseError):
        lenses.preset("Renters", ON)
    with pytest.raises(lenses.RestrictedUseError):
        lenses.preset("Renters", None)


def test_chart_ids_are_known() -> None:
    known = {"income", "age", "tenure", "housing_age", "units_in_structure", "tenure_by_move_in",
             "commute_mode", "vehicles_available", "education", "race", "hispanic"}  # fmt: skip
    for lens in lenses.LENSES:
        assert set(lens.all_charts) <= known
    assert set(lenses.MORE_DEMOGRAPHICS_CHARTS) == {"race", "hispanic"}
