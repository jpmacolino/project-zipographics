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
