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
| 8 | 2 | `moe_proportion` flipped from 0 to a large value under uniform scaling (X=1 ±1 of Y=41.5 ±41.5, w=3 gave 0.034 instead of 0) | Equal relative MOEs make the radicand exactly 0 in theory but ±1e-16 in floats, so rounding chose between the minus and plus branches | A radicand within 1e-12 of its plus-form value counts as 0 (scalar and vectorized) | `test_proportion_moe_radicand_within_float_noise_of_zero_is_zero_not_the_plus_branch`, `test_vectorized_proportion_has_the_same_noise_and_overflow_behavior` (found by the property tests) |
| 9 | 2 | Scalar `moe_proportion` / `moe_ratio` / `index_value` raised `OverflowError` for absurdly small denominators or benchmarks, while the vectorized versions returned NaN | `p**2` and `math.floor(inf)` | Overflow or non-finite results are unknown (None / NaN) in both | `test_proportion_moe_with_an_absurdly_small_denominator_is_unknown_not_a_crash`, `test_overflowing_intermediate_values_are_unknown` (found by the property tests) |
| 10 | 2 | A published median with no `_code` column in the frame was shown as exact and indexable (index 417 instead of null); a median variable with no `EA` column got code `none`; any string was accepted as a code | `profile._Data.code` and `clean_frame` defaulted silently | Both raise; codes validated | `test_a_published_median_without_its_code_column_is_rejected`, `test_an_unknown_median_code_is_rejected`, `test_a_median_variable_without_its_annotation_column_is_an_error`, `test_a_coded_published_median_has_no_index_in_the_per_zip_column` |
| 11 | 2 | A sentinel in the frame (e.g. -666666666) was summed as a number; shares could go negative | profile trusted its input; clamp only at 1 | `_Data` rejects values <= -1e8; shares clamp to [0, 1] and flag | `test_a_sentinel_that_reaches_the_frame_is_rejected`, `test_a_negative_numerator_is_clamped_to_a_zero_share_and_flagged` |
| 12 | 2 | 205 of 223 registry variables had no label check, so a wrong ID could not be caught | Label regexes only on a few cells | Label regex for every single cell; table-driven definition tests; DP regexes anchored | `tests/unit/test_registry_definitions.py` |
| 13 | 2 | `clean_frame` turned integer geography keys into strings (`2108`), losing leading zeros | `astype(str)` on numbers | Non-string keys raise | `test_numeric_geography_keys_are_rejected_not_stringified` |
| 14 | 2 | Exact-half index values rounded down (0.145 -> 14); `build_profile` double-counted duplicate ZIPs and accepted weights of 0, negative or inf; a weighted single count was labeled `published`; unknown states or short county ids broke `benchmark_options` | Float noise; missing input validation | Round before +0.5; validation; source rule; filtering | `test_index_rounds_exact_halves_up_despite_float_noise`, `test_duplicate_zips_are_rejected_instead_of_double_counted`, `test_weights_must_be_in_zero_one`, `test_a_scaled_single_count_is_not_labeled_published`, `test_states_outside_the_acs_geography_are_ignored`, `test_county_ids_must_be_five_digits_and_missing_names_fall_back` |
| 15 | 3 | Scalar and vectorized formulas disagreed at extreme inputs found by seed sweeps of the property tests: (a) a radicand that is zero in theory flipped between 0 and 9e-9 under uniform scaling (the noise clamp covered only the negative side); (b) a denormal denominator made `p = x/y` overflow, which the scalar turned into `0.0` and the vectorized into unknown; (c) an index against a denormal benchmark was ~1e301 with different float rounding in each | Float noise on one side only; no non-finite guard on the scalar; no sanity bound on the index | Radicand within 1e-12 of zero in either direction is zero; non-finite `p`/`plus` is unknown in both; an index above 1e9 is unknown in both | `test_a_zero_radicand_is_zero_on_both_sides_of_float_noise`, `test_a_tiny_denominator_is_unknown_in_both_implementations`, `test_overflow_in_the_proportion_formula_is_unknown_in_both_implementations`, `test_an_absurd_index_is_unknown_in_both_implementations`; verified with a 40-seed Hypothesis sweep |

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

### Phase 2: stats, sentinels, metrics, profile (2026-11-09)
Independent `qa-reviewer` (fresh context). **No HIGH findings.** It re-derived every formula from the
official texts and reproduced every worked example; an independent median + MOE implementation matched
D8 to 10 digits (29,572 random distributions; one exact-tie difference); medians are never averaged,
summed or weighted anywhere; no sentinel survives the sentinel layer; vectorized and scalar formulas
agree on 20,000 random draws. 76 hand-made mutants: most killed; the survivors are now covered.

| # | severity | finding | handling |
|---|---|---|---|
| M1 | MEDIUM | missing/invalid median `_code` fails open | **Fixed** (bug 10) |
| M2 | MEDIUM | profile trusts frame values (sentinels, negatives) | **Fixed** (bug 11) |
| M3 | MEDIUM | label guard absent for most cells; 6 registry mutants survived | **Fixed** (bug 12); table-driven tests pin every share |
| M4 | MEDIUM | vectorized plus-form fallback, all-null bracket, coded `index_column`, empty-end-bracket interval untested | **Fixed**: tests added |
| M5 | MEDIUM | `clean_frame` stringifies numeric keys | **Fixed** (bug 13) |
| L1 | LOW | zero-estimate MOE rule | **Open, recorded** (B12): read the Census worked-examples document at the start of Phase 4 |
| L2 | LOW | exact-half index rounding | **Fixed** (bug 14) |
| L3 | LOW | tie convention differs from PUMS | **Documented** (B12), pinned by test |
| L4, L5 | LOW | `source` on scaled counts; duplicate ZIPs and bad weights | **Fixed** (bug 14) |
| L6 | LOW | benchmark options robustness | **Fixed** (bug 14) |
| L7 | LOW | wrong test file named in D8 | **Fixed** |
| L8 | LOW | DP regexes unanchored | **Fixed** (bug 12) |
| L9 | LOW | shares biased low when a numerator is wholly null; mean vs per-capita handle null differently; a zero-household ZIP flips a median from published to interpolated; one null bracket MOE makes a trade-area median MOE unreliable | **Deferred to Phase 4**: measure how often it happens in real data; all cases are flagged `incomplete` |
| L10 | LOW | in-radius per-ZIP columns, per-ZIP index tier | **Deferred to Phase 5/6** (UI/export layer) |
| L11 | LOW | display text "1939 or earlier" for the 1940 bound | **Deferred to Phase 5/6** (formatting) |
| L12 | LOW | FIPS test spot-checks 3 of 52 (reviewer verified all 52); NaN input to scalar helpers | **Accepted** |
| L13 | LOW | `median_age` sums 46 cells, `limited_english` 12 (approximation degrades) | **Deferred to Phase 4**: compare with published values |

Gates after triage: ruff, format, mypy, size, secrets pass; **582 tests passed**, coverage **99.6 %**
(line + branch); `pytest -m slow`: 3 passed (profile + per-ZIP table + index for 1,000 weighted ZIPs
0.13 s vs 1 s budget).
