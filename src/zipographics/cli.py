"""Command line: ``zipographics profile 33602 33606 02108 ...`` (SPEC §5.8).

Same library code as the app: parse, review, analyze, export. Exit codes: 0 ok, 2 usage, 3 data
not built, 4 the input cannot be profiled (no recognized ZIP, over the limit), 5 an output file
could not be written. The CLI makes no network call and never reads the Census API key.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from zipographics import __version__, data, export, lenses, metrics, report, verticals
from zipographics.analysis import Analysis, Mode, analyze
from zipographics.data import DataNotBuiltError
from zipographics.filters import apply as apply_filters
from zipographics.importer import ColumnChoiceRequired, ImportFileError, import_csv
from zipographics.models import ParsedInput, UsePolicy
from zipographics.restricted import BANNER
from zipographics.review import review_lines
from zipographics.ui import DASH, fmt_moe, fmt_value
from zipographics.zips import parse_paste

EXIT_OK, EXIT_USAGE, EXIT_NO_DATA, EXIT_INPUT, EXIT_OUTPUT = 0, 2, 3, 4, 5


class UsageError(Exception):
    """Bad arguments; the message is shown with exit code 2."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise UsageError(message)


def _parser() -> _Parser:
    p = _Parser(prog="zipographics", description="Demographic profile of a set of US ZIP codes.")
    p.add_argument("--version", action="version", version=f"zipographics {__version__}")
    sub = p.add_subparsers(dest="command")
    prof = sub.add_parser("profile", help="profile ZIPs and print the trade-area figures")
    prof.add_argument(
        "zips", nargs="*", metavar="ZIP", help="ZIP codes (repaired if Excel-mangled)"
    )
    prof.add_argument("--file", type=Path, help="CSV or text file of ZIPs (or a Zipcator export)")
    prof.add_argument("--column", help="header of the ZIP column when a file has several")
    prof.add_argument("--vertical", help="client industry (name or a unique fragment)")
    prof.add_argument("--restricted", choices=["yes", "no"], type=str.lower,
                      help="will this be used for housing, jobs, credit or "
                           "insurance marketing?")  # fmt: skip
    prof.add_argument("--benchmark", choices=["state", "county", "us"], default="state")
    prof.add_argument(
        "--mode", choices=["full", "in-radius"], help="estimate mode (Zipcator input)"
    )
    prof.add_argument("--lens", help="lens name (ignored in restricted mode)")
    prof.add_argument("--project", help="project or client name")
    prof.add_argument("--csv", type=Path, metavar="PATH", help="write the profile as CSV")
    prof.add_argument("--excel", action="store_true", help="make --csv the Excel-safe variant")
    prof.add_argument("--report", type=Path, metavar="PATH", help="write the HTML summary report")
    prof.add_argument("--data-dir", type=Path, help="folder with the built data (default: data/)")
    return p


def _load(data_dir: Path | None) -> data.Artifacts:
    return data.load(data_dir)


def _pick_vertical(text: str) -> str:
    wanted = text.strip().lower()
    for v in verticals.VERTICALS:
        if v.name.lower() == wanted:
            return v.name
    found = verticals.search(text)
    if not found:
        known = ", ".join(v.name.split(" (")[0] for v in verticals.VERTICALS[:6])
        raise UsageError(f"Unknown industry {text!r}. Known industries start with: {known}, ...")
    if len(found) > 1:
        names = "; ".join(v.name for v in found[:4]) + ("; ..." if len(found) > 4 else "")
        raise UsageError(f"More than one industry matches {text!r}: {names}")
    return found[0].name


def _policy(vertical: str | None, restricted: str | None) -> UsePolicy:
    name = _pick_vertical(vertical) if vertical else "Other"
    answer = None if restricted is None else restricted == "yes"
    if not verticals.is_locked(name) and answer is None:
        raise UsageError(
            f"--restricted yes|no is required for {name}: say whether this will be used for "
            "housing, jobs, credit or financing, or insurance marketing."
        )
    return verticals.make_policy(name, answer)


def _merge(first: ParsedInput, second: ParsedInput) -> ParsedInput:
    zips = list(dict.fromkeys([*first.zips, *second.zips]))
    dropped = len(first.zips) + len(second.zips) - len(zips)
    blank = second.blank_overlap
    if second.is_zipcator:  # a typed ZIP the Zipcator file does not list has no overlap: full ZIP
        extra = [z for z in first.zips if z not in second.overlaps and z not in blank]
        blank = (*blank, *dict.fromkeys(extra))
    return dataclasses.replace(
        second,
        zips=tuple(zips),
        blank_overlap=blank,
        repaired=(*first.repaired, *second.repaired),
        truncated=(*first.truncated, *second.truncated),
        invalid=(*first.invalid, *second.invalid),
        duplicates=first.duplicates + second.duplicates + dropped,
    )


def _parse_input(zips: Sequence[str], file: Path | None, column: str | None) -> ParsedInput:
    parsed = parse_paste(" ".join(zips)) if zips else ParsedInput()
    if file is not None:
        try:
            raw = file.read_bytes()
        except OSError:
            raise UsageError(f"Could not read {file}.") from None
        try:
            from_file = import_csv(raw, zip_column=column)
        except ColumnChoiceRequired as exc:
            raise UsageError(f"{exc} Choose one with --column NAME.") from None
        except ImportFileError as exc:
            raise UsageError(f"{file}: {exc}") from None
        parsed = _merge(parsed, from_file) if zips else from_file
    if not parsed.zips and not parsed.invalid:
        raise UsageError("Give at least one ZIP or --file.")
    return parsed


def _kpi_lines(a: Analysis) -> list[str]:
    lines = []
    for mid in a.lens.all_kpis:
        m = metrics.BY_ID[mid]
        v = a.trade.values[mid]
        parts = [f"{m.name:<28}", fmt_value(m, v).rjust(12)]
        moe = fmt_moe(m, v)
        parts.append(moe.ljust(14))
        if m.indexable:
            idx = a.index.get(mid)
            text = DASH if idx is None or idx.value is None else str(idx.value)
            parts.append(f"Index {text} vs {a.benchmark.name}")
        else:
            share = a.share_of_benchmark(mid)
            if share is not None:
                parts.append(f"{share * 100:.1f} % of {a.benchmark.name}")
        lines.append("  " + " ".join(parts).rstrip())
    return lines


def _write(path: Path, content: bytes, err: TextIO) -> bool:
    try:
        path.write_bytes(content)
    except OSError:
        print(f"Could not write {path}.", file=err)
        return False
    return True


def _profile(args: argparse.Namespace, out: TextIO, err: TextIO, now: datetime) -> int:
    policy = _policy(args.vertical, args.restricted)
    parsed = _parse_input(args.zips, args.file, args.column)
    try:
        art = _load(args.data_dir)
    except DataNotBuiltError as exc:
        print(str(exc), file=err)
        return EXIT_NO_DATA
    if args.lens is not None:
        try:
            lenses.resolve(args.lens, policy)
        except ValueError as exc:
            raise UsageError(str(exc)) from None
    modes: dict[str, Mode] = {"full": "full", "in-radius": "in_radius"}
    mode = modes.get(args.mode or "")
    try:
        a = analyze(art, parsed, policy, project_name=args.project, mode=mode, lens=args.lens)
        ref = {"county": a.options.default_county, "us": a.options.us}.get(args.benchmark)
        if args.benchmark == "county" and ref is None:
            raise UsageError("No county benchmark is available for these ZIPs.")
        if ref is not None:
            a = analyze(art, parsed, policy, project_name=args.project, mode=mode,
                        lens=args.lens, benchmark=ref)  # fmt: skip
    except ValueError as exc:
        print(str(exc), file=err)
        return EXIT_INPUT

    print(f"Zipographics: {a.title}", file=out)
    for line in review_lines(a.summary):
        print(line, file=out)
    print(f"Restricted-use answer: {policy.answer}", file=out)
    if args.restricted == "no" and verticals.is_locked(policy.vertical or ""):
        print(f"Note: {verticals.LOCKED_NOTE} Your answer (no) was not used.", file=out)
    if policy.restricted:
        print(BANNER, file=out)
    print(f"Benchmark: {a.benchmark.name} ({a.benchmark.level})", file=out)
    print(f"Estimate mode: {'In-radius estimate' if a.weighted else 'Full ZIPs'}", file=out)
    print(f"Data: {a.vintage_label}", file=out)
    print(f"Lens: {a.lens.name}", file=out)
    print("Trade area (ZIP = Census ZCTA):", file=out)
    for line in _kpi_lines(a):
        print(line, file=out)
    if policy.restricted:
        print(export.ad_platform_notice(policy), file=out)

    result = apply_filters(a, [])
    if args.csv is not None:
        content = export.csv_bytes(a, result, excel=args.excel, now=now, version=__version__)
        if not _write(args.csv, content, err):
            return EXIT_OUTPUT
        print(f"Wrote {args.csv}", file=out)
    if args.report is not None:
        html = report.render(a, result, geo=art.geo, now=now, version=__version__)
        if not _write(args.report, html.encode("utf-8"), err):
            return EXIT_OUTPUT
        print(f"Wrote {args.report}", file=out)
    return EXIT_OK


def _tolerant(stream: TextIO) -> None:
    """Never let an unencodable character (an arrow on a cp1252 Windows console) crash a run:
    it prints as ``?`` instead."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
    now: datetime | None = None,
) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    _tolerant(out)
    _tolerant(err)
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
        if args.command != "profile":
            raise UsageError("Choose a command: profile (see --help).")
        return _profile(args, out, err, now or datetime.now(UTC))
    except UsageError as exc:
        print(f"zipographics: {exc}", file=err)
        return EXIT_USAGE


def run() -> None:  # pragma: no cover - console-script entry point
    sys.exit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
