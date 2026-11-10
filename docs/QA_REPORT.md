# QA report

Bugs found during testing and QA, one entry each, with a regression test. Phase QA-review
summaries are appended at the end of each phase (see CLAUDE.md, "How to work").

## Summary

_Filled in at the end of the build (test counts per layer, coverage, gate results, bugs found and
fixed, golden-scenario verification, SPEC §10 checklist)._

## Bugs

| # | phase | symptom | root cause | fix | regression test |
|---|---|---|---|---|---|
| | | | | | |

## Golden scenarios: independent verification

_For each SPEC §9.4 scenario: the input, where each expected value came from (data.census.gov
table and geography, or a hand calculation shown step by step), and the result._

## Phase reviews

_One entry per phase: reviewer findings, how each was triaged, gate results._

### Phase 0: environment (2026-11-09)
- Windows 11, Python 3.12.15, uv 0.13.5. `uv sync` and `uv run python scripts/check.py`: all six
  gates pass (ruff, format, mypy, pytest 2 passed / 100 % coverage, file size, secrets).
- Git identity present. CI config reviewed against SPEC §7/§9.6 (ubuntu + windows × 3.11 + 3.12,
  `uv sync --locked`, runs `scripts/check.py`, no key). Not run on GitHub (no remote yet).
- No `/qa-review` for this phase: there is no code beyond two smoke tests.
