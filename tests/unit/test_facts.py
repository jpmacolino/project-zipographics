"""Tests for zipographics.facts: facts-frame validation, state names, dominant state (SPEC §6.8)."""

from __future__ import annotations

import pandas as pd
import pytest
from synth_facts import make_facts

from zipographics.facts import STATE_NAMES, dominant_state, validate_facts


def test_state_names_cover_the_50_states_dc_and_puerto_rico() -> None:
    assert len(STATE_NAMES) == 52
    assert STATE_NAMES["FL"] == "Florida"
    assert STATE_NAMES["DC"] == "District of Columbia"
    assert STATE_NAMES["PR"] == "Puerto Rico"
    assert all(len(abbr) == 2 and abbr.isupper() for abbr in STATE_NAMES)


def test_dominant_state_is_the_state_with_the_most_population() -> None:
    facts = make_facts(
        {"33602": ("FL", 3000, 1), "33603": ("FL", 2000, 1), "30301": ("GA", 4000, 1)}
    )
    assert dominant_state(["33602", "33603", "30301"], facts) == "FL"  # 5000 vs 4000


def test_dominant_state_tie_goes_to_the_state_of_the_first_zip_in_input_order() -> None:
    facts = make_facts({"33602": ("FL", 1000, 1), "30301": ("GA", 1000, 1)})
    assert dominant_state(["33602", "30301"], facts) == "FL"
    assert dominant_state(["30301", "33602"], facts) == "GA"


def test_dominant_state_treats_missing_population_as_zero() -> None:
    facts = make_facts({"33602": ("FL", None, None), "30301": ("GA", 10, 1)})
    assert dominant_state(["33602", "30301"], facts) == "GA"


def test_dominant_state_with_no_population_anywhere_uses_the_first_zip() -> None:
    facts = make_facts({"33602": ("FL", None, None), "30301": ("GA", 0, 0)})
    assert dominant_state(["30301", "33602"], facts) == "GA"


def test_dominant_state_ignores_zips_without_facts_or_state() -> None:
    facts = make_facts({"33602": ("FL", 10, 1)})
    assert dominant_state(["99999", "33602"], facts) == "FL"
    assert dominant_state(["99999"], facts) is None
    assert dominant_state([], facts) is None


def test_dominant_state_can_exclude_one_zip() -> None:
    facts = make_facts({"33602": ("FL", 9000, 1), "30301": ("GA", 10, 1), "30302": ("GA", 10, 1)})
    assert dominant_state(["33602", "30301", "30302"], facts) == "FL"
    assert dominant_state(["33602", "30301", "30302"], facts, exclude="33602") == "GA"


def test_validate_facts_accepts_a_good_frame() -> None:
    facts = make_facts({"02108": ("MA", 1, 1)})
    assert validate_facts(facts) is facts


@pytest.mark.parametrize("missing", ["state", "population", "households"])
def test_validate_facts_requires_the_columns(missing: str) -> None:
    facts = make_facts({"02108": ("MA", 1, 1)}).drop(columns=[missing])
    with pytest.raises(ValueError, match=missing):
        validate_facts(facts)


def test_validate_facts_rejects_a_numeric_zip_index() -> None:
    facts = make_facts({"02108": ("MA", 1, 1)})
    facts.index = pd.Index([2108])
    with pytest.raises(ValueError, match="string"):
        validate_facts(facts)


def test_validate_facts_rejects_a_zip_index_that_is_not_five_digits() -> None:
    facts = make_facts({"2108": ("MA", 1, 1)})
    with pytest.raises(ValueError, match="5-character"):
        validate_facts(facts)


# --------------------------------------------------------------------- QA #4: fast exclusion
def test_state_totals_match_the_brute_force_rule_for_every_exclusion() -> None:
    from hypothesis import given
    from hypothesis import strategies as st

    from zipographics.facts import StateEntry, StateTotals, dominant_of

    @given(
        st.lists(
            st.tuples(st.sampled_from("ABCD"), st.integers(0, 5)),
            min_size=0,
            max_size=12,
        )
    )
    def check(rows: list[tuple[str, int]]) -> None:
        entries = [StateEntry(f"{i:05d}", s, float(p)) for i, (s, p) in enumerate(rows)]
        totals = StateTotals(entries)
        assert totals.dominant() == dominant_of(entries)
        for e in entries:
            assert totals.dominant(exclude=e.zip) == dominant_of(entries, exclude=e.zip), e
        assert totals.dominant(exclude="99999") == dominant_of(entries, exclude="99999")

    check()
