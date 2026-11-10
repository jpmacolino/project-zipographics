"""AppTest fixtures: the app runs against a tiny synthetic data folder, never the real ``data/``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box
from streamlit.testing.v1 import AppTest
from synth_art import Z, make_artifacts, write_data_dir

ROOT = Path(__file__).resolve().parents[2]
APP = str(ROOT / "app" / "streamlit_app.py")

WORLD = {
    "33602": Z(5000, 2000, owner=0.40, kids=0.20),
    "33606": Z(8000, 3500, owner=0.70, kids=0.35),
    "33603": Z(900, 280, owner=0.55, kids=0.30, extra={"B25003_002": (154.0, 200.0)}),
    "33605": Z(4000, 1500, owner=0.20, kids=0.25, income=250_001, code="top"),
    "02108": Z(3794, 1973, owner=0.51, kids=0.10, state="MA", county=("25025", "Suffolk County"),
              city="Boston", income=212_928),
    "30301": Z(3000, 1200, owner=0.50, state="GA", county=("13121", "Fulton County"),
              city="Atlanta"),
}  # fmt: skip
GEO = gpd.GeoDataFrame(
    {"zip": list(WORLD)},
    geometry=[box(-82.5 + 0.1 * i, 27.9, -82.4 + 0.1 * i, 28.0) for i in range(len(WORLD))],
    crs="EPSG:4326",
)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return write_data_dir(make_artifacts(WORLD), tmp_path / "data", GEO)


@pytest.fixture
def new_app(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[], AppTest]:
    monkeypatch.setenv("ZIPOGRAPHICS_DATA_DIR", str(data_dir))

    def make() -> AppTest:
        return AppTest.from_file(APP, default_timeout=60).run()

    return make
