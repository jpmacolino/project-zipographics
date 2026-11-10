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
| 16 | 3 | **Key-handling hardening.** Exceptions other than `requests.RequestException` from `session.get` (ValueError, OSError, `http.client.InvalidURL`...) escaped unwrapped and could carry the request URL; a `KeyboardInterrupt` printed a raw traceback; a key cut at the 200-character truncation boundary left a 10-character prefix; an upper-cased echo of the key survived; `extra=` log fields were never scrubbed | `_request` caught only `RequestException`; `main` caught only `Exception`; truncate-then-redact; case-sensitive literal match; the factory runs before `extra` is attached | Any `Exception` becomes a sanitized `NetworkError` raised outside the handler; `main` handles `KeyboardInterrupt` (exit 130, one line); redact then truncate; case-insensitive; `Logger.makeRecord` hook scrubs extras | `test_any_exception_from_the_session_becomes_a_sanitized_network_error`, `test_a_keyboard_interrupt_exits_130_with_one_line`, `test_a_key_at_the_truncation_boundary_is_not_half_printed`, `test_redaction_is_case_insensitive_for_the_literal_key`, `test_extra_fields_on_a_log_record_are_scrubbed` |
| 17 | 3 | The redaction backstop (record factory) had no effective test: its removal survived the suite because pytest's own handlers carried the filter | Unit test ran inside pytest's logging setup | A subprocess test with a filter-less handler added after install, and a constructor-installs-redaction test | `test_a_handler_added_after_install_is_protected_in_a_clean_process`, `test_the_client_constructor_installs_redaction` |
| 18 | 3 | A failure while writing the second or third artifact left the previous build half-replaced (profile new, benchmarks and metadata old) | Each file was atomic alone, with no transaction across files | `_publish` writes every `.tmp` first and renames them all only after every write succeeded, metadata last | `test_a_failure_while_writing_leaves_every_old_artifact_untouched` |
| 19 | 3 | `data.load` did not check five benchmark columns with the real registry (`B28002_013_m`, `DP03_UNINS_*`, `DP03_CIVNONINST_e`) | Sliced `var_columns[:2n]`, but that list interleaves `_code` columns | Explicit `_e`/`_m` list | `test_every_benchmark_column_of_the_real_registry_is_checked` (5 columns), `test_the_real_registry_loads_when_every_column_is_present` |
| 20 | 3 | A truncated or empty 200 response was reported as "API rejected the key" (exit 3, no retry); chunked/corrupt transfers were not retried; a corrupt cached JSON file crashed with exit 1 | Any `json.loads` failure on 200 meant "bad key" | Only non-JSON that does not start with `[`/`{` is a rejected key; truncated bodies and `ChunkedEncodingError`/`ContentDecodingError` retry; a corrupt cache file is fetched again | `test_a_truncated_200_body_is_retried_and_is_not_blamed_on_the_key`, `test_truncated_or_corrupt_transfers_are_retried`, `test_a_corrupt_cache_file_is_refetched_not_a_crash`, `test_an_error_page_is_still_a_rejected_key` |
| 21 | 3 | Validation gaps: duplicate geometry ZIPs accepted; a map covering 1 of 6 ZIPs accepted; `--only geo` with no profile skipped all geometry checks (a null geometry was written, exit 0); `inf`/`1e400` reached the parquet and `-inf` crashed; unparseable text silently became null | Checks only ran with a profile; no finite check | `geometry_problems` (duplicates, nulls, coverage ≥ 95 %) always runs; non-finite values become nulls and are counted (`non_finite`, `non_numeric`) | `test_geometry_checks_apply_even_without_a_profile`, `test_duplicate_geometry_zips_fail`, `test_a_truncated_map_fails_against_the_profile`, `test_non_finite_numbers_become_null_and_are_counted`, `test_non_numeric_text_is_counted_but_blanks_are_not` |
| 22 | 3 | A UTF-16 `.env` (PowerShell 5.1 `echo > .env`) crashed with a traceback; a blank `CENSUS_API_KEY` in the environment hid the key in the file; `--tolerance nan/-1`, `--vintage -5`, `--data-dir <file>` were accepted or crashed; the secrets gate missed bare 40-hex constants, `api_key:` forms, upper-case `KEY=`, `key%3D`, `prod.env`, `.envrc` | Unhandled decode error; `override=False` treats an empty variable as set; no argument validation; narrow gate patterns | UTF-8 message (exit 3); blank counts as unset; validated arguments (exit 2); gate patterns and `.gitignore` widened (tests use a throwaway git repo) | `test_a_utf16_dotenv_gets_a_clear_message_not_a_traceback`, `test_a_blank_real_variable_does_not_hide_the_key_in_the_dotenv_file`, `test_nonsense_numeric_arguments_are_usage_errors`, `tests/unit/test_secrets_gate.py` |
| 23 | 3 | The import-graph tests could be bypassed by a relative import or `importlib.import_module("...")`, and did not ban network modules in runtime files | AST check ignored `node.level` and dynamic imports | Scanner resolves relative imports and literal `import_module`/`__import__`; runtime files may not import `requests`, `urllib3`, `socket`, `http.client` | `test_the_violation_scanner_catches_relative_and_dynamic_imports`, `test_runtime_modules_have_no_forbidden_or_network_imports` |
| 24 | 4 | exit 5: median household income non-null for 92.1 % of ZCTAs with population (< 95 %) | the ACS suppresses published medians for small areas; the spec floor assumed about 100 % | separate 90 % floor for published medians (DECISIONS B16.1) | `test_published_medians_have_their_own_ninety_percent_floor`, `test_a_median_below_ninety_percent_still_fails`, `test_counts_and_shares_keep_the_ninety_five_percent_floor` |
| 25 | 4 | exit 5: no county benchmark for `09001`... (Connecticut) | ACS 2022+ uses planning regions; the 2020 relationship file uses legacy counties | CT ZCTAs keep the county name but not the FIPS; limit 2 %; recorded in metadata (B16.2) | `test_a_county_without_an_acs_row_keeps_its_name_but_loses_its_fips` and 3 more in `test_realdata_rules.py` |
| 26 | 4 | exit 5: geometry has ZIPs with no profile row (`00802`, `00820`...) | the boundary file includes 19 ZCTAs the ACS does not publish | dropped from the map, recorded; more than 25 fails (B16.3) | `test_polygons_without_a_profile_row_are_dropped_and_recorded`, `test_a_boundary_file_with_many_unmatched_polygons_is_rejected` |
| 27 | 4 | pandas `PerformanceWarning` (fragmented frame) on every level | `out[col] = ...` inserted about 450 columns one at a time | columns built at once | `test_cleaning_hundreds_of_variables_does_not_fragment_the_frame` |
| 28 | 4 | map 43 MB at tolerance 0.002 (target about 30 MB) | default tolerance too fine for a map-only layer | default 0.004 gives 25 MB (measured 5 values, B16.4) | `test_the_map_covers_the_profile_within_the_size_target` (data) |
| 29 | 4 | Trade-area shares biased low: a ZIP with a denominator but no numerator (14 % of ZCTAs for B25046) added to the denominator only (600 / 2,000 instead of 600 / 1,000) | sums were taken per cell, independently | paired-ZIP rule (`profile._paired`): such a ZIP leaves both sums and the result is flagged `incomplete` (B17.1) | `tests/unit/test_phase4_regressions.py` (7 tests) |
| 30 | 4 | The data tests and `validate_artifacts` passed on corrupted artifacts (all `_code` set to "none", owner/renter swapped, a column scaled, shuffled map ZIPs, relabelled CRS, null national benchmark cell, wholly null non-core variable, county gaps anywhere under 2 %) | checks only on core variables, plausibility bands and counts | 50 % floor for every variable; non-null national/state benchmark rows; cross-table totals; EPSG:4326 and text ZIPs; Connecticut-only county gaps; loader type checks; independent raw-cache re-parse, point-in-polygon and literal-value data tests | `tests/unit/test_validation_hardening.py` (26 tests), `tests/integration/test_artifact_integrity.py` (29 data tests); 8 mutants, all caught (see Phase 4 below) |
| 31 | 4 | A live test said B25046 was 97 % non-null (truth 86.4 %), which wrongly moved `veh_per_hh` to B25046 | the helper compared `astype(str)` to "None"/"nan"; pandas 3 nulls print as `<NA>` | helper uses `pd.to_numeric` and a sentinel threshold; B25046 reverted to B25044 (B17.2) | `test_b25046_aggregate_vehicles_exists_at_zcta_level_but_is_incomplete` (network), `test_vehicles_per_household_is_the_b25044_weighted_count_labeled_at_least` |
| 32 | 4 | JSON null cells (1,363 estimates, 1,363 margins) were not counted in `metadata.json` | `_numeric` counted only unparseable text | `estimate:null` / `moe:null` counts | `test_json_nulls_are_counted_separately_from_sentinels`, `test_non_numeric_text_and_blanks_are_counted_separately` |

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
| L9 | LOW | shares biased low when a numerator is wholly null; mean vs per-capita handle null differently; a zero-household ZIP flips a median from published to interpolated; one null bracket MOE makes a trade-area median MOE unreliable | **Closed in Phase 4** for shares and ratios (paired-ZIP rule, bug 29, B17.1); the median cases stay flagged `incomplete` |
| L10 | LOW | in-radius per-ZIP columns, per-ZIP index tier | **Deferred to Phase 5/6** (UI/export layer) |
| L11 | LOW | display text "1939 or earlier" for the 1940 bound | **Deferred to Phase 5/6** (formatting) |
| L12 | LOW | FIPS test spot-checks 3 of 52 (reviewer verified all 52); NaN input to scalar helpers | **Accepted** |
| L13 | LOW | `median_age` sums 46 cells, `limited_english` 12 (approximation degrades) | **Deferred to Phase 4**: compare with published values |

Gates after triage: ruff, format, mypy, size, secrets pass; **582 tests passed**, coverage **99.6 %**
(line + branch); `pytest -m slow`: 3 passed (profile + per-ZIP table + index for 1,000 weighted ZIPs
0.13 s vs 1 s budget).

### Phase 3: redact, census_api, data_build, geo_build, data, build CLI (2026-11-09)
Independent `qa-reviewer` (fresh context; fake keys only; it was told not to touch `.env` or run
`scripts/build_data.py`). **What held up:** about 45 failure scenarios through `CensusClient` (HTTP
400/401/403/404/429/5xx with bodies echoing the URL or bare key, timeouts, `InvalidURL`, SSL and
redirect errors, malformed/gzip/UTF-16 bodies, ...) and the CLI behind real proxy behaviours leaked the
key through **no** channel (str, repr, tracebacks with chained causes, DEBUG logs of every library,
cache files and sidecars, metadata, parquet, object reprs); odd key shapes leaked nothing; exit codes
and the three exact messages were right; the **full real registry resolved against the real 2024
`variables.json`** (all 223 variables, none moved, all bracket bounds verified) and D4 on the real file
matched an independent computation (33,791 rows, 0 differences, no land ties). 73 hand-made mutants:
48 killed, 25 survived (about 9 redundant second redactions, the rest test gaps listed below).

| # | severity | finding | handling |
|---|---|---|---|
| 1 | HIGH (by the "any key leak" rule; low likelihood) | non-`RequestException` errors escape unwrapped; `KeyboardInterrupt` prints a chained traceback | **Fixed** (bug 16). A `sys.excepthook` was not added: `main` handles `KeyboardInterrupt`, and the scripts only run through `main` |
| 2 | MEDIUM | multi-file publish not atomic | **Fixed** (bug 18) |
| 3 | MEDIUM | `data.load` skips five benchmark columns | **Fixed** (bug 19), real-registry test |
| 4 | MEDIUM (tests) | redaction backstop untested; CLI exit-code mapping, `reserved=1`, chunk geography mismatch, `--only geo` stale profile, atomic writer, `population > 0` filter, US-over-PR GeoNames, constructor installing redaction untested | **Fixed** (bugs 17, 18, 21 and the regression file); D4 water tie-break was already tested; `stack_info` redaction left as is (nothing logs with `stack_info`) |
| 5 | LOW-MEDIUM | import-graph tests bypassable | **Fixed** (bug 23) |
| 6 | LOW-MEDIUM | truncated 200 body reported as a bad key | **Fixed** (bug 20) |
| 7 | LOW | UTF-16 `.env` traceback; blank real variable hides the file's key | **Fixed** (bug 22) |
| 8 | LOW | secrets gate and `.gitignore` gaps | **Fixed** (bug 22), tested against a throwaway git repo; a key split across string literals, UTF-16 files and notebooks remain undetectable by a line regex and are accepted |
| 9 | LOW | partial key after truncation; upper-case echo; `extra=` | **Fixed** (bug 16) |
| 10 | LOW | validation gaps (`--only geo` with no profile, duplicate or truncated geometry, non-finite values) | **Fixed** (bug 21) |
| 11 | LOW | robustness: corrupt cache hint, chunked-transfer retries, developer wording in a user error, odd arguments, non-str environment value | **Fixed** (bugs 20, 22 and `test_a_non_string_environment_value_does_not_crash`). **Deferred:** `download_file` has no retries or streaming (these files are fetched once and cached); `print` in `data_build.main` (CLI output goes to the terminal, documented in B13); exit code 1 for unexpected errors (recorded in B13); `pytest -l` on a failing `network` test would show `_request`'s `full` URL: **do not use `-l`/`--showlocals` for network runs** (noted in `tests/live` docstring) |
| 12 | INFO | Phase 4 risks: island-area ZCTAs have no state benchmark; detailed vs profile ZCTA sets may differ | **Open for Phase 4**: both fail loudly (exit 5) with a clear message if they occur; decide with the real data |
| - | LOW | `geo_build` coverage 79 % (read-error branches, `_polygonal` repair) | **Deferred**: the real boundary file exercises them in Phase 4; overall coverage 97 % |

Gates after triage: ruff, format, mypy, size, secrets pass; **884 tests passed**, coverage **97 %**
(line + branch). 13 targeted mutants of the new fixes: all killed (generic-exception wrap,
truncate-before-redact, truncated-JSON classification, corrupt-cache trust, case-sensitive redaction,
extras scrubbing, makeRecord hook, benchmark column slice, non-atomic publish, map coverage floor,
interrupt exit code, blank-env override, infinite values).

### Phase 4: real data build (2026-11-09/10)
First real build and an independent `qa-reviewer` (fresh context; told not to touch `.env`). **What held up:**
every published cell matched the reviewer's own re-parse of the API responses (0 mismatches over a sample),
no leading zero lost, no key in any file, all variables resolved with unchanged labels.

| # | severity | finding | handling |
|---|---|---|---|
| 1 | HIGH | shares biased low when one ZIP lacks a numerator but has its denominator (B25046: 14 % of ZCTAs) | **Fixed** (bug 29, DECISIONS B17.1); this also closes Phase 2 L9 for shares and ratios |
| 2 | HIGH (tests) | corrupted artifacts passed the data tests and `validate_artifacts` | **Fixed** (bug 30). Eight corrupted copies of `data/` were run through `pytest -m data`: **all eight caught** (`_code` all "none"; owner/renter swapped; median income x10; home value x1.5, which no total can catch, so only the raw re-parse does; shuffled map ZIPs; relabelled CRS; null national benchmark cell; and MOE 0 turned into null, which **survived the first version** because a random 500-ZIP sample holds almost no controlled margins, so the sample is now stratified: all 13 ZCTAs with one, plus null-margin and null-estimate strata) |
| 3 | MEDIUM | wrong B25046 coverage (97 % vs 86.4 %) and a stale "216 of 223" figure | **Fixed** (bug 31, DECISIONS V5/B17.2); current figures: 233 of 240 variables at 99 % or more |
| 4 | MEDIUM | the lens charts of Appendix D need cells the registry lacked (units in structure, tenure by move-in, vehicles available) | **Decided** (B17.3): 18 variables and 11 metrics added; each group partitions its table exactly once (`tests/unit/test_chart_cells.py`). Appendix C is extended: owner to be told |
| 5 | LOW | county gaps tolerated anywhere under 2 %; map CRS and ZIP type unchecked; loader did not check text ids | **Fixed** (bug 30) |
| 6 | LOW | stale numbers in DECISIONS (V6, households under 10) | **Fixed**: recomputed from the final build |
| 7 | INFO | map simplification distorts small urban ZIPs; two NY ZCTAs have no ACS data | **Disclosed**: metadata note, DECISIONS B17.6-7 |

Gates after triage: ruff, format, mypy, size and secrets pass; **939 default tests** (coverage **97.85 %**,
line + branch), **47 `data` tests** (18 earlier + 29 new) pass on the rebuilt data; the 5 `network` tests
passed on the earlier build (key accepted; the registry resolved against the real `variables.json`) and are
re-run after this triage: 5 passed.

Measured on the real data (not snapshots; SPEC section 6.4/9.3): published vs interpolated median household
income, 1,489 sampled ZCTAs: median gap **1.22 %**, p95 **5.99 %**, max 17.2 %; interpolated MOE / published
MOE: median **1.14**, p10 0.79, p90 1.77. Coverage among ZCTAs with population (33,174 of 33,772): **233 of
240 variables at 99 % or more**; lowest: gross rent 77.6 %, home value 91.2 %, median income 92.1 %, mean
income 96.2 %, year built 97.0 %, per capita income 98.5 %, median age 98.9 % (published medians and means
are suppressed for small areas). Sentinels, top/bottom codes, label resolution and the 5-year notes page:
DECISIONS "Phase 4".
