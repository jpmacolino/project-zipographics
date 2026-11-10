# Claude Code handoff: build Zipographics

This file is the prompt for the Claude Code session that builds Zipographics. The owner starts
Claude Code in the project folder and gives it this file (for example: "Read
docs/CLAUDE_CODE_HANDOFF.md and follow it").

**How the owner starts the session** (Windows, PowerShell):

```powershell
cd C:\dev\project-zipographics
claude --add-dir C:\dev\project-zipcator
```

`--add-dir` gives the session read access to the Zipcator repo, which Phase 1 needs to generate
the import-contract fixtures with Zipcator's real exporter. The main build must not modify
anything in the Zipcator repo (Task B below is a separate session).

---

## Task A: build Zipographics

You are building **Zipographics**, a local-first Python + Streamlit app: a user picks a client
industry, answers one restricted-use question, and enters a set of US ZIP codes (typed, pasted,
or a Zipcator CSV export); the app shows a demographic profile of those ZIPs from Census ACS
5-year data as an interactive dashboard with exports. The full specification is
`docs/SPEC.md` (**approved for build, v1.0**).

### 1. Read first, in full, before writing any code
1. `CLAUDE.md`: conventions, commands, git rules, and the secret-handling rules.
2. `docs/SPEC.md`: the source of truth. §11 is the phased plan; §9 is the test plan; §5.7 is
   restricted mode; §4.5 is API key handling.
3. `docs/DECISIONS.md`: facts verified during scoping (V1-V13) and design decisions (D1-D7),
   including the owner's review (race, B02001, was added; D5 amended).
4. `docs/QA_REPORT.md`, `.claude/agents/qa-reviewer.md`, `.claude/commands/qa-review.md`.

When the spec is ambiguous or wrong, make a reasonable call, log it in `docs/DECISIONS.md`, and
keep going. When an official source conflicts with the spec, follow the official source, log the
conflict, and tell the owner at the next STOP.

### 2. Hard rules (no exceptions)
- **Never read, open, print, copy, grep, edit, write, move, or delete `.env` or any `.env.*`
  file**, by any means: file tools, shell (`cat`, `type`, `Get-Content`, `more`, editors), Python,
  or git. This includes checking whether the key is "there". `.claude/settings.json` denies some
  of this, but those rules are one layer only; following this rule is what counts.
- **Never print, log, or display the Census API key** or any URL containing `key=`. Use made-up
  fake keys in tests and probes (e.g., `0123456789abcdef0123456789abcdef01234567`).
- **The owner pastes the Census API key into `.env` themselves**, before the real data build.
  Until Phase 3 ends you don't need it: all tests use recorded fixtures and mocked HTTP. At the
  end of Phase 3, STOP and ask the owner to paste the key and tell you when it's done.
- The only way to learn whether the key works is to run the build (or a `network` test) and read
  its redacted message: exit code 3 means missing or rejected key; exit code 4 means a network
  problem.
- Never `git add -f`, never set git identity, never push, add remotes, or create the GitHub repo.
- ZIPs are 5-character strings everywhere. Restricted mode is enforced in the library.

### 3. What already exists (scaffolded during scoping; don't recreate it)
`pyproject.toml` (deps, dev and `visual` groups, pytest markers, ruff, mypy, coverage ≥ 90 %),
`uv.lock`, `.python-version` (3.12), `src/zipographics/__init__.py` (`__version__`), `py.typed`,
`tests/conftest.py` (blocks non-loopback network in non-`network` tests), two smoke tests,
`scripts/check.py` (ruff, format, mypy, pytest + coverage, 1 MB gate, secrets gate),
`.github/workflows/ci.yml` (ubuntu + windows × 3.11 + 3.12), `.gitignore`, `.gitattributes`,
`.env.example`, `.claude/settings.json`, `.claude/agents/qa-reviewer.md`,
`.claude/commands/qa-review.md`, `CLAUDE.md`, `README.md` (stub), `LICENSE` (MIT),
`data/README.md`, `docs/`. The repo is on `main` with the owner's initial commit of the
scaffold. The approved spec, the amended DECISIONS.md and this handoff may still be
uncommitted; Phase 0 commits them.
Verified during scoping (Linux, scratch copy): `uv sync`, `uv run pytest` (2 passed), ruff, ruff
format check, mypy and `scripts/check.py` all pass. Not yet verified on Windows.

### 4. How to work
Follow `CLAUDE.md` "How to work" and the phases in SPEC §11, in order:
- Test-first for library code; run `uv run python scripts/check.py` after every meaningful change.
- Small Conventional Commits that reference SPEC sections; red test-first commits say so.
- Log every bug in `docs/QA_REPORT.md` with a regression test; log decisions in
  `docs/DECISIONS.md`.
- **End of every phase:** all gates green → `/qa-review <N>` (the `qa-reviewer` subagent, fresh
  context) → triage every finding (fix with a test, or record why it's deferred) → commit →
  `git tag phase-N`. Any restricted-mode bypass, key leak or lost leading zero is HIGH and blocks
  the phase.
- Keep a task list so the owner can see progress.

### 5. Phases and STOP points (SPEC §11)
At each **STOP**, give the owner a short report: what was done, gate results (tests, coverage),
QA-review findings and how each was handled, decisions and official-source conflicts logged, and
exactly what you need from them. Then wait.

| Phase | Scope | Stop? |
|---|---|---|
| 0 | `uv sync` on Windows; run `scripts/check.py`; check `git config user.name` / `user.email` (if either is empty, **STOP and ask**; never set them); commit any uncommitted docs (`docs: approved spec v1.0 and Claude Code handoff`); confirm CI config | Only if git identity is missing |
| 1 | `zips`, `importer`, Zipcator contract (§5.3), `review`, on synthetic data. Generate the contract fixtures (§6 below) | No |
| 2 | `stats`, sentinel transforms, `metrics` registry, `profile` (aggregation, overlap weighting, benchmark, index). Quote each formula from the official document in DECISIONS.md before implementing (SPEC §6) | No |
| 3 | `redact`, `census_api`, `data_build`, `scripts/build_data.py`, on recorded fixtures with fake keys; missing-key, rejected-key and network messages; redaction tests | **STOP:** ask the owner to paste their Census API key into `.env` (see `.env.example`) and reply when done |
| 4 | Real data build (`uv run python scripts/build_data.py`). Verify: the **5-year** annotation page, label resolution, per-variable ZCTA coverage, top-code cross-check, **B25046 and B02001 availability at ZCTA level**, that 33601 is not a ZCTA; run the `network` tests once; update DECISIONS | **STOP:** report coverage gaps, the final metric list, artifact sizes, and any official-source conflicts; wait for the owner's OK |
| 5 | `verticals`, `restricted`, `lenses` and presets, `filters` (policy-enforced), `export` (ZIP lists, CSV, attestation), `report`, `cli` | No |
| 6 | Streamlit app (four steps), charts, map; AppTest suite; visual QA with Playwright; **open and look at** the screenshots | **STOP:** the owner tries the app and reviews screenshots and a sample report. Ask the owner to open the "CSV for Excel" export in Excel and confirm the leading zeros, and (optionally) to re-save a Zipcator export in Excel and send it as an extra fixture |
| 7 | Golden scenarios (§9.4) verified independently against data.census.gov or by hand, benchmarks, README, final QA review, polish | **STOP:** final report against SPEC §10 |

### 6. Phase 1 detail: Zipcator contract fixtures
The import contract (SPEC §5.3) was read from Zipcator's `src/zipcator/export.py` at commit
`6d9ad8a`. Generate the fixtures with Zipcator's **real** CLI (its data is already built; use
coordinates so no geocoding call is needed), running it from the Zipcator folder without changing
anything there:

```powershell
New-Item -ItemType Directory -Force C:\dev\project-zipographics\tests\fixtures\zipcator
cd C:\dev\project-zipcator
uv run zipcator "27.9506, -82.4572" --radius 5 --csv ..\project-zipographics\tests\fixtures\zipcator\tampa_5mi.csv
uv run zipcator "27.9506, -82.4572" --radius 5 --csv ..\project-zipographics\tests\fixtures\zipcator\tampa_5mi_excel.csv --excel
uv run zipcator "42.3588, -71.0578" --radius 3 --csv ..\project-zipographics\tests\fixtures\zipcator\boston_3mi.csv
uv run zipcator "42.3588, -71.0578" --radius 3 --csv ..\project-zipographics\tests\fixtures\zipcator\boston_3mi_excel.csv --excel
```

(Check `uv run zipcator --help` first; if the CLI or its data doesn't work, STOP and ask the
owner rather than hand-writing "Zipcator" files.) Then derive, with a small committed script
(`tests/fixtures/zipcator/make_variants.py`), simulations of what Excel does on re-save:
leading zeros stripped from the plain file, cp1252 encoding with no BOM, `="02108"` cells
re-saved as `02108`, plus a snake_case-header file. Write `tests/fixtures/zipcator/README.md`
recording the Zipcator commit, the exact commands, and which files are real exports versus
simulated re-saves. Zipcator's current build has no population data, so its exports lack the
`Population` / `Est. pop in radius` columns; cover the with-population shape with a variant made
by Zipcator's own `zipcator.export.to_csv` on a result that has population, if that is easy from
Zipcator's test helpers, or else a clearly labeled synthetic file. Keep every fixture tiny.

### 7. Items carried over from scoping (verify; log results in DECISIONS.md)
- The 2021-2025 ACS 5-year release date was TBD on 2026-11-09 (V1). Build with `--vintage 2024`
  unless a newer vintage is published by then; if so, tell the owner at the Phase 4 STOP.
- The **5-year** annotation-values page (only the 1-year page was read; V6).
- Top/bottom-code values (V7): detect from annotations; log the cross-check.
- The handbook formulas (V9) and the median method and median-MOE derivation (V8, SPEC §6.4):
  quote the official text before implementing.
- Meta's Special Ad Categories rules came from secondary sources (V10). Don't build anything
  that depends on Meta specifics beyond the notice text in SPEC §5.7.
- `api.census.gov` was blocked by a proxy in the scoping sandbox (V13). On the owner's Windows
  machine it should work; if the build reports a proxy/403 error, report it at the STOP instead
  of retrying in loops.

### 8. Done means
SPEC §10 acceptance criteria all met; the final `/qa-review` has no unresolved HIGH or MEDIUM
findings; `docs/QA_REPORT.md` summarizes test counts per layer, coverage, bugs found and fixed,
and the golden-scenario verification; README complete; everything committed and tagged
(`phase-0` … `phase-7`), nothing pushed.

---

## Task B (separate follow-up): Zipcator export-contract test

**Run this as its own Claude Code session in the Zipcator repo**, after Task A's Phase 1 has
committed the fixtures (so both repos test against the same files):

```powershell
cd C:\dev\project-zipcator
claude --add-dir C:\dev\project-zipographics
```

Prompt for that session:

> Read `CLAUDE.md` and `docs/SPEC.md` in this repo and follow their conventions (tests, gates,
> commits; don't push). Zipographics (in `C:\dev\project-zipographics`) imports Zipcator's CSV
> exports under a written contract, "zipcator-export v1", in its `docs/SPEC.md` §5.3. Add a
> contract test so any change to Zipcator's export format fails here first:
> 1. Copy the **real-export** fixtures from
>    `C:\dev\project-zipographics\tests\fixtures\zipcator\` (`tampa_5mi.csv`,
>    `tampa_5mi_excel.csv`, `boston_3mi.csv`, `boston_3mi_excel.csv` and its README) into
>    `tests/fixtures/export_contract/` here. Don't copy the simulated Excel re-saves.
> 2. Add `tests/unit/test_export_contract.py` that pins, with a comment naming
>    "zipcator-export v1" and pointing to the Zipographics spec section:
>    - the exact header tuple (`ZIP, City, County, State, Overlap %, Area in radius (sq mi),
>      ZIP area (sq mi), Nearest distance (mi), Center distance (mi), Contains address`, plus
>      `Population, Est. pop in radius` when population exists), built from
>      `export.TABLE_COLUMNS`/`result_table(full=True)` on a synthetic result, and compared with
>      the fixtures' header rows;
>    - plain format: no BOM, CRLF, ZIP quoted as 5-digit text, `Overlap %` numeric in (0, 100],
>      `Contains address` in {Yes, No};
>    - Excel-safe format: UTF-8 BOM, ZIP cells exactly `="NNNNN"`, otherwise identical columns;
>    - regenerating the Tampa export from the current code (`data`-marked test, since it needs
>      `data/zcta.parquet`) reproduces the fixture's header and ZIP set.
> 3. Don't change Zipcator's export behavior. If the test reveals a mismatch with the contract,
>    stop and tell the owner instead of "fixing" either side.
> 4. Add a short DECISIONS.md entry ("Export format is a contract with Zipographics; changing
>    it needs a coordinated change in both repos") and a README note under the CSV export
>    section. Run the gates, commit, and report.
