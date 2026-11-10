"""Build the data artifacts (SPEC §4.4): ``uv run python scripts/build_data.py [options]``.

This is the only entry point that reads ``.env``. A real ``CENSUS_API_KEY`` environment variable
wins over the file (``override=False``), unless it is empty or blank, which counts as unset. The
Streamlit app never loads ``.env`` and never needs the key. Run with ``--help`` for the options;
exit codes: 0 ok, 2 usage, 3 missing or rejected key, 4 network or API failure, 5 validation
failure.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None, *, env_file: Path | None = None) -> int:
    from dotenv import load_dotenv

    if not (os.environ.get("CENSUS_API_KEY") or "").strip():
        os.environ.pop("CENSUS_API_KEY", None)  # a blank variable must not hide the file's key
    try:
        load_dotenv(env_file if env_file is not None else REPO / ".env", override=False)
    except UnicodeDecodeError:
        print(
            "The .env file could not be read: save it as UTF-8 (in Notepad: Save As, Encoding "
            "UTF-8) with one line, CENSUS_API_KEY=<your key>.",
            file=sys.stderr,
        )
        return 3

    from zipographics import data_build

    return data_build.main(argv, os.environ)


if __name__ == "__main__":
    sys.exit(main())
