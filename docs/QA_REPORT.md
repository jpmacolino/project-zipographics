# QA report

Bugs found during testing and QA, one entry each, with a regression test. Phase QA-review
summaries are appended at the end of each phase (see CLAUDE.md, "How to work").

## Summary

_Filled in at the end of the build (test counts per layer, coverage, gate results, bugs found and
fixed, golden-scenario verification, SPEC §10 checklist)._

## Bugs

| # | phase | symptom | root cause | fix | regression test |
|---|---|---|---|---|---|
| 1 | 1 | Header-less multi-column CSV (`02108,Boston`) silently dropped its first ZIP | Row 1 always treated as a header | Header-less detection (no ZIP-like header name and a ZIP-like value in row 1); columns named `Column N`; row 1 kept as data | `test_header_less_multi_column_file_keeps_its_first_zip` (+ mangled, later-column variants) |
| 2 | 1 | `.txt`/CSV of ZIPs on one line or several per line failed, or offered ZIP values as column names | A single row was read as a header; single-column cells were not split | All-ZIP files are read cell by cell; single-column cells split on paste separators (space, pipe, ...) | `test_zip_lists_in_any_layout_are_accepted` (6 layouts) |
| 3 | 1 | Input whose recognized ZIPs all have 0 population could continue | No block rule | Review blocks: "None of the recognized ZIPs has a residential population..." | `test_all_recognized_zips_without_residents_blocks` |
| 4 | 1 | `summarize` took 13.9 s for 19,000 repaired ZIPs (quadratic) | `dominant_of(exclude=z)` rescanned all ZIPs per repaired ZIP | `StateTotals` (build once, O(states) per exclusion); property test against the brute-force rule | `test_state_totals_match_the_brute_force_rule_for_every_exclusion`, `test_19000_repaired_zips_are_summarized_quickly` (slow) |
| 5 | 1 | `summarize` raised `TypeError` on `Float64`/object population columns; duplicate ZIP index gave a raw pandas error | `math.isnan` on `pd.NA`/`None`; no duplicate check | Coerce with `pd.to_numeric(...).astype("float64")`; `validate_facts` rejects duplicates | `test_nullable_and_object_columns_are_accepted`, `test_duplicate_zip_index_is_rejected_clearly` |
| 6 | 1 | Repaired line printed `"2108"` / `="2109"` with quotes and `=` | Used `raw.strip()` | Uses `clean_token(raw)` | `test_repaired_line_shows_the_cleaned_raw_token` |
| 7 | 1 | (a) blank overlap then a value on a repeat gave no warning; (b) `-5` reported as "not a number"; (c) a 300 KB token of `="` took ~8 s | (a) conflict required a first value; (b) regex had no sign; (c) quadratic cleanup loop | (a) blank-then-value is a conflict; (b) signed-number check; (c) tokens over 40 chars skip cleanup | `test_blank_overlap_then_a_value_on_a_repeat_is_a_conflict`, `test_overlap_rejection_reasons`, `test_a_pathological_token_is_rejected_quickly` |

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

### Phase 1: zips, importer, Zipcator contract, review (2026-11-09)
Independent `qa-reviewer` (fresh context). **No HIGH findings**: no lost leading zero on any probed
path (50+ tokens, all fixtures), no `int()`/numeric dtype/`read_csv` on a ZIP path; fixtures
`boston_3mi.csv` and `tampa_5mi_excel.csv` are byte-identical to a fresh Zipcator run; an
independent `csv.reader` read of all 12 fixtures matches `import_csv`. 27 hand-made mutants: 22
killed, 1 no-op, 5 survived (now covered, below).

| # | severity | finding | handling |
|---|---|---|---|
| 1 | MEDIUM | header-less multi-column CSV drops first ZIP | **Fixed** (bug 1) |
| 2 | MEDIUM | one-line / several-per-line ZIP lists fail | **Fixed** (bug 2). Pipe-delimited files with a header row (`ZIP\|City`) are still unsupported (SPEC §5.2 names comma, semicolon, tab only) |
| 3 | LOW | all-zero-population input does not block | **Fixed** (bug 3) |
| 4 | LOW | review O(n²) in repaired ZIPs | **Fixed** (bug 4) |
| 5 | LOW | `Float64`/object columns crash; duplicate index | **Fixed** (bug 5) |
| 6 | LOW | repaired line shows quotes and `=` | **Fixed** (bug 6) |
| 7 | LOW | blank-then-value overlap; negative-overlap reason; quadratic `clean_token` | **Fixed** (bug 7) |
| 7 | LOW | `02108 1234` (space) creates phantom `01234` | **Deferred**: spaces are separators per SPEC §5.2; documented in B6; the unexpected-state check is the guard |
| 7 | LOW | UTF-16 *without* a BOM decodes as UTF-8 with NULs (all tokens invalid) | **Deferred**: Excel's "Unicode Text" writes a BOM; the user sees invalid entries, not wrong data |
| 7 | LOW | two repaired ZIPs in different states flag each other | **Deferred, pinned by test** (`test_two_repaired_zips_in_different_states_flag_each_other`); spec-literal (B10), noisy only for tiny lists |
| 7 | LOW | context line omitted when `policy=None` | **Deferred**: the UI always passes a policy (Phase 5/6); revisit then |
| 8 | LOW | 02445 asserted as `0 < x <= 0.1` | **Fixed**: exact `0.006514 ± 1e-6` (reproducible: `cmp` vs fresh Zipcator output) |
| 8 | LOW | 5 surviving mutants | **Fixed**: 75 % content share, cp1252-only chars (`€`, curly quotes), UTF-16 BE BOM, whitespace around invalid cell, >20 not-found listing. Not covered: the delimiter-sniff row window (`_SNIFF_ROWS`); accepted, behavior only differs on files whose first 20 rows mislead |
| 8 | LOW | no Zipcator-side export-contract test | **Not Phase 1 work**: SPEC §5.3 / handoff Task B, a separate session in the Zipcator repo, now unblocked (fixtures are committed) |

Also noted (DECISIONS B10): unknown population counts as 0 in the dominant-state rule, so if most
ZIPs have suppressed population the tie-break decides the default benchmark; acceptable.

Gates after triage: ruff, format, mypy, size, secrets pass; **281 tests passed**, coverage
**99.72 %** (line + branch); `pytest -m slow`: 2 passed (1,000 repaired ZIPs parse + review
0.10 s vs 0.5 s budget; 19,000 repaired ZIPs summarize < 1 s, was 13.9 s).
