"""Tests for zipographics.review: the validation summary (SPEC §5.4, §9.2 review)."""

from __future__ import annotations

from synth_facts import make_facts

from zipographics.config import MAX_ZIPS
from zipographics.models import ParsedInput, ReviewSummary, UsePolicy
from zipographics.review import review_lines, summarize
from zipographics.zips import parse_paste

# state, population, households
FL = {
    "33602": ("FL", 5000, 2200),
    "33603": ("FL", 6000, 2500),
    "33604": ("FL", 7000, 3000),
    "33605": ("FL", 8000, 3100),
    "33606": ("FL", 9000, 4000),
}
FACTS = make_facts(
    {
        **FL,
        "02108": ("MA", 3600, 1900),
        "02109": ("MA", 4000, 2100),
        "03360": ("NH", 1500, 600),
        "00601": ("PR", 17000, 6000),
        "33000": ("FL", 0, 0),  # no residents
        "59001": ("MT", 999, 400),  # small: population
        "59002": ("MT", 1000, 299),  # small: households
        "59003": ("MT", 1000, 300),  # NOT small: exactly at both thresholds
        "59004": ("MT", None, None),  # suppressed: unknown, not flagged
        "59005": ("MT", None, 100),  # households alone is enough to flag it
    }
)


def run(
    text: str, policy: UsePolicy | None = None, project_name: str | None = None
) -> ReviewSummary:
    return summarize(parse_paste(text), FACTS, policy=policy, project_name=project_name)


# --------------------------------------------------------------------- recognition
def test_recognized_and_not_found_are_split_by_presence_in_the_data() -> None:
    s = run("33602 33601 33603 00000")
    assert s.recognized == ("33602", "33603")
    assert s.not_found == ("33601", "00000")
    assert s.entered == 4


def test_a_zero_population_zip_is_recognized_and_listed_as_no_residents() -> None:
    s = run("33602 33000")
    assert s.recognized == ("33602", "33000")
    assert s.no_residents == ("33000",)
    assert s.not_found == ()


def test_input_order_is_kept() -> None:
    assert run("33606 33602 33604").recognized == ("33606", "33602", "33604")


# --------------------------------------------------------------------- small populations
def test_small_population_thresholds() -> None:
    # 59001: 999 people; 59002: 299 households; 59005: unknown people, 100 households.
    # Not flagged: 59003 (exactly 1,000 and 300), 59004 (both unknown), 33602 (large).
    s = run("59001 59002 59003 59004 59005 33602")
    assert s.small_population == ("59001", "59002", "59005")


def test_a_no_residents_zip_is_not_also_small() -> None:
    assert run("33000").small_population == ()


# --------------------------------------------------------------------- repairs and the rest
def test_repaired_zips_are_listed_for_the_retained_occurrence() -> None:
    s = run("2108 02109 abc 02109-1234 33602 33602")
    assert [(t.raw, t.zip) for t in s.repaired] == [("2108", "02108")]
    assert s.truncated == ()  # 02109-1234 duplicates 02109, which was plain
    assert s.invalid == ("abc",)
    assert s.duplicates == 2


def test_zip_plus_four_truncation_is_reported() -> None:
    s = run("02108-1234 33602")
    assert [t.raw for t in s.truncated] == ["02108-1234"]


# --------------------------------------------------------------------- unexpected state
def test_a_repaired_zip_in_a_different_state_than_the_rest_is_flagged() -> None:
    s = run("33602 33603 33604 3360")  # 3360 -> 03360 (NH) among Florida ZIPs
    assert s.repaired_unexpected_state == (("03360", "NH", "FL"),)


def test_the_comparison_excludes_the_repaired_zip_itself() -> None:
    # Mangled Boston ZIPs next to one Florida ZIP. For 02108 "the rest" is 02109 (MA 4,000) and
    # 33602 (FL 5,000), so Florida holds most of the rest and 02108 is flagged. If the ZIP were
    # counted in its own comparison, MA (7,600) would win and nothing would be flagged.
    s = run("2108 2109 33602")
    assert s.repaired_unexpected_state == (
        ("02108", "MA", "FL"),
        ("02109", "MA", "FL"),
    )


def test_repaired_zips_all_in_one_state_are_not_flagged() -> None:
    assert run("2108 2109 02110").repaired_unexpected_state == ()  # 02110 is not in the data
    assert run("2108 2109").repaired_unexpected_state == ()


def test_a_lone_repaired_zip_has_no_rest_to_compare_with() -> None:
    assert run("3360").repaired_unexpected_state == ()


def test_a_zip_that_was_not_repaired_is_never_flagged() -> None:
    assert run("33602 33603 03360").repaired_unexpected_state == ()


def test_unexpected_state_check_skips_repaired_zips_that_were_not_found() -> None:
    assert run("33602 33603 3361").repaired_unexpected_state == ()  # 03361 is not in the data


# --------------------------------------------------------------------- states and benchmark
def test_single_state_input_does_not_span() -> None:
    s = run("33602 33603")
    assert s.states == ("FL",)
    assert s.benchmark_state == "FL"


def test_multi_state_input_names_the_dominant_state() -> None:
    s = run("33602 33603 02108")  # FL 11,000 vs MA 3,600
    assert s.states == ("FL", "MA")
    assert s.benchmark_state == "FL"


def test_multi_state_tie_goes_to_the_first_zip() -> None:
    facts = make_facts({"33602": ("FL", 100, 1), "30301": ("GA", 100, 1)})
    assert summarize(parse_paste("30301 33602"), facts).benchmark_state == "GA"


def test_no_recognized_zips_means_no_benchmark_state() -> None:
    s = run("33601")
    assert s.benchmark_state is None
    assert s.states == ()


# --------------------------------------------------------------------- blocking
def test_zero_recognized_zips_blocks() -> None:
    s = run("33601 abc")
    assert not s.can_continue
    assert any("recognized" in b for b in s.blocking)


def test_empty_input_blocks() -> None:
    assert not summarize(ParsedInput(), FACTS).can_continue


def _big(n: int) -> ReviewSummary:
    zips = [f"{10000 + i:05d}" for i in range(n)]
    facts = make_facts({z: ("NY", 5000, 2000) for z in zips})
    return summarize(parse_paste(" ".join(zips)), facts)


def test_exactly_the_maximum_is_allowed() -> None:
    s = _big(MAX_ZIPS)
    assert s.can_continue
    assert s.blocking == ()


def test_one_over_the_maximum_blocks_with_the_split_message() -> None:
    s = _big(MAX_ZIPS + 1)
    assert not s.can_continue
    assert s.blocking == (
        "Zipographics handles up to 1,000 ZIPs at a time. Split the list and run it in parts.",
    )


def test_the_limit_counts_valid_zips_not_recognized_ones() -> None:
    zips = [f"{10000 + i:05d}" for i in range(MAX_ZIPS + 1)]
    s = summarize(parse_paste(" ".join(zips)), make_facts({"10000": ("NY", 1, 1)}))
    assert len(s.recognized) == 1  # only one is in the data, yet the input is over the limit
    assert not s.can_continue


# --------------------------------------------------------------------- Zipcator
def test_zipcator_flags_are_carried_through() -> None:
    parsed = ParsedInput(
        zips=("33602", "33603"),
        overlaps={"33602": 50.0},
        blank_overlap=("33603",),
        overlap_conflicts=("33602",),
        source="zipcator",
    )
    s = summarize(parsed, FACTS)
    assert s.zipcator
    assert s.blank_overlap == ("33603",)
    assert s.overlap_conflicts == ("33602",)
    assert not run("33602").zipcator


# --------------------------------------------------------------------- context
def test_policy_and_project_name_are_carried_and_default_to_none() -> None:
    s = run("33602")
    assert (s.industry, s.restricted, s.project_name) == (None, None, None)
    policy = UsePolicy(restricted=True, vertical="Insurance", answer="Yes (set by industry)")
    s = run("33602", policy=policy, project_name="Acme Roofing")
    assert (s.industry, s.restricted, s.project_name) == ("Insurance", True, "Acme Roofing")


# --------------------------------------------------------------------- lines (what the UI shows)
def test_a_clean_input_shows_only_the_recognized_line() -> None:
    assert review_lines(run("33602 33603")) == ["2 ZIPs recognized"]
    assert review_lines(run("33602")) == ["1 ZIP recognized"]


def test_each_line_appears_when_it_applies() -> None:
    # 2108->02108 (repaired, MA), 02109 (MA), 02109 (duplicate), abc (invalid),
    # 59001-1234 (ZIP+4, MT, small), 33601 (not found), 33000 (no residents),
    # 3360->03360 (repaired, NH), 33602 and 33603 (FL).  7 recognized.
    s = run("2108 02109 02109 abc 59001-1234 33601 33000 3360 33602 33603")
    lines = "\n".join(review_lines(s))
    assert "7 ZIPs recognized" in lines
    assert "1 not found" in lines and "33601" in lines
    assert "no residential population" in lines and "33000" in lines
    assert "2 repaired" in lines and "2108 → 02108" in lines and "3360 → 03360" in lines
    assert "03360 is in NH, the rest are in FL" in lines
    assert "1 ZIP+4 truncated" in lines
    assert "1 invalid" in lines and "abc" in lines
    assert "1 duplicate removed" in lines
    assert "1 has a small population" in lines and "59001" in lines


def test_repaired_lines_show_first_ten_then_count() -> None:
    text = " ".join(str(2100 + i) for i in range(15))  # 15 mangled ZIPs
    facts = make_facts({f"0{2100 + i}": ("MA", 5000, 2000) for i in range(15)})
    lines = review_lines(summarize(parse_paste(text), facts))
    rep = next(line for line in lines if "repaired" in line)
    assert "15 repaired" in rep
    assert "2100 → 02100" in rep and "2109 → 02109" in rep
    assert "2110 → 02110" not in rep
    assert "and 5 more" in rep


def test_invalid_lines_show_first_twenty_then_count() -> None:
    text = "33602 " + " ".join(f"bad{i}" for i in range(25))
    inv = next(line for line in review_lines(run(text)) if "invalid" in line)
    assert "25 invalid" in inv
    assert "bad0" in inv and "bad19" in inv and "bad20" not in inv
    assert "and 5 more" in inv


def test_not_found_counts_are_pluralized() -> None:
    one = next(line for line in review_lines(run("33602 33601")) if "not found" in line)
    two = next(line for line in review_lines(run("33602 33601 99999")) if "not found" in line)
    assert one.startswith("1 not found")
    assert two.startswith("2 not found")


def test_spanning_states_line_names_states_and_benchmark() -> None:
    lines = review_lines(run("33602 33603 02108"))
    span = next(line for line in lines if "Benchmark" in line)
    assert span == (
        "Your ZIPs are in FL and MA. Benchmark: Florida (most of their population). "
        "You can change it."
    )


def test_three_states_are_joined_with_commas_and_and() -> None:
    lines = review_lines(run("33602 02108 03360"))
    assert any("FL, MA and NH" in line for line in lines)


def test_single_state_has_no_spanning_line() -> None:
    assert not any("Benchmark" in line for line in review_lines(run("33602 33603")))


def test_zipcator_lines() -> None:
    parsed = ParsedInput(
        zips=("33602", "33603"),
        overlaps={"33602": 50.0},
        blank_overlap=("33603",),
        overlap_conflicts=("33602",),
        source="zipcator",
    )
    lines = "\n".join(review_lines(summarize(parsed, FACTS)))
    assert "Zipcator export detected: in-radius estimates are on" in lines
    assert "33603" in lines and "full ZIP" in lines
    assert "different overlap" in lines


def test_context_line_is_always_last() -> None:
    policy = UsePolicy(restricted=False, vertical="Home services", answer="No")
    lines = review_lines(run("33602", policy, "Acme"))
    assert lines[-1] == "Project: Acme · Industry: Home services · Restricted mode: off"
    on = UsePolicy(restricted=True, vertical="Insurance", answer="Yes (set by industry)")
    assert review_lines(run("33602", on))[-1] == "Industry: Insurance · Restricted mode: on"


def test_zipcator_rejected_rows_and_plural_forms() -> None:
    from zipographics.models import RejectedRow

    parsed = ParsedInput(
        zips=("33602", "33603", "33604"),
        overlaps={"33602": 50.0},
        blank_overlap=("33603", "33604"),
        rejected_rows=(RejectedRow("33605", "-5", "overlap must be above 0 and at most 100"),),
        overlap_conflicts=("33602", "33603"),
        source="zipcator",
    )
    lines = review_lines(summarize(parsed, FACTS))
    text = "\n".join(lines)
    assert "2 ZIPs have no overlap value and are treated as full ZIPs: 33603, 33604" in text
    assert "1 row rejected for an unusable overlap: 33605 (-5: overlap must be above 0" in text
    assert "2 ZIPs repeat with a different overlap; the first value is used: 33602, 33603" in text


# --------------------------------------------------------------------- QA phase 1 regressions
def test_all_recognized_zips_without_residents_blocks() -> None:
    # QA #3: a trade area with 0 people and 0 households has nothing to profile
    s = run("33000")
    assert not s.can_continue
    assert any("residential population" in b for b in s.blocking)
    assert run("33000 33602").can_continue  # one ZIP with residents is enough


def test_unknown_population_does_not_block() -> None:
    assert run("59004").can_continue  # suppressed, not zero


def test_nullable_and_object_columns_are_accepted() -> None:
    # QA #5: the parquet loader may hand over Float64 (pd.NA) or object (None) columns
    import pandas as pd

    nullable = FACTS.copy()
    nullable["population"] = nullable["population"].astype("Float64")
    nullable["households"] = nullable["households"].astype("Float64")
    assert summarize(parse_paste("59004 59005 33602"), nullable).small_population == ("59005",)

    obj = FACTS.copy()
    obj["population"] = pd.Series([None if pd.isna(v) else v for v in FACTS["population"]],
                                  index=FACTS.index, dtype="object")  # fmt: skip
    obj["households"] = obj["households"].astype("object").where(obj["households"].notna(), None)
    assert summarize(parse_paste("59004 59005 33602"), obj).small_population == ("59005",)


def test_duplicate_zip_index_is_rejected_clearly() -> None:
    import pandas as pd
    import pytest

    from zipographics.facts import validate_facts

    dup = pd.concat([FACTS.loc[["33602"]], FACTS.loc[["33602"]]])
    with pytest.raises(ValueError, match="duplicate"):
        validate_facts(dup)


def test_repaired_line_shows_the_cleaned_raw_token() -> None:
    # QA #6: quotes and "=" from Excel text cells were printed in the repaired line
    lines = review_lines(run('"2108" ="2109"'))
    rep = next(line for line in lines if "repaired" in line)
    assert rep == "2 repaired (leading zeros restored: 2108 → 02108, 2109 → 02109)"


def test_not_found_listing_is_capped_at_twenty() -> None:
    text = "33602 " + " ".join(f"{90000 + i}" for i in range(25))
    nf = next(line for line in review_lines(run(text)) if "not found" in line)
    assert nf.startswith("25 not found")
    assert "90019" in nf and "90020" not in nf
    assert "and 5 more" in nf


def test_two_repaired_zips_in_different_states_flag_each_other() -> None:
    # spec-literal and noisy for tiny lists (DECISIONS B10); pinned so a change is deliberate
    s = run("2108 3360")
    assert s.repaired_unexpected_state == (("02108", "MA", "NH"), ("03360", "NH", "MA"))
