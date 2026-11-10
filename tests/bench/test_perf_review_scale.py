"""QA #4: review must stay linear when a big upload is mostly repaired ZIPs (SPEC §7)."""

from __future__ import annotations

import time

import pytest
from synth_facts import make_facts

from zipographics.review import summarize
from zipographics.zips import parse_paste

pytestmark = pytest.mark.slow


def test_19000_repaired_zips_are_summarized_quickly() -> None:
    zips = [f"0{1000 + i}" for i in range(9000)] + [f"{10000 + i}" for i in range(10000)]
    facts = make_facts({z: ("MA" if z.startswith("0") else "NY", 3000, 1200) for z in zips})
    parsed = parse_paste(" ".join(z.lstrip("0") for z in zips[:9000]) + " " + " ".join(zips[9000:]))
    start = time.perf_counter()
    s = summarize(parsed, facts)
    elapsed = time.perf_counter() - start
    assert len(s.recognized) == 19000
    assert not s.can_continue  # over the 1,000 limit
    assert elapsed < 1.0, f"summarize took {elapsed:.2f}s (was 13.9s when quadratic)"
