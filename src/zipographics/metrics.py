"""The metric registry: every number the app shows, declared as data (SPEC §4.2, Appendix C).

The data build derives its variable list from here, the profile code computes metrics from
these specs, and the restricted-mode tag list (Appendix B) is the ``characteristic`` field, so
adding a metric is one entry here plus tests.

Variable keys: for detailed tables the key *is* the Census variable ID (``B19001_002``); the
build checks that the ID's label still means what we expect (bracket bounds are parsed from the
labels and compared with the bounds below; single cells carry a label regex). Data Profile items
(DP03) have symbolic keys and are resolved by ``(table, label pattern)`` at build time, because
their IDs shift between vintages (SPEC §4.2, DECISIONS D9). Parquet columns are ``<key>_e``,
``<key>_m`` and, for published medians, ``<key>_code``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Kind = Literal["count", "share", "median", "mean", "ratio"]
Unit = Literal["count", "percent", "dollars", "years", "year", "ratio"]
Tag = Literal["race_color", "national_origin", "familial_status", "age", "income", "proxy_other"]
Dataset = Literal["detailed", "profile"]

INF = math.inf


@dataclass(frozen=True, slots=True)
class Var:
    """One Census variable the build must fetch."""

    key: str
    table: str
    #: regex searched (case-insensitively) in the variable's label; None for bracket cells, whose
    #: bounds are verified through the bracket tables below.
    label: str | None = None
    is_median: bool = False  # also fetch the estimate annotation (top/bottom code)
    resolve: Literal["id", "label"] = "id"
    dataset: Dataset = "detailed"


@dataclass(frozen=True, slots=True)
class Bracket:
    """One bracket of a distribution: the cells summed into it and its [lo, hi) bounds."""

    keys: tuple[str, ...]
    lo: float
    hi: float


@dataclass(frozen=True, slots=True)
class CountSpec:
    var: str


@dataclass(frozen=True, slots=True)
class ShareSpec:
    """Σ num / Σ den, where the numerator is a subset of the denominator."""

    num: tuple[str, ...]
    den: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RatioSpec:
    """Σ w_i·num_i / Σ den (numerator not a subset): mean income, vehicles per household."""

    num: tuple[tuple[str, float], ...]
    den: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProductMeanSpec:
    """Σ(rate_i × base_i) / Σ base_i: per capita income aggregated through population."""

    rate: str
    base: str


@dataclass(frozen=True, slots=True)
class MedianSpec:
    """A median: published for one geography, interpolated from ``brackets`` for several."""

    published: str
    brackets: tuple[Bracket, ...]  # ascending, contiguous


Spec = CountSpec | ShareSpec | RatioSpec | ProductMeanSpec | MedianSpec


@dataclass(frozen=True, slots=True)
class Metric:
    id: str
    name: str
    unit: Unit
    kind: Kind
    spec: Spec
    characteristic: Tag | None
    universe: str
    help: str

    @property
    def indexable(self) -> bool:
        """Counts show their share of the benchmark's total instead of an index (SPEC §5.5)."""
        return self.kind != "count"


VARIABLES: dict[str, Var] = {}


def _t(*segments: str) -> str:
    """Regex matching a variable label that *ends* with these segments (``!!``-separated).

    ACS labels look like ``Estimate!!Total:!!Owner occupied``; parent rows carry a trailing colon.
    Matching the tail keeps the pattern readable while still telling ``Owner occupied`` from
    ``Renter occupied`` and a cell from its neighbours.
    """
    return "(?:^|!!)" + "!!".join(re.escape(s) + ":?" for s in segments) + "$"


_TOTAL = _t("Total")
# fmt: off
_VEHICLES = ["1 vehicle available", "2 vehicles available", "3 vehicles available",
             "4 vehicles available", "5 or more vehicles available"]
#: Expected label (regex) of every single-cell variable. Bracket cells are verified by their bounds
#: instead. The Phase 4 build fails with a clear message when an ID's label does not match.
_CELL_LABELS: dict[str, str] = {
    **{k: _TOTAL for k in (
        "B01003_001", "B11001_001", "B25001_001", "B25002_001", "B01001_001", "B19001_001",
        "B11005_001", "B17001_001", "B25003_001", "B25024_001", "B25034_001", "B25038_001",
        "B25044_001", "B08301_001", "B08303_001", "B23025_001", "B15003_001", "C16001_001",
        "B03003_001", "B02001_001", "B28002_001",
    )},
    "B01002_001": r"median age",
    "B19013_001": r"median household income",
    "B19025_001": r"aggregate household income",
    "B19301_001": r"per capita income",
    "B25035_001": r"median year structure built",
    "B25064_001": r"median gross rent",
    "B25077_001": r"median value",
    "B11005_002": _t("Households with one or more people under 18 years"),
    "B17001_002": _t("Income in the past 12 months below poverty level"),
    "B25002_003": _t("Vacant"),
    "B25003_002": _t("Owner occupied"),
    "B25003_003": _t("Renter occupied"),
    "B25024_002": _t("1, detached"),
    "B25024_003": _t("1, attached"),
    "B25024_004": _t("2"),
    "B25024_005": _t("3 or 4"),
    "B25024_006": _t("5 to 9"),
    "B25024_007": _t("10 to 19"),
    "B25024_008": _t("20 to 49"),
    "B25024_009": _t("50 or more"),
    "B25024_010": _t("Mobile home"),
    "B25024_011": _t("Boat, RV, van, etc."),
    **{f"B25038_{n:03d}": r"owner occupied:?!!moved in" for n in range(4, 9)},
    **{f"B25038_{n:03d}": r"renter occupied:?!!moved in" for n in range(11, 16)},
    "B25044_003": _t("Owner occupied", "No vehicle available"),
    "B25044_010": _t("Renter occupied", "No vehicle available"),
    **{f"B25044_{4 + i:03d}": _t("Owner occupied", v) for i, v in enumerate(_VEHICLES)},
    **{f"B25044_{11 + i:03d}": _t("Renter occupied", v) for i, v in enumerate(_VEHICLES)},
    "B08301_003": _t("Drove alone"),
    "B08301_004": _t("Carpooled"),
    "B08301_010": r"public transportation",
    "B08301_018": _t("Bicycle"),
    "B08301_019": _t("Walked"),
    "B08301_021": _t("Worked from home"),
    **{f"B08303_{n:03d}": _t(t) for n, t in zip(
        range(8, 14),
        ["30 to 34 minutes", "35 to 39 minutes", "40 to 44 minutes", "45 to 59 minutes",
         "60 to 89 minutes", "90 or more minutes"], strict=True)},
    "B23025_002": _t("In labor force"),
    "B23025_003": _t("In labor force", "Civilian labor force"),
    "B23025_005": _t("Civilian labor force", "Unemployed"),
    **{f"B15003_{n:03d}": _t(t) for n, t in zip(
        range(17, 26),
        ["Regular high school diploma", "GED or alternative credential",
         "Some college, less than 1 year", "Some college, 1 or more years, no degree",
         "Associate's degree", "Bachelor's degree", "Master's degree",
         "Professional school degree", "Doctorate degree"], strict=True)},
    "C16001_003": _t("Spanish"),
    "B03003_003": _t("Hispanic or Latino"),
    **{f"B02001_{n:03d}": _t(t) for n, t in zip(
        range(2, 9),
        ["White alone", "Black or African American alone",
         "American Indian and Alaska Native alone", "Asian alone",
         "Native Hawaiian and Other Pacific Islander alone", "Some other race alone",
         "Two or more races"], strict=True)},
    "B28002_004": _t("Broadband of any type"),
    "B28002_013": _t("No Internet access"),
}
# fmt: on


def _var(
    key: str,
    label: str | None = None,
    *,
    median: bool = False,
    table: str | None = None,
    resolve: Literal["id", "label"] = "id",
) -> str:
    """Register (once) and return a variable key."""
    if key not in VARIABLES:
        VARIABLES[key] = Var(
            key=key,
            table=table or key.split("_")[0],
            label=label if label is not None else _CELL_LABELS.get(key),
            is_median=median,
            resolve=resolve,
            dataset="profile" if resolve == "label" else "detailed",
        )
    return key


def _cells(table: str, *numbers: int, label: str | None = None) -> tuple[str, ...]:
    return tuple(_var(f"{table}_{n:03d}", label if len(numbers) == 1 else None) for n in numbers)


def _both_sexes(*male: int) -> tuple[str, ...]:
    """B01001 cells for the given male row numbers and the matching female rows (+24)."""
    return _cells("B01001", *male, *(n + 24 for n in male))


def _range(lo: int, hi: int) -> tuple[int, ...]:
    return tuple(range(lo, hi + 1))


# ----------------------------------------------------------------------------- brackets
_AGE_BOUNDS = [(0, 5), (5, 10), (10, 15), (15, 18), (18, 20), (20, 21), (21, 22), (22, 25),
               (25, 30), (30, 35), (35, 40), (40, 45), (45, 50), (50, 55), (55, 60), (60, 62),
               (62, 65), (65, 67), (67, 70), (70, 75), (75, 80), (80, 85), (85, INF)]  # fmt: skip
_INCOME_BOUNDS = [(0, 10_000), (10_000, 15_000), (15_000, 20_000), (20_000, 25_000),
                  (25_000, 30_000), (30_000, 35_000), (35_000, 40_000), (40_000, 45_000),
                  (45_000, 50_000), (50_000, 60_000), (60_000, 75_000), (75_000, 100_000),
                  (100_000, 125_000), (125_000, 150_000), (150_000, 200_000),
                  (200_000, INF)]  # fmt: skip
_VALUE_BOUNDS = [(0, 10_000), (10_000, 15_000), (15_000, 20_000), (20_000, 25_000),
                 (25_000, 30_000), (30_000, 35_000), (35_000, 40_000), (40_000, 50_000),
                 (50_000, 60_000), (60_000, 70_000), (70_000, 80_000), (80_000, 90_000),
                 (90_000, 100_000), (100_000, 125_000), (125_000, 150_000), (150_000, 175_000),
                 (175_000, 200_000), (200_000, 250_000), (250_000, 300_000),
                 (300_000, 400_000), (400_000, 500_000), (500_000, 750_000),
                 (750_000, 1_000_000), (1_000_000, 1_500_000), (1_500_000, 2_000_000),
                 (2_000_000, INF)]  # fmt: skip
_RENT_BOUNDS = [(0, 100), *[(lo, lo + 50) for lo in range(100, 800, 50)], (800, 900), (900, 1000),
                (1000, 1250), (1250, 1500), (1500, 2000), (2000, 2500), (2500, 3000),
                (3000, 3500), (3500, INF)]  # fmt: skip
#: B25034 rows 011 (1939 or earlier) up to 002 (2020 or later), oldest first.
_YEAR_BUILT_BOUNDS = [(-INF, 1940), (1940, 1950), (1950, 1960), (1960, 1970), (1970, 1980),
                      (1980, 1990), (1990, 2000), (2000, 2010), (2010, 2020), (2020, INF)]  # fmt: skip


def _brackets(
    table: str, numbers: tuple[int, ...], bounds: Sequence[tuple[float, float]]
) -> tuple[Bracket, ...]:
    assert len(numbers) == len(bounds)
    return tuple(
        Bracket((_var(f"{table}_{n:03d}"),), lo, hi)
        for n, (lo, hi) in zip(numbers, bounds, strict=True)
    )


_AGE_BRACKETS = tuple(
    Bracket(_both_sexes(n), lo, hi) for n, (lo, hi) in zip(_range(3, 25), _AGE_BOUNDS, strict=True)
)

# ----------------------------------------------------------------------------- shorthand
POP = _var("B01003_001")
HH = _var("B11001_001")
UNITS = _var("B25001_001")
AGE_TOTAL = _var("B01001_001")

REGISTRY_LIST: list[Metric] = []


def _add(
    id: str,
    name: str,
    unit: Unit,
    kind: Kind,
    spec: Spec,
    tag: Tag | None,
    universe: str,
    help: str,
) -> None:
    REGISTRY_LIST.append(Metric(id, name, unit, kind, spec, tag, universe, help))


def _share(
    id: str,
    name: str,
    tag: Tag | None,
    num: tuple[str, ...],
    den: tuple[str, ...],
    universe: str,
    help: str,
) -> None:
    _add(id, name, "percent", "share", ShareSpec(num, den), tag, universe, help)


# ----------------------------------------------------------------------------- totals
_add("pop", "Population", "count", "count", CountSpec(POP), None, "total population",
     "Total population of the ZIP code tabulation area (ACS B01003).")  # fmt: skip
_add("hh", "Households", "count", "count", CountSpec(HH), None, "households",
     "Occupied housing units (ACS B11001).")  # fmt: skip
_add("units", "Housing units", "count", "count", CountSpec(UNITS), None, "housing units",
     "All housing units, occupied or vacant (ACS B25001).")  # fmt: skip
_share("vacancy", "Vacancy rate", None, _cells("B25002", 3), _cells("B25002", 1),
       "housing units", "Share of housing units that are vacant (ACS B25002).")  # fmt: skip

# ----------------------------------------------------------------------------- age (B01001)
_AGE_DEN = (AGE_TOTAL,)
for _id, _name, _rows in [
    ("age_0_17", "Under 18", (3, 4, 5, 6)),
    ("age_18_24", "Age 18-24", (7, 8, 9, 10)),
    ("age_25_34", "Age 25-34", (11, 12)),
    ("age_35_44", "Age 35-44", (13, 14)),
    ("age_45_54", "Age 45-54", (15, 16)),
    ("age_55_64", "Age 55-64", (17, 18, 19)),
    ("age_65_74", "Age 65-74", (20, 21, 22)),
    ("age_75p", "Age 75 and over", (23, 24, 25)),
    ("age_18_34", "Age 18-34", (7, 8, 9, 10, 11, 12)),
    ("age_18_44", "Age 18-44", (7, 8, 9, 10, 11, 12, 13, 14)),
    ("age_65p", "Age 65 and over", (20, 21, 22, 23, 24, 25)),
]:
    _share(_id, _name, "age", _both_sexes(*_rows), _AGE_DEN, "total population",
           f"Share of the population aged {_name.lower().replace('age ', '')} (ACS B01001, both sexes combined).")  # fmt: skip
_share("age_0_4", "Children under 5", "familial_status", _both_sexes(3), _AGE_DEN,
       "total population", "Share of the population under 5 years (ACS B01001).")  # fmt: skip
_share("age_5_17", "School-age (5-17)", "familial_status", _both_sexes(4, 5, 6), _AGE_DEN,
       "total population", "Share of the population aged 5 to 17 (ACS B01001).")  # fmt: skip
_add("median_age", "Median age", "years", "median",
     MedianSpec(_var("B01002_001", median=True), _AGE_BRACKETS), "age", "total population",
     "Single ZIP: the published median age. Several ZIPs: estimated from age brackets.")  # fmt: skip

# ----------------------------------------------------------------------------- families
_share("hh_kids", "Households with children", "familial_status", _cells("B11005", 2),
       _cells("B11005", 1), "households",
       "Households with one or more people under 18 (ACS B11005).")  # fmt: skip
_share(
    "working_parents_u6",
    "Working parents of young children",
    "familial_status",
    (
        _var(
            "DP03_OWN_U6_ALLLF",
            r"^estimate!!.*own children.*under 6 years!!all parents in family in labor force$",
            table="DP03",
            resolve="label",
        ),
    ),
    (
        _var(
            "DP03_OWN_U6",
            r"^estimate!!.*own children.*under 6 years$",
            table="DP03",
            resolve="label",
        ),
    ),
    "own children under 6",
    "Own children under 6 whose parents are all in the labor force (ACS Data Profile DP03).",
)

# ----------------------------------------------------------------------------- income (B19001...)
_INC = _range(2, 17)
_INC_DEN = _cells("B19001", 1)
_brackets("B19001", _INC, _INCOME_BOUNDS)  # registers the 16 bracket variables
for _id, _name, _rows in [
    ("inc_lt25", "Income under $25k", _range(2, 5)),
    ("inc_25_50", "Income $25-50k", _range(6, 10)),
    ("inc_50_75", "Income $50-75k", (11, 12)),
    ("inc_75_100", "Income $75-100k", (13,)),
    ("inc_100_150", "Income $100-150k", (14, 15)),
    ("inc_150_200", "Income $150-200k", (16,)),
    ("inc_200p", "Income $200k+", (17,)),
    ("inc_75p", "Income $75k+", _range(13, 17)),
    ("inc_100p", "Income $100k+", _range(14, 17)),
    ("inc_150p", "Income $150k+", _range(16, 17)),
]:
    _share(_id, _name, "income", _cells("B19001", *_rows), _INC_DEN, "households",
           f"Share of households with annual income in this band: {_name.removeprefix('Income ')} (ACS B19001).")  # fmt: skip
_add("median_hh_income", "Median household income", "dollars", "median",
     MedianSpec(_var("B19013_001", median=True), _brackets("B19001", _INC, _INCOME_BOUNDS)),
     "income", "households",
     "Single ZIP: the published median. Several ZIPs: estimated from income brackets.")  # fmt: skip
_add("mean_hh_income", "Mean household income", "dollars", "mean",
     RatioSpec(((_var("B19025_001"), 1.0),), (HH,)), "income", "households",
     "Aggregate household income divided by households (ACS B19025 / B11001).")  # fmt: skip
_add("per_capita_income", "Per capita income", "dollars", "mean",
     ProductMeanSpec(_var("B19301_001"), POP), "income", "total population",
     "Per capita income, combined across ZIPs by weighting with population (approximate).")  # fmt: skip
_share("poverty", "Below poverty", "income", _cells("B17001", 2), _cells("B17001", 1),
       "population for whom poverty is determined",
       "Share of people below the poverty level in the past 12 months (ACS B17001).")  # fmt: skip

# ----------------------------------------------------------------------------- housing
_share("owner", "Homeowners", "proxy_other", _cells("B25003", 2), _cells("B25003", 1),
       "occupied housing units", "Share of occupied units that are owner-occupied (ACS B25003).")  # fmt: skip
_share("renter", "Renters", "proxy_other", _cells("B25003", 3), _cells("B25003", 1),
       "occupied housing units", "Share of occupied units that are renter-occupied (ACS B25003).")  # fmt: skip
_VALUE = _range(2, 27)
_add("median_value", "Median home value", "dollars", "median",
     MedianSpec(_var("B25077_001", median=True), _brackets("B25075", _VALUE, _VALUE_BOUNDS)),
     "proxy_other", "owner-occupied units",
     "Single ZIP: the published median. Several ZIPs: estimated from value brackets.")  # fmt: skip
_RENT = _range(3, 26)  # 002 "with cash rent" and 027 "no cash rent" are not brackets
_add("median_rent", "Median gross rent", "dollars", "median",
     MedianSpec(_var("B25064_001", median=True), _brackets("B25063", _RENT, _RENT_BOUNDS)),
     "proxy_other", "renter units paying cash rent",
     "Single ZIP: the published median. Several ZIPs: estimated from rent brackets.")  # fmt: skip
_B34_DEN = _cells("B25034", 1)
_brackets("B25034", _range(2, 11), list(reversed(_YEAR_BUILT_BOUNDS)))  # registers the cells
for _id, _name, _rows in [
    ("built_2010p", "Built 2010 or later", (2, 3)),
    ("built_1980_2009", "Built 1980-2009", (4, 5, 6)),
    ("built_1960_1979", "Built 1960-1979", (7, 8)),
    ("built_pre1960", "Built before 1960", (9, 10, 11)),
    ("built_pre1980", "Built before 1980", (7, 8, 9, 10, 11)),
]:
    _share(_id, _name, "proxy_other", _cells("B25034", *_rows), _B34_DEN, "housing units",
           f"Share of housing units: {_name.lower()} (ACS B25034).")  # fmt: skip
_add("median_year_built", "Median year built", "year", "median",
     MedianSpec(
         _var("B25035_001", median=True),
         tuple(
             Bracket((f"B25034_{n:03d}",), lo, hi)
             for n, (lo, hi) in zip(range(11, 1, -1), _YEAR_BUILT_BOUNDS, strict=True)
         ),
     ),
     "proxy_other", "housing units",
     "Single ZIP: the published median. Several ZIPs: estimated from year-built brackets.")  # fmt: skip
_share("single_family", "Single-family homes", "proxy_other", _cells("B25024", 2, 3),
       _cells("B25024", 1), "housing units",
       "Share of units that are 1-unit detached or attached (ACS B25024).")  # fmt: skip
_share("mobile_home", "Mobile homes", "proxy_other", _cells("B25024", 10), _cells("B25024", 1),
       "housing units", "Share of units that are mobile homes (ACS B25024).")  # fmt: skip
_share(
    "new_movers",
    "Moved in: most recent period",
    "proxy_other",
    (
        _var("B25038_003", r"owner occupied:?!!moved in \d{4} or later"),
        _var("B25038_010", r"renter occupied:?!!moved in \d{4} or later"),
    ),
    _cells("B25038", 1),
    "occupied housing units",
    "Share of households whose householder moved in during the most recent ACS period (ACS "
    "B25038). The period's label (for example '2023 or later') comes from the data's variable "
    "labels and moves with each vintage.",
)

# ----------------------------------------------------------------------------- vehicles
_VEH_WEIGHTS = [(4, 1), (5, 2), (6, 3), (7, 4), (8, 5), (11, 1), (12, 2), (13, 3), (14, 4), (15, 5)]
_add("veh_per_hh", "Vehicles per household", "ratio", "ratio",
     RatioSpec(tuple((_var(f"B25044_{n:03d}"), float(w)) for n, w in _VEH_WEIGHTS),
               _cells("B25044", 1)),
     "proxy_other", "occupied housing units",
     "At least this many vehicles per household: '5 or more' is counted as 5 (ACS B25044).")  # fmt: skip
_share("veh_0", "No vehicle", "proxy_other", _cells("B25044", 3, 10), _cells("B25044", 1),
       "occupied housing units", "Share of households with no vehicle available (ACS B25044).")  # fmt: skip
_share("veh_2p", "2+ vehicles", "proxy_other", _cells("B25044", 5, 6, 7, 8, 12, 13, 14, 15),
       _cells("B25044", 1), "occupied housing units",
       "Share of households with two or more vehicles (ACS B25044).")  # fmt: skip

# ----------------------------------------------------------------------------- commuting, work
_C1 = _cells("B08301", 1)
for _id, _name, _rows, _help in [
    ("commute_drive_alone", "Drive alone", (3,), "drive to work alone"),
    ("commute_carpool", "Carpool", (4,), "carpool to work"),
    ("commute_transit", "Public transit", (10,), "use public transportation"),
    ("commute_walk_bike", "Walk or bike", (18, 19), "walk or bike to work"),
    ("wfh", "Work from home", (21,), "work from home"),
]:
    _share(_id, _name, "proxy_other", _cells("B08301", *_rows), _C1, "workers 16 and over",
           f"Share of workers who {_help} (ACS B08301).")  # fmt: skip
_share("commute_30p", "Commute 30+ minutes", "proxy_other", _cells("B08303", *_range(8, 13)),
       _cells("B08303", 1), "workers who commute",
       "Share of commuters whose travel time to work is 30 minutes or more (ACS B08303).")  # fmt: skip
_share("lfpr", "Labor force participation", "proxy_other", _cells("B23025", 2),
       _cells("B23025", 1), "population 16 and over",
       "Share of people 16 and over in the labor force (ACS B23025).")  # fmt: skip
_share("unemployment", "Unemployment rate", "proxy_other", _cells("B23025", 5),
       _cells("B23025", 3), "civilian labor force",
       "Share of the civilian labor force that is unemployed (ACS B23025).")  # fmt: skip

# ----------------------------------------------------------------------------- education
_E1 = _cells("B15003", 1)
for _id, _name, _rows, _help in [
    ("hs_plus", "High school or higher", _range(17, 25), "a high school diploma or more"),
    ("ba_plus", "Bachelor's or higher", _range(22, 25), "a bachelor's degree or more"),
    ("grad", "Graduate degree", _range(23, 25), "a graduate or professional degree"),
]:
    _share(_id, _name, "proxy_other", _cells("B15003", *_rows), _E1, "population 25 and over",
           f"Share of people 25 and over with {_help} (ACS B15003).")  # fmt: skip

# ----------------------------------------------------------------------------- language, origin
_share("spanish_home", "Spanish at home", "national_origin", _cells("C16001", 3),
       _cells("C16001", 1), "population 5 and over",
       "Share of people 5 and over who speak Spanish at home (ACS C16001).")  # fmt: skip
_share(
    "limited_english",
    "Limited English",
    "national_origin",
    tuple(
        _var(f"C16001_{n:03d}", r'less than "?very well"?')
        for n in (5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35, 38)
    ),
    _cells("C16001", 1),
    "population 5 and over",
    "Share of people 5 and over who speak English less than 'very well' (ACS C16001).",
)
_share("hispanic", "Hispanic or Latino", "national_origin", _cells("B03003", 3),
       _cells("B03003", 1), "total population",
       "Hispanic origin is a separate question from race; Hispanic people can be of any race.")  # fmt: skip
for _id, _name, _row in [
    ("race_white", "White alone", 2),
    ("race_black", "Black or African American alone", 3),
    ("race_aian", "American Indian and Alaska Native alone", 4),
    ("race_asian", "Asian alone", 5),
    ("race_nhpi", "Native Hawaiian and Other Pacific Islander alone", 6),
    ("race_other", "Some other race alone", 7),
    ("race_two_plus", "Two or more races", 8),
]:
    _share(_id, _name, "race_color", _cells("B02001", _row), _cells("B02001", 1),
           "total population",
           f"Share of the population: {_name} (ACS B02001). Hispanic origin is separate.")  # fmt: skip

# ----------------------------------------------------------------------------- internet, insurance
_share("broadband", "Broadband subscription", "proxy_other", _cells("B28002", 4),
       _cells("B28002", 1), "households",
       "Share of households with a broadband internet subscription of any type (ACS B28002).")  # fmt: skip
_share("no_internet", "No internet access", "proxy_other", _cells("B28002", 13),
       _cells("B28002", 1), "households",
       "Share of households with no internet access (ACS B28002).")  # fmt: skip
_share(
    "uninsured",
    "No health insurance",
    "proxy_other",
    (
        _var(
            "DP03_UNINS",
            r"^estimate!!health insurance coverage!!civilian noninstitutionalized population!!no health insurance coverage$",
            table="DP03",
            resolve="label",
        ),
    ),
    (
        _var(
            "DP03_CIVNONINST",
            r"^estimate!!health insurance coverage!!civilian noninstitutionalized population$",
            table="DP03",
            resolve="label",
        ),
    ),
    "civilian noninstitutionalized population",
    "Share of the civilian noninstitutionalized population with no health insurance (ACS DP03).",
)

# ----------------------------------------------------------------------------- chart categories
# Appendix D lens charts: units in structure, tenure by move-in, vehicles available. SPEC §4.3 stores
# registry variables only, so every cell a chart needs is a registry metric (DECISIONS B17). Each
# group partitions its universe: with single_family, mobile_home and new_movers, veh_0 above.
_U = _cells("B25024", 1)
for _id, _name, _rows in [
    ("units_2_4", "2-4 unit buildings", (4, 5)),
    ("units_5_19", "5-19 unit buildings", (6, 7)),
    ("units_20p", "20+ unit buildings", (8, 9)),
    ("units_other", "Boat, RV, van, etc.", (11,)),
]:
    _share(_id, _name, "proxy_other", _cells("B25024", *_rows), _U, "housing units",
           f"Share of housing units that are {_name.lower()} (ACS B25024).")  # fmt: skip
_M = _cells("B25038", 1)
for _id, _name, _own, _rent in [
    ("movers_2", "Moved in: 2nd most recent period", (4,), (11,)),
    ("movers_3", "Moved in: 3rd most recent period", (5,), (12,)),
    ("movers_4", "Moved in: 4th most recent period", (6,), (13,)),
    ("movers_older", "Moved in: before that", (7, 8), (14, 15)),
]:
    _share(_id, _name, "proxy_other", _cells("B25038", *_own, *_rent), _M, "occupied housing units",
           "Share of households by when the householder moved in (ACS B25038); the period's "
           "label comes from the data's variable labels.")  # fmt: skip
_V = _cells("B25044", 1)
for _id, _name, _rows in [
    ("veh_1", "1 vehicle", (4, 11)),
    ("veh_2", "2 vehicles", (5, 12)),
    ("veh_3p", "3+ vehicles", (6, 7, 8, 13, 14, 15)),
]:
    _share(_id, _name, "proxy_other", _cells("B25044", *_rows), _V, "occupied housing units",
           f"Share of households with {_name.lower()} available (ACS B25044).")  # fmt: skip

# ----------------------------------------------------------------------------- public API
REGISTRY: tuple[Metric, ...] = tuple(REGISTRY_LIST)
BY_ID: dict[str, Metric] = {x.id: x for x in REGISTRY}


def variable_keys(metric: Metric) -> tuple[str, ...]:
    """Every variable key a metric reads."""
    spec = metric.spec
    if isinstance(spec, CountSpec):
        return (spec.var,)
    if isinstance(spec, ShareSpec):
        return (*spec.num, *spec.den)
    if isinstance(spec, RatioSpec):
        return (*(k for k, _ in spec.num), *spec.den)
    if isinstance(spec, ProductMeanSpec):
        return (spec.rate, spec.base)
    return (spec.published, *(k for b in spec.brackets for k in b.keys))
