"""Restricted mode in the UI: the controls are absent, not just disabled (SPEC 5.7, 9.2)."""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from synth_art import make_artifacts, write_data_dir
from ui.conftest import APP, GEO, WORLD
from ui.helpers import AUTO, MORTGAGE, RETAIL, go_step2, go_step4, labels, texts

from zipographics import data, restricted

NewApp = Callable[[], AppTest]
TEXT = "33606 33602 33603 99999"


def restricted_app(new_app: NewApp, industry: str, answer: str | None) -> AppTest:
    return go_step4(new_app(), TEXT, industry, answer)


@pytest.fixture(params=[(MORTGAGE, None), (AUTO, "Yes")], ids=["forced", "answered"])
def at(request, new_app: NewApp) -> AppTest:  # type: ignore[no-untyped-def]
    industry, answer = request.param
    return restricted_app(new_app, industry, answer)


def test_the_banner_is_shown_at_the_top(at: AppTest) -> None:
    assert any(restricted.BANNER_TITLE in str(w.value) for w in at.warning)
    assert "Restricted mode is on" in " ".join(str(w.value) for w in at.warning)


def test_there_is_no_filter_builder_no_presets_and_no_exclude_or_only_matching(at: AppTest) -> None:
    keys = [b.key for b in at.button]
    assert not any(k.startswith("preset_") for k in keys) and "add_rule" not in keys
    assert not any(k.startswith("r_") for k in keys)
    assert "Filter ZIPs" not in texts(at)
    assert not [s for s in at.selectbox if s.key.startswith("r_")]
    assert not [c for c in at.checkbox if c.key == "exclude_unreliable"]
    assert not [t for t in at.toggle if t.key == "only_matching"]


def test_there_is_no_index_toggle_and_no_sort_by_metric(at: AppTest) -> None:
    assert not [r for r in at.radio if r.key == "show_index"]
    assert not [s for s in at.selectbox if s.key == "sort_by"]
    order = at.radio(key="order_restricted")
    assert list(order.options) == ["As entered", "By ZIP"]  # the only two orderings


def test_the_lens_is_the_context_lens_and_cannot_be_changed(at: AppTest) -> None:
    assert not [s for s in at.selectbox if s.key == "lens_box"]
    fixed = at.text_input(key="lens_fixed")
    assert fixed.value == "Context" and fixed.disabled
    assert labels(at.metric)[-3:] == ["Housing units", "Vacancy rate", "Renters"]


def test_the_table_is_static_not_a_sortable_grid(at: AppTest) -> None:
    assert len(at.table) == 1
    table_frame = at.table[0].value
    assert list(table_frame["ZIP"]) == ["33606", "33602", "33603"]
    # the only dataframes left are the chart data tables, none of which is the ZIP table
    assert not any("ZIP" in df.value.columns and "City" in df.value.columns for df in at.dataframe)


def test_by_zip_order_is_available_and_sorts_only_by_the_zip(at: AppTest) -> None:
    at.radio(key="order_restricted").set_value("zip").run()
    assert list(at.table[0].value["ZIP"]) == ["33602", "33603", "33606"]
    at.checkbox(key="descending").set_value(True).run()
    assert list(at.table[0].value["ZIP"]) == ["33606", "33603", "33602"]


def test_the_zip_list_is_exactly_the_input(at: AppTest) -> None:
    codes = [str(c.value) for c in at.code]
    assert "33606, 33602, 33603, 99999" in codes and "33606\n33602\n33603\n99999" in codes
    assert restricted.AD_PLATFORM_NOTICE in " ".join(str(w.value) for w in at.warning)
    assert not [c for c in at.checkbox if c.key == "export_all"]  # nothing to choose between


def test_the_attestation_says_restricted_mode_is_on(at: AppTest) -> None:
    assert "Attestation recorded with this export" in [e.label for e in at.expander]
    body = " ".join(str(m.value) for m in at.markdown)
    assert "Restricted mode: on" in body or "Restricted mode: on" in " ".join(
        str(x.value) for e in at.expander for x in e.markdown
    )


def test_kpi_cards_and_charts_are_still_shown_as_context(at: AppTest) -> None:
    assert len(at.metric) >= 8 and len(at.get("vega_lite_chart")) >= 4


def test_the_map_is_neutral(at: AppTest) -> None:
    assert "one neutral fill" in texts(at)
    assert not [s for s in at.selectbox if s.key == "map_metric"]  # no metric chooses a color


def test_an_unrestricted_run_does_have_the_controls(new_app: NewApp) -> None:
    at = go_step4(new_app(), TEXT, RETAIL, "No")
    assert "add_rule" in [b.key for b in at.button]
    assert [r for r in at.radio if r.key == "show_index"] and [
        s for s in at.selectbox if s.key == "sort_by"
    ]
    assert [s for s in at.selectbox if s.key == "map_metric"]


# ------------------------------------------------------------------------------ data problems
def test_missing_data_shows_the_build_instruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZIPOGRAPHICS_DATA_DIR", str(tmp_path / "nothing"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("build_data.py" in str(e.value) for e in at.error)
    assert not at.selectbox  # nothing past the error is drawn


def test_missing_geometry_gets_an_explanation_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = write_data_dir(make_artifacts(WORLD), tmp_path / "nogeo", None)
    monkeypatch.setenv("ZIPOGRAPHICS_DATA_DIR", str(folder))
    at = go_step4(AppTest.from_file(APP, default_timeout=60).run(), "33602 33606")
    assert not at.exception
    assert "The map is unavailable" in texts(at)


def test_a_zip_without_a_polygon_is_mentioned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    partial = GEO[GEO["zip"].isin(["33602"])]
    folder = write_data_dir(make_artifacts(WORLD), tmp_path / "partial", partial)
    monkeypatch.setenv("ZIPOGRAPHICS_DATA_DIR", str(folder))
    at = go_step4(AppTest.from_file(APP, default_timeout=60).run(), "33602 33606")
    assert "1 of 2 ZIPs have no boundary" in texts(at)


def test_the_app_still_loads_the_data_the_library_loads(data_dir: Path) -> None:
    assert data.load(data_dir).geo is not None  # the fixture folder is a valid data folder


# ------------------------------------------------------------------------------ no network, no key
def test_the_app_file_imports_nothing_that_could_reach_the_network_or_the_key() -> None:
    tree = ast.parse(Path(APP).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names |= {f"{node.module}.{a.name}" for a in node.names}
    banned = (
        "requests",
        "urllib3",
        "http.client",
        "socket",
        "dotenv",
        "census_api",
        "data_build",
        "redact",
    )
    assert not [n for n in names if any(part in n.split(".") for part in banned)]


def test_the_app_never_reads_environment_variables_for_the_key() -> None:
    text = Path(APP).read_text(encoding="utf-8")
    assert "CENSUS_API_KEY" not in text and "os.environ" not in text and "getenv" not in text


def test_the_steps_do_not_raise_when_walked_in_order(new_app: NewApp) -> None:
    at = go_step2(new_app())
    assert not at.exception
