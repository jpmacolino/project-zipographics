# Decisions

One entry per decision: date, decision, why, alternatives considered, and the source URL when a
fact was verified. When an official source conflicts with the spec or the original brief, the
official source wins and the conflict is recorded here.

## Made during scoping (2026-11-09)

### Facts verified on official sources

**V1. ACS vintage.** The 2020-2024 ACS 5-year estimates were released **January 29, 2026**
([ACS updates](https://www.census.gov/programs-surveys/acs/news/updates.html),
[2024 release schedule](https://www.census.gov/programs-surveys/acs/news/data-releases/2024/release-schedule.html)).
ZCTA-level ACS data exists only in the 5-year product.
**Conflict with the brief:** the brief expected the next vintage (2021-2025) "around December
2026". The official
[2025 release schedule](https://www.census.gov/programs-surveys/acs/news/data-releases/2025/release-schedule.html)
(updated 2026-10-13) lists the 5-year release as **TBD**; the 2025 1-year release slipped to
October 29, 2026 (the updates page cites Departmental Administrative Order 216-26). The
`api.census.gov/data/2025/acs/acs5` endpoint did not exist on 2026-11-09.
Decision: the vintage is a build parameter (`--vintage`, default `2024`), recorded in
`metadata.json` and shown in the app and on every export. Nothing hardcodes "2024" outside that
default.

**V2. API key.** "An API key must be used with all data queries made to the Census Data API"
([Query Limits](https://www.census.gov/data/developers/guidance/api-user-guide.Query_Limits.html)).
Signup: <https://www.census.gov/data/developers/api-key.html> (the
[API key guide](https://www.census.gov/data/developers/guidance/api-user-guide.API_Key.html)
links there). The requesting email must end in .com, .net, .org, .gov or .edu or the key can't
be activated. Note: Zipcator's error message points to `api.census.gov/data/key_signup.html`;
Zipographics uses the page the official guide links to.

**V3. Variables per request:** "You can include up to 50 variables in a single API query" (same
Query Limits page). No daily limit is published on that page.

**V4. ZCTA geography syntax.** In both `2024/acs/acs5` and `2024/acs/acs5/profile`
(`.../geography.json`), ZCTA is geography level 860 with **no `requires`**, so all ZCTAs come
back with `for=zip%20code%20tabulation%20area:*` (no `in=state:`). State (040) and US (010) are
standalone; county (050) requires state: `for=county:*&in=state:*`.

**V5. Tables available in 2024 acs5** (group listing and `groups/<ID>.json`): B01003, B01001,
B01002, B11001, B11003, B11005, B09001, B19001, B19013, B19025, B19301, B17001, B25001, B25002,
B25003, B25024, B25034, B25035, B25038, B25044, B25063, B25064, B25075, B25077, B25037, B08006,
B08301, B08303, B15003, B23025, B27010, C27006, B28002, B21001, B18101, B03003, B01001I, C16001.
Data Profiles DP02, DP03, DP04, DP05 exist in `acs5/profile` (plus DP02PR for Puerto Rico).
B25075's top bracket is "$2,000,000 or more". Presence in the dataset doesn't guarantee non-null
values for every variable at ZCTA level: the Phase 4 build reports per-variable ZCTA coverage and
logs any gap here. B19001 bracket labels were not readable during scoping; the build reads labels
from `variables.json` for the chosen vintage instead of hardcoding them.

**V6. Annotation (sentinel) values**, from the
[ACS notes on estimate and annotation values](https://www.census.gov/data/developers/data-sets/acs-1year/notes-on-acs-estimate-and-annotation-values.html)
(1-year page, revised 2026-07-20; the 5-year page did not load during scoping and must be checked
in Phase 3):

| value | annotation | meaning | Zipographics treatment |
|---|---|---|---|
| -666666666 | `-` | estimate not computable (too few cases, or median in open interval / 5-year median MOE larger than median) | null |
| -999999999 | `N` | too few sample cases to display | null |
| -888888888 | `(X)` | not applicable / not available | null |
| -222222222 | `**` | MOE not computable (too few sample observations) | MOE null -> reliability "unreliable" |
| -333333333 | `***` | MOE not computable (median in open-ended interval) | MOE null; estimate kept and flagged top/bottom-coded |
| -555555555 | `*****` | estimate controlled to an independent estimate; MOE "may be treated as zero" | MOE 0 |
| varies | `median-` / `median+` | median falls in the lowest / highest open-ended interval (e.g. "250,000+") | estimate kept, flagged bottom/top-coded |
| null | | no data for the geography | null |

**V7. Top- and bottom-coded medians.** Not confirmed from an official page during scoping (the
Subject Definitions' "Derived Measures" section and Appendix A could not be extracted). Decision:
detect open-ended medians from the annotation fields (`...EA` = `median+` / `median-`) that
`group(...)` queries return, not from hardcoded numbers. The believed codes (median household
income 250,001 shown as "250,000+"; median home value 2,000,001 "2,000,000+"; median gross rent
3,501 "3,500+") are used only as a build-time cross-check whose result is logged here in Phase 4.

**V8. Median interpolation.** "The ACS calculates medians using a linear interpolation method"
([2020-2024 PUMS Accuracy of the Data](https://www2.census.gov/programs-surveys/acs/tech_docs/pums/accuracy/2020_2024AccuracyPUMS.pdf),
"Medians"). The same document gives the median standard error as half the width of a 68 %
interval found by interpolating at 50 % +/- SE(50 %), and says the 2024 PUMS is the last year
design factors will be published. Published medians are computed from finer "standard
distributions" than the published bracket tables, so a median we interpolate from B19001 for a
single ZIP will differ slightly from the published B19013 value. See SPEC §6.4.

**V9. MOE approximations** ([ACS General Handbook 2020, ch. 8](https://www.census.gov/content/dam/Census/library/publications/2020/acs/acs_general_handbook_2020_ch08.pdf)):
sum: sqrt(sum of MOE^2); proportion: (1/Y) * sqrt(MOE_X^2 - P^2 * MOE_Y^2), using "+" when the
radicand is negative (which equals the ratio formula); ratio: (1/Y) * sqrt(MOE_X^2 +
R^2 * MOE_Y^2); SE = MOE / 1.645; CV = SE / estimate * 100. The handbook warns these ignore
covariance and get worse as more estimates are combined. **It gives no numeric CV thresholds**;
ours (SPEC §6.6) are a judgment call. Formula images didn't extract cleanly during scoping;
Phase 2 must check each formula against the PDF before implementing.

**V10. Ad platform policies** (sanity check of the restricted verticals):
- Google Ads ([personalized advertising policy](https://support.google.com/adspolicy/answer/143465)):
  in the US and Canada, housing, employment and consumer-finance ads can't target by gender, age,
  parental status, marital status, or **ZIP code**; radius targeting of at least 1 km is allowed.
  The page doesn't mention insurance.
- Meta Special Ad Categories (the official help page could not be fetched by tool; facts from
  [Jon Loomer](https://www.jonloomer.com/special-ad-categories-meta-ads/) and
  [PPC Land, 2026-10-11](https://ppc.land/special-ad-category/), **must be confirmed by a human
  on Meta's page**): Housing, Employment, Financial products and services (renamed from Credit,
  January 2025; includes banking, investment and insurance), and Social issues/elections/politics.
  For the first three: no ZIP-code targeting, a 15-mile minimum radius, age fixed at 18-65+, all
  genders, no lookalikes.
- Consequence: the restricted verticals in SPEC §5.1 are consistent with both platforms
  (insurance, banking and investments sit in Meta's financial category; senior living is housing;
  staffing is employment). **Both platforms disallow ZIP-code targeting for these categories**,
  so the restricted-mode ZIP-list export carries a notice saying so (SPEC §5.7).

**V11. Claude Code permission rules**
([permissions docs](https://code.claude.com/docs/en/permissions)). Deny rules take the form
`Read(./.env)`; `./path` is relative to the current directory. **Conflict with the brief:** the
brief said Read, Edit and Write each need their own rule. The docs say Claude Code checks file
permissions against `Read` and `Edit` rules only, and a `Write(path)` rule "is accepted but never
matches"; `Edit` rules apply to every built-in tool that edits files, and a `Read` deny also blocks
Write to that path (Claude Code v2.1.228+) and recognized shell readers (`cat`, `head`, `tail`,
`sed`, `tee`) and redirections. Decision: `.claude/settings.json` denies `Read` and `Edit` on
`./.env`, `./.env.*`, `**/.env`, `**/.env.*` and adds best-effort `Bash(...)` patterns; no
`Write(path)` rules (they would be silently inert and give false comfort). The docs also say a
Bash rule "isn't a security boundary"; CLAUDE.md says the same.
Side effect: `.env.*` also matches `.env.example`, so Claude Code can't edit the example file;
the user edits it if it ever needs to change.

**V12. Zipcator's export contract**, read from `src/zipcator/export.py` at commit `6d9ad8a`
(SPEC §5.3 has the full contract). Header row (display style): `ZIP, City, County, State,
Overlap %, Area in radius (sq mi), ZIP area (sq mi), Nearest distance (mi), Center distance (mi),
Contains address[, Population, Est. pop in radius]`. Two variants: plain (RFC 4180, CRLF, text
fields quoted, no BOM) and Excel-safe (ZIP written as `="02108"`, UTF-8 BOM). Snake_case headers
(`zip`, `overlap_pct`) are accepted too, as a fallback.

**V13. Network note.** During scoping, `api.census.gov` was blocked by the egress proxy both in
Cowork's sandbox and in the shell on the user's machine, so API metadata was read through a web
fetcher. Claude Code running natively on Windows is not behind that proxy. If the data build
fails with a proxy/403 error, it is a network-policy problem, not a key problem; the build's
error message says which.

### Design decisions

**D1. Maximum ZIP count: 1,000.** Large enough for a big DMA or most of a state (Florida has
roughly 1,000 ZCTAs). The profile math is vectorized and cheap at that size; the binding
constraint is the folium choropleth, whose GeoJSON for 1,000 simplified ZCTAs is a few MB and
still renders in about 3 s. Above the limit the review screen refuses with a message suggesting
splitting the list. The limit is a constant in `config.py`, and a `slow` benchmark (SPEC §7)
proves the 1,000-ZIP budget.

**D2. Reliability tiers from the coefficient of variation:** good (CV <= 15 %), use with caution
(15 % < CV <= 30 %), unreliable (CV > 30 %, MOE not computable, or estimate null). Census
publishes no thresholds (V9). 15/30 are cutoffs used by many state data centers and close to the
12/40 that some commercial tools use; we chose the stricter upper bound because clients act on
these numbers. Small-population flag: ZCTA population < 1,000 or households < 300.

**D3. Summary report format: a single self-contained HTML file** (inline CSS, charts and a
static map as inline SVG rendered with matplotlib, print stylesheet). Why: opens in any browser
and email client attachment viewer, prints cleanly to PDF from the browser, needs no network or
JavaScript, and avoids PDF toolchains that are painful on Windows (WeasyPrint needs GTK;
Kaleido needs a headless Chrome). Alternatives: native PDF (Future Ideas), Plotly HTML (3+ MB
of inlined JS, poor printing).

**D4. Restricted mode blocks ranking, filtering and selecting by every demographic metric, not
only the protected/proxy list.** The brief asks for "the most conservative list"; nearly every ACS
measure (tenure, home value, rent, education, vehicles, commute, internet) correlates with race,
national origin or familial status at ZIP level, and selecting ZIPs by such measures is the
pattern regulators have challenged (HUD's 2019 charge against Facebook cited ZIP-based
exclusion). The explicit protected/proxy list (SPEC Appendix B) is still documented and tested,
because it drives which metrics are hidden from *presets and lenses* and labeled in the UI.
Flagged for the user's and counsel's review.

**D5 (amended at owner review, 2026-11-09). Race (B02001) is in v1; disability (B18101) and
veteran status (B21001) are not.** The draft left race out; the owner added it. Race shares
(one race alone by group, and two or more races) are shown as context in every lens (table
columns via the column picker, a "More demographics" chart, exports), tagged `race_color`, and
**no preset or lens KPI uses them** (unit-tested). In restricted mode they are blocked from
selection like every other metric (D4). Disability and veteran status stay out: no lens uses
them and each is protected in at least one restricted context. Hispanic origin (B03003) and
language at home (C16001) stay, for the "Spanish-language households" preset. B02001 was not in
the scoping availability check (V5); Phase 4 confirms it at ZCTA level.

**D6. ZCTA geometry: Zipographics builds its own** simplified 2020 ZCTA cartographic boundary
layer by default (independence from Zipcator). Optionally, `ZIPOGRAPHICS_ZIPCATOR_PARQUET` points
at Zipcator's `data/zcta.parquet` to reuse it and skip the download; the loader validates its
schema (`zip` text, EPSG:4326 geometry) and falls back with a message if it doesn't match.

**D7. Git repository** was initialized from a Linux shell on a Windows folder during scoping, so
`core.filemode=false`, `core.symlinks=false`, `core.ignorecase=true` were set to match what
Windows git uses (and what Zipcator's repo has). No commit was made; git identity is unset in
that shell and is the user's to set.

### Owner review of the draft spec (2026-11-09)
Approved as drafted, with one change: race (B02001) added (D5 amended). Confirmed: the vertical
list including the two added verticals; the restricted characteristic list and D4; GeoNames city
names; the HTML summary report (D3); no footer in the ZIP-list export; D1 and D2 thresholds; preset
thresholds. Counsel review of the vertical mapping and restricted list is still required before
wide internal use.

## Made during build

**B1 (2026-11-09). `uv` is installed but not on the Git Bash PATH.** `uv` 0.13.5 lives in
`C:\Users\<user>\.local\bin`. Claude Code's Bash tool needs `export PATH="$HOME/.local/bin:$PATH"`
per command; the installer was not needed (and failed harmlessly because `uv.exe` was in use).

**B2 (2026-11-09). Contract fixtures are `-text` in `.gitattributes`.** The repo default
`* text=auto eol=lf` would rewrite the CRLF line endings of `tests/fixtures/zipcator/*.csv` on
commit, so a Windows and a Linux checkout would test different bytes than Zipcator writes. Added
`tests/fixtures/zipcator/*.csv -text`; verified with `git ls-files --eol` (index holds `crlf`).
Alternative: a `.gitattributes` inside the fixtures folder; rejected to keep one file.

**B3 (2026-11-09). Fixtures were generated with Zipcator's real CLI at commit `6d9ad8a`** (clean
tree, no network). Zipcator's printed table and `--zips` list are the independent source for the
expected ZIPs in the importer tests. The with-population shape is Zipcator's own `csv_bytes` on a
synthetic result (labeled synthetic in `tests/fixtures/zipcator/README.md`). Excel re-saves are
simulated by `make_variants.py`; none is a real Excel file yet (the Phase 6 STOP asks the owner for
one). One observation for the importer: in the Excel-safe file the raw bytes of a ZIP cell are
`"=""33602"""`, which a CSV reader turns into `="33602"`; the token cleaner also accepts the raw
doubled-quote form (a user pasting lines from the file).

### Phase 1 decisions (2026-11-09): zips, importer, review

**B4. Review takes a "facts frame", not the parquet.** `review.summarize(parsed, facts, ...)`
takes a DataFrame indexed by 5-char string ZIP with `state`, `population`, `households`
(`zipographics.facts.validate_facts` checks the shape). The Phase 4 loader builds it from
`zcta_profile.parquet` via the metrics registry (`pop`, `hh`), so Phase 1 needs no Census data and
no registry. `facts.py` is a module the spec's §8 list doesn't name; it also holds the default
benchmark-state rule (§6.8) so review and `profile` share one implementation. `UsePolicy` is
defined in `models.py` now (the review prints industry and restricted mode) and Phase 5 fills in
the vertical table.

**B5. The CSV importer uses the `csv` module, not pandas.** SPEC §5.2 says "read with
`dtype=str`". The `csv` module never infers types, which is the same guarantee with less
machinery, and handles ragged rows and delimiter sniffing directly. Alternative: `pandas.read_csv(
dtype=str, keep_default_na=False)`; equivalent for ZIPs, rejected for the extra failure modes.

**B6. Token details beyond the §5.2 table.**
- Cleanup strips straight and typographic quotes, whitespace (including non-breaking), a stray BOM
  and zero-width space, a leading `=` (Excel text formula), and a trailing `.0`/`.00`. The raw
  doubled-quote form `"=""02108"""` is accepted.
- Digit checks use `[0-9]`; `str.isdigit()` and `\d` accept Arabic-Indic and full-width digits,
  which are rejected as invalid (tested).
- A header phrase (`zip`, `zipcode`, `zip code`, `zip_code`, `zip5`, `postal code`, `postalcode`,
  `zcta`, `zcta5`) is dropped only at the very start of pasted text, including multi-word forms.
- Repairs and truncations are reported for the retained occurrence only. For `2108` then
  `02108`, the first is kept and reported as repaired and the second is a duplicate. For `02108`
  then `2108`, the second is the duplicate and nothing is reported as repaired.
- `ZIP + space + 4 digits` (`02108 1234`) is two tokens in a paste (the second is padded to
  `01234`). Accepted limitation: spaces are separators per §5.2.

**B7. CSV column detection.** Rows 2+ are data for any file with 2+ columns; row 1 is always the
header. A single column is header-less when its first value is a valid token; a known header name
or (unknown label and the rest ≥ 80 % valid) makes it a header. Content detection (≥ 80 % valid,
no header-name match) can pick a numeric column such as `Population` because 3-4 digit numbers
pass the repair rule; the UI will show the chosen column with a dropdown to change it (Phase 6),
and several candidates require a choice (`ColumnChoiceRequired`). Two header-name matches
(`ZIP` and `Zip Code`) also require a choice.

**B8. Zipcator row rules, details.** Overlap accepts `12.5`, `12.5%` and a quoted `12,5`
(European Excel) and rejects `nan`, `inf`, `1e2`, negatives and `0`; range (0, 100]. A rejected
row is listed with its reason and its ZIP is not imported; a later valid row for that ZIP can
still add it. A repeated ZIP keeps the first row; a different overlap on the repeat is listed
as a conflict. Blank overlap: ZIP kept, treated as full (w = 1), listed.

**B9. Encodings.** Order: UTF-16 when a UTF-16 BOM is present (Excel's "Unicode Text"), UTF-8 with
or without BOM, cp1252, then latin-1 (cp1252 leaves five bytes undefined; latin-1 never fails, so
a bad byte can't crash an upload). A single field over the `csv` module's 128 KB limit gives a
clean "could not be read as CSV" message.

**B10. Review rules the spec left open.**
- A zero-population ZIP is *recognized* (it is in the data) and listed under "no residents"; it is
  not also "small". Unknown (null) population or households is never flagged as small.
- "Repaired ZIP in an unexpected state" compares each repaired ZIP's state with the dominant state
  of *all other* recognized ZIPs (the ZIP itself excluded); a lone repaired ZIP has nothing to
  compare with.
- Dominant state = largest summed population; unknown population counts as 0; ties go to the state
  that appears first in the input. The same function will pick the default benchmark in Phase 2.
- Blocking: zero recognized ZIPs, or more than 1,000 *valid* ZIPs (counted before the data
  lookup), each with its own message; both can apply.
- Measured: parse + review of 1,000 ZIPs that are all repaired takes 0.10 s (budget 0.5 s).

**B11 (2026-11-09). Phase 1 QA follow-ups.**
- All recognized ZIPs having population 0 blocks the review (SPEC §5.4 listed only "zero
  recognized" and ">1,000"): Phase 2 would otherwise divide by zero or show an empty dashboard.
  A mix of zero-population and populated ZIPs continues; unknown (null) population does not block.
- Header-less CSVs are detected when no header cell looks like a ZIP column name and some row-1 cell
  is a valid ZIP token. Such files get column names `Column 1`, `Column 2`, ... and row 1 stays data.
  A file whose every cell (≥ 80 %) is a ZIP token is read as a plain list, whatever the layout.
- Single-column cells are split on the paste separators, so `02108 02109` on one line is two ZIPs.
- Tokens longer than 40 characters (after trimming outer quotes and whitespace) are invalid without
  running the cleanup loop; no valid token is that long.
- Two repaired ZIPs in different states flag each other (spec-literal). Unknown population counts as
  0 when choosing the dominant state.

### Phase 2: formulas quoted from the official documents (2026-11-09)

Sources read from the PDFs' text layers (the equations themselves are images and don't extract;
each formula below was reconstructed from the text and **checked numerically against the
document's published worked example**, shown in the last column).

**V9 verified: ACS General Handbook 2020, ch. 8** ("Calculating Measures of Error for Derived
Estimates", pp. 59-66,
[PDF](https://www.census.gov/content/dam/Census/library/publications/2020/acs/acs_general_handbook_2020_ch08.pdf)).

| measure | official text (verbatim where quoted) | formula | worked example reproduced |
|---|---|---|---|
| Sum (1) | "1. Obtain the MOE of each component estimate. 2. Square the MOE of each component estimate. 3. Sum the squared MOEs. 4. Take the square root of the sum of the squared MOEs." (p. 59) | `MOE = sqrt(sum MOE_i^2)` | ±3,860, ±2,642, ±1,957 -> **±5,070** (we get 5,070.46); sums 203,119 (p. 60) |
| SE (2) | "SE (Fairfax) = 3,860 / 1.645 = 2,347" (p. 60) | `SE = MOE / 1.645` | 2,346.5 / 1,606.1 / 1,189.7 |
| CV (4) | "CV (Subgroup 1) = (630 / 3,497) * 100 = ... 18.0 percent" (p. 63) | `CV = SE / estimate * 100` | 18.0 / 16.0 / 13.0 % (Table 8.2 groups: ±1,036, ±931, ±1,557) |
| Proportion (6) | "With proportions, the numerator is a subset of the denominator." The garbled extraction shows `MOE(P) = (1/Y) sqrt([MOE(X)]^2 - (P^2 * [MOE(Y)]^2))`; "if the value under the square root is negative, then substitute a 'plus' for the 'minus' sign under the square root in formula (6). This modified formula is the same as the formula for the MOE of a ratio" (p. 64) | `MOE(P) = sqrt(MOE(X)^2 - P^2 MOE(Y)^2) / Y` | P = 203,119 / 630,498 = 0.322, MOE(X) = 5,070, MOE(Y) = ±831 -> **0.8 %** (we get 0.803 %; SE 0.488) |
| Ratio (7) | "Ratios are used to compare two estimates where the numerator is not a subset of the denominator." (p. 65) | `MOE(R) = sqrt(MOE(X)^2 + R^2 MOE(Y)^2) / Y` | 226,840 / 203,119 = 1.117, males ±5,556.5, females ±5,070 -> **0.039** (we get 0.0391); CV 2.1 % |
| Product (9) | "The formula to calculate the MOE of a product is: (9)" (p. 66) | `MOE(AB) = sqrt(A^2 MOE(B)^2 + B^2 MOE(A)^2)` | 74,506,512 ± 228,238 × 0.824 ± 0.001 = 61,393,366 -> **±202,289** (we get 202,288.99) |
| Approximation | "this method for calculating the MOE and SE for aggregated count data is an approximation, and caution is warranted because this method does not consider the correlation or covariance between the component estimates... as the number of estimates involved in a sum or difference increases, the results of the approximation formula become increasingly different from the SE derived directly from the ACS microdata. Users are encouraged to work with the fewest number of estimates possible." (p. 61) | labeled "approximate" everywhere | Table 8.3: published ±973 vs derived ±931 (the method can underestimate) |

**Findings that differ from, or are missing in, the spec**
1. **Zero-estimate guidance is not in ch. 8.** SPEC §6.3 says to check "the handbook's guidance on
   including only the largest zero-estimate MOE". The 2020 chapter 8 has no such rule (it points to
   a separate "Worked Examples for Approximating Margins of Error" document, not fetched).
   **Decision:** sum every component MOE (the formula as printed). It is conservative: many
   zero-estimate bracket MOEs can inflate a sum's MOE. Revisit if QA or the owner reads the worked
   examples document.
2. **No numeric CV thresholds** appear in the chapter (it only calls CVs of 0.2-2 % "very
   reliable"). The 15 % / 30 % tiers (D2) stay a documented judgment call.
3. The chapter's examples are 2015 1-year data; the formulas are vintage-independent.

**V8 verified: ACS PUMS Accuracy of the Data 2020-2024** ("Medians", pp. 16-20,
[PDF](https://www2.census.gov/programs-surveys/acs/tech_docs/pums/accuracy/2020_2024AccuracyPUMS.pdf)).
- "The standard error of an estimated median is approximated by constructing a 68 percent
  confidence interval." Steps: "Approximate the standard error of a 50 percent proportion...
  Create the variable p_lower by subtracting the SE from 50 percent. Create p_upper by adding the
  SE to 50 percent... `SE(median) = 1/2 X (Upper Bound – Lower Bound)`".
- Bounds by linear interpolation inside the category holding p: "Define A1 as the smallest value in
  that category. Define A2 as the smallest value in the next (higher) category. Define C1 as the
  cumulative percent of units strictly less than A1. Define C2 as the cumulative percent of units
  strictly less than A2." The formula image didn't extract; from the example it is
  `bound = A1 + (p - C1) / (C2 - C1) * (A2 - A1)`.
- **Worked example reproduced** (Massachusetts household income, B19001-style brackets): A1 =
  60,000, A2 = 75,000, C1 = 44.68, C2 = 53.75; p_lower = 49.80 -> **68,467.48** (we get 68,467.475);
  p_upper = 50.20 -> **69,129.00** (69,128.997); SE(median) = ½ × (69,129.00 − 68,467.48) =
  **330.76** (330.76). Median of that distribution by the same interpolation at 50 %: 68,803.14
  (hand calculation from the document's counts: 60,000 + (1,274,858 − 1,139,123) / 231,284 ×
  15,000).
- "The ACS calculates medians using a linear interpolation method" (p. 17, confirming V8).
- "Users please note that the 2024 ACS PUMS will be the final year design factors will be
  published" (p. 14; confirming V8).
- The document gets SE(50 %) from a design factor (image formulas; the example uses SE(50 %) = 0.20
  with DF 1.5 and base 2,549,716). **Zipographics does not use design factors**: per SPEC §6.4 it
  derives SE(p) from the bracket MOEs with the proportion formula (6) at P = 0.5, applied to the
  cumulative count below the median bracket over N.

**D8 (2026-11-09). Median MOE derivation (SPEC §6.4), recorded before implementing.** For a
trade-area median from summed brackets with counts n_i (MOEs m_i): N = Σ n_i (MOE_N = sqrt(Σ m_i²)).
Let k be the median bracket, X = Σ_{i≤k} n_i the cumulative count through bracket k (MOE_X =
sqrt(Σ_{i≤k} m_i²)). SE(p) for the 50 % point is `MOE(X/N at P=0.5) / 1.645` from formula (6) with
the numerator being the cumulative count up to (and including) the bracket containing the median
and P replaced by 0.5: `SE(p) = sqrt(MOE_X² − 0.25 MOE_N²) / N / 1.645` (ratio form if the radicand
is negative). Then p_lo = 0.5 − SE(p), p_hi = 0.5 + SE(p) (clamped to (0, 1)), the interpolated
values at those proportions give the interval, `SE(median) = ½ (v_hi − v_lo)` and `MOE = 1.645 ×
SE`. Cumulative "through bracket k" is used (not "below k") so the proportion is the share at or
below the bracket boundary the median lies in; it is a labeled approximation. A worked example is
in `tests/unit/test_stats.py::test_median_moe_hand_calculation`.

**D9 (2026-11-09). Metric registry design (SPEC §4.2, Appendix C).** `zipographics.metrics`
declares 74 metrics (Appendix C) over about 270 Census variables.
- **Variable keys.** For detailed tables the key is the Census variable ID (`B19001_002`; these are
  stable by table row). Each single cell carries a label regex and each bracket table carries expected
  bounds; the Phase 3 build checks them against `variables.json` and fails with a clear message, and
  falls back to resolving by `(table, label)` if an ID moved. Data Profile items (DP03) have symbolic
  keys (`DP03_UNINS`, ...) resolved only by label regex, since their IDs shift between vintages. Parquet
  columns are `<key>_e` / `_m` (and `_code` for the five published medians). This is a small
  deviation from SPEC §4.2's "resolve everything by (table, label)": IDs are the primary key
  because they are stable for `B` tables and the label check keeps the safety.
- **Expected IDs and labels are written from memory of the ACS tables and are unverified until
  Phase 4**, which resolves every key against the real `variables.json`. Bracket cells were
  verified structurally here (contiguous, ordered, complete, partition tests).
- **Vehicles per household** is computed from B25044 (cells weighted 1-5, "5 or more" as 5, so
  "at least"). SPEC §6.5 prefers B25046 (aggregate vehicles) if present at ZCTA level; switching
  is a registry-only change once Phase 4 checks availability.
- **Median brackets run ascending.** `median_year_built` lists B25034 rows 011 -> 002 (oldest
  first); the open bottom (`1939 or earlier`) and top (`2020 or later`) brackets are unbounded,
  so a median landing there is reported as a bound. Income, value and rent use 0 as the lower
  bound of their lowest bracket (SPEC §6.4 assumption); age brackets start at 0.
- **Limited English** sums the twelve "less than very well" cells of C16001 (one per language group).
- `indexable` is derived: every kind except `count`.
- `metrics.py` has a ruff per-file ignore for E501/RUF002 in `pyproject.toml`: it is declarative data.

**B12 (2026-11-09). Phase 2 QA follow-ups.**
- **Registry label guard (corrects D9).** D9 originally said every single cell carries a label regex;
  the QA review found only 18 of 223 did. Now every non-bracket variable has one (`_CELL_LABELS`,
  matched against the end of the ACS label so `Owner occupied` cannot match `Renter occupied`), pinned by
  `tests/unit/test_registry_definitions.py`, which also lists every share's numerator and denominator
  cells independently of the registry. Data Profile regexes are anchored to `^estimate!!` because DP
  variables also have `Percent!!` and `Margin of Error!!` labels. Still unverified until Phase 4.
- **Profile fails closed.** A published median needs its `_code` column (values only none/top/bottom);
  any value at or below -100,000,000 (a sentinel that escaped the build) is rejected; duplicate ZIPs and
  overlap weights outside (0, 1] are errors; shares clamp to [0, 1] and are flagged `incomplete` when
  clamped. The sentinel layer rejects numeric geography keys and a median variable with no annotation
  column.
- **Index rounding** rounds the ratio to 9 decimals before adding 0.5, so an exact half indexes up
  (`0.145` -> 15, not 14).
- **`source`:** a count scaled by an overlap weight below 1 is `derived`, not `published`.
- **Benchmark options** ignore states outside the 50 + DC + PR benchmark set and county ids that are not
  5 digits, and fall back to the id when a county name is blank.
- **Tie convention.** At an exact 50 % tie across an empty bracket (`[4, 0, 4]`) we return the lower
  boundary (10); the PUMS rule ("first category with cumulative % greater than p") gives 20. Both are
  valid medians; kept, documented, tested.
- **D8 sanity check (reviewer's simulation).** With multinomial samples whose bracket MOEs match simple
  random sampling (N = 5k, 20k, 60k), D8's median MOE came out 1.09-1.11 times the simulated MOE: mildly
  conservative. **Phase 4 `data` test to add:** compare the interpolated MOE for single ZIPs with the
  published B19013_001M (SPEC §6.4 only measures the median gap).
- **Open: zero-estimate MOEs.** The reviewer recalls the separate Census "Worked Examples for
  Approximating Margins of Error" advising that only one zero-estimate MOE be included in a sum; not
  verified. Our sum includes all of them (conservative). Read that document at the start of Phase 4.
- Deferred, see the Phase 2 entry in QA_REPORT: in-radius per-ZIP household/population columns and a
  per-ZIP index tier (Phase 5/6), "1939 or earlier" display text for the bottom year-built bound
  (Phase 5/6), how often null cells bias shares in real data (Phase 4).

### Phase 3 decisions (2026-11-09): redact, census_api, data_build

**B13. Census client and key handling (SPEC §4.5).**
- **How the API's answers map to exit codes.** HTTP 200 with a non-JSON body (the API's "Invalid
  Key" page) and a 400/401 whose body mentions "key" are a rejected key (exit 3). HTTP 403 and 407
  are a proxy or network policy (exit 4, "not a problem with your key", never retried; DECISIONS
  V13). 429 and 5xx are retried (1, 2, 4, 8 s plus up to 25 % jitter, five attempts in all) and then
  exit 4. Any other 4xx (for example `unknown variable`) is exit 4 with the API's own message and is
  not blamed on the key. An unexpected Python error is exit 1 with one redacted line (the spec lists
  no code for it).
- **URLs are built by hand** (`for=zip%20code%20tabulation%20area:*`): `requests` would encode the
  spaces as `+`. A test through the real `requests` stack (with `responses`) pins the shape.
- **Names per request:** at most 50 in all, counting `NAME`; `NAME` is requested in the first chunk for
  state/county/us only. Each variable's `E`, `M` (and `EA` for medians) stay in one chunk. `MA`
  (margin-of-error annotations) is not requested: nothing uses it (SPEC §4.5 listed it).
- **`variables.json` is fetched without the key** (metadata needs none) and cached like data.
- **Cache:** `data/raw/acs/{vintage}/{sha256 of the key-free URL}.json` plus `.meta.json` (key-free URL,
  fetch time); downloaded files sit in `data/raw/` with the same kind of sidecar. Error pages are never cached.
- **Redaction mechanism.** `redact()` handles `key=` (also `key%3D`), `CENSUS_API_KEY=...` (but not the
  `<your key>` placeholder in the help text) and the key's literal and URL-encoded forms.
  `install_redaction()` replaces the logging record factory, so every record from every logger and
  handler (including handlers added later) is scrubbed, tracebacks included, and sets `urllib3` to
  WARNING. The client installs it in its constructor; the CLI also installs it before anything else.
  Errors are raised outside `except` blocks (no `__cause__`/`__context__`). The secrets gate in
  `scripts/check.py` flags `CENSUS_API_KEY=<8+ chars>` in source, so redact.py builds that string from a
  constant instead of weakening the gate.
- **No `--census-api-key` flag** (a test checks three spellings are usage errors). The key is read
  from the environment only; `scripts/build_data.py` is the only file that imports `dotenv`.

**B14. Data build design.**
- **Validation before writing.** Nothing is written unless the output validates (SPEC §4.4); files are
  written atomically (`.tmp` then rename). The checks: row count (≥ 33,000, `config.MIN_ZCTA_ROWS`),
  5-digit text ZIPs, no value at or below -100,000,000, every referenced state and county and the
  nation has a benchmark row, every registry variable resolved with its `_e`/`_m` columns, core KPI
  variables non-null for ≥ 95 % of ZCTAs with population > 0, geometry ZIPs ⊆ profile ZIPs and no
  null geometry, and ≤ 1 % of ZCTAs without a state (a broken county join).
- **Core KPI variables** are the variables of `pop`, `hh`, `median_hh_income` (the *published* median
  only, not its brackets), `owner` and `hh_kids` (SPEC §5.5 "always" cards).
- **Partial builds:** `--only acs` and `--only geo` merge into the existing `metadata.json`; geometry
  alone is checked against the profile on disk.
- **Artifacts:** `zcta_profile.parquet` stores `zip` as a text column; `benchmarks.parquet` has
  `geo_level`/`geo_id`/`name` (ids are FIPS text: 2-digit state, 5-digit county, `1` for the nation);
  `metadata.json` holds the vintage, key-free dataset and file URLs, resolved variables (id, label,
  table, whether the ID moved), row counts, per-variable coverage, sentinel counts by column and code,
  the top/bottom-code cross-check (counts and bound values per published median), geometry source and
  tolerance, and the app version.
- **Map tolerance default 0.002°** (Zipcator uses 0.0005 for a ~40 MB file; the map needs no area math).
  Phase 4 measures the real size against the ≈30 MB target. Zipcator's parquet is reused when
  `ZIPOGRAPHICS_ZIPCATOR_PARQUET` points at a file with a text `zip` column in EPSG:4326 (not
  re-simplified), otherwise the reason is recorded in `metadata.json`.
- **Unverified until Phase 4:** the D4 relationship-file column names (taken from Zipcator's working
  reader), the GeoNames format, the real `variables.json` labels (the `network` tests resolve the
  registry against the live file), the annotation strings the API returns for top/bottom codes, and
  whether the 5-year notes page lists the same six sentinel values.
- **QA follow-ups (B15).** Publishing is two-phase: every artifact is written to a `.tmp` sibling first and
  all are renamed only when every write succeeded, `metadata.json` last, so a failed build leaves the
  previous build intact. A 200 response is a rejected key only if it is non-JSON text that does not start
  with `[` or `{` (an HTML page); a truncated body is retried. The map must cover at least 95 % of the
  profile's ZIPs with no duplicates or null geometries. Non-finite and unparseable numbers become nulls and
  are counted in `sentinel_counts` as `non_finite` / `non_numeric`. The CLI rejects a non-finite or negative
  `--tolerance`, a vintage before 2009, and a `--data-dir` that is a file (exit 2); `Ctrl-C` exits 130.
  The key-bearing `.env` may be saved as UTF-8 only (a clear message for UTF-16); a blank
  `CENSUS_API_KEY` variable counts as unset. Run network tests without `-l`/`--showlocals`.
- **Hypothesis sweeps.** Running the numeric property tests with 40 more seeds exposed scalar/vectorized
  disagreements at absurd magnitudes (QA_REPORT #15); the rule going forward is that both
  implementations return "unknown" for non-finite intermediates and for an index above 1e9.

### Phase 4 (2026-11-09/10): the real build, and what it verified

First real run: ACS 2020-2024 5-year (`--vintage 2024`), 223 then 222 variables, 33,772 ZCTAs,
3,222 counties, 52 states, the nation. Every number below is from the real data or the official sources.

**Verified facts (updating V1-V13)**
- **V1 (vintage).** `api.census.gov/data/2025/acs/acs5` is still HTTP 404 on 2026-11-10 (only the
  2025 1-year exists). 2020-2024 stays the current 5-year vintage; nothing for the owner to decide.
- **V3/V4 (API).** 50 names per request and the ZCTA-wide call (`for=zip%20code%20tabulation%20area:*`, no
  `in=`) work as documented; the whole build is about 60 requests and took about 75 s with a warm cache.
- **V5 (tables).** Every table in the registry exists in the 2024 dataset and resolved by ID with its
  label unchanged: **all variables resolved, none `moved`**. **B02001 (race) is available at ZCTA level
  (100 % non-null). B25046 (aggregate vehicles) is available at ZCTA level (97 % non-null)**, so
  `veh_per_hh` now uses B25046 / B25044_001 as SPEC §6.5 prefers (exact, no "at least" caveat); the two
  B25044 one-vehicle cells it needed were dropped from the registry.
- **V6 (sentinels).** The **5-year notes page does not exist** (HTTP 404). The 5-year site
  ([acs-5year.html](https://www.census.gov/data/developers/data-sets/acs-5year.html), revised 2026-05-20) points
  to the 1-year notes page, revised 2026-07-20, whose table is exactly our six values plus
  `median-`/`median+` and `null`: -666666666 `-`, -999999999 `N`, -888888888 `(X)`, -222222222 `**`,
  -333333333 `***`, -555555555 `*****`. **Observed in the real data:** `-666666666` only as an *estimate*
  (18,863 cells); `-222222222`, `-333333333` and `-555555555` only as *margins of error* (18,863, 2,053 and
  17,069); `-999999999` and `-888888888` never appeared in these tables. No unknown large negative value.
- **V7 (top/bottom codes).** Detected from the estimate annotation, whose real strings are `250,000+`,
  `2,500-`, `2,000,000+`, `10,000-`, `3,500+`, `100-`, `1939-`, `2020+` (and `-` for "not computable", which
  is not a code). Cross-check of the believed codes: median household income top 250,001 (118 ZCTAs),
  bottom 2,499 (15); home value top 2,000,001 (100), bottom 9,999 (22); gross rent top 3,501 (134), bottom 99
  (4); year built top 2021 (9), **bottom 1938 (1,647: "1939 or earlier")**; median age has none. Phase 5/6
  must display coded values from their *bound* ("$250,000+", "1939 or earlier"), not the stored number.
- **V8/V9 zero estimates (closes the open item).** Neither the 2020 nor the 2025 "Worked Examples for
  Approximating Margins of Error" says to include only the largest zero-estimate MOE in a sum (searched both
  texts). The summed-MOE rule stays as implemented. They do warn that approximated SEs can differ from the
  published ones: they under-estimated in their Example A and **over-estimated by up to 307 % for a sum that
  involves controlled estimates (sex by age)** (Example B). The B01001-based age metrics sum many such
  cells, so their multi-ZIP MOEs are conservative; they stay labeled approximate.
- **V13 (network).** `api.census.gov` was reachable from the owner's Windows machine; no proxy problem.
- **D8 measured.** Across 1,489 sampled ZCTAs (≥ 200 households, uncoded): interpolated vs published median
  household income differ by a median of **1.22 %** (95th percentile **5.99 %**, max 17.2 %); the
  interpolated MOE is **1.14×** the published one at the median (10th/90th percentile 0.79 / 1.77). So the
  bracket-derived MOE is mildly conservative, as the Phase 2 reviewer's simulation predicted.

**B16. Rules the real data forced (official-source conflicts; reported to the owner).**
1. **Published medians get a 90 % coverage floor, not 95 %.** SPEC §4.4 says a core KPI variable must be
   non-null for 95 % of ZCTAs with population > 0. Real coverage of the published median household income is
   **92.1 %**: the ACS suppresses medians for small areas (3 % of ZCTAs with under 10 households have one,
   33 % of those with 10-24, 87 % of those with 100-249, 95 %+ above 250). It is not a broken join: counts and
   shares are 100 % and every null-median ZCTA still has its bracket counts. The spec floor stays 95 % for
   counts and shares; **published medians use `config.MEDIAN_COVERAGE_FLOOR = 0.90`**. Alternative the owner
   may prefer: keep 95 % and measure only ZCTAs with ≥ 100 households, or interpolate a suppressed single-ZIP
   median from its brackets (`profile.bracket_median` exists for that); not done, because a suppressed value
   shown as "—" is the honest default.
2. **Connecticut has no county benchmark.** ACS 2022 onward publishes Connecticut by **planning region**
   (county ids `09110`-`09190`); the 2020 ZCTA-to-county relationship file still uses the 8 legacy counties
   (`09001`-`09015`). 288 ZCTAs (0.85 %) therefore keep their county *name* but get no `county_fips`, so no
   county benchmark is offered for them (state and national benchmarks are unaffected). Limit
   `config.COUNTY_GAP_LIMIT` = 2 % (a larger gap means a broken join); recorded in
   `metadata.json["county_benchmark_gaps"]`. No official ZCTA-to-planning-region crosswalk exists.
3. **Polygons without ACS data are dropped.** The boundary file has 19 ZCTAs the ACS does not publish: 17
   island-area ZCTAs (VI `008xx`; GU, MP and AS `969xx`) and two New York ZCTAs (`11717`, `11798`). They are
   removed from the map and listed in the metadata. More than
   `config.MAX_GEOMETRY_EXTRA` = 25 unmatched polygons fails the build (wrong file).
4. **Map tolerance 0.004°** (about 440 m): 25 MB. Measured on the real boundary file: 0.002 → 43 MB, 0.003 →
   31 MB, 0.004 → 25 MB, 0.005 → 21 MB, 0.01 → 12 MB.
5. **Artifacts:** `zcta_profile.parquet` 20 MB, `benchmarks.parquet` 3 MB, `zcta_geo.parquet` 25 MB;
   `data/raw` cache 201 MB (all gitignored).

**Not changed, by design:** a ZCTA with population but no households (355 group-quarters ZCTAs) stays in the
data; `33601` is not a ZCTA (checked: absent from the profile); population totals of the 33,772 ZCTAs are
within 3 % of the national figure (ZCTAs approximate the 50 states, DC and PR).
