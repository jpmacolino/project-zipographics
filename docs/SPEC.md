# Zipographics: Specification

**Status:** Approved for build · **Version:** 1.0 · **Date:** 2026-11-09
**Owner:** FloridaMenConsulting · **License:** MIT (public GitHub repo)
**Companion app:** Zipcator (`project-zipcator`), whose spec this one mirrors.

> The owner reviewed the draft on 2026-11-09 and approved it with one change: race (B02001)
> is in v1; §13 records the review outcome. Facts checked against official sources during
> scoping are logged in `docs/DECISIONS.md` as V1-V13; design decisions as D1-D7.

## 1. Summary

Zipographics is a small, local-first Python app with a Streamlit UI. An account-team member
picks the client's industry, answers one restricted-use question, and gives the app a set of ZIP
codes (typed, pasted from Excel, or a Zipcator CSV export). The app shows a **demographic profile
of those ZIPs** from U.S. Census Bureau American Community Survey (ACS) 5-year estimates, as an
interactive dashboard: KPI cards indexed against a benchmark (state, county or nation), a ranked
and filterable ZIP table, a few focused charts, a choropleth map, and exports (ZIP list for ad
platforms, CSV, and a shareable summary report titled with the project name).

All Census data is **downloaded once by a build script into local files**. The running app makes
no network calls.

**Primary use case:** an agency account team sizing up a client's trade area ("who lives in these
ZIPs, and how does that compare with the state?") and choosing which ZIPs to target, without
using protected characteristics when the marketing is for housing, jobs, credit or insurance.

## 2. Goals and non-goals

### Goals
- Honest numbers: every ACS figure carries its margin of error (MOE) and a reliability tier;
  medians are aggregated correctly (never averaged); sentinel and top-coded values are never
  shown as ordinary numbers.
- A fast, low-friction flow: industry → ZIPs → a one-glance review → insights in under a second.
- A restricted-use guardrail that keeps housing, employment, credit/financing and insurance
  marketing from selecting ZIPs by protected or proxy characteristics, enforced in the library
  and recorded on every shareable export.
- Correct handling of real-world ZIP input: Excel-mangled leading zeros (`2108` → `02108`,
  `601` → `00601`), ZIP+4, junk, duplicates, and Zipcator exports.
- Runs locally on Windows (primary), macOS and Linux with one setup command and one data build
  command; no API key needed to *run* the app.
- Repo is small, public-safe and redistributable: no data files over 1 MB, no secrets.
- Thorough automated tests; CI on every push.

### Non-goals (v1)
- Non-US geographies; USPS-exact delivery ZIPs (PO-box-only and single-organization ZIPs have no
  ZCTA and no ACS data; documented limitation).
- Business counts (ZIP Codes Business Patterns): phase 2 (§12).
- Any runtime Census API call, user accounts, saved projects, or a hosted multi-user service.
- Disability and veteran-status data (D5).
- Trend comparisons across ACS vintages.
- Native PDF output (the summary report is printable HTML; §5.6, D3).
- Legal compliance determinations. The restricted-use feature is a guardrail, not legal advice
  (§5.7).

## 3. Background

### 3.1 ZIP codes vs ZCTAs
USPS ZIP codes are mail delivery routes, not areas. The Census Bureau publishes data for **ZIP
Code Tabulation Areas (ZCTAs)**, polygons built from census blocks that approximate residential
ZIP coverage, defined once per decennial census (2020 ZCTAs are current until 2030; about 33,800
cover the 50 states, DC and Puerto Rico). Throughout this spec and in the app, "ZIP" means
"5-digit ZCTA". The UI, README and every export say so in one plain sentence:

> "ZIP" here means a Census ZIP Code Tabulation Area (ZCTA). PO-box-only and single-organization
> ZIP codes aren't included. ACS figures are survey estimates with margins of error.

### 3.2 ACS 5-year estimates
ZCTA-level ACS data exists **only in the 5-year product** (pooled from 60 months of survey
responses). Every estimate has a published 90 % MOE. Small ZIPs can have MOEs as large as the
estimate. The current vintage is **2020-2024**, released January 29, 2026; the 2021-2025 release
date is officially **TBD** (V1; the brief's "around December 2026" isn't confirmed). The vintage
is a build parameter, never hardcoded.

## 4. Data

All data is downloaded and processed by `scripts/build_data.py` into `data/` (gitignored).
Nothing under `data/` is committed except `data/README.md`.

### 4.1 Sources

| # | Dataset | Use | License | Required |
|---|---|---|---|---|
| D1 | **ACS 5-year detailed tables** via the Census Data API: `https://api.census.gov/data/{vintage}/acs/acs5` | Counts and bracket distributions with MOEs, for ZCTAs and benchmarks | Public domain | Yes |
| D2 | **ACS 5-year Data Profiles** (DP03, DP04, DP05; DP02 where needed) via `https://api.census.gov/data/{vintage}/acs/acs5/profile` | Measures not in the chosen detailed tables (e.g., working parents, health insurance); published-percentage cross-checks | Public domain | Yes |
| D3 | **Census 2020 ZCTA cartographic boundary file**, 1:500k (`cb_2020_us_zcta520_500k.zip` under `https://www2.census.gov/geo/tiger/GENZ2020/shp/`) | Map polygons (simplified) | Public domain | Yes, unless D3-alt is configured |
| D3-alt | Zipcator's built `data/zcta.parquet`, located by env var `ZIPOGRAPHICS_ZIPCATOR_PARQUET` | Reuse Zipcator's simplified polygons and skip the D3 download (D6) | (derived from D3) | Optional |
| D4 | **Census 2020 ZCTA-to-county relationship file** (`tab20_zcta520_county20_natl.txt` under `https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/`) | State and primary county per ZCTA (county with the largest land overlap); county options for the benchmark | Public domain | Yes |
| D5 | **GeoNames postal codes**: `https://download.geonames.org/export/zip/US.zip` plus `PR.zip` (US.zip has no Puerto Rico entries; Zipcator's build fetches both) | City name per ZIP in the table and exports | CC BY 4.0, attribution in README, app footer and exports | Yes (city may be blank) |
| D6 | ZIP Codes Business Patterns (County Business Patterns API) | Establishment counts for B2B views | Public domain | **Phase 2 only** (§12) |

**Verify before relying on them.** URLs and file names are believed correct (D3, D4 and D5 are
the ones Zipcator's build uses successfully). If one has moved, use the current official location,
update the build, and log it in `docs/DECISIONS.md`. No unofficial mirrors.

**Benchmarks** come from the same D1/D2 variables fetched at the `us`, `state` and `county`
levels and stored alongside the ZCTA data. National = the 50 states + DC (the ACS `us` level
excludes Puerto Rico); the app says so when the input contains PR ZIPs.

### 4.2 Variables and the metric registry

The app works from a **metric registry** (`zipographics.metrics`), a typed, declarative list of
metrics. Each metric has: `id`, display name, unit/format, `kind` (`count`, `share`, `median`,
`mean`, `ratio`), the source variables (numerator, denominator, or bracket distribution), a
`characteristic` tag (§5.7 / Appendix B), whether it can be indexed, a short help text, and the
universe (e.g., "households", "population 25 and over"). The build derives its variable list from
the registry, so adding a metric is one registry entry plus tests.

**Variables are resolved by table and label, not by hardcoded ID.** Data Profile variable IDs
shift between vintages, and some labels do too (e.g., B25038's "Moved in 2021 or later"). The
build downloads `variables.json` for the vintage, resolves each registry entry by `(table,
label pattern)`, fails with a clear message if a label is missing or ambiguous, and records the
resolved IDs and labels in `metadata.json`. Detailed-table bracket lists (B19001, B25075, B25063,
B25034, B01001) are read in label order from `variables.json`, with bracket bounds parsed from the
labels and checked against an expected-bounds table in code.

Candidate tables were confirmed present in the 2024 dataset (V5). The v1 list, with the reason
for each; the exact metrics are in Appendix C:

| Table | What | Why it's in v1 |
|---|---|---|
| B01003 | Total population | Core KPI; denominator |
| B01001 | Sex by age (49 cells, summed over sex) | Age bands, medians for the trade area, children under 5, school-age, seniors. Sex itself isn't shown (D5) |
| B01002 | Median age | Published single-ZIP and benchmark median |
| B11001 | Households | Core KPI; denominator |
| B11005 | Households by presence of people under 18 | % households with children (Families lens) |
| DP03 | "Own children under 6, all parents in family in labor force" (resolved by label) | Childcare lens (working parents) |
| B19001 | Household income, 16 brackets | Income distribution chart; trade-area median; income-band shares |
| B19013 | Median household income (+ annotation) | Published single-ZIP and benchmark median; top-code detection |
| B19025 | Aggregate household income | Mean household income, aggregable exactly |
| B19301 | Per capita income | Per capita income (aggregated via per-capita × population) |
| B17001 | Poverty status (total and below poverty only) | Poverty rate |
| B25001, B25002 | Housing units, occupancy | Vacancy rate (real estate context) |
| B25003 | Tenure | % homeowners / renters (core KPI) |
| B25024 | Units in structure | Single-family share, mobile homes (Home services, Lawn) |
| B25034, B25035 | Year structure built; median year built | Housing age (Home services); trade-area median year built |
| B25038 | Tenure by year householder moved in | "New movers" (most recent move-in category) |
| B25044 | Tenure by vehicles available | Vehicles per household (Automotive). B25046 (aggregate vehicles) is preferred if present at ZCTA level; verify in Phase 4 |
| B25063, B25064 | Gross rent distribution; median gross rent | Rent context; trade-area median rent |
| B25075, B25077 | Home value distribution; median value | Home value; trade-area median value |
| B08301 | Means of transportation to work | Commute mode, work from home (Restaurants, Auto, B2B) |
| B08303 | Travel time to work | Long-commute share |
| B23025 | Employment status | Labor force participation, unemployment (Higher ed) |
| B15003 | Educational attainment, 25+ | HS+, bachelor's+, graduate (Schools, Higher ed) |
| C16001 | Language spoken at home (Spanish; English ability) | "Spanish-language households" preset; limited-English share |
| B03003 | Hispanic or Latino origin | Context for the Spanish-language lens |
| B02001 | Race (one race alone, by group; two or more races) | Added at the owner's review: race composition as context in every lens (D5 amended). Tagged `race_color`; no preset or lens criterion uses it. Not in the scoping availability check (V5): confirm at ZCTA level in Phase 4 |
| B28002 | Internet subscriptions | Broadband share (channel planning for every vertical) |
| DP03 | Health insurance coverage (resolved by label) | Medical lens (% uninsured) |

**Not in v1** (D5): B18101 disability, B21001 veteran status, B09001
(B01001 covers the needed child ages), B11003/B27010/C27006/B08006 (covered by the rows above).

### 4.3 Processed artifacts

| File | Contents |
|---|---|
| `data/zcta_profile.parquet` | One row per ZCTA. `zip` (string, 5 chars, primary key), `state_fips`, `state` (USPS abbr), `county_fips` and `county` (primary county from D4), `city` (D5, nullable), then for each resolved variable `<VAR>_e` and `<VAR>_m` (nullable float64) and, for medians, `<VAR>_code` (`none`/`top`/`bottom`). Only registry variables are stored. |
| `data/benchmarks.parquet` | Same variable columns, one row per geography: `geo_level` (`us`/`state`/`county`), `geo_id` (FIPS as text), `name`. |
| `data/zcta_geo.parquet` | GeoParquet, EPSG:4326: `zip`, simplified `geometry`. Map only (no area math), so simplification can be aggressive: choose a tolerance so the file is ≤ ~30 MB and the 1,000-ZIP map budget (§7) holds; document it. |
| `data/metadata.json` | Vintage; dataset and file URLs (**key-free**); resolved variables (ID, label, table); row counts; per-variable ZCTA coverage (% non-null); sentinel counts by code; top/bottom-code cross-check results (V7); geometry source (D3 or D3-alt) and tolerance; build timestamp; app version. |

Raw downloads cache in `data/raw/` (gitignored): `data/raw/acs/{vintage}/{sha256 of the key-free
request}.json` plus a `.meta.json` sidecar holding the key-free URL and fetch time. **Cache file
names and sidecars never contain the key** (tested). Re-running reuses the cache unless
`--refresh` is passed.

### 4.4 Data build CLI

```
uv run python scripts/build_data.py [--refresh] [--vintage 2024] [--only acs|geo|all] [--no-geo]
```
- A thin wrapper over `zipographics.data_build` (importable, testable).
- Idempotent; clear progress output (one line per request batch, row counts per step).
- Exit codes: `0` success, `2` usage error, `3` missing or rejected API key, `4` network/API
  failure, `5` validation failure. Every failure prints one actionable message, no traceback.
- Validates output: ≥ 33,000 ZCTA rows; every `zip` matches `^\d{5}$` and is a string; no
  sentinel values remain anywhere (§6.1); every state and every county referenced by a ZCTA has
  a benchmark row; `us` benchmark present; every registry variable resolved; per-variable ZCTA
  coverage reported (and the build fails if a core KPI variable is under 95 % non-null for
  ZCTAs with population > 0); geometry ZIPs ⊆ profile ZIPs; no null geometries.
- The app shows "Census data not built yet. Run `uv run python scripts/build_data.py`, then
  reload." if `zcta_profile.parquet` or `benchmarks.parquet` is missing or fails schema checks.
  If only `zcta_geo.parquet` is missing, the app works without the map and says why.

### 4.5 Census API access and the API key (critical)

- **All Census Data API queries require a free key** (V2). Signup:
  <https://www.census.gov/data/developers/api-key.html>; the key must be activated from the email,
  and the email address must end in .com, .net, .org, .gov or .edu.
- **Only the data build needs the key.** The running app never loads `.env`, never imports the
  Census client, and never calls the API. Once built, the `data/` files can be shared internally
  and colleagues can run the app without a key.
- **Config:** `CENSUS_API_KEY` is read from the environment. `scripts/build_data.py` (and only
  it) calls `python-dotenv`'s `load_dotenv(<repo root>/.env, override=False)` first, so a real
  environment variable wins over the file. **There is no `--census-api-key` flag** (command lines
  end up in shell history and process lists; Zipcator's flag is not copied).
- **Missing key** (unset, empty or whitespace): exit code 3 with exactly this message shape:
  "CENSUS_API_KEY is not set. The data build needs a free Census Data API key: request one at
  https://www.census.gov/data/developers/api-key.html, activate it from the email, then add the
  line CENSUS_API_KEY=<your key> to the .env file in the project folder (see .env.example). The
  app itself never needs the key." The message never echoes any part of a key (not its length,
  prefix or suffix).
- **Rejected key:** the API answers an invalid or unactivated key with a non-JSON error page.
  Detect non-JSON or error responses and exit 3 with "The Census API rejected the API key. Check
  that it was copied completely and activated from the email." No echo.
- **Proxy/network errors** (e.g., HTTP 403 from a proxy on CONNECT, DNS failure) exit 4 with a
  message that says it's a network problem, not a key problem (V13).
- **Requests:**
  - Base URLs: `https://api.census.gov/data/{vintage}/acs/acs5` and `.../acs5/profile`.
  - Geography (V4): ZCTAs `for=zip%20code%20tabulation%20area:*` (all ZCTAs in one call, no
    `in=`); states `for=state:*`; counties `for=county:*&in=state:*`; nation `for=us:1`.
  - **At most 50 variables per request** (V3), counting every `E`, `M`, `EA`, `MA` name. The
    client chunks the registry's variable list into ≤ 50 names (E and M together for each
    variable; EA/MA only for medians) and merges chunks on the geography key. `NAME` is
    requested only for state/county/us (for display names).
  - Sequential requests, at most 1 per second; timeouts (connect 10 s, read 120 s, since a
    ZCTA-wide response can be several MB); up to 4 retries with exponential backoff and jitter
    (1, 2, 4, 8 s) on timeouts, connection errors, HTTP 429 and 5xx; no retry on other 4xx.
    Clock and sleeper are injected (tests never sleep).
  - The whole build is roughly 60 requests (about 15 chunks × 4 geography levels × 2 datasets,
    fewer for the profile dataset).
- **Redaction (tested):** the key travels as the `key=` query parameter, so any URL that carries
  it is a secret.
  - `zipographics.redact.redact(text, secrets)` replaces `key=<anything up to & or whitespace or
    quote>` with `key=REDACTED` and replaces every literal occurrence of the key value.
  - A `RedactingFilter` is attached to the build's log handlers and to the `urllib3` and
    `requests` loggers; the `urllib3` logger is set to WARNING during the build anyway.
  - The client never formats `response.url`/`request.url` unredacted, and wraps every
    `requests` exception in its own `CensusApiError(redacted message) from None`, so tracebacks
    don't chain an exception whose text holds the URL.
  - Progress output goes through the same redacting logger (no `print` in library code).
  - `metadata.json` and cache sidecars store key-free URLs only.
- **Never logged or displayed:** the key, any URL with the key, or the request params dict.

### 4.6 Data correctness rules (each has tests; methods in §6)
1. **Sentinels → null** at build time (§6.1). No sentinel value ever reaches the app.
2. **Top/bottom-coded medians** are flagged from the annotation fields and shown honestly
   (§6.2).
3. **Medians are never averaged or summed.** Trade-area medians come from summed bracket
   counts with linear interpolation (§6.4).
4. **Aggregated MOEs** use the Census approximation formulas, labeled as approximations (§6.3).
5. **Overlap-weighted estimates** (Zipcator input) multiply counts by overlap % / 100 and are
   labeled as uniform-density estimates (§6.7).
6. **ZIPs are strings** in every file, dataframe and test.

## 5. Functional requirements

The app is a four-step flow held in `st.session_state`: **1 Industry → 2 ZIPs → 3 Review →
4 Insights**. A step indicator shows where the user is. Back navigation keeps entered values.

### 5.1 Step 1: industry and restricted-use check

- **Client industry** (required): a searchable dropdown with no default selection, listing the
  verticals below. Each vertical maps to a **default lens** (§5.5, Appendix D) and a **restricted
  flag**. The mapping lives in `zipographics.verticals` as data, not in UI code.
- **Restricted-use question** (required, shown for every vertical), worded exactly:
  **"Will this be used for ads, mailers, or any other marketing for housing, jobs, credit or
  financing, or insurance?"** Yes / No, no default.
  - Restricted vertical: pre-answered **Yes** and locked (disabled), with the note "Marketing for
    this industry always counts as restricted use."
  - Other verticals: the user must answer before continuing. **Yes turns on restricted mode**
    whatever the vertical (e.g., a car dealer advertising financing, a restaurant advertising
    jobs). A one-line hint under the question gives those two examples.
- **Project / client name** (optional, ≤ 80 characters): titles the dashboard, the summary
  report and every export, and names the downloaded files (sanitized for Windows file names).
- **Continue** is disabled until the industry and the question are answered.
- Step-1 answers can be changed only by going back to Step 1; the insights screen can switch the
  lens but never the restricted status.

**Verticals (refined from the brief)**

| Vertical | Restricted | Default lens (Appendix D) | Notes |
|---|---|---|---|
| Home services (HVAC, plumbing, roofing, pest, remodeling) | No | Home services | Financing offers → answer Yes |
| Lawn, landscaping & pool | No | Lawn & outdoor | |
| Solar & home energy | No | Lawn & outdoor (homeowner-led) | *Added.* Loans/leases are credit → answer Yes |
| Moving & storage | No | Movers | *Added.* New movers, renters |
| Restaurants & food service | No | Restaurants | Hiring ads → answer Yes |
| Retail (general & specialty) | No | Retail | Store credit cards → answer Yes |
| Automotive sales | No | Auto sales | Financing/lease ads → answer Yes |
| Auto repair & service | No | Auto service | |
| Medical practices & healthcare | No | Health | |
| Dental & orthodontics | No | Dental | Payment plans → answer Yes |
| Veterinary & pet services | No | Pets | |
| Fitness & gyms | No | Fitness | |
| Salon, spa & personal care | No | Salon | |
| Childcare & early education | No | Childcare | |
| Private schools & tutoring | No | Schools | |
| Higher ed & vocational training | No | Higher ed | Student loans → answer Yes |
| Legal services | No | General | |
| B2B / professional services | No | B2B | Business counts in phase 2 |
| Hospitality, entertainment & events | No | Hospitality | |
| Nonprofit & community organizations | No | General | |
| Real estate (brokerage, rentals, property management) | **Yes** | Context only | Meta: Housing |
| Home builders & developers | **Yes** | Context only | Meta: Housing |
| Senior living (communities are housing) | **Yes** | Context only | Meta: Housing |
| Mortgage & lending | **Yes** | Context only | Credit |
| Banking & credit unions | **Yes** | Context only | Meta: Financial products and services |
| Insurance | **Yes** | Context only | Meta: Financial products and services (V10) |
| Financial planning & investments | **Yes** | Context only | Meta includes investments in its financial category (V10) |
| Staffing & recruiting | **Yes** | Context only | Employment |
| Other | Decided by the question | General | |

### 5.2 Step 2: ZIP input

Two inputs on one screen (tabs): **Paste or type** and **Upload CSV**. Both produce the same
`ParsedInput` (accepted ZIPs in input order, repairs, truncations, invalid tokens, duplicate
count, optional per-ZIP overlap %, source type).

**Paste box.**
- Separators: any run of commas, spaces, tabs, semicolons, pipes and newlines (CRLF or LF). A
  column pasted from Excel (newline-separated, possibly with a header cell like `ZIP`) works.
- Each token is stripped of surrounding quotes and whitespace; `="02108"` (Zipcator's Excel-safe
  form) becomes `02108`; a trailing `.0` (Excel float) is dropped.
- A first token that is a known header word (`zip`, `zipcode`, `zip code`, `postal code`, `zcta`,
  case-insensitive) is ignored.

**Token rules** (shared by paste and CSV; `zipographics.zips.normalize_token`):

| Token (after cleanup) | Result |
|---|---|
| 5 digits | accepted |
| 3 or 4 digits | **left-padded to 5, counted as repaired** (`2108` → `02108`, `601` → `00601`) |
| `NNNNN-NNNN` or 9 digits | **truncated to the first 5**, counted as ZIP+4 truncated |
| `NNNN-NNNN` / `NNN-NNNN`, or 7-8 digits | Excel-mangled ZIP+4: pad the ZIP part (or the whole number to 9), then truncate; counted as repaired and truncated |
| 1-2 digits, 6 digits, anything else (letters, `ABC12`, `12-34`, `1e5`) | invalid; listed back to the user verbatim (first 20 shown) |

- **Duplicates** (after normalization) are dropped; the first occurrence keeps its position;
  the review screen shows the count.
- **Order** is input order (it's the default table order and the ZIP-list export order).
- **Maximum: 1,000 distinct valid ZIPs** (D1; `config.MAX_ZIPS`). Rationale: covers a large DMA or
  most of a state (Florida has about 1,000 ZCTAs); profile math is trivial at that size; the map's
  GeoJSON is the binding constraint and stays within the 3 s render budget at 1,000 simplified
  polygons (§7, benchmarked). Above the limit the review screen blocks with "Zipographics handles
  up to 1,000 ZIPs at a time. Split the list and run it in parts."
- ZIPs are `str` everywhere. The parser never calls `int()` on a ZIP except inside a
  digits-only check, and never lets pandas infer dtypes.

**CSV upload.**
- `.csv` or `.txt`, ≤ 5 MB. Encoding: UTF-8 with or without BOM, falling back to cp1252
  (Excel on Windows saves "CSV" as cp1252). Delimiter sniffed among comma, semicolon and tab.
  Read with `dtype=str`, `keep_default_na=False`.
- **Zipcator export** (contract in §5.3) is detected from its headers. Its `Overlap %` column
  turns on **in-radius estimates** (§6.7) and the review screen says "Zipcator export detected:
  in-radius estimates are on."
- **Any other CSV:** the ZIP column is found by header name (`zip`, `zipcode`, `zip code`,
  `zip_code`, `zip5`, `postal code`, `postalcode`, `zcta`, `zcta5`; case- and space-insensitive);
  failing that, the single column in which ≥ 80 % of non-empty values pass the token rules; if
  several columns qualify, the user picks one from a dropdown; a header-less single-column file
  works. Full-ZIP figures only.
- The token rules above (including leading-zero repair) apply to CSV values too.

### 5.3 Zipcator import contract ("zipcator-export v1")

Determined from Zipcator's code, `src/zipcator/export.py` at commit `6d9ad8a` (V12).

**Columns, in order** (display-style headers):
`ZIP`, `City`, `County`, `State`, `Overlap %`, `Area in radius (sq mi)`, `ZIP area (sq mi)`,
`Nearest distance (mi)`, `Center distance (mi)`, `Contains address`, and, only when population
data was built, `Population`, `Est. pop in radius`.

**Formats Zipcator writes:**
- *Plain CSV:* RFC 4180, CRLF line endings, `csv.QUOTE_NONNUMERIC` (text quoted, numbers bare),
  UTF-8 without BOM, ZIP as quoted text (`"02108"`), `Overlap %` as a number with up to 6
  decimals in (0, 100], `Contains address` as `Yes`/`No`.
- *Excel-safe CSV:* the same, plus a UTF-8 BOM, with the ZIP cell written as `="02108"`.

**Formats Zipographics must also accept** (what users actually hand over):
- either file after being **opened and re-saved in Excel** (BOM removed or cp1252 encoding,
  quoting changed, ZIPs possibly reduced to `2108`/`601` in the plain variant: repaired and
  reported per §5.2; `="02108"` cells re-saved as plain `02108`);
- snake_case headers `zip` and `overlap_pct` (forward-compatibility fallback, per the brief).

**Detection:** after stripping a BOM and whitespace and comparing case-insensitively, the file is
a Zipcator export if it has `ZIP` and `Overlap %` and at least one of `Contains address`,
`Area in radius (sq mi)`, `Nearest distance (mi)`; or it has `zip` and `overlap_pct`. Only `ZIP`
and `Overlap %` are used; other columns are ignored (City/County/State come from Zipographics'
own data).

**Row rules:** overlap must parse as a number in (0, 100] (values like `12.5%` are accepted);
blank → the ZIP is treated as a full ZIP and listed on the review screen; out of range or
unparseable → row rejected and listed; a ZIP repeated with different overlaps keeps the first
and warns.

**Tests on both sides:** Zipographics has importer tests against committed fixture files in
`tests/fixtures/zipcator/` (plain, Excel-safe, Excel-re-saved plain with zeros stripped,
Excel-re-saved cp1252, snake_case, without population columns), produced by running Zipcator's
real `export.to_csv` for downtown Tampa, 5 mi, and Boston, 3 mi. Zipcator's repo gets a matching
**export-contract test** that pins the header tuple and both formats against the same fixtures
(follow-up task in the Claude Code handoff). A header change in Zipcator then fails a test in
Zipcator before it can break Zipographics.

### 5.4 Step 3: review screen

Replaces a "building insights" loading screen: the data is local and the insights build in under
a second, so a short validation summary is more useful than a spinner. Example:

> **15 ZIPs recognized** · 1 not found (33601 has no residential Census data; it's likely a
> PO-box or single-organization ZIP) · 2 repaired (leading zeros restored: 2108 → 02108,
> 2109 → 02109) · 2 have small populations, so some figures will be less reliable ·
> Industry: Home services · Restricted mode: off
> **[Back]  [Show insights]**

Lines, each shown only when it applies (all counts computed by the library, not the UI):

| Line | Rule |
|---|---|
| N ZIPs recognized | valid-format ZIPs present in `zcta_profile` |
| Not found | valid format but not a ZCTA: "likely a PO-box or single-organization ZIP, or not a ZIP code"; listed |
| No residents | a ZCTA with population 0: "has no residential population in Census data"; kept, contributes nothing |
| Repaired | leading zeros restored; each shown as `2108 → 02108` (first 10, then "and N more") |
| Repaired ZIP in an unexpected state | a repaired ZIP whose state differs from the state holding most of the other ZIPs' population: "check it: 03360 is in NH, the rest are in FL" (catches typos that padding would hide) |
| ZIP+4 truncated | count |
| Invalid entries | count plus the tokens (first 20) |
| Duplicates removed | count |
| Small populations | ZCTAs with population < 1,000 or households < 300 (D2): "some figures will be less reliable"; listed |
| Zipcator export | "in-radius estimates are on" + ZIPs with blank overlap |
| Spans states | "Your ZIPs are in FL and GA. Benchmark: Florida (most of their population). You can change it." |
| Industry, project name, restricted mode on/off | always |

Blocking conditions (Show insights disabled, reason shown): zero recognized ZIPs; more than
1,000 valid ZIPs.

### 5.5 Step 4: insights dashboard

**Header:** project name (or "Untitled project"), industry, ZIP count (recognized of entered),
benchmark (with a selector: state / county / national), estimate mode when Zipcator data is
present (**In-radius estimate** default / Full ZIPs toggle), ACS vintage ("ACS 2020-2024 5-year
estimates"), and the restricted-mode banner when on (§5.7). The ZIP = ZCTA note sits under the
header.

**Benchmark (§6.8):** defaults to the state holding the most population among the recognized
ZIPs (each ZIP's state from D4); a message explains the choice when ZIPs span states. Options:
any state represented, any county represented (default: the county with the most input
population), or national. Switching recomputes indexes instantly.

**Lens selector:** one lens per vertical by default (Appendix D); the user can switch to any
other lens. A lens sets which KPI cards lead, which charts show, which table columns are visible
first, and which presets are offered. Restricted mode allows only the Context lens.

**KPI cards** (trade area = all recognized ZIPs, overlap-weighted when on):
- Always: Households, Population, Median household income, % homeowners, % households with
  children; then 2-4 lens-specific cards (Appendix D).
- Each card: value; `± MOE` in small type; **index vs benchmark** (100 = benchmark; shown for
  shares, medians, means and ratios, e.g., "Index 128 vs Florida"); a reliability marker when the
  value or index is "use with caution" or "unreliable", with a tooltip explaining it.
- Counts (households, population) don't get an index; they show the share of the benchmark's
  total instead ("1.4 % of Florida's households").
- Top-coded medians show as "$250,000+" with no index ("above the published range").

**Ranked table** (`st.dataframe`):
- One row per recognized ZIP; columns ZIP (text), City, County, State, Population, Households,
  [In-radius households, Overlap %], then the lens's metric columns; a column picker adds any
  other metric.
- **Sort by any metric** (header click and an explicit "Sort by" control); default order is
  input order.
- **Raw values / Index** toggle; **Show margins of error** toggle (adds `± MOE`).
- **Reliability shading:** "use with caution" cells in muted text; "unreliable" cells in grey
  italics with a marker (`†`, so the meaning doesn't depend on color alone); null cells show "—".
  Explanation: column header help tooltips, a legend under the table, and a "Why are some values
  grey?" expander listing each unreliable cell with its estimate, MOE and CV. If the installed
  Streamlit can show per-cell tooltips, use them too; record in DECISIONS which was possible.
- Filter-qualifying ZIPs are highlighted (bold ZIP and a ✓ column) and can be shown alone
  ("Only matching ZIPs" toggle).

**Filter builder and presets:**
- Stackable rules combined with AND: `metric` · `≥ / ≤` · `value` · basis `value` or `index`
  (e.g., "Household income $100k+ share ≥ 40 %" AND "% homeowners ≥ 60 %"; "Households with
  children index ≥ 115"). Up to 6 rules. OR groups are a future idea.
- Null values never qualify. A ZIP that qualifies only on an unreliable estimate is marked
  "qualifies on an unreliable estimate"; an "Exclude unreliable matches" checkbox (default off)
  drops those.
- Top/bottom-coded medians compare as bounds (§6.2): "$250,000+" satisfies `≥ 200,000` but is
  "uncertain" for `≤ 300,000` and doesn't qualify.
- **Presets** (Appendix D) are one-click bundles that fill the rule list; the user can then edit
  the rules. Each lens offers 2-4 presets. Thresholds are starting points in a data table.
- Qualifying ZIPs are highlighted in the table and on the map; a summary line says "7 of 15 ZIPs
  match (households: 12,400 of 31,900)".

**Charts** (trade area vs benchmark, side by side, as shares; Altair, which ships with
Streamlit): always income distribution (7 bands), age breakdown (8 bands), owner vs renter,
housing age (4 bands); plus 1-2 lens charts (Appendix D). Keep it to about six charts. A "More
demographics" expander in every lens adds a race and Hispanic-origin chart (context; its help text
says Hispanic origin is a separate Census question and Hispanic people can be of any race). Chart
data comes from `zipographics.charts` (tested); rendering is thin.

**Map** (folium via `streamlit-folium`): choropleth of the selected metric over the recognized
ZIP polygons (sequential palette, quantile or equal-interval breaks, legend with units);
qualifying ZIPs outlined more heavily; unreliable values hatched or outlined dashed and noted in
the tooltip; tooltip: ZIP, city, value ± MOE, index, reliability. Auto-fit bounds. If geometry is
missing, an explanatory placeholder.

### 5.6 Exports

1. **ZIP list for ad platforms:** copy boxes and a `.txt` download, comma-separated
   (`02108, 02109`) and newline-separated. Without filters, all valid-format input ZIPs in input
   order (including "not found" ones, because USPS ZIPs can still be targetable even without
   Census data; a checkbox drops them). With filters, the qualifying ZIPs, with a checkbox to
   export all instead. **No footer in the ZIP list itself** (it must paste and upload cleanly);
   the attestation block is displayed directly above the copy box and recorded in the CSV and
   report.
2. **CSV** (two variants, as in Zipcator): *CSV* (plain; ZIPs as quoted text, RFC 4180, UTF-8)
   and *CSV for Excel* (UTF-8 BOM, ZIP cells as `="02108"` so Excel keeps the zeros; both tested).
   Rows: one per recognized ZIP, then one `Trade area` row and one benchmark row (in a `Row type`
   column, so the ZIP column stays pure ZIPs). Columns: ZIP, City, County, State, then for each
   metric value, MOE, reliability tier and index; overlap and in-radius columns when on; a
   "qualifies" column when filters are active. Text fields are defused against formula injection
   (leading `= + - @`, as Zipcator does). After the table: one blank line, then the **footer**
   lines, each a single quoted cell starting with `Note:` (spreadsheet users see it at the
   bottom; programs read the table with `skipfooter` or stop at the blank line, documented in the
   README and tested).
3. **Shareable summary report:** one **self-contained HTML file** (D3): title (project name),
   date, industry, benchmark, estimate mode, KPI cards, the lens's charts and a static map (inline
   SVG via matplotlib, Agg backend), the ZIP table (all rows, current column set), active filters,
   sources and data notes, footer. Print stylesheet so "Print → Save as PDF" in any browser gives a
   clean PDF (page breaks between sections, no interactive elements). No external requests,
   scripts or fonts. Why HTML: opens anywhere, prints to PDF from any browser, no Windows-hostile
   PDF toolchain (WeasyPrint needs GTK; Kaleido needs headless Chrome), easy to test by parsing.
4. **Footer / attestation** (CSV footer, report footer, and the block above the ZIP list),
   generated by one function (`export.attestation(...)`) so all exports agree:
   project name; industry (vertical); the restricted-use question and the answer given ("Yes",
   "Yes (set by industry)", or "No"); restricted mode on/off; benchmark; estimate mode; filters
   applied (or "none"); ACS vintage; "ZIP = Census ZCTA; PO-box-only and single-organization ZIPs
   aren't included."; "ACS figures are survey estimates with margins of error at the 90 %
   confidence level; aggregated MOEs and in-radius estimates are approximations."; generated
   timestamp and app version; "This product uses the Census Bureau Data API but is not endorsed or
   certified by the Census Bureau."; GeoNames CC BY 4.0 attribution.
   Recording the answer on the export creates accountability without heavy process.
5. File names: `<project>_<yyyy-mm-dd>_zips.csv`, `..._zips_excel.csv`, `..._ziplist.txt`,
   `..._report.html`; `<project>` sanitized (Windows-reserved names and characters handled), or
   `zipographics` if blank.

### 5.7 Restricted mode

**When:** the Step-1 answer is Yes (forced for restricted verticals).

**Principle:** profile figures stay visible as context, but nothing lets the user rank, filter,
select, highlight or export ZIPs based on demographics.

**What changes:**

| Feature | Restricted mode |
|---|---|
| Filter builder, presets | Not shown; library refuses |
| Lens selector | Context lens only |
| Table | Rendered without interactive sorting (static table or a grid with sorting disabled, whichever the installed Streamlit supports; record in DECISIONS), in input order, with "Order: as entered / by ZIP" as the only ordering choice; no Index toggle; values and MOEs visible |
| Map | Recognized ZIPs drawn with one neutral fill (no choropleth); tooltips still show values |
| KPI cards and charts | Shown (trade-area context vs benchmark) |
| ZIP-list export | Exactly the user's valid input ZIPs, in input order; never a filtered subset |
| CSV and report | All recognized ZIPs in input order; no qualifies column; footer says restricted mode on |
| Banner | Shown at the top of the insights screen and in the report |
| Ad-platform notice | Above the ZIP list: "Google Ads and Meta don't allow ZIP-code targeting for housing, employment, credit/financial-services ads in the US (Meta also requires at least a 15-mile radius). Check the platform's current rules before uploading this list." (V10) |

**Banner text** (plain, not lecturing):
> **Restricted mode is on.** You said this will be used to market housing, jobs, credit or
> financing, or insurance. Fair-housing, fair-lending and equal-employment rules, and Google and
> Meta ad policies, don't allow choosing who sees that kind of marketing based on characteristics
> like age, income, family status or national origin, or on stand-ins for them. You can see the
> profile as context, but ZIPs can't be ranked, filtered or selected by it, and the ZIP list stays
> the one you entered.

**Enforcement in the library, not only the UI.** A `UsePolicy(restricted: bool, vertical,
answer)` object is created at Step 1 and passed to every function that could select ZIPs:
- `filters.apply(profile, rules, policy)` raises `RestrictedUseError` if `policy.restricted` and
  `rules` is non-empty;
- `table.order(profile, key, policy)` allows only `input`/`zip` keys when restricted;
- `presets.for_lens(lens, policy)` returns `[]`; `lenses.available(policy)` returns `[CONTEXT]`;
- `mapview.layer(profile, metric, policy)` returns the neutral style;
- `export.zip_list(parsed_input, policy, qualifying=...)` ignores `qualifying` when restricted;
  `export.csv`/`report` drop filter state.
Each has unit tests, and AppTest checks the UI never offers these controls.

**Protected and proxy characteristics** (most conservative across fair housing, fair lending,
employment and insurance; Appendix B): race, color, national origin (including language spoken
at home, Hispanic origin and ancestry as proxies), religion, sex (including gender identity and
sexual orientation), familial status (households with children, household or family type,
children's ages), age, disability, marital status, receipt of public assistance, veteran or
military status, and genetic information; plus income as a proxy (the brief's list). These
metrics are tagged in the registry and are never offered as preset or lens criteria in restricted
mode.

**Stricter than the list (D4):** in restricted mode, ranking, filtering and selection
are blocked for **every** metric, not just tagged ones, because at ZIP level nearly every ACS
measure (tenure, home value, rent, education, vehicles, commuting, internet) correlates with race,
national origin or familial status, and selecting areas by such measures is the pattern regulators
have challenged. The tag list still matters: it is documented, tested, and used to label
characteristics in the UI.

**Not legal advice.** The app, README and DECISIONS.md state: "Restricted mode is a guardrail,
not legal advice. It does not make a campaign compliant. The agency's counsel should review the
industry-to-restricted mapping and the restricted characteristic list before wide internal use."
Both lists live in one data module (`zipographics.verticals`, `zipographics.restricted`) so
counsel's changes are one-file edits with tests.

### 5.8 CLI (secondary, small)

`uv run zipographics profile 33602 33606 02108 [--file zips.csv] [--vertical "Home services"]
[--restricted yes|no] [--benchmark state|county|us] [--csv out.csv] [--report out.html]` prints
the review summary and the trade-area KPIs. Same library code as the app; `--restricted` is
required unless the vertical is restricted. Exists mainly for scripting and end-to-end tests.

## 6. Statistical methods

All formulas live in `zipographics.stats` and are unit-tested against hand calculations. Before
implementing, the builder checks each formula against the cited official document (V8, V9) and
quotes it in DECISIONS.md, because the formula images didn't extract cleanly during scoping.

### 6.1 Sentinels and annotations (V6)
At build time, every estimate or MOE equal to an annotation value becomes null, with these
specifics: -666666666, -999999999, -888888888 → estimate null (and its MOE null); -222222222,
-333333333 → MOE null (estimate kept); -555555555 → MOE **0** ("may be treated as zero");
`median-`/`median+` annotations → `<VAR>_code` = `bottom`/`top` (estimate kept). The build
verifies the list against the **5-year** notes page for the vintage (only the 1-year page could be
read during scoping) and fails if any other large negative value (< -100000000) appears in the
data. A null estimate is excluded from sums; a sum that loses a component is flagged
"incomplete" (shown as a footnote, never silently presented as complete).

### 6.2 Top- and bottom-coded medians (V7)
Open-ended medians are identified from the annotation fields, not from hardcoded numbers. They
are displayed with their bound ("$250,000+", "1939 or earlier"), get no index ("above the
published range"), get no CV-based tier (tier "use with caution", tooltip explains), and compare
as bounds in filters (§5.5). The believed codes (250,001 / 2,000,001 / 3,501) are a build-time
cross-check only; results go in DECISIONS.md.

### 6.3 Sums, proportions, ratios (V9)
With `MOE` meaning the published 90 % MOE:
- **Sum** `X = Σ xᵢ`: `MOE(X) = √(Σ MOE(xᵢ)²)`. When several components are zero estimates,
  check the handbook's guidance on including only the largest zero-estimate MOE; implement it if
  the 2020 handbook (or its successor) says so, and record the decision.
- **Proportion** `P = X / Y` where X is a subset of Y: `MOE(P) = (1/Y) √(MOE(X)² − P² MOE(Y)²)`;
  if the radicand is negative, use `+` (the ratio formula).
- **Ratio** `R = X / Y` where X is not a subset of Y (mean income = aggregate / households):
  `MOE(R) = (1/Y) √(MOE(X)² + R² MOE(Y)²)`.
- **Product** (per-capita income × population, to aggregate per-capita income):
  `MOE(A·B) = √(A² MOE(B)² + B² MOE(A)²)`.
- `SE = MOE / 1.645`. All aggregated MOEs are labeled "approximate" in the UI and exports
  (the formulas ignore covariance and degrade as more estimates are combined; the UI says so in
  the help text).
- Shares are stored as fractions internally and displayed as percentages; their MOEs in
  percentage points.

### 6.4 Medians (V8)
- **Single ZIP** (and single ZIP with overlap weighting, since uniform weighting scales every
  bracket equally): show the **published** median and its published MOE (B19013, B25077, B25064,
  B01002, B25035) with its top/bottom code.
- **Trade area of 2+ ZIPs:** sum the bracket counts across ZIPs (overlap-weighted when on), then
  **linear interpolation** within the median bracket, the method the ACS uses ("The ACS calculates
  medians using a linear interpolation method", V8):
  `median = L + ((N/2 − C) / f) × W`, where N = total count, C = cumulative count below the
  median bracket, f = count in the median bracket, L = its lower bound, W = its width. Bracket
  bounds come from the labels, using the continuous convention (`$10,000 to $14,999` →
  [10,000, 15,000)). The open lowest bracket uses 0 as its lower bound for income, value and rent
  (an assumption, recorded); if the median lands in an open-ended top or bottom bracket, report the
  bound ("$200,000+", "1939 or earlier") with no MOE.
- Because published medians use finer "standard distributions" than the published bracket
  tables, a single ZIP's interpolated median differs from its published one. A `data` test
  measures that gap across all ZCTAs and records the distribution (median and 95th percentile
  absolute % difference) in QA_REPORT.md; the UI help text says trade-area medians are estimated
  from income brackets.
- **Median MOE (approximation, labeled):** the Census 68 %-interval method (V8):
  `p_lo = 0.5 − SE(p)`, `p_hi = 0.5 + SE(p)`; interpolate the values at `p_lo` and `p_hi` as above;
  `SE(median) = (value(p_hi) − value(p_lo)) / 2`; `MOE = 1.645 × SE`. Census computes `SE(p)` from
  a design factor, which won't be published after the 2024 PUMS; Zipographics instead derives
  `SE(p)` from the bracket MOEs: the proportion formula (§6.3) applied to the cumulative count up
  to the median bracket over N, evaluated at P = 0.5. Record the derivation and a worked example in
  DECISIONS.md.
- Median age from B01001 (summed over sex; age bands parsed from labels; top band "85 years and
  over" open); median year built from B25034; median rent from B25063 excluding "No cash rent".

### 6.5 Means
Mean household income = Σ B19025 / Σ B11001 (ratio MOE). Per-capita income = Σ(B19301 × B01003) /
Σ B01003 (product then ratio MOE; labeled approximate). Vehicles per household from B25046 if
present at ZCTA level, else from B25044 counting "5 or more" as 5 (labeled "at least").

### 6.6 Coefficient of variation and reliability tiers (D2)
`CV = SE / estimate × 100`. Tiers: **good** CV ≤ 15 %; **use with caution** 15 % < CV ≤ 30 %;
**unreliable** CV > 30 %, or MOE not computable, or estimate null. An estimate of exactly 0 is
"use with caution" (CV undefined) and displays as `0 (± MOE)`. For shares, the CV is that of the
share. Census publishes no numeric thresholds (V9); these are a judgment call, recorded in
DECISIONS.md, and live in `config.py`. **Small-population flag:** population < 1,000
or households < 300.

### 6.7 Overlap-weighted (in-radius) estimates
When a Zipcator export supplies overlap %, each ZIP's count estimates (and bracket counts) are
multiplied by `w = overlap / 100` and their MOEs by `w` (w treated as a constant). Shares, means
and medians are computed from the weighted counts. Everything weighted is labeled "in-radius
estimate (assumes people and homes are spread evenly across each ZIP)". The Full ZIPs toggle uses
w = 1. Per-ZIP rows show full-ZIP values plus in-radius households and population columns.

### 6.8 Benchmarks and index
- Each ZCTA's state and primary county come from D4 (largest land overlap). The **default
  benchmark** is the state with the largest summed population across recognized ZIPs (ties: the
  state of the first ZIP in input order); the county default works the same way among primary
  counties. National = `us` (50 states + DC; PR ZIPs get a note).
- Benchmark values are the published figures for that geography (published medians included).
- **Index** = `100 × trade-area value / benchmark value`, rounded to an integer, for shares,
  medians, means and ratios; null if either side is null, top/bottom-coded, or the benchmark is 0.
  Its reliability tier is the worse of the two inputs' tiers.
- Per-ZIP index (table toggle) uses the same benchmark.

## 7. Non-functional requirements

- **Performance** (Windows laptop, data cached after first load; each budget has a `slow`
  benchmark test): data load ≤ 3 s cold (`st.cache_resource`); parsing and review summary for
  1,000 ZIPs ≤ 0.5 s; trade-area profile, indexes and table for 1,000 ZIPs ≤ 1 s; map GeoJSON
  preparation for 1,000 ZIPs ≤ 1 s and visible render ≤ 3 s; summary report ≤ 5 s.
- **No runtime network:** the app and everything it imports at runtime make no network calls
  (tested with the socket guard and an AppTest run). Folium tiles load in the user's browser from
  the tile provider; the report has no external requests at all.
- **Platforms:** Windows 10/11 first-class (primary dev machine), plus Linux and macOS. CI on
  `ubuntu-latest` and `windows-latest`, Python 3.11 and 3.12.
- **Code quality:** `ruff check` and `ruff format --check` clean; `mypy` clean on `src/`;
  coverage ≥ 90 % (line + branch) on `src/zipographics`.
- **Logging:** `logging`, no `print` in library code; every handler used by the build has the
  redacting filter (§4.5).
- **Config:** environment variables only: `ZIPOGRAPHICS_DATA_DIR` (default `<repo>/data`),
  `ZIPOGRAPHICS_ZIPCATOR_PARQUET` (optional, D3-alt), `CENSUS_API_KEY` (build only; from `.env`).
- **Agent guardrails (one layer only):** `.claude/settings.json` denies Claude Code `Read` and
  `Edit` on `.env`/`.env.*` (per the current docs, `Edit` rules also cover Write, and `Write(path)`
  rules never match; V11) plus best-effort `Bash(...)` patterns. Deny rules have reportedly not
  always been enforced and shell patterns can't block every way to read a file, so the real
  protections are the ones in §4.5: env-only key, nothing ever displays it, redacted and tested
  logs. `CLAUDE.md` says this plainly.
- **Security and privacy:** no secrets in the repo (`scripts/check.py` secrets gate); the key is
  never logged; uploaded files are processed in memory and never written to disk; no telemetry
  (`.streamlit/config.toml` sets `browser.gatherUsageStats = false`).
- **Accessibility:** reliability never conveyed by color alone (marker + text); charts have text
  alternatives (a table under an expander); chart palettes are colorblind-safe.
- **Public-repo safety:** no data files over 1 MB tracked (`uv.lock` exempt), test fixtures are
  tiny and synthetic or small real excerpts (public-domain Census data).

## 8. Architecture

```
src/zipographics/
  __init__.py      # __version__
  config.py        # env-var config, paths, MAX_ZIPS, CV thresholds, small-pop thresholds
  models.py        # dataclasses: ParsedInput, ZipToken, ReviewSummary, UsePolicy, Rule, TradeAreaProfile, ...
  zips.py          # token normalization (repair, ZIP+4, junk), paste parsing, dedupe
  importer.py      # CSV reading (encoding/delimiter sniffing), Zipcator detection (contract §5.3), generic ZIP column
  verticals.py     # vertical list: restricted flag, default lens  (counsel-editable data)
  restricted.py    # protected/proxy characteristic list, banner/notice text, policy checks (counsel-editable data)
  metrics.py       # metric registry (Appendix C): kinds, sources, characteristic tags, formats
  lenses.py        # lenses and presets (Appendix D) as data
  redact.py        # redact(), RedactingFilter
  census_api.py    # CensusClient: chunking, retries, cache, sanitized errors (build only)
  data_build.py    # resolve variables, download, sentinels, merge D4/D5, geometry, validate, write
  data.py          # load artifacts (+ schema validation), DataNotBuiltError
  stats.py         # sums, proportions, ratios, products, CV, tiers, interpolation, median MOE
  profile.py       # trade-area aggregation (incl. overlap weighting), per-ZIP table, benchmark choice, indexes
  review.py        # ReviewSummary from ParsedInput + data
  filters.py       # rules, evaluation (bounds semantics), presets application; policy-enforced
  charts.py        # chart data frames + Altair specs (app)
  mapview.py       # GeoJSON prep, folium choropleth/neutral layer
  export.py        # ZIP lists, CSV (plain/Excel), attestation footer, file names
  report.py        # self-contained HTML report (matplotlib SVG charts/map)
  ui.py            # small Streamlit helpers (formatting, markers) testable without a browser
  cli.py           # CLI entry point
app/
  streamlit_app.py # layout and wiring only
scripts/
  build_data.py    # loads .env, calls zipographics.data_build
  check.py         # all quality gates (exists)
tests/
  unit/  integration/ (marker data)  live/ (marker network)  ui/ (AppTest; visual marker for Playwright)
  fixtures/        # recorded API responses with fake keys, tiny synthetic data, Zipcator CSVs
docs/
  SPEC.md, DECISIONS.md, QA_REPORT.md, CLAUDE_CODE_HANDOFF.md
```

Rules: **all logic lives in `src/zipographics`**; the Streamlit file is layout and wiring only.
`census_api`, `data_build` and `dotenv` are never imported by the app (an import-graph test
enforces it). Policy (`UsePolicy`) is an explicit argument wherever ZIPs could be selected.

## 9. Testing and QA strategy

Tests are first-class deliverables. The build is a full write → test → fix → QA loop, as in
Zipcator.

### 9.1 Test layers and markers
| Layer | Marker | Runs by default / in CI | Notes |
|---|---|---|---|
| Unit | (none) | Yes | Synthetic data, mocked HTTP (`responses`), fast (< 30 s total) |
| Property | (none) | Yes | `hypothesis` |
| UI | (none) | Yes | `streamlit.testing.v1.AppTest` with a tiny synthetic data dir |
| Integration | `data` | No (local, after the data build) | Real artifacts in `data/`; golden scenarios |
| Live | `network` | No (manual, needs the key) | A few polite real API calls |
| Benchmark | `slow` | No | §7 budgets |
| Visual QA | `visual` | No | Playwright screenshots for human/agent review |

`tests/conftest.py` (exists) blocks non-loopback sockets in every test not marked `network`.

### 9.2 Required unit and property tests (minimum)
**zips / importer**
- Paste: commas, spaces, tabs, semicolons, pipes, CRLF and LF newlines, mixed separators, an
  Excel column with a `ZIP` header cell, quoted tokens, `="02108"`, `2108.0`.
- Leading-zero repair: every 4-digit and 3-digit numeric token is padded and reported (`2108` →
  `02108`, `601` → `00601`, `501` → `00501`); 1-2 and 6 digits invalid; repaired ZIPs reported in
  order; the state-mismatch warning fires for a padded typo.
- ZIP+4: `02108-1234`, `021081234`, Excel-mangled `21081234` and `2108-1234`, `6011234`.
- Junk (`abc`, `1e5`, `12-34`, emoji, empty strings), duplicates (before and after repair:
  `2108` and `02108` are duplicates), mixed valid/invalid, order preservation, the 1,000 limit
  (1,000 OK; 1,001 blocks).
- CSV: UTF-8, UTF-8 BOM, cp1252 with accents; comma/semicolon/tab; header-name detection
  variants; content-based detection; multiple candidate columns → choice required; header-less
  single column; 5 MB limit.
- **Zipcator contract:** every fixture in `tests/fixtures/zipcator/` parses to the expected ZIPs
  and overlaps; detection true for each variant and false for a generic CSV that happens to have a
  `ZIP` column; blank/invalid/duplicate overlap rows handled per §5.3.
- **Properties:** for any list of 5-digit strings, parse → normalize is idempotent; output ZIPs
  are always 5-char digit strings; dedupe preserves first-occurrence order; padding never changes
  a 5-digit token.

**sentinels / build transforms**
- Each annotation value → the treatment in §6.1 (estimate null, MOE null, or MOE 0);
  `median+`/`median-` codes set; an unknown large negative value fails the build.
- No sentinel survives into any output frame (property test over random frames seeded with
  sentinels).

**stats** (expected values computed by hand in the test, with the arithmetic shown in comments)
- Sum MOE, proportion MOE (including the negative-radicand fallback), ratio MOE, product MOE,
  against the handbook's worked examples where available (e.g., ±3,860, ±2,642, ±1,957 → ±5,070).
- Linear interpolation: medians for small hand-built distributions (median in the first, a middle,
  and the open top bracket; even/odd totals; an empty bracket; all-zero distribution → null).
- Median MOE per §6.4 against a hand calculation.
- Single-ZIP and uniformly weighted single-ZIP medians equal the published median (§6.4).
- CV and tiers at the boundaries (15.0 %, 15.01 %, 30.0 %, 30.01 %), zero estimates, null MOE.
- Index math; null/top-coded/zero-benchmark → null index; tier = worse of the two.
- **Properties:** shares ∈ [0, 1]; interpolated median within the bounds of its bracket;
  sum MOE ≥ max component MOE; scaling all counts by w scales MOEs by w and leaves shares and
  medians unchanged.

**profile / benchmark**
- Aggregation over synthetic ZIPs; overlap weighting; in-radius vs full toggle; incomplete sums
  flagged.
- Default benchmark: single state; multi-state by population (and the tie rule); county default;
  PR inputs get the national-benchmark note.

**restricted / filters / lenses**
- Vertical table: every restricted vertical has the locked Yes; every other vertical requires an
  answer; `Other` follows the answer.
- With restricted mode **on**, every path is refused or neutral: `filters.apply` with any rule
  (parametrized over **every** metric, not just tagged ones); `table.order` by every metric;
  `presets.for_lens` for every lens; `lenses.available`; `mapview.layer` style; `export.zip_list`
  with a `qualifying` subset (output = input ZIPs); CSV and report contain no filter state.
- With restricted mode **off**: rules AND together; index-basis rules; null never qualifies;
  unreliable matches marked and optionally excluded; bound semantics for coded medians; each
  preset produces the documented rules.
- The protected/proxy tag list matches Appendix B exactly (a test fails if a metric is added
  without a tag decision); no preset or lens KPI references a `race_color` metric.

**exports**
- ZIP lists (comma, newline), order, not-found inclusion checkbox, empty input.
- CSV (both variants): ZIPs as text; `="02108"` + BOM in the Excel variant; formula injection
  defused; trade-area and benchmark rows; footer after a blank line; the table part round-trips
  through `csv` and `pandas.read_csv(dtype=str, skipfooter=...)`. "Opens in Excel with leading
  zeros" is proven the way Zipcator did it (the Excel-safe form) and checked once by hand on
  Windows (recorded in QA_REPORT.md).
- **Attestation:** every field in §5.6 item 4 present in CSV footer, report footer and the ZIP-list
  block, for restricted-on (forced and answered) and restricted-off runs.
- Report: parses as HTML; contains no `<script>`, no `http(s)://` resource references (links in
  the sources section excepted), the title, KPI values, the footer; the restricted banner when on.
- File-name sanitization (Windows reserved names, slashes, long names).

**redaction and key handling** (fake key only, never a real one)
- `redact` on URLs with `key=` first, middle, last, URL-encoded, and the bare key value.
- With HTTP mocked to fail (400, 403, 429-then-200, 500 ×5, timeout, connection error, non-JSON
  "invalid key" page): captured logs at DEBUG (including the `urllib3` and `requests` loggers),
  exception `str()`, `traceback.format_exc()`, progress output (capsys), cache file names, cache
  sidecars and `metadata.json` contain neither the key nor `key=<value>`.
- Missing key (unset, empty, whitespace): exit code 3, message names `CENSUS_API_KEY` and the
  signup URL, contains no part of a key; rejected key: exit 3 with the rejection message; proxy
  403: exit 4 with the network message.
- `.env` loading: a fake `.env` in a temp dir is loaded by the build entry point; a real
  environment variable wins; the app import graph never imports `dotenv` or `census_api`.

**census_api / data_build** (recorded fixtures with fake keys)
- Chunking never exceeds 50 names; chunk merge on geography keys; ZCTA, state, county
  (`in=state:*`) and us URLs built correctly; retries with injected sleeper; cache hit skips HTTP;
  `--refresh` bypasses cache.
- Variable resolution by label (including a label that moved IDs between two fake vintages; a
  missing label fails clearly).
- Pipeline on tiny synthetic inputs → correct schema, ZIPs as zero-padded strings, primary county
  = largest land overlap, validation rejects bad outputs.
- `data.load` raises `DataNotBuiltError` with the build instruction when files are missing.

**UI (AppTest)**
- Step 1: verticals listed; restricted vertical locks Yes; non-restricted requires an answer;
  Yes on a non-restricted vertical turns restricted mode on; Continue gating; project name.
- Step 2: paste and upload paths (generic CSV, Zipcator CSV).
- Step 3: each review line appears for a crafted input (repaired, not found, no residents,
  truncated, invalid, duplicates, small population, spans states, Zipcator detected); blocking
  conditions; Back keeps inputs.
- Step 4: header fields; benchmark switch changes an index; lens switch; KPI cards; table
  toggles; a filter highlights the right ZIPs; preset fills rules; download buttons present.
- Restricted mode: banner present; no filter builder, presets, index toggle or sortable grid;
  Context lens only; ZIP list equals input.
- Missing-data message; missing-geometry message.

**CLI:** argument parsing, exit codes, CSV/report output on synthetic data.

### 9.3 Integration tests (marker `data`)
- Artifact smoke: row counts, schemas, ZIP dtype, no sentinels, benchmarks complete, metadata
  key-free.
- Published-vs-interpolated median gap across all ZCTAs (§6.4), recorded.
- Single-ZIP shares computed from counts match the Data Profile percentages within rounding for a
  sample of ZCTAs (cross-check of variable resolution).
- Golden scenarios (§9.4).

### 9.4 Golden scenarios
Expected values must be established **independently** of the code: looked up on data.census.gov
(table, geography and vintage cited) or computed by hand from those published numbers in a
worked table, recorded in `docs/QA_REPORT.md`. Never snapshot the code's output.

1. **Tampa Zipcator export:** Zipcator's real export for downtown Tampa, 5 mi (both variants, plus
   an Excel-re-saved copy). Check: ZIP count; in-radius households = Σ households × overlap,
   computed by hand; trade-area median household income interpolated by hand from summed B19001;
   Florida benchmark values; one index.
2. **Boston with leading zeros:** 02108-02111, 02113-02116, pasted correctly and as an
   Excel-mangled list (`2108, 2109, ...`) and an Excel-re-saved CSV: identical results; repaired
   count shown; Massachusetts benchmark.
3. **Rural small-population set:** 6-8 rural ZCTAs with population < 1,000 (chosen from the data,
   e.g., in Montana or Nebraska) with large MOEs: small-population flags, CVs and tiers computed by
   hand from published MOEs; unreliable cells de-emphasized.
4. **Puerto Rico:** `601, 603, 610, 612` (Excel-mangled 00601, 00603, 00610, 00612): repaired;
   Puerto Rico state benchmark; national-benchmark note; check how the Data Profile items behave
   for PR (DP02PR exists; V5).
5. **Restricted vertical:** the Tampa set with "Mortgage & lending": question locked Yes; every
   selection path blocked (UI and library); ZIP list equals input; footer says restricted on.
6. **Restricted by answer:** the Tampa set with "Automotive sales" answered Yes (financing ads):
   restricted mode on; footer records "Yes" (answered, not forced).
7. **Multi-state:** a Kansas City set spanning Kansas and Missouri (e.g., 66101, 66102, 66103,
   64105, 64106, 64108, 64109): default benchmark is the state with more of their population
   (computed by hand) and the message says so; county default likewise.
8. **Messy paste:** valid, repaired, ZIP+4, junk, duplicates and a not-found ZIP (33601, if the
   build confirms it isn't a ZCTA; otherwise another verified non-ZCTA ZIP) in one paste: every
   review count matches a hand count.

### 9.5 UI and visual QA
- AppTest as in §9.2.
- Visual (`visual`, manual): Playwright runs `streamlit run`, performs golden scenarios 1, 2, 5
  and a filtered run, and saves screenshots of each step plus the report rendered and printed to
  PDF to `qa/screenshots/` (gitignored). The builder **opens and looks at** them and fixes layout
  problems before the UI phase closes.

### 9.6 Coverage and gates
- Coverage ≥ 90 % line + branch on `src/zipographics` (excluding `cli.py` main guard).
- `uv run python scripts/check.py` (exists): ruff, format check, mypy, pytest + coverage, the
  1 MB file-size gate, and the secrets gate (no tracked `.env*` except `.env.example`; no
  key-looking values). CI runs it on ubuntu + windows × Python 3.11 + 3.12.

### 9.7 QA process
- Bugs are logged in `docs/QA_REPORT.md` (symptom, root cause, fix, regression test). Every fix
  gets a regression test.
- Decisions and verified facts go in `docs/DECISIONS.md`.
- An **independent QA review** (fresh-context subagent, `.claude/agents/qa-reviewer.md`, via the
  `/qa-review` command) runs at the end of each phase; every finding is fixed or explicitly
  deferred with reasoning. Any restricted-mode bypass, key leak or lost leading zero is HIGH and
  blocks the phase.

## 10. Acceptance criteria (v1 done)
1. Fresh clone on Windows, following only the README: `uv sync` → paste key into `.env` →
   `uv run python scripts/build_data.py` → `uv run streamlit run app/streamlit_app.py` works.
   Then, with `.env` removed and the built `data/` folder copied into a second clone, the app
   still runs (no key needed at runtime).
2. All 8 golden scenarios pass and are documented with independent verification notes.
3. Restricted mode: every selection path is refused in the library and absent in the UI (tests
   plus a QA-reviewer probe); attestation present on every shareable export.
4. Key handling: redaction tests green; the QA reviewer's forced-failure probe finds no key in
   logs, errors, tracebacks, caches or metadata; the missing-key message is exact.
5. Leading zeros survive every path (paste, CSV, Zipcator variants, CSV export opened in Excel,
   verified by hand once on Windows).
6. Unit + UI suite green on CI (ubuntu + windows, 3.11 + 3.12), coverage ≥ 90 %, lint/type clean,
   secrets and size gates clean.
7. Performance budgets in §7 met (`slow` benchmarks).
8. Screenshots of every step and the printed report reviewed.
9. README: what it does, screenshot, setup (including the key and that it's build-only), data
   build, ZIP-vs-ZCTA note, MOE note, restricted-mode explanation and not-legal-advice statement,
   data sources with licenses/attribution (Census API notice, GeoNames CC BY 4.0), how to read the
   CSV footer, MIT license.
10. Repo contains no data files over 1 MB and no secrets.

## 11. Phased plan

Each phase ends with all gates green, `/qa-review <N>`, triage, commits, and `git tag phase-N`.
**STOP** means Claude Code stops and waits for the owner.

| Phase | Scope | Exit criteria |
|---|---|---|
| 0 | Environment check: `uv sync`, gates run, git identity present (else STOP and ask), CI skeleton | `scripts/check.py` green; scaffold reviewed |
| 1 | `zips`, `importer`, Zipcator contract fixtures (generated with Zipcator's real exporter), `review` on synthetic data (TDD) | §9.2 zips/importer tests green |
| 2 | `stats`, sentinel transforms, `metrics` registry, `profile` (aggregation, weighting, benchmark, index) on synthetic data (TDD); formulas quoted from official docs in DECISIONS | §9.2 stats/profile tests green |
| 3 | `redact`, `census_api`, `data_build` on recorded fixtures with fake keys (TDD); missing-key and error messages; build CLI | §9.2 redaction/build tests green. **STOP: ask the owner to paste the Census API key into `.env` and confirm.** Never check for the key by reading `.env`. |
| 4 | Real data build; verify the 5-year annotation page, labels, coverage, top-code cross-check, B25046 and B02001 availability at ZCTA level, 33601 status; run `network` tests once; DECISIONS updated | Artifacts built and validated; `data` smoke tests green. **STOP: report coverage gaps, final metric list, and any official-source conflicts for the owner's OK.** |
| 5 | `verticals`, `restricted`, `lenses`/presets, `filters` (policy-enforced), `export` (ZIP lists, CSV, attestation), `report`, `cli` (TDD) | §9.2 restricted/filters/exports tests green; CLI end to end on real data |
| 6 | Streamlit app (4 steps), charts, map; AppTest suite; visual QA | AppTest green; screenshots reviewed. **STOP: owner tries the app and reviews screenshots and a sample report.** |
| 7 | Golden scenarios, benchmarks, README, full QA review, polish | §10 all met. **STOP: final report to the owner.** |

## 12. Future ideas (not v1)
- **Business counts (phase 2):** ZIP Codes Business Patterns via the County Business Patterns
  API, for B2B and competitive-density views. Caveats to show: it lags the ACS (different
  reference year), it's keyed by **USPS ZIP**, not ZCTA (some won't match, PO-box ZIPs appear),
  and ZIP-level data gives all-sector totals and establishment-size classes, with industry detail
  limited or suppressed.
- Native PDF export; PowerPoint export of KPI cards and charts.
- OR groups in the filter builder; saved projects; comparing two trade areas.
- Population-weighted in-radius estimates using census blocks (better than uniform density),
  shared with Zipcator.
- A shared `zip-tools` package used by both apps (ZIP normalization, the export contract).
- Counsel-maintained restricted mappings loaded from a reviewed config file.
- Spanish-language UI; hosted internal deployment with SSO.
- Trend views across non-overlapping 5-year vintages.

## 13. Review outcome (2026-11-09)
The owner reviewed the draft and approved:
1. the vertical list (§5.1), including the two added verticals;
2. the restricted characteristic list (Appendix B) and D4 (restricted mode blocks selection by
   every metric), with counsel review still required before wide internal use (§5.7);
3. the variable list (§4.2, Appendix C) **with one change: race (B02001) is added**, as context
   tagged `race_color` (D5 amended); disability and veteran status stay out; GeoNames city names
   stay in;
4. the self-contained printable HTML summary report (D3);
5. the ZIP-list export without a footer, with the attestation beside it and in the CSV and report;
6. the 1,000-ZIP maximum (D1), CV thresholds 15/30 and small-population thresholds (D2), and the
   preset thresholds (Appendix D).

## Appendix A: glossary
- **ZCTA:** ZIP Code Tabulation Area (§3.1). **ACS:** American Community Survey.
- **MOE:** margin of error at 90 % confidence, as published. **SE** = MOE / 1.645.
- **CV:** coefficient of variation = SE / estimate. **Index:** 100 × trade area / benchmark.
- **Trade area:** the set of recognized input ZIPs (overlap-weighted when from Zipcator).
- **Restricted mode:** §5.7.

## Appendix B: protected and proxy characteristics (restricted tags)

The union across the Fair Housing Act, the Equal Credit Opportunity Act, Title VII / ADEA / ADA /
GINA / USERRA (employment), and state unfair-discrimination rules for insurance, plus the brief's
proxies. Tags drive labels and the restricted-lens rules; D4 blocks selection by **all** metrics
regardless.

| Tag | Covers | Zipographics metrics tagged |
|---|---|---|
| `race_color` | race, color | race shares (B02001) |
| `national_origin` | national origin, ancestry, Hispanic origin, language spoken at home | Hispanic share, Spanish-at-home share, limited-English share |
| `religion` | religion | (none) |
| `sex` | sex, gender identity, sexual orientation | (none; B01001 is summed over sex) |
| `familial_status` | children present, household/family type, children's ages | households with children, children under 5, school-age share, working parents of young children |
| `age` | age | all age bands, median age, seniors share |
| `disability` | disability | (none in v1, D5) |
| `marital_status` | marital status | (none) |
| `public_assistance` | receipt of public assistance income | (none; poverty rate tagged `income` instead) |
| `military` | veteran or military status | (none in v1, D5) |
| `genetic` | genetic information | (none) |
| `income` (proxy) | income, poverty, wealth stand-ins | all income metrics, poverty rate, per-capita and mean income |
| `proxy_other` | measures that track the above at ZIP level | tenure, home value, rent, education, vehicles, commute, internet, new movers, housing age, units in structure |
| (untagged) | totals | population, households, housing units, vacancy |

## Appendix C: v1 metrics

Kinds: C count, S share, M median, A mean/ratio. Universe in parentheses.

| ID | Metric | Kind | Source | Tag |
|---|---|---|---|---|
| `pop` | Population | C | B01003 | — |
| `hh` | Households | C | B11001 | — |
| `units` | Housing units | C | B25001 | — |
| `vacancy` | Vacancy rate (units) | S | B25002 | — |
| `age_0_17`, `age_18_24`, `age_25_34`, `age_35_44`, `age_45_54`, `age_55_64`, `age_65_74`, `age_75p` | Age bands (pop) | S | B01001 | age |
| `age_18_34`, `age_18_44`, `age_65p` | Derived age groups (pop) | S | B01001 | age |
| `age_0_4`, `age_5_17` | Children under 5; school-age (pop) | S | B01001 | familial_status |
| `median_age` | Median age | M | B01002 / B01001 | age |
| `hh_kids` | Households with people under 18 (hh) | S | B11005 | familial_status |
| `working_parents_u6` | Own children under 6 with all parents in the labor force (own children under 6) | S | DP03 (by label) | familial_status |
| `inc_lt25`, `inc_25_50`, `inc_50_75`, `inc_75_100`, `inc_100_150`, `inc_150_200`, `inc_200p` | Household income bands (hh) | S | B19001 | income |
| `inc_75p`, `inc_100p`, `inc_150p` | Derived income shares (hh) | S | B19001 | income |
| `median_hh_income` | Median household income | M | B19013 / B19001 | income |
| `mean_hh_income` | Mean household income | A | B19025 / B11001 | income |
| `per_capita_income` | Per capita income | A | B19301 × B01003 | income |
| `poverty` | Below poverty (pop for whom determined) | S | B17001 | income |
| `owner`, `renter` | Owner- / renter-occupied (occupied units) | S | B25003 | proxy_other |
| `median_value` | Median home value (owner units) | M | B25077 / B25075 | proxy_other |
| `median_rent` | Median gross rent (renter units paying cash rent) | M | B25064 / B25063 | proxy_other |
| `built_2010p`, `built_1980_2009`, `built_1960_1979`, `built_pre1960`, `built_pre1980` | Housing age (units) | S | B25034 | proxy_other |
| `median_year_built` | Median year built | M | B25035 / B25034 | proxy_other |
| `single_family`, `mobile_home` | 1-unit detached + attached; mobile homes (units) | S | B25024 | proxy_other |
| `new_movers` | Householder moved in during the most recent category, e.g., "2021 or later" (occupied units) | S | B25038 (by label) | proxy_other |
| `veh_per_hh`, `veh_0`, `veh_2p` | Vehicles per household; no vehicle; 2+ vehicles (hh) | A/S | B25046 or B25044 | proxy_other |
| `commute_drive_alone`, `commute_carpool`, `commute_transit`, `commute_walk_bike`, `wfh` | Means of transportation (workers 16+) | S | B08301 | proxy_other |
| `commute_30p` | Commute 30+ minutes (workers who commute) | S | B08303 | proxy_other |
| `lfpr`, `unemployment` | Labor force participation (pop 16+); unemployment (civilian labor force) | S | B23025 | proxy_other |
| `hs_plus`, `ba_plus`, `grad` | Education (pop 25+) | S | B15003 | proxy_other |
| `spanish_home`, `limited_english` | Spanish at home; speaks English less than "very well" (pop 5+) | S | C16001 | national_origin |
| `hispanic` | Hispanic or Latino (pop) | S | B03003 | national_origin |
| `race_white`, `race_black`, `race_aian`, `race_asian`, `race_nhpi`, `race_other`, `race_two_plus` | One race alone (White; Black or African American; American Indian and Alaska Native; Asian; Native Hawaiian and Other Pacific Islander; Some other race) and two or more races (pop). Shares sum to 100 %; Hispanic origin is separate | S | B02001 | race_color |
| `broadband`, `no_internet` | Broadband of any type; no internet (hh) | S | B28002 | proxy_other |
| `uninsured` | No health insurance (civilian noninstitutionalized pop) | S | DP03 (by label) | proxy_other |

## Appendix D: lenses and presets

Every lens starts with the five core KPI cards (§5.5) and the four core charts. Presets are
starting points; the user edits rules after applying one. Thresholds live in `lenses.py`.

| Lens | Extra KPI cards | Extra charts | Presets |
|---|---|---|---|
| Home services | single-family, built before 1980, median home value | units in structure | Home services, Affluent homeowners, New movers |
| Lawn & outdoor | single-family, median home value, $100k+ | units in structure | Affluent homeowners, Home services |
| Movers | new movers, renters, households | tenure by move-in (bars) | New movers, Renters |
| Restaurants | median age, 18-34, work from home, drive alone | commute mode | Young adults, Families, Commuters |
| Retail | median age, $75k+, mean household income | — | Families, Premium, Young adults |
| Auto sales | vehicles per household, 2+ vehicles, drive alone | vehicles available | Commuters, Premium |
| Auto service | vehicles per household, drive alone, commute 30+ min | commute mode | Commuters |
| Health | 65+, median age, uninsured | — | Seniors, Families |
| Dental | households with children, school-age, $75k+ | — | Families, Premium |
| Pets | single-family, $75k+ | — | Affluent homeowners, Home services |
| Fitness | 18-44, renters, $75k+ | — | Young adults, Renters |
| Salon | median age, $75k+, households | — | Premium, Young adults |
| Childcare | children under 5, working parents, households with children | — | Young children, Families |
| Schools | school-age, households with children, $100k+, bachelor's+ | — | Families, Premium |
| Higher ed | 18-34, unemployment, bachelor's+ | education | Young adults |
| Hospitality | 25-44 (25-34 + 35-44), $100k+, median age | — | Premium, Young adults |
| B2B | work from home, bachelor's+, labor force participation | commute mode | (none until business counts) |
| General | median age, mean household income | — | Families, Premium, Seniors |
| Context (restricted) | housing units, vacancy, renters | — | none (restricted) |

| Preset | Rules (AND) |
|---|---|
| Home services | owner ≥ 60 %; built before 1980 ≥ 40 %; $75k+ ≥ 40 % |
| Affluent homeowners | owner ≥ 70 %; median home value index ≥ 120 |
| New movers | new movers index ≥ 120 |
| Renters | renter ≥ 50 % |
| Families | households with children index ≥ 115 |
| Young children | children under 5 index ≥ 115 |
| Premium | $150k+ ≥ 25 % |
| Young adults | 18-34 index ≥ 120 |
| Seniors | 65+ index ≥ 120 |
| Commuters | drive alone ≥ 75 %; commute 30+ min index ≥ 110 |
| Spanish-language households | Spanish at home ≥ 25 % (offered in Retail, Restaurants, Health, General) |

No preset or lens KPI uses a race metric (a unit test enforces it). Race metrics appear as table
columns (via the column picker), in the "More demographics" chart, and in exports.
