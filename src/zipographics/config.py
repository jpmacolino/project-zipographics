"""Constants shared across the library (SPEC §5.2, §5.4, §7).

Thresholds that counsel or the owner may want to change live here, in one place.
"""

from __future__ import annotations

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
