"""scripts/check.py also type-checks and tests on Python 3.11, the oldest supported version.

Regression (Phase 6): CI failed on 3.11 only. uv.lock pins numpy 2.4 below Python 3.12 (numpy 2.5
needs 3.12), whose type stubs differ, so mypy passed on 3.12 and failed on 3.11. Nothing local ran
3.11, so it reached CI. The gate runs mypy and the tests in a separate 3.11 environment.
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_check() -> Any:
    spec = importlib.util.spec_from_file_location("check_script", ROOT / "scripts" / "check.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_311_steps_sync_typecheck_and_test_in_their_own_environment() -> None:
    check = load_check()
    steps = check.PY311_STEPS
    assert [s[0] for s in steps] == ["py311 sync", "py311 mypy", "py311 pytest"]
    for _name, cmd in steps:
        assert cmd[0] == "uv" and "--python" in cmd and cmd[cmd.index("--python") + 1] == "3.11"
    assert "mypy" in steps[1][1] and "pytest" in steps[2][1]
    assert check.PY311_ENV == ROOT / ".venv311"  # never the developer's main environment


def test_the_311_environment_is_ignored_by_git() -> None:
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".venv311/" in lines


def test_arguments() -> None:
    check = load_check()
    assert check.parse_args([]) == (False, False)
    assert check.parse_args(["--no-cov"]) == (True, False)
    assert check.parse_args(["--skip-py311", "--no-cov"]) == (True, True)
    with pytest.raises(SystemExit) as exc:
        check.parse_args(["--bogus"])
    assert exc.value.code == 2


def test_the_tools_target_python_311_and_ci_tests_both_versions() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["ruff"]["target-version"] == "py311"
    assert config["tool"]["mypy"]["python_version"] == "3.11"
    assert config["project"]["requires-python"] == ">=3.11"
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert '"3.11"' in ci and '"3.12"' in ci


def test_the_lockfile_pins_numpy_per_python_so_the_stubs_differ() -> None:
    # the reason mypy must run on 3.11 itself: the same code meets a different numpy there
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert "python_full_version < '3.12'" in lock and "python_full_version >= '3.12'" in lock
