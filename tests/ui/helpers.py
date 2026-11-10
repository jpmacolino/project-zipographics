"""Small drivers for the AppTest suite."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

RETAIL = "Retail (general & specialty)"
MORTGAGE = "Mortgage & lending"
AUTO = "Automotive sales"
HOME = "Home services (HVAC, plumbing, roofing, pest, remodeling)"


def choose_industry(at: AppTest, industry: str, answer: str | None = None) -> AppTest:
    at.selectbox(key="industry_box").select(industry).run()
    if answer is not None:
        at.radio(key=f"answer_{industry}").set_value(answer).run()
    return at


def go_step2(at: AppTest, industry: str = RETAIL, answer: str | None = "No") -> AppTest:
    choose_industry(at, industry, answer)
    at.button(key="continue_1").click().run()
    assert at.session_state.step == 2
    return at


def go_step3(at: AppTest, text: str, industry: str = RETAIL, answer: str | None = "No") -> AppTest:
    go_step2(at, industry, answer)
    at.text_area[0].input(text).run()
    at.button(key="next_2").click().run()
    assert at.session_state.step == 3, [e.value for e in at.error]
    return at


def go_step4(
    at: AppTest, text: str = "33602 33606 33603", industry: str = RETAIL, answer: str | None = "No"
) -> AppTest:
    go_step3(at, text, industry, answer)
    at.button(key="next_3").click().run()
    assert at.session_state.step == 4 and not at.exception
    return at


def texts(at: AppTest) -> str:
    """Every piece of text on the page (markdown, captions, alerts), joined."""
    parts: list[str] = []
    for group in (at.markdown, at.caption, at.info, at.success, at.warning, at.error, at.title,
                  at.subheader):  # fmt: skip
        parts += [str(e.value) for e in group]
    return "\n".join(parts)


def labels(elements) -> list[str]:  # type: ignore[no-untyped-def]
    return [e.label for e in elements]
