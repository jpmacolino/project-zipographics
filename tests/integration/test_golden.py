"""The eight golden scenarios (SPEC 9.4; marker ``data``), verified independently of the code.

Expected values come from ``oracle`` (the raw Census API responses re-parsed by its own code, and
the relationship file) plus arithmetic written out here; nothing is a snapshot of the app's
output. ``-s`` prints each worked table (they are copied into docs/QA_REPORT.md).
"""

from __future__ import annotations

import csv
import io
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest
from integration import oracle as o

from zipographics import analysis, config, data, export, filters, importer, review, table, verticals
from zipographics.errors import RestrictedUseError
from zipographics.models import Rule
from zipographics.zips import parse_paste

pytestmark = pytest.mark.data
ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "zipcator"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
HOME = verticals.make_policy("Home services (HVAC, plumbing, roofing, pest, remodeling)", False)
MORTGAGE = verticals.make_policy("Mortgage & lending", None)
AUTO_YES = verticals.make_policy("Automotive sales", True)

if not (config.data_dir() / "zcta_profile.parquet").exists():  # pragma: no cover
    pytest.skip("data/ has not been built", allow_module_level=True)


@pytest.fixture(scope="module")
def art() -> data.Artifacts:
    return data.load(config.data_dir())


def say(capsys: pytest.CaptureFixture[str], *lines: str) -> None:
    with capsys.disabled():
        print("\n" + "\n".join(lines))


def zipcator_rows(path: Path) -> list[tuple[str, float]]:
    """(ZIP, overlap %) from a Zipcator export, parsed here with the csv module only."""
    text = path.read_bytes().decode("utf-8-sig")
    delimiter = ";" if text.splitlines()[0].count(";") > 3 else ","
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    head = [h.strip().lower() for h in rows[0]]
    zi, oi = head.index("zip"), head.index("overlap %")
    return [
        (r[zi].replace('="', "").replace('"', "").zfill(5), float(r[oi])) for r in rows[1:] if r
    ]


# ------------------------------------------------------------------------------------ 1 Tampa
def test_golden_1_tampa_zipcator_export(
    art: data.Artifacts, capsys: pytest.CaptureFixture[str]
) -> None:
    results = []
    for name in ("tampa_5mi.csv", "tampa_5mi_excel.csv", "tampa_5mi_semicolon.csv"):
        rows = zipcator_rows(FIX / name)
        zips = [z for z, _ in rows if o.present(z)]
        w = {z: pct / 100 for z, pct in rows if o.present(z)}
        a = analysis.analyze(art, importer.import_csv((FIX / name).read_bytes()), HOME)
        assert list(a.zips) == zips and a.mode == "in_radius" and len(zips) == len(rows)

        # in-radius households = sum of households x overlap, by hand from B11001_001
        hh = sum(o.get("zcta", z, "B11001_001")[0] * w[z] for z in zips)
        assert a.trade.values["hh"].estimate == pytest.approx(hh, rel=1e-9)
        hh_moe = o.sum_moe([o.get("zcta", z, "B11001_001")[1] * w[z] for z in zips])
        assert a.trade.values["hh"].moe == pytest.approx(hh_moe, rel=1e-9)

        # median household income: interpolated by hand from the overlap-weighted sum of B19001
        counts = [
            sum(o.get("zcta", z, f"B19001_{k:03d}")[0] * w[z] for z in zips) for k in range(2, 18)
        ]
        median = o.interpolated_median(counts, o.B19001)
        assert a.trade.values["median_hh_income"].estimate == pytest.approx(median, rel=1e-6)

        # owner share, the Florida benchmark and one index
        own = sum(o.get("zcta", z, "B25003_002")[0] * w[z] for z in zips)
        occ = sum(o.get("zcta", z, "B25003_001")[0] * w[z] for z in zips)
        fl = o.get("state", "12", "B25003_002")[0] / o.get("state", "12", "B25003_001")[0]
        assert a.trade.values["owner"].estimate == pytest.approx(own / occ, rel=1e-9)
        assert (a.benchmark.name, a.bench.values["owner"].estimate) == (
            "Florida",
            pytest.approx(fl, rel=1e-9),
        )
        assert a.index["owner"].value == o.round_half_up(100 * (own / occ) / fl)
        assert a.bench.values["median_hh_income"].estimate == o.get("state", "12", "B19013_001")[0]
        results.append((len(zips), hh, median, own / occ, fl, a.index["owner"].value))
    assert len({r for r in results}) == 1  # plain, Excel-safe and semicolon files agree exactly
    n, hh, median, share, fl, idx = results[0]
    say(capsys, "GOLDEN 1 Tampa 5 mi (three file variants identical)",
        f"  ZIPs {n}; in-radius households = sum(hh x overlap) = {hh:,.1f}",
        f"  trade-area median household income (B19001 interpolated) = ${median:,.0f}",
        f"  owner share {share:.4f} vs Florida {fl:.4f} -> index {idx}")  # fmt: skip


# ------------------------------------------------------------------------------------ 2 Boston
BOSTON = ["02108", "02109", "02110", "02111", "02113", "02114", "02115", "02116"]


def test_golden_2_boston_leading_zeros(
    art: data.Artifacts, capsys: pytest.CaptureFixture[str]
) -> None:
    crlf = chr(13) + chr(10)
    resaved = (crlf.join(["ZIP", *[z.lstrip("0") for z in BOSTON]]) + crlf).encode("cp1252")
    inputs = {
        "correct paste": parse_paste(", ".join(BOSTON)),
        "Excel-mangled paste": parse_paste(", ".join(z.lstrip("0") for z in BOSTON)),
        "Excel-re-saved CSV (zeros stripped, cp1252)": importer.import_csv(resaved),
    }
    runs = {k: analysis.analyze(art, v, HOME) for k, v in inputs.items()}
    pop = sum(o.get("zcta", z, "B01003_001")[0] for z in BOSTON)
    ma_owner = o.get("state", "25", "B25003_002")[0] / o.get("state", "25", "B25003_001")[0]
    values = []
    for name, a in runs.items():
        assert list(a.zips) == BOSTON, name
        assert a.trade.values["pop"].estimate == pytest.approx(pop, rel=1e-12)
        assert a.benchmark.name == "Massachusetts"
        assert a.bench.values["owner"].estimate == pytest.approx(ma_owner, rel=1e-9)
        values.append({k: (v.estimate, v.moe) for k, v in a.trade.values.items()})
    assert values[0] == values[1] == values[2]  # identical results from all three inputs
    assert [len(a.summary.repaired) for a in runs.values()] == [0, 8, 8]
    assert [t.zip for t in runs["Excel-mangled paste"].summary.repaired] == BOSTON
    say(
        capsys,
        "GOLDEN 2 Boston 02108-02111, 02113-02116",
        f"  population = sum of B01003 = {pop:,.0f}; Massachusetts owner share {ma_owner:.4f}",
        "  repaired: correct paste 0, mangled 8, re-saved CSV 8; values identical",
    )


# ------------------------------------------------------------------------------------ 3 rural
def rural_zips() -> list[str]:
    """Seven Montana/Nebraska ZCTAs with population under 1,000: the four whose owner share has the
    largest coefficient of variation and the three with the smallest, chosen from the raw data."""
    scored = []
    for z, (county, _) in sorted(o.primary_county().items()):
        if county[:2] not in ("30", "31") or not o.present(z):
            continue
        pop = o.get("zcta", z, "B01003_001")[0]
        x, mx = o.get("zcta", z, "B25003_002")
        y, my = o.get("zcta", z, "B25003_001")
        if 150 <= pop < 900 and y >= 60 and not math.isnan(mx) and 0 < x < y:
            scored.append((o.cv_percent(x / y, o.share_moe(x, mx, y, my)), z))
    scored.sort()
    return [z for _, z in (*scored[-4:], *scored[:3])]


def test_golden_3_rural_small_populations(
    art: data.Artifacts, capsys: pytest.CaptureFixture[str]
) -> None:
    zips = rural_zips()
    assert len(zips) == 7
    a = analysis.analyze(art, parse_paste(" ".join(zips)), HOME)
    assert set(a.summary.small_population) == set(zips)  # all under 1,000 people
    view = table.build_view(a, None, metric_ids=["owner"], show_moe=True)
    shown = dict(zip(view.frame["ZIP"], view.frame["Homeowners"], strict=True))
    styles = dict(zip(view.frame["ZIP"], view.styles["Homeowners"], strict=True))
    lines = [
        "GOLDEN 3 rural small-population set (MT/NE)",
        "  ZIP    pop   CV(pop)  owner CV  tier",
    ]
    tiers = []
    for z in zips:
        pop, pop_moe = o.get("zcta", z, "B01003_001")
        x, mx = o.get("zcta", z, "B25003_002")
        y, my = o.get("zcta", z, "B25003_001")
        cv_pop, cv_own = o.cv_percent(pop, pop_moe), o.cv_percent(x / y, o.share_moe(x, mx, y, my))
        expected = o.tier(cv_own)
        assert a.value(z, "owner").tier == expected, (z, cv_own)
        assert a.value(z, "pop").tier == o.tier(cv_pop), z
        assert a.value(z, "owner").moe == pytest.approx(o.share_moe(x, mx, y, my), rel=1e-9)
        if expected == "unreliable":
            assert shown[z].endswith("\N{DAGGER}") and "italic" in styles[z]
        elif expected == "caution":
            assert shown[z].endswith("~") and styles[z]
        else:
            assert not shown[z].endswith(("\N{DAGGER}", "~")) and styles[z] == ""
        tiers.append(expected)
        lines.append(f"  {z} {pop:5.0f}  {cv_pop:6.1f}  {cv_own:7.1f}  {expected}")
    assert "unreliable" in tiers  # the point of the scenario: de-emphasized cells exist
    say(capsys, *lines)


# ------------------------------------------------------------------------------------ 4 Puerto Rico
def test_golden_4_puerto_rico(art: data.Artifacts, capsys: pytest.CaptureFixture[str]) -> None:
    parsed = parse_paste("601, 603, 610, 612")
    a = analysis.analyze(art, parsed, HOME)
    assert [t.zip for t in a.summary.repaired] == ["00601", "00603", "00610", "00612"]
    assert list(a.zips) == ["00601", "00603", "00610", "00612"]
    assert (a.benchmark.level, a.benchmark.geo_id, a.benchmark.name) == (
        "state",
        "72",
        "Puerto Rico",
    )
    pr = o.get("state", "72", "B25003_002")[0] / o.get("state", "72", "B25003_001")[0]
    assert a.bench.values["owner"].estimate == pytest.approx(pr, rel=1e-9)
    assert a.options.puerto_rico_note and "Puerto Rico" in a.options.puerto_rico_note
    assert a.options.us.name == "United States"
    # how the Data Profile items (DP03, V5) behave for PR ZCTAs: present in the ACS 5-year profile
    uninsured = [a.value(z, "uninsured").estimate for z in a.zips]
    say(
        capsys,
        "GOLDEN 4 Puerto Rico 601, 603, 610, 612 (repaired to 00601...)",
        f"  PR benchmark owner share {pr:.4f}; national-benchmark note shown",
        "  DP03 uninsured share for the four ZCTAs: "
        f"{[None if v is None else round(v, 3) for v in uninsured]}",
    )
    assert all(
        v is not None for v in uninsured
    )  # DP03 exists for Puerto Rico ZCTAs in this vintage


# ------------------------------------------------------------------ 5 / 6 restricted
TAMPA_ZIPS = [z for z, _ in zipcator_rows(FIX / "tampa_5mi.csv")]


def test_golden_5_restricted_vertical_blocks_every_selection_path(art: data.Artifacts) -> None:
    assert verticals.is_locked("Mortgage & lending") and MORTGAGE.answer == "Yes (set by industry)"
    a = analysis.analyze(art, parse_paste(" ".join(TAMPA_ZIPS)), MORTGAGE, project_name="Tampa")
    assert a.restricted
    for rule in (
        Rule("owner", ">=", 0.5),
        Rule("median_hh_income", ">=", 50_000),
        Rule("pop", ">=", 1),
    ):
        with pytest.raises(RestrictedUseError):
            filters.apply(a, [rule])
    for key in ("owner", "median_hh_income", "pop"):
        with pytest.raises(RestrictedUseError):
            table.order(a, key)
    assert export.zip_list(a, qualifying=("33602",)) == ", ".join(
        TAMPA_ZIPS
    )  # the input, unchanged
    text = export.csv_text(a, None, now=NOW, version="1")
    assert "Qualifies" not in text.splitlines()[0] and "index" not in text.splitlines()[0]
    assert "Note: Restricted mode: on" in text and "Note: Answer: Yes (set by industry)" in text
    from zipographics import lenses

    assert [x.name for x in lenses.available(MORTGAGE)] == ["Context"] and not lenses.presets_for(
        "Retail", MORTGAGE
    )


def test_golden_5_restricted_vertical_in_the_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    app = str(ROOT / "app" / "streamlit_app.py")
    at = AppTest.from_file(app, default_timeout=120).run()
    at.selectbox(key="industry_box").select("Mortgage & lending").run()
    radio = at.radio(key="locked_Mortgage & lending")
    assert radio.disabled and radio.value == "Yes"  # locked
    at.button(key="continue_1").click().run()
    at.text_area[0].input(" ".join(TAMPA_ZIPS)).run()
    at.button(key="next_2").click().run()
    at.button(key="next_3").click().run()
    assert not at.exception
    assert any("Restricted mode is on" in str(w.value) for w in at.warning)
    assert "add_rule" not in [b.key for b in at.button] and not [
        s for s in at.selectbox if s.key == "sort_by"
    ]
    assert any(
        ", ".join(TAMPA_ZIPS) == str(c.value) for c in at.code
    )  # the ZIP list equals the input


def test_golden_6_restricted_by_answer(art: data.Artifacts) -> None:
    a = analysis.analyze(art, parse_paste(" ".join(TAMPA_ZIPS)), AUTO_YES)
    assert a.restricted and AUTO_YES.answer == "Yes"  # answered, not forced
    lines = export.attestation(a, None, now=NOW, version="1")
    assert "Answer: Yes" in lines and "Answer: Yes (set by industry)" not in lines
    assert "Restricted mode: on" in lines and "Industry: Automotive sales" in lines
    assert export.zip_list(a) == ", ".join(TAMPA_ZIPS)


# ------------------------------------------------------------------------------------ 7 Kansas City
KC = ["66101", "66102", "66103", "64105", "64106", "64108", "64109"]


def test_golden_7_multi_state_default_benchmark(
    art: data.Artifacts, capsys: pytest.CaptureFixture[str]
) -> None:
    pop = {z: o.get("zcta", z, "B01003_001")[0] for z in KC}
    by_state: dict[str, float] = {}
    by_county: dict[str, float] = {}
    for z in KC:
        county = o.primary_county()[z][0]
        by_state[county[:2]] = by_state.get(county[:2], 0) + pop[z]
        by_county[county] = by_county.get(county, 0) + pop[z]
    top_state = max(by_state, key=lambda k: by_state[k])
    top_county = max(by_county, key=lambda k: by_county[k])
    a = analysis.analyze(art, parse_paste(" ".join(KC)), HOME)
    assert a.options.default.geo_id == top_state
    assert a.options.default_county is not None and a.options.default_county.geo_id == top_county
    names = {"20": "Kansas", "29": "Missouri"}
    msg = [x for x in review.review_lines(a.summary) if x.startswith("Your ZIPs are in")]
    assert msg and f"Benchmark: {names[top_state]}" in msg[0] and "KS and MO" in msg[0]
    county_name = next(n for c, n in o.primary_county().values() if c == top_county)
    by_name = {names[k]: round(v) for k, v in by_state.items()}
    say(
        capsys,
        "GOLDEN 7 Kansas City (66101-66103 KS, 64105-64109 MO)",
        f"  population by state (hand sum of B01003): {by_name}",
        f"  default benchmark = {names[top_state]}; default county = {top_county} ({county_name})",
    )


# ------------------------------------------------------------------------------------ 8 messy paste
def test_golden_8_messy_paste_counts(
    art: data.Artifacts, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "33602, 2108 ,33606-1234;\t02109\n33602 abc 12-34 1e5 33601 99999"
    # counted by hand: 33602 (valid), 2108 (repaired to 02108), 33606-1234 (truncated to 33606),
    # 02109 (valid), 33602 again (duplicate), abc / 12-34 / 1e5 (invalid), 33601 and 99999 (valid
    # format, no ZCTA: not found)
    assert not o.present("33601") and not o.present("99999")
    recognized = ["33602", "02108", "33606", "02109"]
    assert all(o.present(z) for z in recognized)
    small = [
        z
        for z in recognized
        if o.get("zcta", z, "B01003_001")[0] < 1000 or o.get("zcta", z, "B11001_001")[0] < 300
    ]
    a = analysis.analyze(art, parse_paste(text), HOME)
    s = a.summary
    assert s.entered == 6 and list(s.recognized) == recognized and s.not_found == ("33601", "99999")
    assert [t.zip for t in s.repaired] == ["02108"] and [t.zip for t in s.truncated] == ["33606"]
    assert list(s.invalid) == ["abc", "12-34", "1e5"] and s.duplicates == 1
    assert list(s.small_population) == small and s.states == ("FL", "MA")
    lines = review.review_lines(s)
    joined = "\n".join(lines)
    needles = [
        "4 ZIPs recognized", "2 not found (33601, 99999)", "1 repaired", "2108",
        "1 ZIP+4 truncated", "3 invalid entries: abc, 12-34, 1e5", "1 duplicate removed",
    ]  # fmt: skip
    for needle in needles:
        assert needle in joined, needle
    say(
        capsys,
        "GOLDEN 8 messy paste (hand count = review summary)",
        "  entered 6 distinct valid: recognized 4, not found 2 (33601, 99999), repaired 1, "
        "ZIP+4 1, invalid 3, duplicates 1",
        f"  small-population ZIPs (hand rule pop<1000 or hh<300): {small}",
    )
