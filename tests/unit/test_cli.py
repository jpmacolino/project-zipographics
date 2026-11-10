"""The small CLI: same library code as the app (SPEC 5.8, 9.2)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from synth_art import Z, make_artifacts

from zipographics import cli, config

NOW = datetime(2026, 11, 10, 14, 30, tzinfo=UTC)
WORLD = {
    "33602": Z(5000, 2000, owner=0.40, kids=0.20),
    "33606": Z(8000, 3500, owner=0.70, kids=0.35),
    "02108": Z(3794, 1973, owner=0.51, kids=0.10, state="MA", county=("25025", "Suffolk County"),
              city="Boston", income=212_928),
}  # fmt: skip
ART = make_artifacts(WORLD)
RETAIL = "Retail (general & specialty)"


def run(argv: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path | None = None):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli, "_load", lambda data_dir: ART)
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, out=out, err=err, now=NOW)
    return code, out.getvalue(), err.getvalue()


def test_profile_prints_the_review_and_the_kpis(monkeypatch: pytest.MonkeyPatch) -> None:
    code, out, err = run(
        ["profile", "33602", "33606", "--vertical", RETAIL, "--restricted", "no"], monkeypatch
    )
    assert code == 0 and err == ""
    assert "2 ZIPs recognized" in out
    assert "Industry: Retail (general & specialty)" in out and "Restricted mode: off" in out
    assert "Households" in out and "Population" in out and "Median household income" in out
    assert "Homeowners" in out and "Index" in out and "Florida" in out
    assert "13,000" in out  # trade-area population


def test_restricted_is_required_unless_the_vertical_is_restricted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, out, err = run(["profile", "33602", "--vertical", RETAIL], monkeypatch)
    assert code == 2 and "--restricted" in err and out == ""
    code, out, err = run(["profile", "33602", "--vertical", "Mortgage & lending"], monkeypatch)
    assert code == 0 and "Restricted mode: on" in out and "Yes (set by industry)" in out


def test_a_restricted_vertical_ignores_a_no_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    code, out, _ = run(
        ["profile", "33602", "--vertical", "Insurance", "--restricted", "no"], monkeypatch
    )
    assert code == 0 and "Restricted mode: on" in out
    assert "Restricted mode is on." in out  # the banner is printed


def test_the_vertical_can_be_given_by_a_unique_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    code, out, _ = run(
        ["profile", "33602", "--vertical", "dental", "--restricted", "no"], monkeypatch
    )
    assert code == 0 and "Industry: Dental & orthodontics" in out


def test_an_unknown_or_ambiguous_vertical_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _, err = run(
        ["profile", "33602", "--vertical", "astrology", "--restricted", "no"], monkeypatch
    )
    assert code == 2 and "industry" in err.lower()
    code, _, err = run(
        ["profile", "33602", "--vertical", "services", "--restricted", "no"], monkeypatch
    )
    assert code == 2 and "more than one" in err.lower()


def test_without_a_vertical_the_industry_is_other_and_follows_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run(["profile", "33602"], monkeypatch)[0] == 2  # an answer is required
    code, out, _ = run(["profile", "33602", "--restricted", "yes"], monkeypatch)
    assert code == 0 and "Industry: Other" in out and "Restricted mode: on" in out


def test_zips_can_come_from_a_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "zips.csv"
    f.write_text("ZIP,Name\n2108,Boston\n33602,Tampa\n", encoding="utf-8")
    code, out, _ = run(
        ["profile", "--file", str(f), "--vertical", RETAIL, "--restricted", "no"], monkeypatch
    )
    assert code == 0 and "2 ZIPs recognized" in out and "1 repaired" in out


def test_a_zipcator_file_turns_on_in_radius_estimates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    f = tmp_path / "z.csv"
    rows = ['"ZIP","Overlap %","Contains address"', '"33602",50.0,"Yes"', '"33606",100.0,"No"']
    crlf = chr(13) + chr(10)
    f.write_bytes((crlf.join(rows) + crlf).encode("utf-8"))
    code, out, _ = run(
        ["profile", "--file", str(f), "--vertical", RETAIL, "--restricted", "no"], monkeypatch
    )
    assert code == 0 and "In-radius estimate" in out and "10,500" in out  # 2,500 + 8,000


def test_zips_and_a_file_can_be_combined_with_the_file_taking_no_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    f = tmp_path / "zips.txt"
    f.write_text("33606\n", encoding="utf-8")
    code, out, _ = run(
        ["profile", "33602", "--file", str(f), "--vertical", RETAIL, "--restricted", "no"],
        monkeypatch,
    )
    assert code == 0 and "2 ZIPs recognized" in out


def test_no_zips_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _, err = run(["profile", "--vertical", RETAIL, "--restricted", "no"], monkeypatch)
    assert code == 2 and "ZIP" in err


def test_nothing_recognized_is_exit_4(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _out, err = run(
        ["profile", "99999", "--vertical", RETAIL, "--restricted", "no"], monkeypatch
    )
    assert code == 4 and "No ZIPs were recognized" in err


def test_a_missing_file_is_a_usage_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code, _, err = run(
        [
            "profile",
            "--file",
            str(tmp_path / "nope.csv"),
            "--vertical",
            RETAIL,
            "--restricted",
            "no",
        ],
        monkeypatch,
    )
    assert code == 2 and "nope.csv" in err


def test_the_benchmark_can_be_county_or_national(monkeypatch: pytest.MonkeyPatch) -> None:
    base = ["profile", "33602", "33606", "--vertical", RETAIL, "--restricted", "no"]
    assert "Hillsborough County" in run([*base, "--benchmark", "county"], monkeypatch)[1]
    assert "United States" in run([*base, "--benchmark", "us"], monkeypatch)[1]
    assert run([*base, "--benchmark", "galaxy"], monkeypatch)[0] == 2


def test_csv_and_report_files_are_written(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    csv_path, html_path = tmp_path / "out.csv", tmp_path / "out.html"
    code, out, _ = run(
        ["profile", "33602", "2108", "--vertical", RETAIL, "--restricted", "no",
         "--project", "Acme", "--csv", str(csv_path), "--report", str(html_path)],
        monkeypatch,
    )  # fmt: skip
    assert code == 0 and csv_path.exists() and html_path.exists()
    frame = pd.read_csv(
        csv_path, dtype=str, skipfooter=len(cli_footer(csv_path)) + 1, engine="python"
    )
    assert list(frame["ZIP"][:2]) == ["33602", "02108"]  # leading zero kept
    html = html_path.read_text(encoding="utf-8")
    assert "<title>Acme" in html and "Restricted mode: off" in html
    assert str(csv_path) in out and str(html_path) in out


def cli_footer(path: Path) -> list[str]:
    text = path.read_bytes().decode("utf-8")  # read_text would turn the CRLFs into LFs
    return [line for line in text.split("\r\n\r\n", 1)[1].split("\r\n") if line]


def test_the_excel_flag_writes_the_bom_and_formula_zips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "x.csv"
    code, _, _ = run(
        [
            "profile",
            "2108",
            "--vertical",
            RETAIL,
            "--restricted",
            "no",
            "--csv",
            str(path),
            "--excel",
        ],
        monkeypatch,
    )
    raw = path.read_bytes()
    assert code == 0 and raw[:3] == b"\xef\xbb\xbf" and b'"=""02108"""' in raw


def test_restricted_runs_write_input_order_and_no_filter_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "r.csv"
    code, _, _ = run(
        ["profile", "33606", "33602", "--vertical", "Insurance", "--csv", str(path)], monkeypatch
    )
    text = path.read_bytes().decode("utf-8")
    assert code == 0 and text.index("33606") < text.index("33602")
    header = text.splitlines()[0]
    assert "Qualifies" not in header and "index" not in header.lower()


def test_an_unwritable_output_path_is_exit_5(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code, _, err = run(
        ["profile", "33602", "--vertical", RETAIL, "--restricted", "no",
         "--csv", str(tmp_path / "no" / "such" / "dir" / "x.csv")],
        monkeypatch,
    )  # fmt: skip
    assert code == 5 and "x.csv" in err


def test_a_missing_data_build_is_exit_3_with_the_build_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setenv(config.DATA_DIR_ENV, str(Path("definitely") / "missing"))
    code = cli.main(
        ["profile", "33602", "--vertical", RETAIL, "--restricted", "no"], out=out, err=err, now=NOW
    )
    assert code == 3 and "build_data.py" in err.getvalue()


def test_help_and_version_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in ("--help", "--version"):
        out = io.StringIO()
        with pytest.raises(SystemExit) as exc:
            cli.main([flag], out=out, err=io.StringIO(), now=NOW)
        assert exc.value.code == 0


def test_no_command_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _, err = run([], monkeypatch)
    assert code == 2 and "profile" in err


def test_the_cli_never_touches_the_network_or_the_key() -> None:
    import ast

    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    imported = {
        n.module if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom | ast.Import)
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert not {m for m in imported if m and m.split(".")[0] in {"requests", "dotenv", "urllib3"}}
    assert not any("census_api" in (m or "") or "data_build" in (m or "") for m in imported)


def test_a_console_that_cannot_encode_the_arrows_does_not_crash_the_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Windows consoles are cp1252: the review line "2108 -> 02108" (an arrow) used to raise
    # UnicodeEncodeError and kill the run after the first line (found running the CLI on real data)
    monkeypatch.setattr(cli, "_load", lambda data_dir: ART)
    raw_out, raw_err = io.BytesIO(), io.BytesIO()
    out = io.TextIOWrapper(raw_out, encoding="cp1252", write_through=True)
    err = io.TextIOWrapper(raw_err, encoding="cp1252", write_through=True)
    code = cli.main(
        ["profile", "2108", "--vertical", RETAIL, "--restricted", "no"], out=out, err=err, now=NOW
    )
    text = raw_out.getvalue().decode("cp1252")
    assert code == 0 and "1 repaired" in text and "02108" in text
    assert "Homeowners" in text  # the run went on past the arrow line
