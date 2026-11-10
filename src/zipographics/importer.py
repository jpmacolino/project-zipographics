"""CSV import: encoding and delimiter sniffing, ZIP column detection, Zipcator contract.

Implements SPEC §5.2 (CSV upload) and §5.3 ("zipcator-export v1"). Rows are read with the
``csv`` module, so no value is ever type-inferred (a ZIP column cannot lose its leading zeros);
every cell is a string until the token rules in :mod:`zipographics.zips` have run.
"""

from __future__ import annotations

import codecs
import csv
import io
import re
from collections import Counter
from collections.abc import Sequence

from zipographics.config import MAX_UPLOAD_BYTES
from zipographics.models import ColumnDetection, ParsedInput, RejectedRow
from zipographics.zips import ZipCollector, normalize_token, split_tokens

_BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"

#: Header names (case-, space-, underscore- and hyphen-insensitive) that mean "the ZIP column".
_ZIP_NAMES = frozenset({"zip", "zipcode", "zip5", "postalcode", "zcta", "zcta5"})
_ZIPCATOR_ONLY = frozenset({"contains address", "area in radius (sq mi)", "nearest distance (mi)"})
_CONTENT_SHARE = 0.8
_DELIMITERS = (",", ";", "\t")
_SNIFF_ROWS = 20
_OVERLAP_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]*)?|\.[0-9]+")
_SIGNED_NUMBER = re.compile(r"-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_COMMA_DECIMAL = re.compile(r"[0-9]+,[0-9]+")


class ImportFileError(ValueError):
    """The file can't be used. The message is written for the user."""


class ColumnChoiceRequired(ImportFileError):
    """More than one column could hold the ZIPs; the caller should ask which."""

    def __init__(self, candidates: Sequence[str]) -> None:
        self.candidates = tuple(candidates)
        super().__init__(
            "Several columns could hold the ZIP codes: "
            + ", ".join(repr(c) for c in self.candidates)
            + ". Pick one."
        )


def decode_bytes(data: bytes) -> str:
    """UTF-8 (BOM or not), UTF-16 with BOM (Excel "Unicode Text"), then cp1252, then latin-1."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252")  # what Excel on Windows writes as "CSV"
    except UnicodeDecodeError:
        return data.decode("latin-1")  # cp1252 leaves five bytes undefined; latin-1 never fails


def _rows(text: str, delimiter: str, limit: int | None = None) -> list[list[str]]:
    rows: list[list[str]] = []
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        for row in reader:
            if any(cell.strip() for cell in row):
                rows.append(row)
                if limit is not None and len(rows) >= limit:
                    break
    except csv.Error as exc:
        raise ImportFileError(f"The file could not be read as CSV ({exc}).") from None
    return rows


def sniff_delimiter(text: str) -> str:
    """Pick comma, semicolon or tab by how consistently each splits the first rows."""
    best: tuple[float, int, int] = (0.0, 0, 0)
    chosen = ","
    for priority, delim in enumerate(_DELIMITERS):
        try:
            lengths = [len(r) for r in _rows(text, delim, _SNIFF_ROWS)]
        except ImportFileError:
            continue
        if not lengths:
            continue
        modal, freq = Counter(lengths).most_common(1)[0]
        consistent = freq / len(lengths) if modal >= 2 else 0.0
        multi = sum(1 for n in lengths if n >= 2)
        score = (consistent, multi, -priority)
        if score > best:
            best, chosen = score, delim
    return chosen


def _norm(header: str) -> str:
    return header.replace(_BOM, "").strip().casefold()


def _norm_name(header: str) -> str:
    return re.sub(r"[\s_\-]+", "", _norm(header))


def is_zipcator_header(headers: Sequence[str]) -> bool:
    """The §5.3 detection rule, on already-split headers."""
    names = {_norm(h) for h in headers}
    if "zip" in names and "overlap_pct" in names:
        return True
    return "zip" in names and "overlap %" in names and bool(names & _ZIPCATOR_ONLY)


def _overlap_text(raw: str) -> str:
    s = raw.strip().removesuffix("%").strip()
    if _COMMA_DECIMAL.fullmatch(s):  # "12,5" from a quoted cell or a European Excel
        s = s.replace(",", ".")
    return s


def parse_overlap(raw: str) -> float | None:
    """A number in (0, 100], optionally with a ``%`` sign; ``None`` if it isn't one."""
    s = _overlap_text(raw)
    if not _OVERLAP_NUMBER.fullmatch(s):
        return None
    value = float(s)
    return value if 0 < value <= 100 else None


def overlap_problem(raw: str) -> str:
    """Why :func:`parse_overlap` rejected ``raw`` (for the review screen)."""
    if _SIGNED_NUMBER.fullmatch(_overlap_text(raw)):
        return "overlap must be above 0 and at most 100"
    return "overlap is not a number"


def _cell(row: Sequence[str], index: int) -> str:
    return row[index] if index < len(row) else ""


def _share_valid(values: Sequence[str]) -> float:
    values = [v for v in values if v.strip()]
    if not values:
        return 0.0
    return sum(normalize_token(v).valid for v in values) / len(values)


def import_csv(data: bytes, *, zip_column: str | None = None) -> ParsedInput:
    """Read an uploaded CSV/TXT into a :class:`ParsedInput`.

    ``zip_column`` names the column to use when the caller already asked the user (see
    :class:`ColumnChoiceRequired`). Raises :class:`ImportFileError` for unusable files.
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImportFileError("The file is larger than 5 MB. Split it and upload it in parts.")
    text = decode_bytes(data).lstrip(_BOM)
    if not text.strip():
        raise ImportFileError("The file is empty.")
    rows = _rows(text, sniff_delimiter(text))
    if not rows:
        raise ImportFileError("The file is empty.")

    header = [c.replace(_BOM, "").strip() for c in rows[0]]
    if is_zipcator_header(header):
        return _import_zipcator(header, rows[1:])
    if max(len(r) for r in rows) == 1:
        return _import_single_column(rows)
    return _import_generic(rows, zip_column)


# ------------------------------------------------------------------------- Zipcator (§5.3)
def _import_zipcator(header: list[str], body: list[list[str]]) -> ParsedInput:
    names = [_norm(h) for h in header]
    zi = names.index("zip")
    oi = names.index("overlap %" if "overlap %" in names else "overlap_pct")
    collector = ZipCollector()
    overlaps: dict[str, float] = {}
    blank: list[str] = []
    rejected: list[RejectedRow] = []
    conflicts: list[str] = []

    for row in body:
        cell = _cell(row, zi)
        tok = normalize_token(cell)
        if not tok.valid:
            collector.add(cell)  # recorded as invalid (blank cells are ignored)
            continue
        assert tok.zip is not None
        raw_overlap = _cell(row, oi).strip()
        value = parse_overlap(raw_overlap) if raw_overlap else None
        if raw_overlap and value is None:
            rejected.append(RejectedRow(tok.zip, raw_overlap, overlap_problem(raw_overlap)))
            continue
        added = collector.add(cell)
        assert added is not None
        if not added.new:  # a repeated ZIP: first row wins
            first = overlaps.get(tok.zip)
            differs = tok.zip in blank if first is None else value not in (None, first)
            if value is not None and differs and tok.zip not in conflicts:
                conflicts.append(tok.zip)
            continue
        if value is None:
            blank.append(tok.zip)
        else:
            overlaps[tok.zip] = value

    return collector.build(
        "zipcator",
        overlaps=overlaps,
        blank_overlap=tuple(blank),
        rejected_rows=tuple(rejected),
        overlap_conflicts=tuple(conflicts),
        zip_column=header[zi],
        detected_by="zipcator",
    )


# ------------------------------------------------------------------------- generic CSV (§5.2)
def _tokens(cells: Sequence[str]) -> list[str]:
    """Every token in the cells, splitting on the paste separators (``02108 02109`` is two)."""
    return [t for cell in cells for t in split_tokens(cell) if t]


def _import_single_column(rows: list[list[str]]) -> ParsedInput:
    first = _cell(rows[0], 0).strip()
    rest = [_cell(r, 0) for r in rows[1:]]
    first_tokens = _tokens([first])
    detected: ColumnDetection = "single"
    if _norm_name(first) in _ZIP_NAMES:
        has_header, detected = True, "header"
    elif first_tokens and all(normalize_token(t).valid for t in first_tokens):
        has_header = False  # header-less: the first line is data
    else:
        # an unknown label ("my zips") or junk: a label only if the rest looks like ZIPs
        has_header = _share_valid(_tokens(rest)) >= _CONTENT_SHARE
    collector = ZipCollector()
    for token in _tokens(rest if has_header else [_cell(r, 0) for r in rows]):
        collector.add(token)
    return collector.build("csv", zip_column=first if has_header else None, detected_by=detected)


def _import_generic(rows: list[list[str]], zip_column: str | None) -> ParsedInput:
    first = [c.replace(_BOM, "").strip() for c in rows[0]]
    named = any(_norm_name(h) in _ZIP_NAMES for h in first)
    # No ZIP-like header name and a ZIP-like value in row 1: the file has no header row.
    headerless = not named and any(normalize_token(c).valid for c in first if c)
    if headerless:
        header = [f"Column {i + 1}" for i in range(max(len(r) for r in rows))]
        body = rows
        cells = [c for r in rows for c in r if c.strip()]
        if zip_column is None and _share_valid(cells) >= _CONTENT_SHARE:
            # a plain list of ZIPs laid out on one or several lines: take every cell
            collector = ZipCollector()
            for cell in cells:
                collector.add(cell)
            return collector.build("csv", zip_column=None, detected_by="single")
    else:
        header, body = first, rows[1:]

    if zip_column is not None:
        wanted = zip_column.strip()
        matches = [i for i, h in enumerate(header) if h == wanted] or [
            i for i, h in enumerate(header) if h.casefold() == wanted.casefold()
        ]
        if not matches:
            raise ImportFileError(f"The file has no column named {zip_column!r}.")
        index, detected = matches[0], "choice"
    else:
        by_name = [i for i, h in enumerate(header) if _norm_name(h) in _ZIP_NAMES]
        if len(by_name) == 1:
            index, detected = by_name[0], "header"
        elif len(by_name) > 1:
            raise ColumnChoiceRequired([header[i] for i in by_name])
        else:
            by_content = [
                i
                for i in range(len(header))
                if _share_valid([_cell(r, i) for r in body]) >= _CONTENT_SHARE
            ]
            if not by_content:
                raise ImportFileError(
                    "Couldn't find a ZIP column. Name the column 'ZIP' or 'Zip Code', "
                    "or upload a file with the ZIPs in one column."
                )
            if len(by_content) > 1:
                raise ColumnChoiceRequired([header[i] for i in by_content])
            index, detected = by_content[0], "content"

    collector = ZipCollector()
    for row in body:
        collector.add(_cell(row, index))
    return collector.build("csv", zip_column=header[index], detected_by=detected)
