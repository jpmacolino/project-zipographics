"""Regression tests from the Phase 3 independent QA review (see docs/QA_REPORT.md, Phase 3).

Fake keys only; nothing here touches the repository's real .env or the network.
"""

from __future__ import annotations

import ast
import http.client
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import requests
from shapely.geometry import box
from synth_acs import (
    REGISTRY,
    ZCTAS,
    E2ESession,
    FakeClient,
    FakeDownload,
    FileSession,
)

from zipographics import data, data_build, metrics
from zipographics.census_api import (
    CensusApiError,
    CensusClient,
    NetworkError,
    RejectedKeyError,
    VarRequest,
)
from zipographics.data import DataNotBuiltError
from zipographics.data_build import (
    DEFAULT_SOURCES,
    BuildError,
    build,
    geometry_problems,
    main,
    validate_artifacts,
)
from zipographics.redact import redact, uninstall_redaction
from zipographics.sentinels import clean_pair

KEY = "0123456789abcdef0123456789abcdef01234567"
ROOT = Path(__file__).resolve().parents[2]
BODY = json.dumps([["NAME", "B01003_001E", "state"], ["Florida", "1", "12"]])


@pytest.fixture(autouse=True)
def _restore_logging() -> Any:
    yield
    uninstall_redaction()


class Script:
    """A session that plays back outcomes: responses (status, text) or exceptions to raise."""

    def __init__(self, *outcomes: tuple[int, str] | BaseException) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, url: str, **kwargs: Any) -> FakeDownload:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeDownload(outcome[1].encode(), outcome[0])


def client(tmp_path: Path, session: Any) -> CensusClient:
    return CensusClient(
        KEY, cache_root=tmp_path / "raw", session=session, sleeper=lambda s: None, jitter=lambda: 0
    )


def fetch(c: CensusClient) -> Any:
    return c.fetch_table("detailed", 2024, "state", [VarRequest("B01003_001")])


# ------------------------------------------------------------------ 1: unwrapped exceptions
@pytest.mark.parametrize(
    "make",
    [
        lambda url: ValueError(f"bad url {url}"),
        lambda url: OSError(f"socket error talking to {url}"),
        lambda url: http.client.InvalidURL(f"URL can't contain control characters. {url!r}"),
        lambda url: RuntimeError(f"unexpected failure for {url}"),
    ],
)
def test_any_exception_from_the_session_becomes_a_sanitized_network_error(
    tmp_path: Path, make: Any
) -> None:
    url = f"https://api.census.gov/data/2024/acs/acs5?get=X&key={KEY}"
    with pytest.raises(NetworkError) as exc:
        fetch(client(tmp_path, Script(make(url))))
    assert KEY not in str(exc.value) and f"key={KEY}" not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def test_a_keyboard_interrupt_propagates_unwrapped(tmp_path: Path) -> None:
    with pytest.raises(KeyboardInterrupt):
        fetch(client(tmp_path, Script(KeyboardInterrupt())))


# ------------------------------------------------------------------ 9: truncate after redacting
def test_a_key_at_the_truncation_boundary_is_not_half_printed(tmp_path: Path) -> None:
    body = "x" * 190 + KEY  # the first 200 characters would end 10 characters into the key
    with pytest.raises(CensusApiError) as exc:
        fetch(client(tmp_path, Script((404, body))))
    assert KEY[:10] not in str(exc.value)


def test_redaction_is_case_insensitive_for_the_literal_key() -> None:
    assert KEY.upper() not in redact(f"echo {KEY.upper()}", [KEY])
    assert KEY.title() not in redact(f"echo {KEY.title()}", [KEY])


def test_extra_fields_on_a_log_record_are_scrubbed(tmp_path: Path) -> None:
    import io

    from zipographics.redact import install_redaction

    install_redaction([KEY])
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s | %(detail)s"))
    logger = logging.getLogger("phase3.extra")
    logger.handlers, logger.propagate = [handler], False
    logger.warning("hello", extra={"detail": f"url key={KEY} and {KEY}"})
    assert KEY not in stream.getvalue() and "hello" in stream.getvalue()


# ------------------------------------------------------------------ 4: the backstop, for real
def test_a_handler_added_after_install_is_protected_in_a_clean_process() -> None:
    # In a subprocess there are no pytest handlers carrying the filter, so only the record
    # factory can protect a handler that has no filter of its own.
    script = (
        "import logging, sys\n"
        "from zipographics.redact import install_redaction\n"
        f"KEY = {KEY!r}\n"
        "install_redaction([KEY])\n"
        "handler = logging.StreamHandler(sys.stdout)  # no filter attached\n"
        "log = logging.getLogger('late'); log.addHandler(handler); log.setLevel(logging.DEBUG)\n"
        "log.info('GET https://x/?key=%s and bare %s', KEY, KEY)\n"
        "try:\n"
        "    raise RuntimeError('url https://x/?key=' + KEY)\n"
        "except RuntimeError:\n"
        "    log.exception('boom')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, cwd=ROOT, check=True
    ).stdout
    assert "GET" in out and "Traceback" in out
    assert KEY not in out


def test_the_client_constructor_installs_redaction(tmp_path: Path) -> None:
    import io

    client(tmp_path, Script())
    stream = io.StringIO()
    logger = logging.getLogger("phase3.ctor")
    logger.handlers, logger.propagate = [logging.StreamHandler(stream)], False
    logger.warning("secret %s", KEY)
    assert KEY not in stream.getvalue()


# ------------------------------------------------------------------ 6: truncated bodies
@pytest.mark.parametrize("body", ['[["a",', "", "   ", '{"truncated": '])
def test_a_truncated_200_body_is_retried_and_is_not_blamed_on_the_key(
    tmp_path: Path, body: str
) -> None:
    session = Script(*[(200, body)] * 5)
    with pytest.raises(NetworkError) as exc:
        fetch(client(tmp_path, session))
    assert not isinstance(exc.value, RejectedKeyError)
    assert session.calls == 5


def test_a_truncated_body_followed_by_a_good_one_succeeds(tmp_path: Path) -> None:
    assert len(fetch(client(tmp_path, Script((200, '[["a",'), (200, BODY))))) == 1


@pytest.mark.parametrize(
    "page", ["<html>Invalid Key</html>", "Invalid Key", "error: invalid key", "<!DOCTYPE html>"]
)
def test_an_error_page_is_still_a_rejected_key(tmp_path: Path, page: str) -> None:
    with pytest.raises(RejectedKeyError):
        fetch(client(tmp_path, Script((200, page))))


@pytest.mark.parametrize(
    "failure",
    [
        requests.exceptions.ChunkedEncodingError("cut"),
        requests.exceptions.ContentDecodingError("bad"),
    ],
)
def test_truncated_or_corrupt_transfers_are_retried(tmp_path: Path, failure: Exception) -> None:
    session = Script(failure, (200, BODY))
    assert len(fetch(client(tmp_path, session))) == 1 and session.calls == 2


def test_a_corrupt_cache_file_is_refetched_not_a_crash(tmp_path: Path) -> None:
    first = Script((200, BODY))
    fetch(client(tmp_path, first))
    for path in (tmp_path / "raw" / "acs" / "2024").glob("*.json"):
        if not path.name.endswith(".meta.json"):
            path.write_text("[[truncated", encoding="utf-8")
    second = Script((200, BODY))
    assert len(fetch(client(tmp_path, second))) == 1 and second.calls == 1


def test_name_counts_toward_the_fifty_name_limit(tmp_path: Path) -> None:
    urls: list[str] = []

    class Spy:
        def get(self, url: str, **kwargs: Any) -> FakeDownload:
            urls.append(url)
            names = url.split("get=")[1].split("&")[0].split(",")
            return FakeDownload(
                json.dumps([[*names, "state"], *[["1"] * len(names) + ["12"]]]).encode()
            )

    reqs = [VarRequest(f"B{i:05d}_001", with_moe=False) for i in range(60)]
    client(tmp_path, Spy()).fetch_table("detailed", 2024, "state", reqs)
    assert len(urls) == 2
    for url in urls:
        assert len(url.split("get=")[1].split("&")[0].split(",")) <= 50, "NAME must be counted"


# ------------------------------------------------------------------ CLI: interrupt and arguments
def run(
    tmp_path: Path, *extra: str, environ: dict[str, str] | None = None, session: Any = None
) -> int:
    return main(
        ["--data-dir", str(tmp_path / "data"), "--tolerance", "0.002", *extra],
        {"CENSUS_API_KEY": KEY} if environ is None else environ,
        session=session or E2ESession(tmp_path),
        registry=REGISTRY,
        min_rows=5,
        client_options={"sleeper": lambda s: None, "jitter": lambda: 0.0},
    )


def test_a_keyboard_interrupt_exits_130_with_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(data_build, "build", interrupt)
    assert run(tmp_path) == 130
    out, err = capsys.readouterr()
    assert "Interrupted" in err and "Traceback" not in out + err


@pytest.mark.parametrize(
    "args",
    [["--tolerance", "nan"], ["--tolerance", "-1"], ["--tolerance", "inf"], ["--vintage", "-5"],
     ["--vintage", "1800"]],
)  # fmt: skip
def test_nonsense_numeric_arguments_are_usage_errors(tmp_path: Path, args: list[str]) -> None:
    assert run(tmp_path, *args) == 2


def test_a_data_dir_that_is_a_file_is_a_usage_error(tmp_path: Path) -> None:
    target = tmp_path / "afile"
    target.write_text("x", encoding="utf-8")
    assert (
        main(["--data-dir", str(target)], {"CENSUS_API_KEY": KEY}, session=E2ESession(tmp_path))
        == 2
    )


def test_a_non_string_environment_value_does_not_crash(tmp_path: Path) -> None:
    code = run(tmp_path, environ={"CENSUS_API_KEY": 12345})  # type: ignore[dict-item]
    assert isinstance(code, int)


def test_a_failed_download_exits_4_with_a_user_facing_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session = E2ESession(tmp_path)
    session.files.pop(DEFAULT_SOURCES.county_rel_url)
    assert run(tmp_path, session=session) == 4
    err = capsys.readouterr().err
    assert "HTTP 404" in err and "DECISIONS" not in err and "Traceback" not in err


def test_the_acs_step_without_a_client_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(BuildError) as exc:
        build(
            tmp_path / "data",
            client=None,
            session=FileSession(tmp_path),
            only="acs",
            registry=REGISTRY,
        )
    assert exc.value.exit_code == 2


# ------------------------------------------------------------------ 2: atomic multi-file publish
def test_a_failure_while_writing_leaves_every_old_artifact_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    old = {
        n: f"old {n}".encode()
        for n in ("zcta_profile.parquet", "benchmarks.parquet", "metadata.json")
    }
    for name, content in old.items():
        (data_dir / name).write_bytes(content)

    real = pd.DataFrame.to_parquet
    calls = {"n": 0}

    def flaky(self: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:  # the second parquet file, as with a file lock or a full disk
            raise PermissionError("simulated lock")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", flaky)
    with pytest.raises(PermissionError):
        build(data_dir, client=FakeClient(), session=FileSession(tmp_path), registry=REGISTRY,
              min_rows=5, only="acs")  # fmt: skip
    for name, content in old.items():
        assert (data_dir / name).read_bytes() == content, name
    assert not list(data_dir.glob("*.tmp"))


# ------------------------------------------------------------------ 3: data.load, real registry
def write_real_artifacts(folder: Path, drop_from_benchmarks: str | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    cols: dict[str, Any] = {}
    for key, var in metrics.VARIABLES.items():
        cols[f"{key}_e"] = [1.0, 2.0]
        cols[f"{key}_m"] = [1.0, 1.0]
        if var.is_median:
            cols[f"{key}_code"] = ["none", "none"]
    profile = pd.DataFrame(
        {"zip": ["02108", "00601"], "state_fips": ["25", "72"], "state": ["MA", "PR"],
         "county_fips": ["25025", "72001"], "county": ["Suffolk", "Adjuntas"],
         "city": ["Boston", "Adjuntas"], **cols}
    )  # fmt: skip
    profile.to_parquet(folder / "zcta_profile.parquet")
    bench = pd.DataFrame(
        {
            "geo_level": ["us", "state"],
            "geo_id": ["1", "25"],
            "name": ["United States", "MA"],
            **cols,
        }
    )
    if drop_from_benchmarks:
        bench = bench.drop(columns=[drop_from_benchmarks])
    bench.to_parquet(folder / "benchmarks.parquet")
    (folder / "metadata.json").write_text(json.dumps({"vintage": 2024}), encoding="utf-8")


def test_the_real_registry_loads_when_every_column_is_present(tmp_path: Path) -> None:
    write_real_artifacts(tmp_path / "d")
    assert len(data.load(tmp_path / "d").profile) == 2


@pytest.mark.parametrize(
    "column", ["B28002_013_m", "DP03_UNINS_e", "DP03_UNINS_m", "DP03_CIVNONINST_e", "B19013_001_e"]
)
def test_every_benchmark_column_of_the_real_registry_is_checked(
    tmp_path: Path, column: str
) -> None:
    # the old check sliced a list that interleaves _code columns and skipped the last five
    write_real_artifacts(tmp_path / "d", drop_from_benchmarks=column)
    with pytest.raises(DataNotBuiltError, match=column):
        data.load(tmp_path / "d")


# ------------------------------------------------------------------ 5: import-graph rules
FORBIDDEN = {
    "zipographics.census_api",
    "zipographics.data_build",
    "zipographics.geo_build",
    "dotenv",
}
NETWORK = {"requests", "urllib3", "socket", "http.client", "urllib.request", "httpx", "aiohttp"}


def _violations(source: str, package: str = "zipographics") -> set[str]:
    """Every forbidden module the source could import, including relative imports and
    ``importlib.import_module("...")`` / ``__import__("...")`` calls with a literal name."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:  # resolve "from . import x" / "from .x import y" against the package
                base = package + ("." + base if base else "")
            found.add(base)
            found |= {f"{base}.{a.name}" for a in node.names}
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", getattr(func, "id", ""))
            if name in {"import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
    return {
        f
        for f in found
        if f in FORBIDDEN or f in NETWORK or f.split(".")[0] in {"requests", "urllib3"}
    }


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from .census_api import CensusClient", {"zipographics.census_api"}),
        ("from . import data_build", {"zipographics.data_build"}),
        ("import dotenv", {"dotenv"}),
        (
            "import importlib\nimportlib.import_module('zipographics.data_build')",
            {"zipographics.data_build"},
        ),
        ("__import__('dotenv')", {"dotenv"}),
        ("import requests", {"requests"}),
        ("from urllib3 import PoolManager", {"urllib3"}),
        ("import socket", {"socket"}),
        ("from . import stats\nimport math", set()),
    ],
)
def test_the_violation_scanner_catches_relative_and_dynamic_imports(
    source: str, expected: set[str]
) -> None:
    found = _violations(source)
    assert found == expected if not expected else expected <= found


def test_runtime_modules_have_no_forbidden_or_network_imports() -> None:
    build_only = {"census_api", "data_build", "geo_build", "errors"}
    offenders = {}
    for path in (ROOT / "src" / "zipographics").glob("*.py"):
        if path.stem in build_only:
            continue
        bad = _violations(path.read_text(encoding="utf-8"))
        if bad:
            offenders[path.name] = sorted(bad)
    for path in (ROOT / "app").rglob("*.py") if (ROOT / "app").exists() else []:
        bad = _violations(path.read_text(encoding="utf-8"))
        if bad:
            offenders[str(path.relative_to(ROOT))] = sorted(bad)
    assert offenders == {}


# ------------------------------------------------------------------ 7: the entry-point script
def load_script() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_data_script2", ROOT / "scripts" / "build_data.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_utf16_dotenv_gets_a_clear_message_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CENSUS_API_KEY", "x")
    monkeypatch.delenv("CENSUS_API_KEY")
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"CENSUS_API_KEY={KEY}\n", encoding="utf-16"
    )  # PowerShell 5.1 `echo > .env`
    assert load_script().main([], env_file=env_file) == 3
    err = capsys.readouterr().err
    assert "UTF-8" in err and "Traceback" not in err and KEY not in err


def test_a_blank_real_variable_does_not_hide_the_key_in_the_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"CENSUS_API_KEY={KEY}\n", encoding="utf-8")
    monkeypatch.setenv("CENSUS_API_KEY", "   ")
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        data_build, "main", lambda argv, environ: seen.update(key=environ["CENSUS_API_KEY"]) or 0
    )
    load_script().main([], env_file=env_file)
    assert seen["key"] == KEY


# ------------------------------------------------------------------ 10: validation gaps
def geo_for(zips: list[str]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"zip": zips}, geometry=[box(i, 0, i + 1, 1) for i, _ in enumerate(zips)], crs="EPSG:4326"
    )


def test_geometry_checks_apply_even_without_a_profile() -> None:
    geo = geo_for(["02108", "02109"])
    geo.loc[1, "geometry"] = None
    assert any("null" in p for p in geometry_problems(geo, None))


def test_duplicate_geometry_zips_fail() -> None:
    assert any("duplicate" in p for p in geometry_problems(geo_for(["02108", "02108"]), None))


def test_a_truncated_map_fails_against_the_profile() -> None:
    zips = {f"{10000 + i}" for i in range(100)}
    short = geo_for(sorted(zips)[:50])
    assert any("covers only" in p for p in geometry_problems(short, zips))
    assert geometry_problems(geo_for(sorted(zips)), zips) == []


def test_validate_artifacts_reports_duplicate_and_truncated_geometry(tmp_path: Path) -> None:
    from synth_acs import FakeClient as FC

    art = data_build.acs_artifacts(
        FC(), 2024, REGISTRY, FileSession(tmp_path), tmp_path / "raw", False, DEFAULT_SOURCES
    )
    problems, _ = validate_artifacts(
        art.profile, art.benchmarks, art.resolved, REGISTRY, geo=geo_for(ZCTAS[:1]), min_rows=5
    )
    assert any("covers only" in p for p in problems)


def test_coverage_ignores_zctas_without_population(tmp_path: Path) -> None:
    art = data_build.acs_artifacts(
        FakeClient(),
        2024,
        REGISTRY,
        FileSession(tmp_path),
        tmp_path / "raw",
        False,
        DEFAULT_SOURCES,
    )
    p = art.profile.copy()
    p.loc[["33602", "33603"], "B01003_001_e"] = 0.0  # nobody lives there ...
    p.loc[["33602", "33603"], "B11001_001_e"] = np.nan  # ... so missing households don't count
    problems, coverage = validate_artifacts(p, art.benchmarks, art.resolved, REGISTRY, min_rows=5)
    assert coverage["B11001_001"] == 1.0 and problems == []


def test_geonames_us_wins_over_pr_for_a_zip_in_both_files(tmp_path: Path) -> None:
    from synth_acs import geonames_bytes

    session = FileSession(tmp_path)
    session.files[DEFAULT_SOURCES.geonames_pr_url] = geonames_bytes(
        "PR.txt", [("00601", "Adjuntas"), ("02108", "Wrong City")]
    )
    art = data_build.acs_artifacts(
        FakeClient(), 2024, REGISTRY, session, tmp_path / "raw", False, DEFAULT_SOURCES
    )
    assert art.profile.loc["02108", "city"] == "Boston"


def test_geo_only_against_a_stale_profile_rejects_extra_zips(tmp_path: Path) -> None:
    build(tmp_path / "data", client=FakeClient(), session=FileSession(tmp_path), registry=REGISTRY,
          min_rows=5, only="acs")  # fmt: skip
    session = FileSession(tmp_path, geo_zips=[*ZCTAS, "99999"])
    with pytest.raises(BuildError, match="99999"):
        build(
            tmp_path / "data",
            client=None,
            session=session,
            registry=REGISTRY,
            only="geo",
            min_rows=5,
        )


# ------------------------------------------------------------------ 10: non-finite and odd values
def s(*values: object) -> pd.Series:
    return pd.Series(list(values), dtype="object")


@pytest.mark.parametrize("bad", ["inf", "-inf", "1e400", "Infinity"])
def test_non_finite_numbers_become_null_and_are_counted(bad: str) -> None:
    est, _moe, counts = clean_pair(s(bad, 5), s(1, 1))
    assert np.isnan(est[0]) and est[1] == 5
    assert counts == {"estimate:non_finite": 1}


def test_non_numeric_text_is_counted_but_blanks_are_not() -> None:
    est, _, counts = clean_pair(s("12,345", "(X)", None, "", "null", "NaN", 7), s(*[1] * 7))
    assert est.isna().sum() == 6 and est[6] == 7
    assert counts == {"estimate:non_numeric": 2}
