"""Performance budget for input handling (SPEC §7): parse + review of 1,000 ZIPs <= 0.5 s."""

from __future__ import annotations

import time

import pytest
from synth_facts import make_facts

from zipographics.review import review_lines, summarize
from zipographics.zips import parse_paste

pytestmark = pytest.mark.slow


def test_parse_and_review_of_1000_mangled_zips_fits_the_budget() -> None:
    # worst case for review: every ZIP is repaired, so every one is compared with "the rest"
    zips = [f"0{2000 + i}" for i in range(1000)]
    states = ["MA", "NH", "RI", "CT"]
    facts = make_facts({z: (states[i % 4], 5000 + i, 2000) for i, z in enumerate(zips)})
    text = ", ".join(z.lstrip("0") for z in zips)

    start = time.perf_counter()
    parsed = parse_paste(text)
    summary = summarize(parsed, facts)
    lines = review_lines(summary)
    elapsed = time.perf_counter() - start

    assert len(summary.recognized) == 1000
    assert len(summary.repaired) == 1000
    assert lines
    assert elapsed <= 0.5, f"parse + review took {elapsed:.3f}s (budget 0.5s)"
