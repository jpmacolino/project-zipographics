"""The README's promises are tested: the footer snippet runs on a real export, the files it links
to exist, and the commands it lists are real (SPEC 10.9)."""

from __future__ import annotations

import re
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest
from synth_art import Z, make_artifacts

from zipographics import analysis, export, verticals
from zipographics.zips import parse_paste

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def python_blocks() -> list[str]:
    return re.findall(r"```python\n(.*?)```", README, flags=re.S)


def test_the_footer_snippet_reads_a_real_csv_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    art = make_artifacts(
        {"02108": Z(3794, 1973, state="MA", county=("25025", "Suffolk County"), city="Boston"),
         "33602": Z(5000, 2000)}
    )  # fmt: skip
    policy = verticals.make_policy("Retail (general & specialty)", False)
    a = analysis.analyze(art, parse_paste("2108 33602"), policy, project_name="Acme")
    for excel in (False, True):
        monkeypatch.chdir(tmp_path)
        payload = export.csv_bytes(
            a, None, excel=excel, now=datetime(2026, 1, 1, tzinfo=UTC), version="1"
        )
        (tmp_path / "acme.csv").write_bytes(payload)
        scope: dict[str, object] = {}
        (block,) = [b for b in python_blocks() if "skipfooter" in b]
        exec(textwrap.dedent(block), scope)
        table = scope["table"]
        zips = [str(z).replace('="', "").replace('"', "") for z in table["ZIP"] if z]  # type: ignore[index]
        assert zips == ["02108", "33602"]  # zeros kept, footer excluded
        assert list(table["Row type"])[-2:] == ["Trade area", "Benchmark"]  # type: ignore[index]


def test_files_and_images_the_readme_links_to_exist() -> None:
    for rel in re.findall(r"\]\((?!http|#)([^)]+)\)", README):
        assert (ROOT / rel).exists(), rel


def test_the_images_are_small_enough_to_commit() -> None:
    for img in (ROOT / "docs" / "img").glob("*.png"):
        assert img.stat().st_size < 1_000_000, img.name


def test_the_documented_commands_exist() -> None:
    assert (ROOT / "scripts" / "build_data.py").exists() and (
        ROOT / "app" / "streamlit_app.py"
    ).exists()
    text = (ROOT / "src" / "zipographics" / "data_build.py").read_text(encoding="utf-8")
    for flag in ("--refresh", "--vintage", "--only", "--no-geo", "--tolerance", "--data-dir"):
        assert flag in text and flag in README, flag
    cli = (ROOT / "src" / "zipographics" / "cli.py").read_text(encoding="utf-8")
    for flag in (
        "--restricted",
        "--vertical",
        "--benchmark",
        "--csv",
        "--report",
        "--excel",
        "--file",
    ):
        assert flag in cli and flag in README, flag


def test_the_readme_has_every_section_the_spec_asks_for() -> None:
    need = [
        "Setup", "Restricted mode", "not legal advice", "Data sources and attribution",
        "GeoNames", "CC BY 4.0", "not endorsed or certified", "Reading the numbers", "margin",
        "ZCTA", "CSV footer", "MIT", "only by the one-time data build",
    ]  # fmt: skip
    for needle in need:
        assert needle.lower() in README.lower(), needle
