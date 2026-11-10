"""The data build: download, resolve, clean, join, validate and write the artifacts (SPEC §4).

Build-only; the running app never imports this module (an import-graph test enforces it). The
Census API key is handled in :mod:`zipographics.census_api`; nothing here sees or prints it.

Exit codes of ``scripts/build_data.py``: 0 success, 2 usage, 3 missing/rejected key, 4 network or
API failure, 5 validation failure (:class:`BuildError`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from zipographics.metrics import MedianSpec, Var

Dataset = Literal["detailed", "profile"]
VarMeta = Mapping[str, str]  # one entry of variables.json: {"label": ..., "group": ...}


class BuildError(Exception):
    """A failed build step. ``exit_code`` is the CLI exit code (5 = validation failure)."""

    def __init__(self, message: str, exit_code: int = 5) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# ----------------------------------------------------------------------------- bracket bounds
_NUM = r"\$?([0-9][0-9,]*)"
_BOUND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"less than {_NUM}$", re.I), "below"),
    (re.compile(r"under ([0-9]+) years?$", re.I), "below"),
    (re.compile(rf"{_NUM} or more$", re.I), "above"),
    (re.compile(r"([0-9]+) years and over$", re.I), "above"),
    (re.compile(r"(?:built )?([0-9]{4}) or later$", re.I), "above"),
    (re.compile(r"(?:built )?([0-9]{4}) or earlier$", re.I), "earlier"),
    (re.compile(rf"(?:built )?{_NUM} to {_NUM}(?: years)?$", re.I), "range"),
    (re.compile(r"([0-9]+) and ([0-9]+) years$", re.I), "range"),
    (re.compile(r"([0-9]+) years$", re.I), "single"),
]


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def parse_bounds(label: str) -> tuple[float, float] | None:
    """The [lo, hi) bounds a bracket label describes, using the continuous convention
    (``$10,000 to $14,999`` is [10,000, 15,000)); ``None`` if the label is not a bracket."""
    tail = label.split("!!")[-1].strip().rstrip(":").strip()
    for pattern, kind in _BOUND_PATTERNS:
        m = pattern.match(tail)
        if m is None:
            continue
        nums = [_number(g) for g in m.groups()]
        if kind == "below":
            return -math.inf, nums[0]
        if kind == "above":
            return nums[0], math.inf
        if kind == "earlier":
            return -math.inf, nums[0] + 1
        if kind == "range":
            return nums[0], nums[1] + 1
        return nums[0], nums[0] + 1  # single
    return None


def bounds_match(label: tuple[float, float], expected: tuple[float, float]) -> bool:
    """Does a label's bounds equal the registry's? An open lowest bracket in the label matches an
    expected lower bound of 0 (income, value, rent and age use 0, SPEC §6.4)."""
    if label[1] != expected[1]:
        return False
    return label[0] == expected[0] or (label[0] == -math.inf and expected[0] == 0)


# ----------------------------------------------------------------------------- resolution
@dataclass(frozen=True, slots=True)
class ResolvedVar:
    """A registry variable resolved to a concrete Census variable for this vintage."""

    key: str
    id: str  # the estimate variable, e.g. B19013_001E or DP03_0099E
    base_id: str  # id without the trailing E, used to build E/M/EA names
    label: str
    table: str
    dataset: Dataset
    moved: bool = False  # the registry's ID no longer carried this label; found by label

    def as_metadata(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "table": self.table,
            "dataset": self.dataset,
            "moved": self.moved,
        }


def _is_estimate(info: VarMeta) -> bool:
    return str(info.get("label", "")).lower().startswith("estimate!!")


def _search(var: Var, meta: Mapping[str, VarMeta]) -> list[str]:
    """Estimate variables of the variable's table whose label matches its regex."""
    assert var.label is not None
    pattern = re.compile(var.label, re.IGNORECASE)
    return sorted(
        vid
        for vid, info in meta.items()
        if info.get("group") == var.table
        and _is_estimate(info)
        and vid.endswith("E")
        and pattern.search(str(info.get("label", "")))
    )


def resolve_variables(
    variables: Mapping[str, Var],
    meta: Mapping[Dataset, Mapping[str, VarMeta]],
    brackets: Sequence[MedianSpec],
) -> dict[str, ResolvedVar]:
    """Resolve each registry variable against ``variables.json`` and verify bracket bounds.

    IDs are primary for detailed tables, with the label regex as a guard; if an ID's label no
    longer matches (or the ID vanished) the variable is searched by label within its table.
    Data Profile items are resolved by label only. Missing, ambiguous or mismatched variables
    raise :class:`BuildError` naming the registry key.
    """
    resolved: dict[str, ResolvedVar] = {}
    for key, var in variables.items():
        dataset_meta = meta[var.dataset]
        found: str | None = None
        moved = False
        if var.resolve == "id":
            vid = f"{key}E"
            info = dataset_meta.get(vid)
            if info is not None and (
                var.label is None or re.search(var.label, str(info.get("label", "")), re.I)
            ):
                found = vid
            elif var.label is None:
                raise BuildError(
                    f"variable {key}: {vid} is not in the {var.dataset} variables for this "
                    "vintage (a bracket cell without a label cannot be searched). The ACS "
                    "table layout may have changed."
                )
        if found is None:
            if var.label is None:
                raise BuildError(f"variable {key} has no label pattern to resolve it by")
            candidates = _search(var, dataset_meta)
            if not candidates:
                raise BuildError(
                    f"variable {key}: no variable in table {var.table} matches the label "
                    f"pattern {var.label!r}. The ACS label may have changed; update the registry."
                )
            if len(candidates) > 1:
                raise BuildError(
                    f"variable {key}: label pattern {var.label!r} is ambiguous in table "
                    f"{var.table}: {', '.join(candidates)}."
                )
            found = candidates[0]
            moved = var.resolve == "id"
        resolved[key] = ResolvedVar(
            key=key,
            id=found,
            base_id=found[:-1],
            label=str(dataset_meta[found].get("label", "")),
            table=var.table,
            dataset=var.dataset,
            moved=moved,
        )

    for spec in brackets:
        for bracket in spec.brackets:
            for key in bracket.keys:
                label = resolved[key].label
                bounds = parse_bounds(label)
                if bounds is None or not bounds_match(bounds, (bracket.lo, bracket.hi)):
                    raise BuildError(
                        f"bracket {key} ({resolved[key].id}) has label {label!r}, which does not "
                        f"match the expected bounds [{bracket.lo}, {bracket.hi}). The ACS "
                        "brackets may have changed; update the registry."
                    )
    return resolved
