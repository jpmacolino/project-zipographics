"""Tests for variable resolution and bracket verification in zipographics.data_build.

Uses a tiny injected registry and fake ``variables.json`` content (SPEC §4.2, §9.2: a label that
moved IDs between two fake vintages; a missing or ambiguous label fails clearly).
"""

from __future__ import annotations

import json
import math

import pytest

from zipographics.data_build import (
    BuildError,
    ResolvedVar,
    bounds_match,
    parse_bounds,
    resolve_variables,
)
from zipographics.metrics import Bracket, MedianSpec, Var

INF = math.inf


# ------------------------------------------------------------------------------- parse_bounds
@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Estimate!!Total:!!Less than $10,000", (-INF, 10_000)),
        ("Estimate!!Total:!!$10,000 to $14,999", (10_000, 15_000)),
        ("Estimate!!Total:!!$200,000 or more", (200_000, INF)),
        ("Estimate!!Total:!!$2,000,000 or more", (2_000_000, INF)),
        ("Estimate!!Total:!!With cash rent:!!Less than $100", (-INF, 100)),
        ("Estimate!!Total:!!With cash rent:!!$100 to $149", (100, 150)),
        ("Estimate!!Total:!!With cash rent:!!$3,500 or more", (3_500, INF)),
        ("Estimate!!Total:!!Male:!!Under 5 years", (-INF, 5)),
        ("Estimate!!Total:!!Male:!!5 to 9 years", (5, 10)),
        ("Estimate!!Total:!!Male:!!15 to 17 years", (15, 18)),
        ("Estimate!!Total:!!Male:!!18 and 19 years", (18, 20)),
        ("Estimate!!Total:!!Male:!!20 years", (20, 21)),
        ("Estimate!!Total:!!Male:!!22 to 24 years", (22, 25)),
        ("Estimate!!Total:!!Female:!!60 and 61 years", (60, 62)),
        ("Estimate!!Total:!!Female:!!85 years and over", (85, INF)),
        ("Estimate!!Total:!!Built 2020 or later", (2020, INF)),
        ("Estimate!!Total:!!Built 2010 to 2019", (2010, 2020)),
        ("Estimate!!Total:!!Built 1939 or earlier", (-INF, 1940)),
    ],
)
def test_bounds_are_parsed_from_the_last_label_segment(
    label: str, expected: tuple[float, float]
) -> None:
    assert parse_bounds(label) == expected


@pytest.mark.parametrize(
    "label",
    [
        "Estimate!!Total:",
        "Estimate!!Total:!!Owner occupied",
        "Estimate!!Total:!!Male:",
        "Estimate!!Median age",
    ],
)
def test_labels_that_are_not_brackets_have_no_bounds(label: str) -> None:
    assert parse_bounds(label) is None


@pytest.mark.parametrize(
    ("label", "expected", "ok"),
    [
        ((-INF, 10_000), (0, 10_000), True),  # open lowest bracket uses 0 (SPEC §6.4 assumption)
        ((-INF, 1940), (-INF, 1940), True),
        ((10_000, 15_000), (10_000, 15_000), True),
        ((10_000, 15_000), (10_000, 14_999), False),
        ((200_000, INF), (200_000, INF), True),
        ((200_000, INF), (250_000, INF), False),
        ((-INF, 10_000), (5, 10_000), False),
    ],
)
def test_bounds_match(label: tuple[float, float], expected: tuple[float, float], ok: bool) -> None:
    assert bounds_match(label, expected) is ok


# ------------------------------------------------------------------------------- resolution
TOTAL = r"(?:^|!!)Total:?$"
VARS = {
    "B01003_001": Var("B01003_001", "B01003", TOTAL),
    "B19013_001": Var("B19013_001", "B19013", r"median household income", is_median=True),
    "B19001_002": Var("B19001_002", "B19001"),
    "B19001_003": Var("B19001_003", "B19001"),
    "B19001_004": Var("B19001_004", "B19001"),
    "DP03_UNINS": Var(
        "DP03_UNINS",
        "DP03",
        r"^estimate!!health insurance coverage!!civilian noninstitutionalized population"
        r"!!no health insurance coverage$",
        resolve="label",
        dataset="profile",
    ),
}
BRACKETS = [
    MedianSpec(
        "B19013_001",
        (
            Bracket(("B19001_002",), 0, 10_000),
            Bracket(("B19001_003",), 10_000, 15_000),
            Bracket(("B19001_004",), 15_000, 20_000),
        ),
    )
]


def detailed_meta() -> dict[str, dict[str, str]]:
    return {
        "B01003_001E": {"label": "Estimate!!Total", "group": "B01003"},
        "B01003_001M": {"label": "Margin of Error!!Total", "group": "B01003"},
        "B19013_001E": {
            "label": "Estimate!!Median household income in the past 12 months "
            "(in 2024 inflation-adjusted dollars)",
            "group": "B19013",
        },
        "B19001_002E": {"label": "Estimate!!Total:!!Less than $10,000", "group": "B19001"},
        "B19001_003E": {"label": "Estimate!!Total:!!$10,000 to $14,999", "group": "B19001"},
        "B19001_004E": {"label": "Estimate!!Total:!!$15,000 to $19,999", "group": "B19001"},
    }


def profile_meta() -> dict[str, dict[str, str]]:
    base = "HEALTH INSURANCE COVERAGE!!Civilian noninstitutionalized population"
    return {
        "DP03_0095E": {"label": f"Estimate!!{base}", "group": "DP03"},
        "DP03_0099E": {"label": f"Estimate!!{base}!!No health insurance coverage", "group": "DP03"},
        "DP03_0099M": {
            "label": f"Margin of Error!!{base}!!No health insurance coverage",
            "group": "DP03",
        },
        "DP03_0099PE": {"label": f"Percent!!{base}!!No health insurance coverage", "group": "DP03"},
        "DP03_0099PM": {
            "label": f"Percent Margin of Error!!{base}!!No health insurance coverage",
            "group": "DP03",
        },
    }


def resolve(detailed=None, profile=None, variables=None, brackets=BRACKETS):  # type: ignore[no-untyped-def]
    return resolve_variables(
        variables or VARS,
        {"detailed": detailed or detailed_meta(), "profile": profile or profile_meta()},
        brackets,
    )


def test_id_variables_resolve_to_their_estimate_id_and_label() -> None:
    got = resolve()
    pop = got["B01003_001"]
    assert isinstance(pop, ResolvedVar)
    assert (pop.id, pop.base_id, pop.dataset, pop.moved) == (
        "B01003_001E",
        "B01003_001",
        "detailed",
        False,
    )
    assert pop.label == "Estimate!!Total"
    assert got["B19001_002"].id == "B19001_002E"


def test_data_profile_variables_resolve_by_label_to_the_estimate_not_percent_or_moe() -> None:
    got = resolve()
    assert got["DP03_UNINS"].id == "DP03_0099E"
    assert got["DP03_UNINS"].base_id == "DP03_0099"
    assert got["DP03_UNINS"].dataset == "profile"


def test_a_data_profile_id_that_moves_between_vintages_still_resolves() -> None:
    moved = {k.replace("0099", "0108"): v for k, v in profile_meta().items()}
    assert resolve(profile=moved)["DP03_UNINS"].id == "DP03_0108E"


def test_a_label_that_moved_to_a_new_id_is_found_in_the_same_table() -> None:
    # B01003_001E now says something else; the "Total" row lives at B01003_002E in this fake vintage
    detailed = detailed_meta()
    detailed["B01003_001E"] = {"label": "Estimate!!Total!!Something new", "group": "B01003"}
    detailed["B01003_002E"] = {"label": "Estimate!!Total", "group": "B01003"}
    got = resolve(detailed=detailed)["B01003_001"]
    assert got.id == "B01003_002E" and got.moved


def test_an_id_that_vanished_is_found_by_label() -> None:
    detailed = detailed_meta()
    detailed["B01003_007E"] = detailed.pop("B01003_001E")
    got = resolve(detailed=detailed)["B01003_001"]
    assert got.id == "B01003_007E" and got.moved


def test_a_missing_label_fails_clearly() -> None:
    profile = {k: v for k, v in profile_meta().items() if not k.startswith("DP03_0099")}
    with pytest.raises(BuildError) as exc:
        resolve(profile=profile)
    assert exc.value.exit_code == 5
    assert "DP03_UNINS" in str(exc.value) and "no variable" in str(exc.value)


def test_an_ambiguous_label_fails_clearly_and_lists_the_candidates() -> None:
    profile = profile_meta()
    profile["DP03_0200E"] = dict(profile["DP03_0099E"])
    with pytest.raises(BuildError) as exc:
        resolve(profile=profile)
    msg = str(exc.value)
    assert "ambiguous" in msg and "DP03_0099E" in msg and "DP03_0200E" in msg


def test_a_bracket_cell_that_is_missing_fails_clearly() -> None:
    detailed = detailed_meta()
    del detailed["B19001_003E"]
    with pytest.raises(BuildError, match="B19001_003"):
        resolve(detailed=detailed)


def test_a_bracket_whose_label_no_longer_matches_its_expected_bounds_fails() -> None:
    detailed = detailed_meta()
    detailed["B19001_003E"]["label"] = "Estimate!!Total:!!$10,000 to $12,499"  # a new split
    with pytest.raises(BuildError) as exc:
        resolve(detailed=detailed)
    assert "B19001_003" in str(exc.value) and "$12,499" in str(exc.value)


def test_a_bracket_cell_with_an_unparseable_label_fails() -> None:
    detailed = detailed_meta()
    detailed["B19001_004E"]["label"] = "Estimate!!Total:!!Prosperous"
    with pytest.raises(BuildError, match="B19001_004"):
        resolve(detailed=detailed)


def test_resolution_is_deterministic_and_json_serializable() -> None:
    got = resolve()
    payload = {k: v.as_metadata() for k, v in got.items()}
    assert json.loads(json.dumps(payload)) == payload
    assert payload["B01003_001"] == {
        "id": "B01003_001E",
        "label": "Estimate!!Total",
        "table": "B01003",
        "dataset": "detailed",
        "moved": False,
    }
    assert list(resolve()) == list(got)
