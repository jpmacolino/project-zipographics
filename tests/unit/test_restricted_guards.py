"""Every guarded function, every restricted policy, every metric (SPEC 5.7, D4).

The policy lives on the Analysis (``Analysis.policy``); no guarded function takes a second one, so a
permissive policy can never be passed next to a restricted analysis. These tests pin that, and
check each guard against the three ways an analysis can be restricted: forced by the industry,
answered Yes, and (a caller bug) ``UsePolicy(False, <restricted industry>, "No")``.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import export, filters, lenses, metrics, report, restricted, table, verticals
from zipographics.errors import RestrictedUseError
from zipographics.models import Rule, UsePolicy
from zipographics.zips import parse_paste

OFF = verticals.make_policy("Retail (general & specialty)", False)
FORCED = verticals.make_policy("Insurance", None)
ANSWERED = verticals.make_policy("Automotive sales", True)
LIAR = UsePolicy(False, "Insurance", "No")  # a restricted industry with a permissive flag
RESTRICTED = {"forced": FORCED, "answered": ANSWERED, "liar": LIAR}
NOW = datetime(2026, 11, 10, 14, 30, tzinfo=UTC)

ART = make_artifacts(
    {
        "33602": Z(5000, 2000, owner=0.40, kids=0.20),
        "33606": Z(8000, 3500, owner=0.70, kids=0.35),
        "33603": Z(900, 280, owner=0.55, kids=0.30),
    }
)
TEXT = "33606 33602 33603"
ANALYSES = {
    name: an.analyze(ART, parse_paste(TEXT), policy, project_name="Acme")
    for name, policy in {**RESTRICTED, "off": OFF}.items()
}
METRIC_IDS = [m.id for m in metrics.REGISTRY]


def rules_for(metric: str, basis: str) -> list[Rule]:
    return [Rule(metric, ">=", 0.0, basis)]  # type: ignore[arg-type]


# ----------------------------------------------------------------------------- no second policy
@pytest.mark.parametrize(
    "fn",
    [filters.apply, table.order, export.zip_list, export.csv_text, export.csv_bytes, report.render],
)
def test_no_guarded_function_takes_a_separate_policy(fn) -> None:  # type: ignore[no-untyped-def]
    names = set(inspect.signature(fn).parameters)
    assert not {n for n in names if "policy" in n}, fn.__name__


def test_the_analysis_carries_the_policy_and_reads_it_strictly() -> None:
    assert ANALYSES["liar"].policy is LIAR
    assert ANALYSES["liar"].restricted and ANALYSES["forced"].restricted
    assert ANALYSES["answered"].restricted and not ANALYSES["off"].restricted


# ----------------------------------------------------------------------------- filters
@pytest.mark.parametrize("name", RESTRICTED)
@pytest.mark.parametrize("metric", METRIC_IDS)
def test_filters_refuse_a_rule_on_every_metric(metric: str, name: str) -> None:
    a = ANALYSES[name]
    bases = ["value", "index"] if metrics.BY_ID[metric].indexable else ["value"]
    for basis in bases:
        with pytest.raises(RestrictedUseError):
            filters.apply(a, rules_for(metric, basis))


@pytest.mark.parametrize("name", RESTRICTED)
def test_the_policy_is_checked_before_the_rules_are_validated(name: str) -> None:
    with pytest.raises(RestrictedUseError):
        filters.apply(ANALYSES[name], [Rule("nope", "==", float("nan"))])  # type: ignore[arg-type]


@pytest.mark.parametrize("name", RESTRICTED)
def test_an_empty_rule_list_selects_nothing_so_it_is_allowed(name: str) -> None:
    a = ANALYSES[name]
    assert filters.apply(a, []).qualifying == a.zips


# ----------------------------------------------------------------------------- ordering
@pytest.mark.parametrize("name", RESTRICTED)
@pytest.mark.parametrize("metric", METRIC_IDS)
def test_ordering_refuses_every_metric_key(metric: str, name: str) -> None:
    a = ANALYSES[name]
    with pytest.raises(RestrictedUseError):
        table.order(a, metric)
    with pytest.raises(RestrictedUseError):
        table.order(a, metric, index=True, descending=True)


@pytest.mark.parametrize("name", RESTRICTED)
def test_input_and_zip_order_stay_available(name: str) -> None:
    a = ANALYSES[name]
    assert table.order(a, "input") == a.zips
    assert table.order(a, "zip") == tuple(sorted(a.zips))


# ----------------------------------------------------------------------------- exports and report
@pytest.mark.parametrize("name", RESTRICTED)
def test_the_zip_list_is_exactly_the_input_whatever_is_asked(name: str) -> None:
    a = ANALYSES[name]
    for qualifying in (None, ("33606",), ()):
        for style, sep in (("comma", ", "), ("newline", "\n")):
            got = export.zip_list(
                a,
                qualifying=qualifying,
                include_not_found=False,
                style=style,  # type: ignore[arg-type]
            )
            assert got == sep.join(a.parsed.zips)


@pytest.mark.parametrize("name", RESTRICTED)
def test_the_csv_has_no_index_no_qualifies_and_input_order(name: str) -> None:
    a = ANALYSES[name]
    text = export.csv_text(
        a, order=("33603", "33602", "33606"), metric_ids=["owner", "pop"], now=NOW, version="1"
    )
    header = text.splitlines()[0]
    assert "index" not in header and "Qualifies" not in header
    assert text.index("33606") < text.index("33602") < text.index("33603")  # input order kept
    assert "Restricted mode: on" in text and "Filters applied: none" in text


@pytest.mark.parametrize("name", RESTRICTED)
def test_a_filter_result_with_rules_is_refused_by_the_csv_and_the_report(name: str) -> None:
    result = filters.apply(ANALYSES["off"], [Rule("owner", ">=", 0.5)])
    a = ANALYSES[name]
    with pytest.raises(RestrictedUseError):
        export.csv_text(a, result, now=NOW, version="1")
    with pytest.raises(RestrictedUseError):
        export.csv_bytes(a, result, excel=True, now=NOW, version="1")
    with pytest.raises(RestrictedUseError):
        report.render(a, result, geo=None, now=NOW, version="1")


@pytest.mark.parametrize("name", RESTRICTED)
def test_the_attestation_never_lists_filters_for_a_restricted_analysis(name: str) -> None:
    result = filters.apply(ANALYSES["off"], [Rule("owner", ">=", 0.5)])
    lines = export.attestation(ANALYSES[name], result, now=NOW, version="1")
    assert "Filters applied: none" in lines
    assert not any(line.startswith("ZIPs matching") for line in lines)


@pytest.mark.parametrize("name", RESTRICTED)
def test_the_report_shows_the_banner_and_no_filter_section(name: str) -> None:
    page = report.render(ANALYSES[name], None, geo=None, now=NOW, version="1")
    assert restricted.BANNER_TITLE in page and 'id="filters"' not in page


# ----------------------------------------------------------------------------- lenses (no Analysis)
@pytest.mark.parametrize("policy", [FORCED, ANSWERED, LIAR, None])
@pytest.mark.parametrize("lens", [lens.name for lens in lenses.LENSES])
def test_lenses_and_presets_for_every_restricted_policy(
    lens: str, policy: UsePolicy | None
) -> None:
    assert [x.name for x in lenses.available(policy)] == ["Context"]
    assert lenses.presets_for(lens, policy) == []
    assert lenses.resolve(lens, policy).name == "Context"
    with pytest.raises(RestrictedUseError):
        lenses.preset("Renters", policy)


def test_a_restricted_analysis_resolves_the_context_lens_whatever_is_asked() -> None:
    for name in RESTRICTED:
        a = an.analyze(ART, parse_paste(TEXT), RESTRICTED[name], lens="Retail")
        assert a.lens.name == "Context"


def test_an_unrestricted_analysis_still_works() -> None:
    a = ANALYSES["off"]
    assert filters.apply(a, [Rule("owner", ">=", 0.5)]).qualifying
    assert table.order(a, "owner")[0] == "33602"


def test_a_policy_whose_answer_says_yes_is_restricted_even_if_its_flag_is_not() -> None:
    assert restricted.is_restricted(UsePolicy(False, "Retail (general & specialty)", "Yes"))
    assert restricted.is_restricted(
        UsePolicy(False, "Retail (general & specialty)", "Yes (set by industry)")
    )
    assert not restricted.is_restricted(UsePolicy(False, "Retail (general & specialty)", "No"))
