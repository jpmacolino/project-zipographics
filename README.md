# Zipographics

Give Zipographics a set of US ZIP codes (typed, pasted from Excel, or a
[Zipcator](https://github.com/jpmacolino/project-zipcator) CSV export) and it shows a
**demographic profile of those ZIPs** from U.S. Census Bureau American Community Survey (ACS)
5-year data: KPI cards indexed against a state, county or national benchmark, a ranked and
filterable ZIP table, charts, a map, and exports an account team can share with clients.

> **Status:** pre-build. The specification is in [docs/SPEC.md](docs/SPEC.md).

> **"ZIP" here means a Census ZIP Code Tabulation Area (ZCTA).** PO-box-only and
> single-organization ZIP codes have no ZCTA and aren't included. ACS figures are survey
> estimates with margins of error, not exact counts.

## Setup

_Placeholder: filled in during the build._ Outline:

1. Install [`uv`](https://docs.astral.sh/uv/) and run `uv sync`.
2. Get a free Census Data API key (https://www.census.gov/data/developers/api-key.html), copy
   `.env.example` to `.env`, and paste the key after `CENSUS_API_KEY=`. The key is used **only**
   by the one-time data build; the app itself makes no Census API calls.
3. `uv run python scripts/build_data.py` (one-time data build).
4. `uv run streamlit run app/streamlit_app.py`.

## Restricted uses

Marketing for housing, jobs, credit or financing, or insurance must not target people by
protected characteristics or their proxies. Zipographics asks about this up front and, when it
applies, turns on a restricted mode that keeps the demographic profile visible as context but
blocks ranking, filtering, and selecting ZIPs by demographics. This is a guardrail, not legal
advice.

## Data sources and attribution

_Placeholder._ This product uses the Census Bureau Data API but is not endorsed or certified by
the Census Bureau. Sources: ACS 5-year estimates (vintage recorded in `data/metadata.json`);
Census 2020 ZCTA cartographic boundary file; Census 2020 ZCTA-to-county relationship file.

## License

MIT; see [LICENSE](LICENSE).
