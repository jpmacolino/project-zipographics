"""The CLI end to end on the real built data (marker ``data``; Phase 5 exit criterion)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from zipographics import cli, config

pytestmark = pytest.mark.data
DATA = config.data_dir()
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

if not (DATA / "zcta_profile.parquet").exists():  # pragma: no cover - only without a build
    pytest.skip("data/ has not been built (run scripts/build_data.py)", allow_module_level=True)

BOSTON = ["02108", "02109", "02110", "02111", "02113", "02114", "02115", "02116"]
MANGLED = [z.lstrip("0") for z in BOSTON]  # what Excel does to a ZIP column
HOME = ["--vertical", "Home services", "--restricted", "no"]


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, out=out, err=err, now=NOW)
    return code, out.getvalue(), err.getvalue()


def test_a_pasted_and_an_excel_mangled_list_give_identical_profiles() -> None:
    _, good, _ = run(["profile", *BOSTON, *HOME])
    code, mangled, _ = run(["profile", *MANGLED, *HOME])
    assert code == 0 and "8 repaired" in mangled
    kpis = lambda text: [x for x in text.splitlines() if x.startswith("  ")]  # noqa: E731
    assert kpis(good) == kpis(mangled) and kpis(good)
    assert "Benchmark: Massachusetts (state)" in good


def test_the_trade_area_population_is_the_sum_of_the_zctas() -> None:
    prof = pd.read_parquet(DATA / "zcta_profile.parquet").set_index("zip")
    expected = int(prof.loc[BOSTON, "B01003_001_e"].sum())
    _, out, _ = run(["profile", *BOSTON, *HOME])
    assert f"{expected:,}" in out


def test_a_restricted_vertical_is_locked_and_its_outputs_are_input_ordered(tmp_path: Path) -> None:
    zips = ["33606", "33602", "33609"]
    csv, html = tmp_path / "r.csv", tmp_path / "r.html"
    code, out, _ = run(
        [
            "profile",
            *zips,
            "--vertical",
            "Mortgage & lending",
            "--csv",
            str(csv),
            "--report",
            str(html),
        ]
    )
    assert code == 0 and "Restricted mode: on" in out and "Yes (set by industry)" in out
    text = csv.read_bytes().decode("utf-8")
    assert text.index("33606") < text.index("33602") < text.index("33609")
    assert "Qualifies" not in text.splitlines()[0] and "Restricted mode: on" in text
    page = html.read_text(encoding="utf-8")
    assert "Restricted mode is on." in page and 'id="filters"' not in page


def test_the_excel_csv_keeps_boston_zips_with_their_zeros(tmp_path: Path) -> None:
    path = tmp_path / "b.csv"
    code, _, _ = run(["profile", *BOSTON, *HOME, "--csv", str(path), "--excel"])
    raw = path.read_bytes()
    assert code == 0 and raw.startswith(b"\xef\xbb\xbf") and b'"=""02108"""' in raw


def test_the_report_is_self_contained_with_the_real_map(tmp_path: Path) -> None:
    path = tmp_path / "r.html"
    code, _, _ = run(["profile", *BOSTON, *HOME, "--project", "Boston", "--report", str(path)])
    html = path.read_text(encoding="utf-8")
    assert code == 0 and "<script" not in html and html.count("<svg") >= 6
    assert "map is unavailable" not in html and len(html) < 2_000_000


def test_puerto_rico_zips_are_repaired_and_get_the_pr_benchmark() -> None:
    code, out, _ = run(["profile", "601", "603", "610", "612", *HOME])
    assert code == 0 and "4 repaired" in out and "Benchmark: Puerto Rico" in out


def test_a_single_zip_report_renders_with_the_real_map(tmp_path: Path) -> None:
    # Phase 5 QA HIGH 1: one ZIP (one distinct map value) crashed the report with an IndexError
    path = tmp_path / "one.html"
    code, _, err = run(["profile", "33602", *HOME, "--report", str(path)])
    html = path.read_text(encoding="utf-8")
    section = html.split('id="map"')[1].split("</section>")[0]
    assert code == 0 and err == "" and "<svg" in section


def test_zips_with_null_values_render_with_the_real_map(tmp_path: Path) -> None:
    # Phase 5 QA HIGH 2: ZIPs with no median age / owner share mixed with valid ones crashed it
    path = tmp_path / "nulls.html"
    code, _, err = run(
        ["profile", "08095", "10199", "33602", "33606", *HOME, "--report", str(path)]
    )
    section = path.read_text(encoding="utf-8").split('id="map"')[1].split("</section>")[0]
    assert code == 0 and err == "" and "<svg" in section


def test_a_thousand_real_zips_render_a_report_and_a_csv_quickly(tmp_path: Path) -> None:
    import time

    prof = pd.read_parquet(DATA / "zcta_profile.parquet", columns=["zip", "B01003_001_e"])
    zips = list(prof.loc[prof["B01003_001_e"] > 0, "zip"].sample(1000, random_state=3))
    f = tmp_path / "zips.txt"
    f.write_text("\n".join(zips), encoding="utf-8")
    html, csv = tmp_path / "big.html", tmp_path / "big.csv"
    start = time.perf_counter()
    code, _, err = run(
        ["profile", "--file", str(f), *HOME, "--report", str(html), "--csv", str(csv)]
    )
    assert code == 0 and err == "" and time.perf_counter() - start < 30
    assert html.read_text(encoding="utf-8").count("<tr") >= 1000
