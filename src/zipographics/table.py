"""Ordering of the ZIP table, policy-enforced (SPEC §5.5, §5.7).

Input order and ZIP order are always allowed. Ordering by any metric is ranking ZIPs by a
demographic characteristic, so restricted mode refuses it for **every** metric (D4).
"""

from __future__ import annotations

import math

from zipographics import metrics
from zipographics.analysis import Analysis
from zipographics.models import UsePolicy
from zipographics.restricted import require_unrestricted

INPUT = "input"
ZIP = "zip"


def order(
    a: Analysis,
    key: str,
    policy: UsePolicy | None,
    *,
    descending: bool = False,
    index: bool = False,
) -> tuple[str, ...]:
    """The recognized ZIPs of ``a`` ordered by ``key``: ``"input"``, ``"zip"`` or a metric id.

    ``index=True`` orders by the ZIP's index against the benchmark instead of its value. Unknown
    values sort last in both directions; ties keep input order.
    """
    if key == INPUT:
        return a.zips[::-1] if descending else a.zips
    if key == ZIP:
        return tuple(sorted(a.zips, reverse=descending))
    require_unrestricted(policy, "rank")
    if key not in metrics.BY_ID:
        raise ValueError(f"Unknown order key: {key!r}")
    if index:
        if not metrics.BY_ID[key].indexable:
            raise ValueError(f"{metrics.BY_ID[key].name} is a count and has no index.")
        values: list[float | None] = [v.value for v in a.zip_index(key)]
    else:
        values = [a.value(z, key).estimate for z in a.zips]
    known = [
        (v, z) for v, z in zip(values, a.zips, strict=True) if v is not None and not math.isnan(v)
    ]
    unknown = tuple(z for v, z in zip(values, a.zips, strict=True) if v is None or math.isnan(v))
    known.sort(key=lambda item: item[0], reverse=descending)  # stable, so ties keep input order
    return tuple(z for _, z in known) + unknown
