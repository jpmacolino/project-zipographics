"""Constants shared across the library (SPEC §5.2, §5.4, §7).

Thresholds that counsel or the owner may want to change live here, in one place.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Maximum distinct valid ZIPs per run (SPEC §5.2, D1).
MAX_ZIPS = 1000

#: Maximum size of an uploaded CSV (SPEC §5.2).
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: Maximum project / client name length (SPEC §5.1).
MAX_PROJECT_NAME = 80

#: Small-population flag: ZCTA population or household count below these (SPEC §6.6, D2).
SMALL_POPULATION = 1000
SMALL_HOUSEHOLDS = 300

#: How many invalid tokens / repairs the review screen lists before "and N more" (SPEC §5.2, §5.4).
SHOWN_INVALID = 20
SHOWN_REPAIRED = 10

#: Reliability tiers from the coefficient of variation, in percent (SPEC §6.6, D2). The Census
#: Bureau publishes no numeric thresholds (DECISIONS V9); these are a judgment call.
CV_GOOD = 15.0
CV_CAUTION = 30.0

#: z-score for a 90 % margin of error: SE = MOE / 1.645 (ACS General Handbook, formula 2).
Z90 = 1.645

#: Data build (SPEC §4.4). The ACS vintage is a build parameter; this is only its default.
DEFAULT_VINTAGE = 2024
#: A build with fewer ZCTA rows than this is rejected (about 33,800 exist in the 50 states, DC, PR).
MIN_ZCTA_ROWS = 33_000
#: A core KPI variable must be non-null for at least this share of ZCTAs with population > 0.
COVERAGE_FLOOR = 0.95
#: A *published median* is suppressed by the ACS for small areas (measured on the real 2020-2024
#: data: 92 % of ZCTAs with population have a published median household income, 3 % of those with
#: under 10 households), so it gets a lower floor than counts and shares (DECISIONS B16).
MEDIAN_COVERAGE_FLOOR = 0.90
#: At most this share of ZCTAs may have a primary county with no ACS county row. In 2020-2024 that
#: is Connecticut only (the ACS uses planning regions; the 2020 relationship file uses counties).
COUNTY_GAP_LIMIT = 0.02
#: Only these states may have such a gap; any other ZCTA without a county benchmark fails the build.
COUNTY_GAP_STATES = ("CT",)
#: Every registry variable must be non-null for at least this share of ZCTAs with population > 0
#: (core KPI variables and published medians have their own floors).
VARIABLE_COVERAGE_FLOOR = 0.5
#: Tables that must agree: at most this share of ZCTAs may disagree on a total two tables share.
TOTAL_DISAGREE_LIMIT = 0.005
#: The boundary file also holds island-area ZCTAs (VI, GU, MP, AS) that have no ACS data; at most
#: this many polygons without a profile row are dropped, more means the wrong file (DECISIONS B16).
MAX_GEOMETRY_EXTRA = 25
#: Metrics every dashboard leads with (SPEC §5.5); their variables are held to COVERAGE_FLOOR.
CORE_METRICS = ("pop", "hh", "median_hh_income", "owner", "hh_kids")
#: Environment variable naming Zipcator's built ``zcta.parquet`` to reuse for the map (D6).
ZIPCATOR_PARQUET_ENV = "ZIPOGRAPHICS_ZIPCATOR_PARQUET"
DATA_DIR_ENV = "ZIPOGRAPHICS_DATA_DIR"


def data_dir() -> Path:
    """The folder holding the built artifacts: ``$ZIPOGRAPHICS_DATA_DIR`` or ``<repo>/data``."""
    override = os.environ.get(DATA_DIR_ENV, "").strip()
    return Path(override) if override else Path(__file__).resolve().parents[2] / "data"
