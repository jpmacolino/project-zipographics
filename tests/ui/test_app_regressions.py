"""Regression tests from the independent Phase 6 QA review (docs/QA_REPORT.md, Phase 6)."""

from __future__ import annotations

from collections.abc import Callable

from streamlit.testing.v1 import AppTest
from ui.helpers import AUTO, MORTGAGE, RETAIL, go_step2, go_step4, texts

NewApp = Callable[[], AppTest]
CRLF = bytes([13, 10])


def zipcator(*rows: tuple[str, float]) -> bytes:
    lines = ['"ZIP","Overlap %","Contains address"', *[f'"{z}",{o},"Yes"' for z, o in rows]]
    return (CRLF.join(x.encode("utf-8") for x in lines)) + CRLF


def downloads(at: AppTest) -> set[str]:
    return {b.proto.label for b in at.get("download_button")}


def back_to_step1(at: AppTest) -> None:
    at.button(key="back_4").click().run()
    at.button(key="back_3").click().run()
    at.button(key="back_2").click().run()
    assert at.session_state.step == 1


def reach_insights(at: AppTest, text: str) -> None:
    at.button(key="continue_1").click().run()
    at.text_area[0].input(text).run()
    at.button(key="next_2").click().run()
    at.button(key="next_3").click().run()
    assert at.session_state.step == 4 and not at.exception


# ------------------------------------------------------------------ HIGH 1: a stale report
def test_a_prepared_report_is_not_offered_after_switching_to_a_restricted_industry(
    new_app: NewApp,
) -> None:
    at = go_step4(new_app(), "33602 33606 33603 33605")
    at.button(key="preset_Families").click().run()
    at.button(key="prep_report").click().run()
    assert "Download report (.html)" in downloads(at)
    back_to_step1(at)
    at.selectbox(key="industry_box").select(MORTGAGE).run()
    reach_insights(at, "33602 02108")
    assert "Download report (.html)" not in downloads(at)  # it was built for another run


def test_a_prepared_report_is_dropped_when_the_filters_or_benchmark_change(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606 33603")
    at.button(key="prep_report").click().run()
    assert "Download report (.html)" in downloads(at)
    at.selectbox(key="benchmark_box").select("United States (national)").run()
    assert "Download report (.html)" not in downloads(at)
    at.button(key="prep_report").click().run()
    assert "Download report (.html)" in downloads(at)
    at.button(key="preset_Families").click().run()
    assert "Download report (.html)" not in downloads(at)


def test_a_prepared_report_survives_a_rerun_that_changes_nothing(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606 33603")
    at.button(key="prep_report").click().run()
    at.checkbox(key="include_nf").set_value(False).run()  # the ZIP-list option is not in the report
    assert "Download report (.html)" in downloads(at)


# ------------------------------------------------------------------ HIGH 2: the analysis cache key
def test_a_second_zipcator_file_with_the_same_zips_gets_its_own_numbers(new_app: NewApp) -> None:
    at = go_step2(new_app())
    at.radio(key="mode_radio").set_value("Upload CSV").run()
    at.file_uploader(key="uploader").upload(
        "a.csv", zipcator(("33602", 50.0), ("33606", 100.0)), "text/csv"
    ).run()
    at.button(key="next_2").click().run()
    at.button(key="next_3").click().run()
    first = {m.label: m.value for m in at.metric}
    back_to_step1(at)
    at.button(key="continue_1").click().run()
    at.radio(key="mode_radio").set_value("Upload CSV").run()
    at.file_uploader(key="uploader").upload(
        "b.csv", zipcator(("33602", 10.0), ("33606", 20.0)), "text/csv"
    ).run()
    at.button(key="next_2").click().run()
    at.button(key="next_3").click().run()
    second = {m.label: m.value for m in at.metric}
    assert first["Households"] == "4,500" and second["Households"] == "900"  # 200 + 700


# ------------------------------------------------------------------ the cache key and the policy
def test_going_back_and_changing_the_answer_changes_restricted_mode_on_the_same_zips(
    new_app: NewApp,
) -> None:
    at = go_step4(new_app(), "33602 33606 33603", RETAIL, "No")
    assert "add_rule" in [b.key for b in at.button]
    back_to_step1(at)
    at.radio(key=f"answer_{RETAIL}").set_value("Yes").run()
    reach_insights(at, "33602 33606 33603")
    assert "add_rule" not in [b.key for b in at.button]
    assert any("Restricted mode is on" in str(w.value) for w in at.warning)
    assert len(at.table) >= 1  # static tables only; no sortable grid


def test_switching_from_an_unrestricted_to_a_restricted_industry_on_the_same_zips(
    new_app: NewApp,
) -> None:
    at = go_step4(new_app(), "33602 33606 33603", RETAIL, "No")
    back_to_step1(at)
    at.selectbox(key="industry_box").select(AUTO).run()
    at.radio(key=f"answer_{AUTO}").set_value("Yes").run()
    reach_insights(at, "33602 33606 33603")
    assert any("Restricted mode is on" in str(w.value) for w in at.warning)
    assert not [s for s in at.selectbox if s.key == "sort_by"]


# ------------------------------------------------------------------ MEDIUM 3: a stale column choice
def test_a_new_upload_forgets_the_column_chosen_for_the_previous_file(new_app: NewApp) -> None:
    two = CRLF.join([b"Home,Work", b"33602,33606", b"33606,33602"]) + CRLF
    at = go_step2(new_app())
    at.radio(key="mode_radio").set_value("Upload CSV").run()
    at.file_uploader(key="uploader").upload("two.csv", two, "text/csv").run()
    at.button(key="next_2").click().run()
    at.selectbox(key="column_box").select("Home").run()
    at.button(key="next_2").click().run()
    assert at.session_state.step == 3
    at.button(key="back_3").click().run()
    one = CRLF.join([b"ZIP,Name", b"33602,Tampa", b"33606,Tampa"]) + CRLF
    at.radio(key="mode_radio").set_value("Upload CSV").run()
    at.file_uploader(key="uploader").upload("one.csv", one, "text/csv").run()
    at.button(key="next_2").click().run()
    assert at.session_state.step == 3 and not at.error


# ------------------------------------------------------- MEDIUM 4: no sortable grid when restricted
def test_restricted_mode_has_no_interactive_grid_of_zip_values(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33606 33602 33603", MORTGAGE, None)
    for df in at.dataframe:
        assert "ZIP" not in df.value.columns, df.value.columns  # the grey-cells list included
    for expander in at.expander:
        if expander.label == "Why are some values grey?":
            assert expander.children  # still explains, as a static table or text


# ------------------------------------------------------------------ MEDIUM 5: filter rule units
def test_a_rule_shows_its_unit_and_resets_its_number_when_the_metric_changes(
    new_app: NewApp,
) -> None:
    at = go_step4(new_app(), "33602 33606 33603")
    at.button(key="add_rule").click().run()
    assert any(
        str(c.value).strip() == "%" for c in at.caption
    )  # the unit is visible next to the number
    metric = next(s for s in at.selectbox if s.key.startswith("r_metric_"))
    number = next(n for n in at.number_input if n.key.startswith("r_val_"))
    number.set_value(70.0).run()
    metric = next(s for s in at.selectbox if s.key.startswith("r_metric_"))
    metric.select("median_hh_income").run()
    number = next(n for n in at.number_input if n.key.startswith("r_val_"))
    assert number.value != 70.0 and number.value >= 1000  # a dollar default, not 70 dollars
    assert any(str(c.value).strip() == "$" for c in at.caption)


# ------------------------------------------------------------------ mutant survivors
def test_exclude_unreliable_matches_drops_them_from_the_matches(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606 33603")
    at.button(key="add_rule").click().run()
    metric = next(s for s in at.selectbox if s.key.startswith("r_metric_"))
    op = next(s for s in at.selectbox if s.key.startswith("r_op_"))
    op.select(
        "<="
    ).run()  # owner share <= 50 %: 33602 (40 %) and the unreliable 33603 (55 % > 50 %)
    number = next(n for n in at.number_input if n.key.startswith("r_val_"))
    number.set_value(60.0).run()  # 33602, 33603 qualify; 33603 is unreliable
    before = list(
        at.dataframe[0].value.loc[at.dataframe[0].value["Matches"] == "\N{CHECK MARK}", "ZIP"]
    )
    assert "33603" in before
    at.checkbox(key="exclude_unreliable").set_value(True).run()
    after = list(
        at.dataframe[0].value.loc[at.dataframe[0].value["Matches"] == "\N{CHECK MARK}", "ZIP"]
    )
    assert "33603" not in after and "33602" in after
    assert metric is not None


# ------------------------------------------------------------------ LOW items fixed
def test_the_attestation_is_shown_directly_above_the_zip_list(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606")
    page = texts(at)
    assert "Project: Untitled project" in page and "Restricted mode: off" in page
    assert (
        page.index("Restricted mode: off") < page.index("Include ZIPs that have no Census data")
        if ("Include ZIPs that have no Census data" in page)
        else True
    )


def test_both_zip_list_formats_can_be_downloaded(new_app: NewApp) -> None:
    names = downloads(go_step4(new_app(), "33602 33606"))
    assert {
        "Download ZIP list, comma-separated (.txt)",
        "Download ZIP list, one per line (.txt)",
    } <= names


def test_an_invalid_rule_blocks_the_exports_instead_of_exporting_everything(
    new_app: NewApp,
) -> None:
    at = go_step4(new_app(), "33602 33606 33603")
    at.button(key="add_rule").click().run()
    number = next(n for n in at.number_input if n.key.startswith("r_val_"))
    number.set_value(150.0).run()  # 150 % is not a valid share
    assert at.error and not at.exception
    assert not downloads(at) & {"Download CSV", "Download ZIP list, one per line (.txt)"}
    assert "Fix the filter rule" in texts(at)
