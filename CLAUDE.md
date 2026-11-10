# Zipographics: instructions for Claude Code

Zipographics: give it a set of US ZIP codes (typed, pasted, or a Zipcator CSV export) and it shows
a demographic profile of those ZIPs (Census ZCTAs) from ACS 5-year data, as an interactive
dashboard an account team can filter, sort, title and export for clients. Python + Streamlit,
local-first, MIT-licensed, public GitHub repo.

**The spec is the source of truth: read `docs/SPEC.md` in full before writing code.** If the spec
is ambiguous or wrong, make a reasonable call, record it in `docs/DECISIONS.md` (date, decision,
why, alternatives), and keep going. Stop and ask the user only at the phase boundaries the spec
defines (SPEC §11) and for things that are irreversible or outside the repo (pushing to GitHub,
changing the license, adding a paid service, anything involving `.env`).

## Secrets: the Census API key (read this first)

The data build calls the Census Data API, which requires a free key. The key lives in `.env` as
`CENSUS_API_KEY=...`. The user pastes it there themselves.

- **Never read, open, print, copy, edit, write, move, or delete `.env` or any `.env.*` file**,
  by any tool or command (file tools, shell, Python, PowerShell, grep, editors, git). If you need
  to know whether the key is set, run the build or a `network` test and read its (redacted)
  message. If `.env.example` ever needs a change, ask the user.
- **Never print, log, echo, or display the key** or any part of it, and never put it in a file,
  test fixture, commit, cache file name, metadata, or error message.
- The key is sent as a URL query parameter (`key=...`). Every URL that carries it is a secret.
  The HTTP layer **redacts `key=...`** (and the literal key value) from every log line, exception
  message, progress line and cached-file name, and raises its own sanitized errors (`from None`)
  so tracebacks never include the original request URL. Redaction has unit tests; keep them green.
- Only the data build needs the key. The Streamlit app never loads `.env` and never calls the
  Census API (or any other network service) at runtime.
- Never `git add -f` anything; `.env` and `.env.*` (except `.env.example`) are gitignored, and
  `scripts/check.py` fails if one is tracked.
- **The deny rules in `.claude/settings.json` are one layer only.** There are reported cases of
  permission rules not being enforced, and shell commands can't be fully pattern-blocked (another
  program, an absolute path, `python -c`, or a script that opens files itself all get past a
  `Bash(...)` pattern; the official docs say Bash rules are "not a security boundary"). The real
  protections are: the code reads the key from the environment only; nothing ever needs to
  display it; logs and errors are redacted and tested; and you follow the rules above.

## Environment
- Primary machine is **Windows**. Use `uv` for everything (install it if missing:
  `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`). `.python-version` = 3.12;
  CI also runs 3.11.
- Use `pathlib` everywhere; never hard-code `/` or `\` separators.
- Commands:
  - setup: `uv sync`
  - tests (default, fast, no network, no real data): `uv run pytest`
  - with coverage: `uv run pytest --cov=zipographics --cov-report=term-missing`
  - data tests (after the data build): `uv run pytest -m data`
  - live Census API tests (need the key; run manually, sparingly): `uv run pytest -m network`
  - benchmarks: `uv run pytest -m slow`
  - visual QA (one-time setup: `uv sync --group visual` then
    `uv run playwright install chromium`): `uv run pytest -m visual`
  - lint/format: `uv run ruff check . --fix` and `uv run ruff format .`
  - types: `uv run mypy`
  - build data: `uv run python scripts/build_data.py [--refresh] [--vintage 2024]`
  - app: `uv run streamlit run app/streamlit_app.py`
  - all gates at once: `uv run python scripts/check.py`
- Network is needed only for `uv sync`, the data build, and `network` tests.

## Test markers
| marker | what | runs by default |
|---|---|---|
| (none) | unit, property (`hypothesis`), UI (`streamlit.testing.v1.AppTest`) | yes |
| `data` | needs the built files in `data/` | no |
| `network` | calls the real Census API (needs the key) | no |
| `slow` | performance benchmarks | no |
| `visual` | Playwright screenshots of the running app | no |

`tests/conftest.py` blocks non-loopback network connections in every test not marked `network`.
Don't weaken that guard. Mock HTTP with `responses`; inject clocks/sleepers instead of sleeping.

## How to work
1. **Follow the phases in SPEC §11 in order** and stop where the spec says to stop. Track progress
   in your task list. Don't start a phase until the previous phase's exit criteria pass.
2. **Test-first for library code** (`src/zipographics`): write the failing tests from SPEC §9,
   watch them fail for the right reason, then implement.
3. **Run the gates after every meaningful change**: `uv run python scripts/check.py` (ruff,
   format check, mypy, pytest + coverage >= 90 %, file-size and secrets gates).
4. **Never weaken a test to make it pass.** If a test is wrong, say why in the commit message or
   QA report, then fix it. No `skip`/`xfail` without a logged reason.
5. **Log bugs in `docs/QA_REPORT.md`** (symptom, root cause, fix, regression test name). Every bug
   fix gets a regression test.
6. **Log decisions in `docs/DECISIONS.md`** (date, decision, why, alternatives, source URL when a
   fact was verified). When an official source conflicts with the spec, follow the official
   source, log the conflict, and tell the user at the next stop.
7. **Golden-scenario expectations are verified independently** against data.census.gov or by hand
   calculation (SPEC §9.4); never snapshot the code's first output and call it correct.
8. **Look at the app.** For UI work, run the visual QA tests and open the screenshots in
   `qa/screenshots/` before calling a UI phase done.
9. **End of each phase:** run all gates, then `/qa-review <phase>` (uses the `qa-reviewer`
   subagent in `.claude/agents/`). Triage every finding: fix it with a test, or record why it's
   deferred. Commit, then `git tag phase-N`.
10. **Git:** before the first commit, check `git config user.name` and `git config user.email`; if
    either is empty, stop and ask the user; never set git identity yourself. Small commits with
    Conventional Commit messages (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`,
    `build:`) that reference the SPEC section. Red test-first commits must say so. Never commit
    `data/` contents (except `data/README.md`), `qa/screenshots/`, `.env*` (except
    `.env.example`), or files over 1 MB. Never amend or rewrite pushed history; never force.
    **Do not push, add remotes, or create the GitHub repo**: the user does that.
11. Keep `app/streamlit_app.py` to layout and wiring; all logic goes in `src/zipographics`.

## Conventions
- **ZIPs are always 5-character strings** (`"02108"`, `"00601"`), never ints: in parsing, pandas
  dtypes (`string`/`object`, never numeric), parquet schemas, CSV output, tests and fixtures.
  Read every CSV with `dtype=str`.
- **ACS sentinel values** (-666666666, -999999999, -888888888, -222222222, -333333333,
  -555555555) become nulls at build time, never numbers. Never average or sum medians.
- **Restricted mode is enforced in the library**, not just hidden in the UI (SPEC §5.7). Any
  function that ranks, filters, selects or exports a demographically chosen subset must refuse
  when restricted mode is on, and has a test proving it.
- Library code uses `logging`, not `print` (the build script's progress output goes through a
  logger whose handlers redact). Type-hint all public functions.
- "ZIP" means Census ZIP Code Tabulation Area; say so wherever users see ZIPs.

## Done means
SPEC §10 acceptance criteria all met, the final `/qa-review` has no unresolved high/medium
findings, and `docs/QA_REPORT.md` summarizes test counts, coverage, bugs found/fixed and the
golden-scenario verification.
