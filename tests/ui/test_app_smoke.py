"""First AppTest run: the app starts on step 1 against the synthetic data."""

from __future__ import annotations

from collections.abc import Callable

from streamlit.testing.v1 import AppTest

from zipographics import verticals


def test_the_app_starts_on_step_one_without_an_exception(new_app: Callable[[], AppTest]) -> None:
    at = new_app()
    assert not at.exception
    assert at.session_state.step == 1
    box = at.selectbox(key="industry_box")
    assert len(box.options) == len(verticals.VERTICALS)
    assert box.value is None
