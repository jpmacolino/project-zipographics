"""Zipographics: the Streamlit app (SPEC §5). Layout and wiring only.

Every decision (restricted mode, filters, ordering, exports, the map, the numbers) is made by
``src/zipographics``; this file draws widgets and passes their values on. It never loads ``.env``
and never makes a network call (the map tiles load in the browser from the tile provider).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from zipographics import (
    __version__,
    analysis,
    charts,
    config,
    data,
    export,
    filters,
    flow,
    importer,
    kpis,
    lenses,
    mapview,
    metrics,
    report,
    restricted,
    table,
    verticals,
)
from zipographics import review as review_mod
from zipographics.models import ParsedInput, Rule, UsePolicy
from zipographics.ui import DAGGER, TILDE
from zipographics.zips import parse_paste

STEPS = ["Industry", "ZIPs", "Review", "Insights"]
ANSWERS = ["Yes", "No"]

st.set_page_config(page_title="Zipographics", page_icon=None, layout="wide")


# ----------------------------------------------------------------------------- state
def _form() -> dict:  # type: ignore[type-arg]
    if "form" not in st.session_state:
        st.session_state.form = {
            "industry": None, "answer": None, "project": "",
            "input_mode": "Paste or type", "paste": "", "csv_name": None, "csv_bytes": None,
            "csv_column": None,
        }  # fmt: skip
    if "step" not in st.session_state:
        st.session_state.step = 1
    return st.session_state.form  # type: ignore[no-any-return]


def _go(step: int) -> None:
    st.session_state.step = step
    st.session_state.pop("report", None)  # a report belongs to one run of step 4


def _start_over() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


@st.cache_resource(show_spinner="Loading the Census data...")
def _artifacts(folder: str) -> data.Artifacts:
    return data.load(Path(folder))


def _load() -> data.Artifacts:
    try:
        return _artifacts(str(config.data_dir()))
    except data.DataNotBuiltError as exc:
        st.error(str(exc))
        st.stop()


def _stepper(step: int) -> None:
    parts = [f"**{i} {name}**" if i == step else f"{i} {name}" for i, name in enumerate(STEPS, 1)]
    st.markdown(" \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} ".join(parts))
    st.progress(step / len(STEPS))


# ----------------------------------------------------------------------------- step 1
def step_industry(form: dict) -> None:  # type: ignore[type-arg]
    st.subheader("1. Client industry")
    names = [v.name for v in verticals.VERTICALS]
    current = form["industry"]
    industry = st.selectbox(
        "Client industry",
        names,
        index=names.index(current) if current in names else None,
        placeholder="Search or choose an industry",
        key="industry_box",
    )
    if industry != form["industry"]:
        form["answer"] = None
    form["industry"] = industry
    note = verticals.get(industry).note if industry else None
    if note and not verticals.is_locked(industry):
        st.caption(note)

    answer: str | None = None
    if industry and verticals.is_locked(industry):
        st.radio(verticals.RESTRICTED_QUESTION, ANSWERS, index=0, disabled=True,
                 horizontal=True, key=f"locked_{industry}")  # fmt: skip
        st.info(verticals.LOCKED_NOTE)
    elif industry:
        saved = form["answer"]
        answer = st.radio(
            verticals.RESTRICTED_QUESTION,
            ANSWERS,
            index=ANSWERS.index(saved) if saved in ANSWERS else None,
            horizontal=True,
            key=f"answer_{industry}",
        )
        st.caption(verticals.QUESTION_HINT)
    else:
        st.radio(verticals.RESTRICTED_QUESTION, ANSWERS, index=None, disabled=True,
                 horizontal=True, key="answer_placeholder")  # fmt: skip
    form["answer"] = answer
    form["project"] = st.text_input(
        "Project / client name (optional)", value=form["project"], max_chars=config.MAX_PROJECT_NAME
    )
    st.caption(restricted.NOT_LEGAL_ADVICE)

    ready = flow.step1_ready(industry, answer)
    if st.button("Continue", disabled=not ready, type="primary", key="continue_1"):
        _go(2)
        st.rerun()


# ----------------------------------------------------------------------------- step 2
def step_zips(form: dict) -> None:  # type: ignore[type-arg]
    st.subheader("2. ZIP codes")
    st.caption("ZIP here means Census ZIP Code Tabulation Area (ZCTA).")
    modes = ["Paste or type", "Upload CSV"]
    form["input_mode"] = st.radio(
        "How do you want to add ZIPs?",
        modes,
        horizontal=True,
        index=modes.index(form["input_mode"]),
        key="mode_radio",
    )
    candidates: list[str] | None = None
    if form["input_mode"] == modes[0]:
        form["paste"] = st.text_area(
            "ZIP codes",
            value=form["paste"],
            height=160,
            placeholder="Paste or type ZIPs: 33602, 33606 02108 ...",
            help="Commas, spaces, tabs, semicolons and new lines all work. Up to "
            f"{config.MAX_ZIPS:,} ZIPs.",
        )
    else:
        up = st.file_uploader("CSV or text file", type=["csv", "txt"], key="uploader")
        if up is not None:
            if up.getvalue() != form["csv_bytes"]:  # a different file: forget the old column choice
                form["csv_column"] = form["csv_candidates"] = form["notice"] = None
            form["csv_name"], form["csv_bytes"] = up.name, up.getvalue()
        elif form["csv_name"]:
            st.caption(f"Using the file you added earlier: {form['csv_name']}")
        if form.get("notice"):
            st.warning(form["notice"])
        if form.get("csv_candidates"):
            candidates = form["csv_candidates"]
            form["csv_column"] = st.selectbox(
                "Which column holds the ZIPs?",
                candidates,
                key="column_box",
                index=_index_of(candidates, form["csv_column"]),
            )

    col_back, col_next, _ = st.columns([1, 1, 6])
    col_back.button("Back", on_click=_go, args=(1,), key="back_2")
    if col_next.button("Review ZIPs", type="primary", key="next_2"):
        try:
            if form["input_mode"] == modes[0]:
                parsed = parse_paste(form["paste"])
            else:
                if not form["csv_bytes"]:
                    raise importer.ImportFileError("Choose a CSV or text file first.")
                parsed = importer.import_csv(form["csv_bytes"], zip_column=form["csv_column"])
            form["csv_candidates"] = form["notice"] = None
        except importer.ColumnChoiceRequired as exc:
            form["csv_candidates"] = list(exc.candidates)
            form["notice"] = str(exc)
            st.rerun()
        except importer.ImportFileError as exc:
            st.error(str(exc))
            return
        if not parsed.zips and not parsed.invalid:
            st.error("Add at least one ZIP.")
            return
        st.session_state.parsed = parsed
        _go(3)
        st.rerun()


# ----------------------------------------------------------------------------- step 3
def _policy(form: dict) -> UsePolicy:  # type: ignore[type-arg]
    return flow.policy_for(form["industry"], form["answer"])


def step_review(form: dict, art: data.Artifacts) -> None:  # type: ignore[type-arg]
    st.subheader("3. Review")
    parsed: ParsedInput = st.session_state.parsed
    policy = _policy(form)
    summary = review_mod.summarize(
        parsed, data.facts_from_profile(art.profile), policy=policy,
        project_name=form["project"] or None,
    )  # fmt: skip
    lines = review_mod.review_lines(summary)
    st.markdown("\n".join(f"- {line}" for line in lines))
    for reason in summary.blocking:
        st.error(reason)
    if policy.restricted:
        _banner()
    col_back, col_next, _ = st.columns([1, 1, 6])
    col_back.button("Back", on_click=_go, args=(2,), key="back_3")
    if col_next.button(
        "Show insights", type="primary", disabled=not summary.can_continue, key="next_3"
    ):
        _go(4)
        st.rerun()


# ----------------------------------------------------------------------------- step 4
def _input_key(parsed: ParsedInput) -> tuple[object, ...]:
    """Everything in the parsed input that changes the numbers (ZIPs *and* overlaps)."""
    return (
        parsed.zips, tuple(sorted(parsed.overlaps.items())), parsed.blank_overlap, parsed.source,
    )  # fmt: skip


def _analysis(form: dict, art: data.Artifacts, parsed: ParsedInput, policy: UsePolicy,
              ref: object, mode: str | None, lens: str | None) -> analysis.Analysis:  # type: ignore[type-arg]  # fmt: skip
    key = (_input_key(parsed), repr(ref), mode, lens, form["project"], policy)
    cache = st.session_state.get("analysis_cache")
    if cache and cache[0] == key:
        return cache[1]  # type: ignore[no-any-return]
    a = analysis.analyze(art, parsed, policy, project_name=form["project"] or None,
                         benchmark=ref, mode=mode, lens=lens)  # type: ignore[arg-type]  # fmt: skip
    st.session_state.analysis_cache = (key, a)
    return a


def _base_analysis(
    form: dict,
    art: data.Artifacts,
    parsed: ParsedInput,
    policy: UsePolicy,  # type: ignore[type-arg]
) -> analysis.Analysis:
    """The default-benchmark analysis whose options fill the selectors (cached)."""
    key = (_input_key(parsed), form["project"], policy)
    cache = st.session_state.get("base_cache")
    if cache and cache[0] == key:
        return cache[1]  # type: ignore[no-any-return]
    base = analysis.analyze(art, parsed, policy, project_name=form["project"] or None)
    st.session_state.base_cache = (key, base)
    return base


def _rules_state() -> list[Rule]:
    if "rules" not in st.session_state:
        st.session_state.rules = []
    return st.session_state.rules  # type: ignore[no-any-return]


def _apply_preset(name: str, policy: UsePolicy) -> None:
    st.session_state.rules = list(lenses.preset(name, policy).rules)
    st.session_state.rules_version = st.session_state.get("rules_version", 0) + 1
    _reset_rule_state()


def _reset_rule_state() -> None:
    st.session_state.rule_sigs = {}


def _add_rule() -> None:
    rules = _rules_state()
    if len(rules) < filters.MAX_RULES:
        rules.append(Rule("owner", ">=", 0.5))
        st.session_state.rules_version = st.session_state.get("rules_version", 0) + 1


def _remove_rule(i: int) -> None:
    rules = _rules_state()
    del rules[i]
    st.session_state.rules_version = st.session_state.get("rules_version", 0) + 1


def _filter_builder(a: analysis.Analysis) -> list[Rule]:
    """The filter builder and presets. Not drawn at all in restricted mode."""
    st.markdown("#### Filter ZIPs")
    labels = flow.metric_labels()
    ids = list(labels)
    presets = lenses.presets_for(a.lens, a.policy)
    if presets:
        cols = st.columns(len(presets) + 1)
        for col, p in zip(cols, presets, strict=False):
            col.button(p.name, key=f"preset_{p.name}", help=p.summary, on_click=_apply_preset,
                       args=(p.name, a.policy))  # fmt: skip
    rules = _rules_state()
    version = st.session_state.get("rules_version", 0)
    edited: list[Rule] = []
    for i, rule in enumerate(rules):
        metric, op, number, basis = flow.rule_to_inputs(rule)
        c = st.columns([3, 1, 2, 2, 1])
        k = f"{version}_{i}"
        metric = c[0].selectbox("Metric", ids, index=ids.index(metric), format_func=labels.get,
                                key=f"r_metric_{k}", label_visibility="collapsed")  # fmt: skip
        bases = flow.bases_for(metric)
        basis = c[3].selectbox("Compare", bases, index=bases.index(basis) if basis in bases else 0,
                               key=f"r_basis_{k}", label_visibility="collapsed")  # fmt: skip
        op = c[1].selectbox("Operator", [">=", "<="], index=[">=", "<="].index(op),
                            key=f"r_op_{k}", label_visibility="collapsed")  # fmt: skip
        unit = flow.value_unit(metric, basis)
        sigs = st.session_state.setdefault("rule_sigs", {})
        if sigs.get(k, (metric, basis)) != (metric, basis):  # the unit changed: the old number is
            number = flow.default_number(metric, basis)  # meaningless ("70 %" is not "$70")
        sigs[k] = (metric, basis)
        number = c[2].number_input(
            f"Value ({unit or 'number'})", value=float(number), key=f"r_val_{k}_{metric}_{basis}",
            label_visibility="collapsed",
        )  # fmt: skip
        c[2].caption(unit or "number")
        c[4].button("Remove", key=f"r_del_{k}", on_click=_remove_rule, args=(i,))
        edited.append(flow.rule_from_inputs(metric, op, number, basis))
    st.session_state.rules = edited
    if len(edited) < filters.MAX_RULES:
        st.button("Add rule", on_click=_add_rule, key="add_rule")
    return edited


def _table_section(
    a: analysis.Analysis, result: filters.FilterResult | None
) -> tuple[list[str], tuple[str, ...]]:
    st.markdown("#### ZIP table")
    labels = flow.metric_labels()
    default_cols = [m for m in a.lens.columns]
    chosen = st.multiselect("Columns", list(labels), default=default_cols, format_func=labels.get,
                            key=f"cols_{a.lens.name}")  # fmt: skip
    ids = list(chosen)
    c1, c2, c3, c4 = st.columns(4)
    choices = flow.sort_choices(restricted=a.restricted)
    sort_label = dict(choices)
    if a.restricted:
        sort = c1.radio("Order", [k for k, _ in choices], format_func=sort_label.get,
                        horizontal=True, key="order_restricted")  # fmt: skip
    else:
        sort = c1.selectbox(
            "Sort by", [k for k, _ in choices], format_func=sort_label.get, key="sort_by"
        )
    descending = c2.checkbox("Descending", key="descending")
    show_moe = c3.toggle("Show margins of error", key="show_moe")
    index = False
    if not a.restricted:
        index = (
            c4.radio("Show", ["Raw values", "Index"], horizontal=True, key="show_index") == "Index"
        )
    only = False
    if result is not None and result.active:
        only = st.toggle("Only matching ZIPs", key="only_matching")
    view = table.build_view(a, result, metric_ids=ids, show_moe=show_moe, index=index, sort=sort,
                            descending=descending, only_matching=only)  # fmt: skip
    styled = view.frame.style.apply(lambda _f: view.styles, axis=None)
    if a.restricted:
        st.table(styled)  # static: no sortable headers (DECISIONS P12)
    else:
        config_cols = {
            c: st.column_config.TextColumn(c, help=h)
            for c, h in view.help.items()
            if c in view.frame
        }
        st.dataframe(styled, hide_index=True, column_config=config_cols, width="stretch")
    st.caption(
        f"{DAGGER} marks an unreliable estimate (grey italics); {TILDE} means use with caution "
        "(a margin of error of 15-30 % of the estimate, shown in muted text); "
        "\N{EM DASH} means no estimate."
    )
    bad = table.unreliable_cells(a, ids)
    with st.expander("Why are some values grey?"):
        if not bad:
            st.write("No unreliable values in the columns shown.")
        else:
            rows = [
                {
                    "ZIP": c.zip,
                    "Metric": c.metric,
                    "Estimate": c.estimate,
                    "Margin of error": c.moe,
                    "CV %": None if c.cv is None else round(c.cv, 1),
                }
                for c in bad
            ]
            grey = pd.DataFrame(rows)
            if a.restricted:  # a click-sortable grid of ZIP values would be ranking (SPEC 5.7)
                st.table(grey.set_index("ZIP"))
            else:
                st.dataframe(grey, hide_index=True)
    return ids, view.zips


def _banner() -> None:
    st.warning(f"**{restricted.BANNER_TITLE}** {restricted.BANNER_BODY}")


def _index_of(options: list[str], value: str | None) -> int | None:
    return options.index(value) if value in options else None


def _charts_section(a: analysis.Analysis) -> None:
    st.markdown("#### Trade area vs benchmark")
    all_charts = charts.charts_for(a)
    for i in range(0, len(all_charts), 2):
        cols = st.columns(2)
        for col, d in zip(cols, all_charts[i : i + 2], strict=False):
            with col:
                st.altair_chart(charts.altair_chart(d), width="stretch")
                if d.note:
                    st.caption(d.note)
                with st.expander(f"{d.title}: data table"):
                    st.dataframe(charts.table_frame(d), hide_index=True)
    with st.expander("More demographics"):
        st.caption(
            "Context only. Hispanic origin is a separate Census question; Hispanic people can "
            "be of any race."
        )
        for d in charts.more_demographics(a):
            st.altair_chart(charts.altair_chart(d), width="stretch")
            with st.expander(f"{d.title}: data table"):
                st.dataframe(charts.table_frame(d), hide_index=True)


def _map_section(
    a: analysis.Analysis, art: data.Artifacts, result: filters.FilterResult | None
) -> None:
    st.markdown("#### Map")
    metric = None
    if not a.restricted:
        labels = flow.metric_labels()
        ids = list(labels)
        default = next((m for m in a.lens.kpis if metrics.BY_ID[m].indexable), "owner")
        metric = st.selectbox(
            "Shade by", ids, index=ids.index(default), format_func=labels.get, key="map_metric"
        )
    layer = mapview.layer(a, metric, result, art.geo)
    if layer is None:
        st.info(
            art.geo_note or "No boundaries are available for these ZIPs, so the map is not drawn."
        )
        return
    if layer.note:
        st.caption(layer.note)
    south_west, north_east = layer.bounds
    fmap = folium.Map(tiles="OpenStreetMap", control_scale=True)
    folium.GeoJson(
        layer.geojson,
        style_function=lambda f: f["properties"]["style"],
        tooltip=folium.GeoJsonTooltip(
            fields=["tooltip"], aliases=[""], labels=False, sticky=True, localize=False
        ),
    ).add_to(fmap)
    fmap.fit_bounds([list(south_west), list(north_east)])
    st_folium(fmap, height=520, width="stretch", returned_objects=[], key="map")
    if layer.legend:
        st.markdown(f"**{layer.legend_title}**")
        swatch = '<span style="background:{};padding:0 10px;border:1px solid #888">&nbsp;</span>'
        st.markdown(
            " ".join(f"{swatch.format(i.color)} {i.label}&nbsp;&nbsp;" for i in layer.legend),
            unsafe_allow_html=True,
        )
    else:
        st.caption(
            "Recognized ZIPs are drawn with one neutral fill (restricted mode); hover for values."
        )


def _report_key(
    a: analysis.Analysis, result: filters.FilterResult | None, ids: list[str]
) -> tuple[object, ...]:
    """What a prepared report was built from; a download is offered only while it still matches."""
    rules = () if result is None else result.rules
    kept = () if result is None else result.qualifying
    cache = st.session_state.get("analysis_cache")
    return (cache[0] if cache else None, rules, kept, tuple(ids), a.restricted, a.policy)


def _exports_section(a: analysis.Analysis, art: data.Artifacts, result: filters.FilterResult | None,
                     ids: list[str], zips: tuple[str, ...]) -> None:  # fmt: skip
    st.markdown("#### Export")
    now = datetime.now(UTC)
    names = export.filenames(a.project_name, now.date())
    notice = export.ad_platform_notice(a.policy)
    st.markdown("**ZIP list for ad platforms**")
    for line in export.attestation(a, result, now=now, version=__version__):
        st.caption(line)  # shown directly above the list (SPEC 5.6): recorded in the CSV and report
    if notice:
        st.warning(notice)
    include_nf = st.checkbox("Include ZIPs that have no Census data", value=True, key="include_nf")
    export_all = False
    if result is not None and result.active:
        export_all = st.checkbox("Export all ZIPs instead of only the matches", key="export_all")
    qualifying = None if (result is None or not result.active or export_all) else result.qualifying
    lists = {
        style: export.zip_list(a, qualifying=qualifying, include_not_found=include_nf, style=style)
        for style in ("comma", "newline")
    }
    c1, c2 = st.columns(2)
    c1.caption("Comma-separated")
    c1.code(lists["comma"] or " ", language=None, wrap_lines=True)
    c2.caption("One per line")
    c2.code(lists["newline"] or " ", language=None, wrap_lines=True)
    d1, d2 = st.columns(2)
    d1.download_button(
        "Download ZIP list, comma-separated (.txt)", lists["comma"].encode("utf-8"),
        file_name=names["ziplist"], mime="text/plain", key="dl_zips_comma",
    )  # fmt: skip
    d2.download_button(
        "Download ZIP list, one per line (.txt)", lists["newline"].encode("utf-8"),
        file_name=names["ziplist"], mime="text/plain", key="dl_zips_lines",
    )  # fmt: skip

    st.markdown("**Table as CSV**")
    c1, c2 = st.columns(2)
    order = zips if not a.restricted and len(zips) == len(a.zips) else None
    for col, excel, label, fname in (
        (c1, False, "Download CSV", names["csv"]),
        (c2, True, "Download CSV for Excel", names["csv_excel"]),
    ):
        payload = export.csv_bytes(
            a, result, excel=excel, metric_ids=ids or None, order=order, now=now,
            version=__version__,
        )  # fmt: skip
        col.download_button(label, payload, file_name=fname, mime="text/csv", key=f"dl_csv_{excel}")
    st.caption(
        "The CSV ends with a blank line and then Note: lines (the attestation). Programs can "
        "stop at the blank line."
    )

    st.markdown("**Summary report**")
    key = _report_key(a, result, ids)
    if st.button("Prepare the summary report", key="prep_report"):
        started = time.perf_counter()
        html = report.render(
            a, result, geo=art.geo, now=now, version=__version__, metric_ids=ids or None
        )
        st.session_state.report = (key, html.encode("utf-8"), time.perf_counter() - started)
    saved = st.session_state.get("report")
    if saved is not None and saved[0] == key:
        st.download_button("Download report (.html)", saved[1], file_name=names["report"],
                           mime="text/html", key="dl_report")  # fmt: skip
        st.caption(
            f"Prepared in {saved[2]:.1f} s. Open it in a browser; Print > Save as PDF makes a PDF."
        )
    elif saved is not None:
        st.caption(
            "The report you prepared no longer matches the settings above; prepare it again."
        )


def step_insights(form: dict, art: data.Artifacts) -> None:  # type: ignore[type-arg]
    parsed: ParsedInput = st.session_state.parsed
    policy = _policy(form)
    base = _base_analysis(form, art, parsed, policy)
    choices = flow.benchmark_choices(base.options)

    top = st.columns([3, 2, 2])
    st.title(base.title)
    with top[0]:
        bench_label = st.selectbox("Benchmark", [c.label for c in choices], key="benchmark_box")
    ref = flow.find_choice(choices, bench_label).ref
    mode: str | None = None
    if parsed.is_zipcator and parsed.overlaps:
        with top[1]:
            pick = st.radio(
                "Estimate mode",
                ["In-radius estimate", "Full ZIPs"],
                horizontal=True,
                key="mode_box",
            )
        mode = "in_radius" if pick == "In-radius estimate" else "full"
    available = lenses.available(policy)
    lens_name: str | None = None
    with top[2]:
        if len(available) == 1:
            st.text_input("Lens", value=available[0].name, disabled=True, key="lens_fixed")
        else:
            default = base.lens.name if base.lens in available else available[0].name
            names = [lens.name for lens in available]
            lens_name = st.selectbox("Lens", names, index=names.index(default), key="lens_box")
    a = _analysis(form, art, parsed, policy, ref, mode, lens_name)

    s = a.summary
    dot = " \N{MIDDLE DOT} "
    st.caption(
        f"{policy.vertical}{dot}{len(a.zips)} of {s.entered} ZIPs recognized{dot}"
        f"Benchmark: {a.benchmark.name}{dot}{a.vintage_label}"
        + (" \N{MIDDLE DOT} In-radius estimates" if a.weighted else "")
    )
    st.caption(
        "ZIP = Census ZIP Code Tabulation Area (ZCTA). PO-box-only and single-organization ZIPs "
        "are not included."
    )
    if a.restricted:
        _banner()
    msg = flow.span_message(a)
    if msg:
        st.info(msg)
    if base.options.puerto_rico_note:
        st.info(base.options.puerto_rico_note)

    cards = kpis.cards(a)
    for i in range(0, len(cards), 4):
        cols = st.columns(4)
        for col, c in zip(cols, cards[i : i + 4], strict=False):
            sub = " \N{MIDDLE DOT} ".join(
                x for x in (c.moe, c.index_text or c.share_text, c.tier_label) if x
            )
            col.metric(c.label, f"{c.value} {c.marker}".strip(), help=c.tooltip or None)
            col.caption(sub)

    rules: list[Rule] = []
    result: filters.FilterResult | None = None
    rules_ok = True
    if not a.restricted:
        rules = _filter_builder(a)
        exclude = (
            st.checkbox("Exclude unreliable matches", key="exclude_unreliable") if rules else False
        )
        try:
            result = filters.apply(a, rules, exclude_unreliable=exclude)
        except ValueError as exc:
            st.error(str(exc))
            result = None
            rules_ok = False
        if result is not None and result.active:
            st.success(result.summary_line())
            if result.unreliable_matches:
                st.caption(
                    "Qualifies on an unreliable estimate: " + ", ".join(result.unreliable_matches)
                )
            uncertain = [z for z, m in result.matches.items() if m.uncertain]
            if uncertain:
                st.caption(
                    "Could not be decided (top- or bottom-coded value): " + ", ".join(uncertain)
                )

    ids, zips = _table_section(a, result)
    _map_section(a, art, result)  # before the charts: the map is slower to draw (DECISIONS P17)
    _charts_section(a)
    if rules_ok:
        _exports_section(a, art, result, ids, zips)
    else:  # exporting every ZIP while a broken filter is on screen would mislead
        st.markdown("#### Export")
        st.warning("Fix the filter rule above to enable the exports.")
    st.button("Back to review", on_click=_go, args=(3,), key="back_4")
    st.button("Start over", on_click=_start_over, key="start_over")


# ----------------------------------------------------------------------------- main
def main() -> None:
    form = _form()
    st.markdown("### Zipographics")
    step = st.session_state.step
    _stepper(step)
    art = _load()
    if step == 1:
        step_industry(form)
    elif step == 2:
        step_zips(form)
    elif step == 3:
        step_review(form, art)
    else:
        step_insights(form, art)


main()
