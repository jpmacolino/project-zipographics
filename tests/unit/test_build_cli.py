"""Tests for the build command line: exit codes, messages, key handling, .env loading (SPEC §4.4,
§4.5, §9.2). A fake key is used throughout; nothing reads the repository's real .env.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest
from synth_acs import REGISTRY, E2ESession, Synth

from zipographics import data_build
from zipographics.census_api import MISSING_KEY_MESSAGE, REJECTED_KEY_MESSAGE
from zipographics.data_build import main

KEY = "0123456789abcdef0123456789abcdef01234567"
ENV = {"CENSUS_API_KEY": KEY}


class NoSleep:
    """Injected clock and sleeper so retry back-off never really waits."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def options(self) -> dict[str, Any]:
        return {"clock": lambda: self.now, "sleeper": self._sleep, "jitter": lambda: 0.0}

    def _sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def run(
    tmp_path: Path,
    *extra: str,
    environ: dict[str, str] | None = None,
    session: Any = None,
    sleep: NoSleep | None = None,
) -> tuple[int, Any]:
    session = session or E2ESession(tmp_path)
    code = main(
        ["--data-dir", str(tmp_path / "data"), "--tolerance", "0.002", *extra],
        ENV if environ is None else environ,
        session=session,
        registry=REGISTRY,
        min_rows=5,
        client_options=(sleep or NoSleep()).options(),
    )
    return code, session


# --------------------------------------------------------------------------- success
def test_a_successful_build_exits_zero_prints_progress_and_leaks_no_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, session = run(tmp_path)
    out, err = capsys.readouterr()
    assert code == 0 and err == ""
    assert "resolved" in out and "zcta: 6 rows" in out and "wrote" in out
    assert session.urls_with_key > 0  # the key really was sent to the API ...
    everything = out + err
    for path in (tmp_path / "data").rglob("*"):
        everything += path.name
        if path.is_file() and path.suffix in {".json", ".txt"}:
            everything += path.read_text(encoding="utf-8")
    assert KEY not in everything and f"key={KEY}" not in everything  # ... but is written nowhere
    meta = json.loads((tmp_path / "data" / "metadata.json").read_text(encoding="utf-8"))
    assert meta["vintage"] == 2024


def test_the_vintage_is_a_parameter_not_a_constant(tmp_path: Path) -> None:
    code, session = run(tmp_path, "--vintage", "2025", "--only", "acs")
    assert code == 0
    assert any("/data/2025/acs/acs5" in u for u in session.calls)
    assert not any("/data/2024/" in u for u in session.calls)
    meta = json.loads((tmp_path / "data" / "metadata.json").read_text(encoding="utf-8"))
    assert meta["vintage"] == 2025


def test_a_second_run_uses_the_cache_and_refresh_goes_back_to_the_api(tmp_path: Path) -> None:
    _, first = run(tmp_path)
    api_calls = sum(u.startswith("https://api.census.gov/") for u in first.calls)
    _, second = run(tmp_path)
    assert sum(u.startswith("https://api.census.gov/") for u in second.calls) == 0
    _, third = run(tmp_path, "--refresh")
    assert sum(u.startswith("https://api.census.gov/") for u in third.calls) == api_calls


def test_geo_only_needs_no_key_and_makes_no_api_call(tmp_path: Path) -> None:
    code, session = run(tmp_path, "--only", "geo", environ={})
    assert code == 0
    assert not any(u.startswith("https://api.census.gov/") for u in session.calls)
    assert (tmp_path / "data" / "zcta_geo.parquet").exists()


# --------------------------------------------------------------------------- key problems (exit 3)
@pytest.mark.parametrize("env", [{}, {"CENSUS_API_KEY": ""}, {"CENSUS_API_KEY": "   "}])
def test_a_missing_key_exits_3_with_the_exact_message_and_no_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], env: dict[str, str]
) -> None:
    code, session = run(tmp_path, environ=env)
    out, err = capsys.readouterr()
    assert code == 3
    assert err.strip() == MISSING_KEY_MESSAGE
    assert session.calls == []  # failed before any request
    assert "Traceback" not in out + err


def test_a_rejected_key_exits_3_with_the_rejection_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = run(tmp_path, session=E2ESession(tmp_path, mode="invalid_key"))
    out, err = capsys.readouterr()
    assert code == 3
    assert err.strip() == REJECTED_KEY_MESSAGE
    assert KEY not in out + err and "Traceback" not in out + err
    assert not (tmp_path / "data" / "zcta_profile.parquet").exists()


# ------------------------------------------------------------------ network problems (exit 4)
def test_a_proxy_403_exits_4_and_says_it_is_the_network_not_the_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, session = run(tmp_path, session=E2ESession(tmp_path, mode="blocked"))
    out, err = capsys.readouterr()
    assert code == 4
    assert "network or proxy problem, not a problem with your key" in err
    assert KEY not in out + err
    assert len([u for u in session.calls if "variables.json" in u]) == 1  # not retried in a loop


def test_server_errors_are_retried_then_exit_4_without_waiting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sleep = NoSleep()
    code, session = run(tmp_path, session=E2ESession(tmp_path, mode="server_error"), sleep=sleep)
    out, err = capsys.readouterr()
    assert code == 4
    assert len(session.calls) == 5 and sleep.sleeps == [1.0, 2.0, 4.0, 8.0]
    assert "could not be reached after 5 attempts" in err and KEY not in out + err


# --------------------------------------------------------------------------- validation (exit 5)
def test_a_validation_failure_exits_5_with_one_line_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = run(tmp_path, session=E2ESession(tmp_path, Synth(null_core=True)))
    out, err = capsys.readouterr()
    assert code == 5
    assert (
        err.count("\n") == 1 and "output validation failed" in err and "Nothing was written" in err
    )
    assert "Traceback" not in out + err
    assert not (tmp_path / "data" / "zcta_profile.parquet").exists()


def test_an_unknown_sentinel_exits_5(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = run(tmp_path, session=E2ESession(tmp_path, Synth(bad_sentinel=True)))
    assert code == 5 and "-123456789" in capsys.readouterr().err


# --------------------------------------------------------------------------- usage errors (exit 2)
@pytest.mark.parametrize(
    "args", [["--vintage", "abc"], ["--only", "bogus"], ["--nope"], ["--no-geo", "--only", "geo"]]
)
def test_usage_errors_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    code, session = run(tmp_path, *args)
    assert code == 2
    assert session.calls == []
    assert capsys.readouterr().err  # a usage message was printed


def test_there_is_no_key_command_line_flag(tmp_path: Path) -> None:
    for flag in ("--census-api-key", "--api-key", "--key"):
        code, _ = run(tmp_path, flag, KEY)
        assert code == 2  # command lines end up in shell history; the key is env-only


# --------------------------------------------------------------------------- the unexpected
def test_an_unexpected_error_is_one_redacted_line_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"connection to https://api.census.gov/data?key={KEY} exploded")

    monkeypatch.setattr(data_build, "build", boom)
    code, _ = run(tmp_path)
    out, err = capsys.readouterr()
    assert code == 1 and "Unexpected error (RuntimeError)" in err
    assert KEY not in out + err and "Traceback" not in out + err and err.count("\n") == 1


def test_logging_is_restored_after_a_run(tmp_path: Path) -> None:
    factory = logging.getLogRecordFactory()
    handlers = list(logging.getLogger("zipographics").handlers)
    run(tmp_path)
    assert logging.getLogRecordFactory() is factory
    assert logging.getLogger("zipographics").handlers == handlers


# --------------------------------------------------------------------------- scripts/build_data.py
def load_script() -> Any:
    path = Path(__file__).resolve().parents[2] / "scripts" / "build_data.py"
    spec = importlib.util.spec_from_file_location("build_data_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clean_key_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("CENSUS_API_KEY", "placeholder")
    monkeypatch.delenv("CENSUS_API_KEY")  # restored to "unset" when the test ends
    return monkeypatch


def test_the_entry_point_loads_a_dotenv_file_for_the_build(
    tmp_path: Path, clean_key_env: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"  # a throwaway file; the repository's own .env is never touched
    env_file.write_text(f"CENSUS_API_KEY={KEY}\n", encoding="utf-8")
    seen: dict[str, Any] = {}

    def fake_main(argv: Any, environ: Any) -> int:
        seen["key"] = environ.get("CENSUS_API_KEY")
        seen["argv"] = list(argv)
        return 0

    clean_key_env.setattr(data_build, "main", fake_main)
    assert load_script().main(["--only", "geo"], env_file=env_file) == 0
    assert seen == {"key": KEY, "argv": ["--only", "geo"]}


def test_a_real_environment_variable_wins_over_the_dotenv_file(
    tmp_path: Path, clean_key_env: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CENSUS_API_KEY=from-the-file\n", encoding="utf-8")
    clean_key_env.setenv("CENSUS_API_KEY", "from-the-environment")
    seen: dict[str, Any] = {}
    clean_key_env.setattr(
        data_build, "main", lambda argv, environ: seen.update(key=environ["CENSUS_API_KEY"]) or 0
    )
    load_script().main([], env_file=env_file)
    assert seen["key"] == "from-the-environment"


def test_a_missing_dotenv_file_is_fine(tmp_path: Path, clean_key_env: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    clean_key_env.setattr(
        data_build,
        "main",
        lambda argv, environ: seen.update(key=environ.get("CENSUS_API_KEY")) or 3,
    )
    assert load_script().main([], env_file=tmp_path / "absent.env") == 3
    assert seen["key"] is None and "CENSUS_API_KEY" not in os.environ
