"""The four-step flow through AppTest (SPEC 9.2 UI list). Synthetic data only."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from streamlit.testing.v1 import AppTest
from ui.helpers import (
    AUTO,
    HOME,
    MORTGAGE,
    RETAIL,
    choose_industry,
    go_step2,
    go_step3,
    go_step4,
    labels,
    texts,
)

from zipographics import restricted, verticals

NewApp = Callable[[], AppTest]
CRLF = bytes([13, 10])


# ------------------------------------------------------------------------------ step 1
def test_every_vertical_is_listed_and_none_is_preselected(new_app: NewApp) -> None:
    at = new_app()
    box = at.selectbox(key="industry_box")
    assert list(box.options) == [v.name for v in verticals.VERTICALS] and box.value is None


def test_continue_is_disabled_until_the_industry_and_the_question_are_answered(
    new_app: NewApp,
) -> None:
    at = new_app()
    assert at.button(key="continue_1").disabled
    choose_industry(at, RETAIL)
    assert at.button(key="continue_1").disabled  # still no answer
    at.radio(key=f"answer_{RETAIL}").set_value("No").run()
    assert not at.button(key="continue_1").disabled


def test_the_question_is_worded_exactly_and_has_no_default_answer(new_app: NewApp) -> None:
    at = new_app()
    choose_industry(at, RETAIL)
    radio = at.radio(key=f"answer_{RETAIL}")
    assert radio.label == verticals.RESTRICTED_QUESTION and radio.value is None
    assert list(radio.options) == ["Yes", "No"] and not radio.disabled
    assert verticals.QUESTION_HINT in texts(at)


def test_a_restricted_industry_has_the_question_locked_to_yes(new_app: NewApp) -> None:
    at = new_app()
    choose_industry(at, MORTGAGE)
    radio = at.radio(key=f"locked_{MORTGAGE}")
    assert radio.disabled and radio.value == "Yes"
    assert verticals.LOCKED_NOTE in texts(at)
    assert not at.button(key="continue_1").disabled  # nothing to answer


def test_the_project_name_is_limited_to_eighty_characters(new_app: NewApp) -> None:
    at = new_app()
    assert at.text_input[0].max_chars == 80


def test_changing_the_industry_clears_a_previous_answer(new_app: NewApp) -> None:
    at = new_app()
    choose_industry(at, RETAIL, "No")
    choose_industry(at, AUTO)
    assert at.radio(key=f"answer_{AUTO}").value is None and at.button(key="continue_1").disabled


def test_the_not_legal_advice_statement_is_shown(new_app: NewApp) -> None:
    assert restricted.NOT_LEGAL_ADVICE in texts(new_app())


# ------------------------------------------------------------------------------ step 2 and 3
def test_paste_leads_to_a_review_with_each_applicable_line(new_app: NewApp) -> None:
    at = go_step3(new_app(), "2108 33602 33602 33606-1234 abc 99999 33603")
    page = texts(at)
    assert "4 ZIPs recognized" in page  # 02108, 33602, 33606, 33603
    assert "1 not found (99999)" in page
    assert "1 repaired" in page and "2108" in page and "02108" in page
    assert "1 ZIP+4 truncated" in page
    assert "1 invalid entry: abc" in page
    assert "1 duplicate removed" in page
    assert "1 has a small population" in page and "33603" in page
    assert "Industry: Retail" in page and "Restricted mode: off" in page


def test_ZIPs_in_two_states_get_the_benchmark_sentence(new_app: NewApp) -> None:
    page = texts(go_step3(new_app(), "33602 33606 30301"))
    assert "Your ZIPs are in FL and GA. Benchmark: Florida" in page


def test_nothing_recognized_blocks_with_a_reason(new_app: NewApp) -> None:
    at = go_step3(new_app(), "99999 12345")
    assert at.button(key="next_3").disabled
    assert any("No ZIPs were recognized" in e.value for e in at.error)


def test_more_than_a_thousand_zips_blocks(new_app: NewApp) -> None:
    text = " ".join(f"{10000 + i:05d}" for i in range(1001))
    at = go_step3(new_app(), text)
    assert at.button(key="next_3").disabled
    assert any("up to 1,000 ZIPs" in e.value for e in at.error)


def test_empty_input_stays_on_step_two(new_app: NewApp) -> None:
    at = go_step2(new_app())
    at.button(key="next_2").click().run()
    assert at.session_state.step == 2 and any("at least one ZIP" in e.value for e in at.error)


def test_back_keeps_what_was_entered(new_app: NewApp) -> None:
    at = go_step3(new_app(), "33602 33606")
    at.button(key="back_3").click().run()
    assert at.session_state.step == 2 and at.text_area[0].value == "33602 33606"
    at.button(key="back_2").click().run()
    assert at.session_state.step == 1
    assert at.selectbox(key="industry_box").value == RETAIL
    assert at.radio(key=f"answer_{RETAIL}").value == "No"


def test_restricted_mode_is_announced_on_the_review_screen(new_app: NewApp) -> None:
    page = texts(go_step3(new_app(), "33602 33606", MORTGAGE, None))
    assert restricted.BANNER_TITLE in page and "Restricted mode: on" in page


def test_yes_on_an_unrestricted_industry_turns_restricted_mode_on(new_app: NewApp) -> None:
    at = go_step3(new_app(), "33602 33606", AUTO, "Yes")
    assert "Restricted mode: on" in texts(at) and restricted.BANNER_TITLE in texts(at)


# ------------------------------------------------------------------------------ uploads
def test_a_generic_csv_upload_is_parsed(new_app: NewApp) -> None:
    at = go_step2(new_app())
    at.radio(key="mode_radio").set_value("Upload CSV").run()
    csv = b"ZIP,Name" + CRLF + b"2108,Boston" + CRLF + b"33602,Tampa" + CRLF
    at.file_uploader(key="uploader").upload("zips.csv", csv, "text/csv").run()
    at.button(key="next_2").click().run()
    page = texts(at)
    assert at.session_state.step == 3 and "2 ZIPs recognized" in page and "1 repaired" in page


def test_a_zipcator_export_turns_on_in_radius_estimates(new_app: NewApp) -> None:
    crlf = chr(13) + chr(10)
    csv = (
        crlf.join(
            ['"ZIP","Overlap %","Contains address"', '"33602",50.0,"Yes"', '"33606",100.0,"No"']
        )
        + crlf
    )
    at = go_step2(new_app())
    at.radio(key="mode_radio").set_value("Upload CSV").run()
    at.file_uploader(key="uploader").upload("tampa.csv", csv.encode("utf-8"), "text/csv").run()
    at.button(key="next_2").click().run()
    assert "Zipcator export detected: in-radius estimates are on." in texts(at)
    at.button(key="next_3").click().run()
    assert at.radio(key="mode_box").value == "In-radius estimate"
    assert "In-radius estimates" in texts(at)
    at.radio(key="mode_box").set_value("Full ZIPs").run()
    assert "In-radius estimates" not in texts(at)


def test_a_file_with_two_zip_columns_asks_which(new_app: NewApp) -> None:
    csv = b"Home,Work\r\n33602,33606\r\n33606,33602\r\n"
    at = go_step2(new_app())
    at.radio(key="mode_radio").set_value("Upload CSV").run()
    at.file_uploader(key="uploader").upload("two.csv", csv, "text/csv").run()
    at.button(key="next_2").click().run()
    assert at.session_state.step == 2 and any("column" in e.value.lower() for e in at.warning)
    at.selectbox(key="column_box").select("Home").run()
    at.button(key="next_2").click().run()
    assert at.session_state.step == 3


def test_an_unusable_file_shows_an_error_not_a_traceback(new_app: NewApp) -> None:
    at = go_step2(new_app())
    at.radio(key="mode_radio").set_value("Upload CSV").run()
    at.button(key="next_2").click().run()
    assert any("Choose a CSV" in e.value for e in at.error) and not at.exception


# ------------------------------------------------------------------------------ step 4
def test_the_dashboard_header_cards_and_core_charts(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606 33603", HOME, "No")
    page = texts(at)
    assert "3 of 3 ZIPs recognized" in page and "Benchmark: Florida" in page
    assert (
        "ACS 2020-2024 5-year estimates" in page and "ZIP = Census ZIP Code Tabulation Area" in page
    )
    got = labels(at.metric)
    assert got[:5] == ["Households", "Population", "Median household income", "Homeowners",
                       "Households with children"]  # fmt: skip
    assert "Single-family homes" in got  # a Home services lens card
    assert restricted.BANNER_TITLE not in page


def test_the_project_name_titles_the_dashboard(new_app: NewApp) -> None:
    at = choose_industry(new_app(), RETAIL, "No")
    at.text_input[0].input("Acme HVAC Q4").run()
    at.button(key="continue_1").click().run()
    at.text_area[0].input("33602 33606").run()
    at.button(key="next_2").click().run()
    at.button(key="next_3").click().run()
    assert at.title[0].value == "Acme HVAC Q4"


def test_untitled_project_says_so(new_app: NewApp) -> None:
    assert go_step4(new_app()).title[0].value == "Untitled project"


def test_switching_the_benchmark_changes_the_index(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606 33603")
    captions = lambda: " ".join(str(c.value) for c in at.caption)  # noqa: E731
    assert "vs Florida" in captions()
    options = list(at.selectbox(key="benchmark_box").options)
    assert options[0] == "Florida (state)" and options[-1] == "United States (national)"
    at.selectbox(key="benchmark_box").select("United States (national)").run()
    assert "vs United States" in captions() and "vs Florida" not in captions()


def test_switching_the_lens_changes_the_cards(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606 33603", HOME, "No")
    assert "Built before 1980" in labels(at.metric)
    at.selectbox(key="lens_box").select("Fitness").run()
    got = labels(at.metric)
    assert "Built before 1980" not in got and "Age 18-44" in got


def test_the_unreliable_card_is_marked_with_a_dagger_and_a_tooltip(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33603")
    owners = next(m for m in at.metric if m.label == "Homeowners")
    assert "\N{DAGGER}" in owners.value and owners.help


def test_a_preset_fills_the_rules_and_highlights_matching_zips(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606 33603 33605")
    at.button(key="preset_Families").click().run()
    assert any("ZIPs match" in str(s.value) for s in at.success)
    frame = at.dataframe[0].value
    assert "Matches" in frame.columns
    assert list(frame.loc[frame["Matches"] == "\N{CHECK MARK}", "ZIP"]) == [
        "33606"
    ]  # 35 % kids, FL 27 %


def test_rules_can_be_added_edited_and_removed(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606 33603 33605")
    at.button(key="add_rule").click().run()
    assert any("ZIPs match" in str(s.value) for s in at.success)
    metric = next(s for s in at.selectbox if s.key.startswith("r_metric_"))
    metric.select("hh_kids").run()
    value = next(n for n in at.number_input if n.key.startswith("r_val_"))
    value.set_value(30.0).run()  # 30 % of households with children
    frame = at.dataframe[0].value
    assert list(frame.loc[frame["Matches"] == "\N{CHECK MARK}", "ZIP"]) == ["33606", "33603"]
    next(b for b in at.button if b.key.startswith("r_del_")).click().run()
    assert "Matches" not in at.dataframe[0].value.columns


def test_only_matching_zips_hides_the_rest(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606 33603 33605")
    at.button(key="preset_Families").click().run()
    at.toggle(key="only_matching").set_value(True).run()
    assert list(at.dataframe[0].value["ZIP"]) == ["33606"]


def test_the_table_toggles(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606 33603")
    base = list(at.dataframe[0].value.columns)
    at.toggle(key="show_moe").set_value(True).run()
    assert len(at.dataframe[0].value.columns) > len(base)
    at.radio(key="show_index").set_value("Index").run()
    assert any("(index)" in c for c in at.dataframe[0].value.columns)
    at.selectbox(key="sort_by").select("owner").run()
    at.checkbox(key="descending").set_value(True).run()
    assert at.dataframe[0].value["ZIP"].iloc[0] == "33606"


def test_zip_cells_stay_text_with_their_leading_zero(new_app: NewApp) -> None:
    at = go_step4(new_app(), "2108 33602")
    assert list(at.dataframe[0].value["ZIP"]) == ["02108", "33602"]


def test_download_buttons_and_the_report(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606 33603")
    names = {b.proto.label for b in at.get("download_button")}
    assert {"Download ZIP list (.txt)", "Download CSV", "Download CSV for Excel"} <= names
    at.button(key="prep_report").click().run()
    names = {b.proto.label for b in at.get("download_button")}
    assert "Download report (.html)" in names and not at.exception


def test_the_zip_list_and_attestation_are_shown(new_app: NewApp) -> None:
    at = go_step4(new_app(), "2108 33602 99999")
    codes = [str(c.value) for c in at.code]
    assert "02108, 33602, 99999" in codes  # all valid input ZIPs, including the not-found one
    assert "02108\n33602\n99999" in codes
    at.checkbox(key="include_nf").set_value(False).run()
    assert "02108, 33602" in [str(c.value) for c in at.code]


def test_a_filter_exports_only_the_matches_unless_asked_otherwise(new_app: NewApp) -> None:
    at = go_step4(new_app(), "33602 33606 33603 33605")
    at.button(key="preset_Families").click().run()
    assert "33606" in [str(c.value) for c in at.code]
    at.checkbox(key="export_all").set_value(True).run()
    assert "33602, 33606, 33603, 33605" in [str(c.value) for c in at.code]


def test_more_demographics_is_in_every_lens(new_app: NewApp) -> None:
    at = go_step4(new_app())
    assert "More demographics" in [e.label for e in at.expander]


def test_charts_have_a_text_alternative(new_app: NewApp) -> None:
    at = go_step4(new_app())
    assert any("data table" in e.label for e in at.expander)
    assert len([e for e in at.get("vega_lite_chart")]) >= 4


def test_start_over_returns_to_step_one(new_app: NewApp) -> None:
    at = go_step4(new_app())
    at.button(key="start_over").click().run()
    assert at.session_state.step == 1 and at.selectbox(key="industry_box").value is None


@pytest.mark.parametrize("step_text", ["33602 33606"])
def test_no_step_raises(new_app: NewApp, step_text: str) -> None:
    at = new_app()
    assert not at.exception
    go_step2(at)
    assert not at.exception
    at.text_area[0].input(step_text).run()
    at.button(key="next_2").click().run()
    assert not at.exception
    at.button(key="next_3").click().run()
    assert not at.exception
