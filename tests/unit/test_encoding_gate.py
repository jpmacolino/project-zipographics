"""The encoding gate in scripts/check.py: every text file read or write names its encoding.

Ruff's PLW1514 only sees `open()` and inline `Path(...)` calls; it cannot tell that a variable
holds a Path, so `p.read_text()` slips through. This gate parses the code and catches those, and
`subprocess(..., text=True)` / `io.TextIOWrapper(...)` without an encoding too. Windows defaults to
cp1252, so an implicit encoding is a latent bug.
"""

from __future__ import annotations

import importlib.util
import subprocess
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


def problems(tmp_path: Path, code: str) -> list[str]:
    f = tmp_path / "mod.py"
    f.write_text(code, encoding="utf-8")
    return load_check().encoding_problems([f], tmp_path)


@pytest.mark.parametrize(
    "code",
    [
        "from pathlib import Path\np = Path('x')\np.read_text()\n",
        "def f(p):\n    return p.read_text()\n",
        "def f(p):\n    p.write_text('abc')\n",
        "def f(p):\n    p.write_text('abc', newline='')\n",
        "with open('x') as fh:\n    fh.read()\n",
        "with open('x', 'w') as fh:\n    fh.write('a')\n",
        "import subprocess\nsubprocess.run(['x'], text=True)\n",
        "import subprocess\nsubprocess.check_output(['x'], universal_newlines=True)\n",
        "import io\nio.TextIOWrapper(b)\n",
    ],
)
def test_implicit_encodings_are_found(tmp_path: Path, code: str) -> None:
    found = problems(tmp_path, code)
    assert len(found) == 1 and "mod.py:" in found[0], code


@pytest.mark.parametrize(
    "code",
    [
        "def f(p):\n    return p.read_text(encoding='utf-8')\n",
        "def f(p):\n    return p.read_text('utf-8')\n",
        "def f(p):\n    p.write_text('abc', encoding='utf-8')\n",
        "def f(p):\n    p.write_text('abc', 'utf-8')\n",
        "with open('x', encoding='utf-8') as fh:\n    fh.read()\n",
        "with open('x', 'rb') as fh:\n    fh.read()\n",
        "import subprocess\nsubprocess.run(['x'], text=True, encoding='utf-8')\n",
        "import subprocess\nsubprocess.run(['x'], capture_output=True)\n",
        "import io\nio.TextIOWrapper(b, encoding='utf-8')\n",
        "def f(p):\n    return p.read_bytes().decode('utf-8')\n",
    ],
)
def test_explicit_encodings_pass(tmp_path: Path, code: str) -> None:
    assert problems(tmp_path, code) == []


def test_the_repository_itself_is_clean() -> None:
    check = load_check()
    files = [ROOT / rel for rel in check.tracked_files(ROOT) if rel.endswith(".py")]
    assert files and check.encoding_problems(files, ROOT) == []


def test_the_gate_is_part_of_the_check_script() -> None:
    text = (ROOT / "scripts" / "check.py").read_text(encoding="utf-8")
    assert '"encoding"' in text and "encoding_problems" in text
    assert subprocess.run(["git", "--version"], capture_output=True, check=False).returncode == 0


@pytest.mark.parametrize(
    "code",
    [
        "import io\nio.open('x')\n",
        "from subprocess import run\nrun(['x'], text=True)\n",
        "import subprocess\nsubprocess.getoutput('x')\n",
        "import subprocess\nsubprocess.run(['x'], **kw)\n",
        "import subprocess\nsubprocess.run(['x'], text=flag)\n",
        "import subprocess as sp\nsp.run(['x'], text=True)\n",
    ],
)
def test_more_implicit_encodings_are_found(tmp_path: Path, code: str) -> None:
    assert len(problems(tmp_path, code)) == 1, code


@pytest.mark.parametrize(
    "code",
    [
        "from subprocess import run\nrun(['x'], text=True, encoding='utf-8')\n",
        "from subprocess import run\nrun(['x'], text=False)\n",
        "import subprocess\nsubprocess.run(['x'], **kw, encoding='utf-8')\n",
        "import io\nio.open('x', 'rb')\n",
        "import io\nio.open('x', encoding='utf-8')\n",
    ],
)
def test_the_new_checks_have_no_false_positives(tmp_path: Path, code: str) -> None:
    assert problems(tmp_path, code) == []


def test_untracked_python_files_are_scanned_too(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "new.py").write_text("p.read_text()\n", encoding="utf-8")  # never `git add`ed
    check = load_check()
    assert "new.py" in check.python_files(tmp_path)
    assert check.encoding_problems([tmp_path / "new.py"], tmp_path)
