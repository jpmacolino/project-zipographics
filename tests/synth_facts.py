"""Tiny synthetic per-ZIP facts frames for tests (SPEC §9.2: no real Census files)."""

from __future__ import annotations

import pandas as pd

Row = tuple[str, float | None, float | None]  # (state, population, households)


def make_facts(rows: dict[str, Row]) -> pd.DataFrame:
    """A facts frame indexed by 5-char string ZIP with state, population, households."""
    return pd.DataFrame(
        {
            "state": pd.Series([r[0] for r in rows.values()], index=list(rows), dtype="object"),
            "population": pd.Series(
                [float("nan") if r[1] is None else r[1] for r in rows.values()],
                index=list(rows),
                dtype="float64",
            ),
            "households": pd.Series(
                [float("nan") if r[2] is None else r[2] for r in rows.values()],
                index=list(rows),
                dtype="float64",
            ),
        },
        index=pd.Index(list(rows), name="zip", dtype="object"),
    )
