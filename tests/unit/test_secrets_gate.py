"""The secrets gate in scripts/check.py must catch the plausible ways a key could be committed.

Every key here is made up; the gate runs against a throwaway git repository.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
FAKE = "0123456789abcdef0123456789abcdef01234567"


def load_check() -> Any:
    spec = importlib.util.spec_from_file_location("check_script", ROOT / "scripts" / "check.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def findings(tmp_path: Path, files: dict[str, str]) -> list[str]:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-f", "."], cwd=tmp_path, check=True)
    return load_check().secret_findings(tmp_path)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("src/pkg/a.py", f'API_KEY = "{FAKE}"\n'),  # a bare constant in source
        ("src/pkg/b.py", f'x = "{FAKE.upper()}"\n'),
        ("scripts/c.py", f"token = '{FAKE}'\n"),
        ("config.json", f'{{"api_key": "{FAKE}"}}\n'),
        ("config.yaml", f"census_api_key: {FAKE}\n"),
        ("docs/notes.md", f"curl 'https://api.census.gov/data?get=X&KEY={FAKE}'\n"),
        ("docs/n2.md", f"https://x/?get=X&key%3D{FAKE}\n"),
        ("docs/n3.md", f"CENSUS_API_KEY={FAKE}\n"),
        (
            "docs/n4.md",
            "CENSUS_API_" + "KEY = " + "'abcdefgh" + "12345678'\n",
        ),  # not a literal here
        ("prod.env", "anything\n"),
        (".envrc", "export X=1\n"),
        (".env.local", "X=1\n"),
        (".ENV", "X=1\n"),
    ],
)
def test_the_gate_flags_a_committed_key_or_env_file(tmp_path: Path, name: str, text: str) -> None:
    found = findings(tmp_path, {name: text})
    assert found, f"{name} was not flagged"
    assert all(FAKE not in line for line in found)  # findings never print the value


@pytest.mark.parametrize(
    ("name", "text"),
    [
        (".env.example", "CENSUS_API_KEY=\n"),  # the blank template
        ("docs/help.md", "add the line CENSUS_API_KEY=<your key> to the .env file\n"),
        ("tests/unit/t.py", f'KEY = "{FAKE}"\n'),  # the tests' own made-up key
        ("src/pkg/ok.py", "sha = 'deadbeef'\n"),
        ("src/pkg/ok2.py", "monkey=banana\n"),
        ("uv.lock", "hash = 'sha256:" + "a" * 64 + "'\n"),
    ],
)
def test_the_gate_leaves_legitimate_files_alone(tmp_path: Path, name: str, text: str) -> None:
    assert findings(tmp_path, {name: text}) == []


def test_the_real_repository_passes_its_own_gate() -> None:
    assert load_check().secret_findings(ROOT) == []
