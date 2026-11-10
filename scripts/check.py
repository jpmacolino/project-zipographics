"""Run every quality gate: ruff lint, ruff format check, mypy, pytest + coverage, and two
repo-hygiene checks (no tracked file over 1 MB; no tracked secrets). See docs/SPEC.md section 8.

Usage: uv run python scripts/check.py [--no-cov]
Exits non-zero if any gate fails. Prints a summary table at the end.
Always runs from the repository root, whatever the current directory is.

The secrets gate never prints a matched value: it reports only the file and line number.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 1_000_000  # SPEC: "no data files over 1 MB"
# The uv lockfile is generated, not data; it is the only size exemption.
SIZE_EXEMPT = frozenset({"uv.lock"})

# A tracked .env file (other than the committed, blank example) is always a failure.
_ENV_NAME = re.compile(r"(^|/)(\.env[^/]*|[^/]*\.env|\.envrc)$", re.IGNORECASE)
_ENV_ALLOWED = frozenset({".env.example"})
# Census API keys are 40 hex characters. Flag a non-empty key assignment or a key= query value.
_SECRET_PATTERNS = (
    re.compile(r"CENSUS_API_KEY\s*[=:]\s*['\"]?[0-9A-Za-z]{8,}", re.IGNORECASE),
    re.compile(r"\bkey(?:=|%3d)[0-9a-f]{32,}", re.IGNORECASE),
    re.compile(r"(?:api|census)[_-]?key['\"]?\s*[:=]\s*['\"]?[0-9a-f]{32,}", re.IGNORECASE),
)
# A bare 40-hex literal in source folders is a key (or looks like one). The made-up key used by
# the tests lives under tests/, which is not scanned for this pattern.
_BARE_KEY = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", re.IGNORECASE)
_BARE_KEY_DIRS = ("src/", "scripts/", "app/")

GATES: list[tuple[str, list[str]]] = [
    ("ruff lint", ["ruff", "check", "."]),
    ("ruff format", ["ruff", "format", "--check", "."]),
    ("mypy", ["mypy"]),
    ("pytest", ["pytest", "--cov=zipographics", "--cov-report=term-missing"]),
]


def tracked_files(root: Path) -> list[str]:
    """Paths (POSIX, relative to ``root``) of every git-tracked or staged file."""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    return [p for p in out.split("\0") if p]


def oversized_tracked_files(root: Path) -> list[tuple[str, int]]:
    """Return (path, bytes) for tracked files larger than ``MAX_FILE_BYTES``."""
    big: list[tuple[str, int]] = []
    for rel in tracked_files(root):
        path = root / rel
        if rel in SIZE_EXEMPT or not path.is_file():
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            big.append((rel, size))
    return big


def secret_findings(root: Path) -> list[str]:
    """Human-readable findings (file and line only, never the value) for tracked secrets."""
    findings: list[str] = []
    for rel in tracked_files(root):
        if _ENV_NAME.search(rel) and rel not in _ENV_ALLOWED:
            findings.append(f"{rel}: .env files must never be tracked")
            continue
        path = root / rel
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable: not a text secret
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(p.search(line) for p in _SECRET_PATTERNS) or (
                rel.startswith(_BARE_KEY_DIRS) and _BARE_KEY.search(line)
            ):
                findings.append(f"{rel}:{lineno}: looks like a Census API key (value not shown)")
    return findings


_SUBPROCESS_CALLS = frozenset({"run", "Popen", "check_output", "check_call", "call"})
_ALWAYS_LOCALE = frozenset({"getoutput", "getstatusoutput"})  # text mode, no encoding parameter


def _kwarg_names(call: ast.Call) -> set[str | None]:
    return {k.arg for k in call.keywords}


def _text_mode(call: ast.Call) -> bool:
    """True when ``text=`` / ``universal_newlines=`` is on or cannot be told (a variable)."""
    for k in call.keywords:
        if k.arg in ("text", "universal_newlines"):
            return not (isinstance(k.value, ast.Constant) and k.value.value is False)
    return False


def _aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Names bound to the subprocess module, and to subprocess functions, in this file."""
    modules, funcs = {"subprocess"}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.asname or a.name for a in node.names if a.name == "subprocess"}
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            funcs |= {a.asname or a.name for a in node.names}
    return modules, funcs


def _open_issue(call: ast.Call, name: str) -> str | None:
    kw, n = _kwarg_names(call), len(call.args)
    mode: ast.expr | None = call.args[1] if n > 1 else None
    for k in call.keywords:
        if k.arg == "mode":
            mode = k.value
    binary = isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value
    return None if binary or "encoding" in kw else f"{name}() without encoding"


def _subprocess_issue(call: ast.Call, name: str) -> str | None:
    kw = _kwarg_names(call)
    if "encoding" in kw:
        return None
    if _text_mode(call) or None in kw:  # None is **kwargs: text mode cannot be ruled out
        return f"subprocess.{name}() in text mode without encoding"
    return None


def _encoding_issue(call: ast.Call, modules: set[str], funcs: set[str]) -> str | None:
    """What is wrong with this call, if it reads or writes text without naming an encoding."""
    func, kw, n = call.func, _kwarg_names(call), len(call.args)
    if isinstance(func, ast.Attribute):
        if func.attr == "read_text" and "encoding" not in kw and n < 1:
            return "read_text() without encoding"
        if func.attr == "write_text" and "encoding" not in kw and n < 2:
            return "write_text() without encoding"
        if func.attr == "TextIOWrapper" and "encoding" not in kw and n < 2:
            return "TextIOWrapper() without encoding"
        owner = func.value.id if isinstance(func.value, ast.Name) else None
        if owner == "io" and func.attr == "open":
            return _open_issue(call, "io.open")
        if owner in modules:
            if func.attr in _ALWAYS_LOCALE:
                return f"subprocess.{func.attr}() uses the locale encoding"
            if func.attr in _SUBPROCESS_CALLS:
                return _subprocess_issue(call, func.attr)
    elif isinstance(func, ast.Name):
        if func.id == "open":
            return _open_issue(call, "open")
        if func.id in funcs:
            if func.id in _ALWAYS_LOCALE:
                return f"subprocess.{func.id}() uses the locale encoding"
            if func.id in _SUBPROCESS_CALLS:
                return _subprocess_issue(call, func.id)
    return None


def encoding_problems(files: Iterable[Path], root: Path) -> list[str]:
    """``path:line: what`` for every text read or write that leaves the encoding to the platform
    default (cp1252 on Windows). Ruff's PLW1514 cannot see ``p.read_text()`` on a variable, an
    aliased ``subprocess`` or ``io.open``."""
    found: list[str] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
        modules, funcs = _aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (issue := _encoding_issue(node, modules, funcs)):
                found.append(f"{rel}:{node.lineno}: {issue}")
    return sorted(found)


def python_files(root: Path) -> list[str]:
    """Tracked and untracked (not ignored) ``.py`` files, so a new file is checked before it is
    ``git add``ed."""
    others = subprocess.run(
        ["git", "ls-files", "-z", "--others", "--exclude-standard"],
        cwd=root, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout  # fmt: skip
    names = {*tracked_files(root), *(x for x in others.split("\0") if x)}
    return sorted(n for n in names if n.endswith(".py"))


def _encoding_gate() -> int:
    files = [REPO_ROOT / rel for rel in python_files(REPO_ROOT)]
    found = encoding_problems(files, REPO_ROOT)
    for line in found:
        print(f"  {line}")
    return 1 if found else 0


def _size_gate() -> int:
    big = oversized_tracked_files(REPO_ROOT)
    for rel, size in big:
        print(f"  too large: {rel} ({size:,} bytes > {MAX_FILE_BYTES:,})")
    return 1 if big else 0


def _secrets_gate() -> int:
    found = secret_findings(REPO_ROOT)
    for line in found:
        print(f"  {line}")
    return 1 if found else 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    unknown = [a for a in args if a != "--no-cov"]
    if unknown:
        print(
            f"unknown argument(s): {' '.join(unknown)}\nusage: check.py [--no-cov]", file=sys.stderr
        )
        return 2
    no_cov = "--no-cov" in args
    results: list[tuple[str, bool, float]] = []
    for name, cmd in GATES:
        if no_cov and name == "pytest":
            cmd = ["pytest"]
        print(f"\n=== {name}: {' '.join(cmd)} ===", flush=True)
        start = time.perf_counter()
        code = subprocess.call([sys.executable, "-m", *cmd], cwd=REPO_ROOT)
        results.append((name, code == 0, time.perf_counter() - start))

    gates = (("file size", _size_gate), ("secrets", _secrets_gate), ("encoding", _encoding_gate))
    for name, gate in gates:
        print(f"\n=== {name} ===", flush=True)
        start = time.perf_counter()
        results.append((name, gate() == 0, time.perf_counter() - start))

    print("\n=== summary ===")
    for name, ok, secs in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<12} {secs:6.1f}s")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
