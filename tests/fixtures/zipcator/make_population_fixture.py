"""Generate the SYNTHETIC with-population Zipcator export fixtures.

Zipcator's current data build has no population, so its real exports lack the
``Population`` / ``Est. pop in radius`` columns. To cover that header shape this script runs
Zipcator's own ``zipcator.export.csv_bytes`` on a synthetic search result (made-up geometry and
populations; real ZIP strings, including leading zeros, an accent and a quoted comma in a city).

It is NOT part of the Zipographics package or its tests. Run it from the Zipcator repo so its
virtualenv and test kit are importable (it writes nothing inside the Zipcator repo)::

    cd C:\\dev\\project-zipcator
    uv run python <zipographics>\\tests\\fixtures\\zipcator\\make_population_fixture.py \\
        <zipographics>\\tests\\fixtures\\zipcator

Mirrors ``_result()`` in Zipcator's ``tests/unit/test_export.py`` at commit 6d9ad8a.
"""

from __future__ import annotations

import sys
from pathlib import Path

ZIPCATOR_ROOT = Path.cwd()
sys.path.insert(0, str(ZIPCATOR_ROOT / "tests"))

from shapely.geometry import box  # noqa: E402
from zc_testkit.synth import TAMPA, make_gdf  # noqa: E402
from zipcator import export  # noqa: E402
from zipcator.search import find_zips  # noqa: E402


def main(out_dir: Path) -> None:
    zones = {
        "02108": box(-1000, -1000, 1000, 1000),  # home, leading zero
        "00501": box(3000, 3000, 6000, 6000),  # leading zeros
        "33602": box(0, 14_000, 20_000, 34_000),  # partial overlap
    }
    pops = {"02108": 3500, "00501": 600, "33602": 10_000}
    gdf = make_gdf(zones, TAMPA, population=pops)
    gdf.loc[gdf["zip"] == "00501", "city"] = 'Mayagüez, "Quoted"'
    result = find_zips(gdf, TAMPA, 10)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "synthetic_population.csv").write_bytes(export.csv_bytes(result))
    (out_dir / "synthetic_population_excel.csv").write_bytes(
        export.csv_bytes(result, excel_safe=True)
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
