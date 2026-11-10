"""Visual QA (marker ``visual``; run manually): drive the real app with Playwright on the real data
and save screenshots of every step to ``qa/screenshots/`` for a human (or the builder) to look at.

    uv sync --group visual && uv run playwright install chromium
    uv run pytest -m visual -q --no-cov

Scenarios (SPEC 9.5): golden 1 (Tampa Zipcator export, in-radius), golden 2 (Boston, Excel-mangled
paste), golden 5 (restricted vertical, Tampa), and a filtered run; plus the summary report rendered
and printed to PDF. Needs the built ``data/`` folder.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.visual
ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "qa" / "screenshots"
TAMPA_CSV = ROOT / "tests" / "fixtures" / "zipcator" / "tampa_5mi.csv"
BOSTON_MANGLED = "2108, 2109, 2110, 2111, 2113, 2114, 2115, 2116"
HOME = "Home services (HVAC, plumbing, roofing, pest, remodeling)"
MORTGAGE = "Mortgage & lending"

if not (ROOT / "data" / "zcta_profile.parquet").exists():  # pragma: no cover
    pytest.skip("data/ has not been built", allow_module_level=True)
playwright = pytest.importorskip("playwright.sync_api")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app/streamlit_app.py",
         "--server.headless", "true", "--server.port", str(port),
         "--browser.gatherUsageStats", "false"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            if urllib.request.urlopen(url + "/_stcore/health", timeout=1).status == 200:
                break
        except OSError:
            time.sleep(0.5)
    else:  # pragma: no cover
        proc.kill()
        pytest.fail("streamlit did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=15)


@pytest.fixture(scope="module")
def browser():  # type: ignore[no-untyped-def]
    SHOTS.mkdir(parents=True, exist_ok=True)
    with playwright.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser, base_url):  # type: ignore[no-untyped-def]
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    pg = ctx.new_page()
    pg.set_default_timeout(60_000)
    pg.goto(base_url)
    pg.wait_for_selector("text=Client industry")
    yield pg
    ctx.close()


def shot(page, name: str, tall: bool = True) -> None:  # type: ignore[no-untyped-def]
    if tall:
        height = page.evaluate("document.querySelector('[data-testid=stMain]').scrollHeight")
        page.set_viewport_size({"width": 1400, "height": min(max(int(height) + 80, 900), 9000)})
        page.wait_for_timeout(800)
    page.screenshot(path=str(SHOTS / f"{name}.png"))
    page.set_viewport_size({"width": 1400, "height": 900})


def choose_industry(page, industry: str, answer: str | None) -> None:  # type: ignore[no-untyped-def]
    page.locator('[data-testid="stSelectbox"]').first.click()
    page.keyboard.type(industry[:18])
    page.get_by_role("option", name=industry).first.click()
    page.wait_for_timeout(500)
    if answer:
        page.get_by_text(answer, exact=True).first.click()
        page.wait_for_timeout(500)


def click(page, text: str) -> None:  # type: ignore[no-untyped-def]
    page.get_by_role("button", name=text).first.click()
    page.wait_for_timeout(1200)


def to_insights(page, name: str) -> None:  # type: ignore[no-untyped-def]
    shot(page, f"{name}_3_review")
    click(page, "Show insights")
    page.wait_for_selector("text=Trade area vs benchmark")
    page.wait_for_timeout(2500)  # charts and the map settle


def test_golden_1_tampa_zipcator_in_radius(page) -> None:  # type: ignore[no-untyped-def]
    shot(page, "g1_1_industry_empty", tall=False)
    choose_industry(page, HOME, "No")
    page.get_by_label("Project / client name (optional)").fill("Tampa 5 mi")
    shot(page, "g1_1_industry")
    click(page, "Continue")
    page.get_by_text("Upload CSV", exact=True).click()
    page.wait_for_timeout(800)
    page.locator('input[type="file"]').set_input_files(str(TAMPA_CSV))
    page.wait_for_timeout(1500)
    shot(page, "g1_2_zips")
    click(page, "Review ZIPs")
    to_insights(page, "g1")
    shot(page, "g1_4_insights")
    assert page.get_by_text("In-radius estimates").first.is_visible()


def test_golden_2_boston_mangled_paste(page) -> None:  # type: ignore[no-untyped-def]
    choose_industry(page, HOME, "No")
    click(page, "Continue")
    page.get_by_role("textbox", name="ZIP codes").fill(BOSTON_MANGLED)
    page.keyboard.press("Control+Enter")
    page.wait_for_timeout(800)
    shot(page, "g2_2_zips")
    click(page, "Review ZIPs")
    assert page.get_by_text("8 repaired").first.is_visible()
    to_insights(page, "g2")
    shot(page, "g2_4_insights")
    assert page.get_by_text("Benchmark: Massachusetts").first.is_visible()


def test_golden_5_restricted_vertical(page) -> None:  # type: ignore[no-untyped-def]
    choose_industry(page, MORTGAGE, None)
    shot(page, "g5_1_industry_locked", tall=False)
    click(page, "Continue")
    page.get_by_role("textbox", name="ZIP codes").fill("33602 33606 33609 33611 33629")
    page.keyboard.press("Control+Enter")
    page.wait_for_timeout(800)
    click(page, "Review ZIPs")
    to_insights(page, "g5")
    shot(page, "g5_4_insights_restricted")
    assert page.get_by_text("Restricted mode is on.").first.is_visible()
    assert page.get_by_role("button", name="Add rule").count() == 0


def test_filtered_run(page) -> None:  # type: ignore[no-untyped-def]
    choose_industry(page, HOME, "No")
    click(page, "Continue")
    page.get_by_role("textbox", name="ZIP codes").fill(
        "33602 33606 33609 33611 33629 33606 33611 33647 33618 33613"
    )
    page.keyboard.press("Control+Enter")
    page.wait_for_timeout(800)
    click(page, "Review ZIPs")
    to_insights(page, "gf")
    click(page, "Affluent homeowners")
    page.wait_for_timeout(1500)
    shot(page, "gf_4_filtered")


def test_the_report_renders_and_prints_to_pdf(browser) -> None:  # type: ignore[no-untyped-def]
    html = SHOTS / "report_boston.html"
    subprocess.run(
        [sys.executable, "-m", "zipographics.cli", "profile",
         *BOSTON_MANGLED.replace(",", "").split(), "--vertical", HOME, "--restricted", "no",
         "--project", "Boston report", "--report", str(html)],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )  # fmt: skip
    ctx = browser.new_context(viewport={"width": 1200, "height": 900})
    pg = ctx.new_page()
    pg.goto(html.as_uri())
    pg.wait_for_timeout(500)
    pg.screenshot(path=str(SHOTS / "report_boston.png"), full_page=True)
    pg.pdf(path=str(SHOTS / "report_boston.pdf"), format="Letter", print_background=True)
    assert (SHOTS / "report_boston.pdf").stat().st_size > 5_000
    ctx.close()
    (SHOTS / "STAMP.txt").write_text(
        f"captured {datetime.now(UTC):%Y-%m-%d %H:%M} UTC\n", encoding="utf-8"
    )
