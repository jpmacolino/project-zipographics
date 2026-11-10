"""variables.json fetching (key-free) and the import-graph rule (SPEC §4.5, §8, §9.2)."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from zipographics.census_api import CensusApiError, CensusClient
from zipographics.redact import uninstall_redaction

KEY = "0123456789abcdef0123456789abcdef01234567"
ROOT = Path(__file__).resolve().parents[2]
BODY = json.dumps(
    {
        "variables": {
            "B01003_001E": {
                "label": "Estimate!!Total",
                "concept": "TOTAL POPULATION",
                "group": "B01003",
            },
            "B01003_001M": {"label": "Margin of Error!!Total", "group": "B01003"},
            "for": {"label": "Census API FIPS 'for' clause", "predicateType": "fips-for"},
            "NAME": {"label": "Geographic Area Name", "predicateType": "string"},
        }
    }
)


class Resp:
    def __init__(self, status: int, text: str) -> None:
        self.status_code, self.text = status, text


class Session:
    def __init__(self, *outcomes: Resp) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> Resp:
        self.calls.append(url)
        return self.outcomes.pop(0)


@pytest.fixture(autouse=True)
def _restore_logging() -> Any:
    yield
    uninstall_redaction()


def client(tmp_path: Path, session: Session) -> CensusClient:
    return CensusClient(KEY, cache_root=tmp_path / "raw", session=session, sleeper=lambda s: None)


# ------------------------------------------------------------------------------ variables.json
def test_variables_are_fetched_without_the_key_and_reduced_to_label_and_group(
    tmp_path: Path,
) -> None:
    session = Session(Resp(200, BODY))
    got = client(tmp_path, session).fetch_variables(2024, "detailed")
    assert session.calls == ["https://api.census.gov/data/2024/acs/acs5/variables.json"]
    assert KEY not in session.calls[0] and "key=" not in session.calls[0]  # metadata needs no key
    assert got["B01003_001E"] == {"label": "Estimate!!Total", "group": "B01003"}
    assert got["NAME"] == {"label": "Geographic Area Name", "group": ""}


def test_the_profile_dataset_has_its_own_variables_url(tmp_path: Path) -> None:
    session = Session(Resp(200, BODY))
    client(tmp_path, session).fetch_variables(2024, "profile")
    assert session.calls == ["https://api.census.gov/data/2024/acs/acs5/profile/variables.json"]


def test_variables_are_cached(tmp_path: Path) -> None:
    session = Session(Resp(200, BODY))
    c = client(tmp_path, session)
    first = c.fetch_variables(2024, "detailed")
    assert c.fetch_variables(2024, "detailed") == first
    assert len(session.calls) == 1
    files = list((tmp_path / "raw" / "acs" / "2024").glob("*.json"))
    assert len(files) == 2  # the body and its sidecar
    assert all(KEY not in f.read_text(encoding="utf-8") for f in files)


@pytest.mark.parametrize("body", ["[]", '{"nothing": 1}', '{"variables": []}'])
def test_unexpected_metadata_is_an_api_error(tmp_path: Path, body: str) -> None:
    with pytest.raises(CensusApiError):
        client(tmp_path, Session(Resp(200, body))).fetch_variables(2024, "detailed")


# ------------------------------------------------------------------------------ import graph
BUILD_ONLY = {
    "zipographics.census_api",
    "zipographics.data_build",
    "zipographics.geo_build",
}


def test_importing_the_whole_runtime_package_does_not_load_build_code_or_dotenv() -> None:
    script = (
        "import importlib, pkgutil, sys, zipographics\n"
        f"skip = {sorted(BUILD_ONLY)!r}\n"
        "for m in pkgutil.iter_modules(zipographics.__path__):\n"
        "    name = 'zipographics.' + m.name\n"
        "    if name not in skip:\n"
        "        importlib.import_module(name)\n"
        "bad = [n for n in sys.modules if n == 'dotenv' or n in skip]\n"
        "print(','.join(sorted(bad)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
        check=True,
    )
    assert result.stdout.strip() == "", f"runtime import pulled in: {result.stdout.strip()}"


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names |= {f"{node.module}.{a.name}" for a in node.names}
    return names


def test_no_runtime_source_file_imports_build_modules_or_dotenv() -> None:
    forbidden = BUILD_ONLY | {"dotenv"}
    runtime = [
        p
        for p in (ROOT / "src" / "zipographics").glob("*.py")
        if f"zipographics.{p.stem}" not in BUILD_ONLY
    ]
    runtime += list((ROOT / "app").rglob("*.py")) if (ROOT / "app").exists() else []
    offenders = {
        p.name: sorted(_imports(p) & forbidden) for p in runtime if _imports(p) & forbidden
    }
    assert offenders == {}


def test_build_modules_may_import_each_other_but_only_the_script_loads_dotenv() -> None:
    users = [p.name for p in (ROOT / "src").rglob("*.py") if "dotenv" in _imports(p)] + [
        p.name for p in (ROOT / "app").rglob("*.py") if "dotenv" in _imports(p)
    ]
    assert users == []  # only scripts/build_data.py imports dotenv
    assert "dotenv" in _imports(ROOT / "scripts" / "build_data.py")
