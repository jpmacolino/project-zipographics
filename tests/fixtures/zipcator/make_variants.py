"""Derive simulated "re-saved in Excel" variants from the REAL Zipcator exports.

Run from anywhere (pure stdlib, deterministic, no network)::

    uv run python tests/fixtures/zipcator/make_variants.py

Inputs (real Zipcator exports, see README.md): ``boston_3mi.csv``, ``boston_3mi_excel.csv``,
``tampa_5mi.csv`` and the synthetic ``synthetic_population.csv``.

Outputs (all SIMULATED; they model what Excel does when a user opens and re-saves a file, not
bytes Excel produced; the owner may later add real re-saves as extra fixtures):

* ``boston_3mi_resave_zeros_stripped.csv``: plain export re-saved as "CSV (Comma delimited)":
  cp1252, no BOM, quotes dropped, ZIP column reduced to ``2108`` (leading zeros lost), numbers
  as Excel's General format shows them (``100.0`` -> ``100``).
* ``boston_3mi_resave_utf8_bom.csv``: the same re-saved as "CSV UTF-8": BOM kept, zeros lost.
* ``boston_3mi_excel_resave_plain_zips.csv``: the Excel-safe export (``="02108"``) re-saved:
  the formula cells evaluate to the text ``02108``, written unquoted; cp1252, no BOM.
* ``boston_3mi_snake_case.csv``: the forward-compatibility header shape (``zip``,
  ``overlap_pct``, ... snake_case), plain quoting, UTF-8, no BOM.
* ``tampa_5mi_semicolon.csv``: semicolon-delimited re-save (European Excel locales), cp1252.
* ``synthetic_population_resave_cp1252.csv``: the with-population shape re-saved as cp1252
  (exercises the accent in ``Mayagüez``) with the leading zeros stripped.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read_rows(name: str) -> list[list[str]]:
    """Read a fixture the way a careful reader would: BOM-tolerant, never inferring types."""
    text = (HERE / name).read_bytes().decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text, newline="")))


def excel_number(value: str) -> str:
    """How Excel's General format shows a numeric cell (100.0 -> 100, 2.958248 stays)."""
    try:
        return f"{float(value):.10g}"
    except ValueError:
        return value


def strip_zip(value: str) -> str:
    """``02108`` -> ``2108``: what Excel does to an unquoted-as-text ZIP column."""
    if value.startswith('="') and value.endswith('"'):
        value = value[2:-1]
    return str(int(value))  # intentional: this models Excel losing the zeros


def render(rows: list[list[str]], delimiter: str = ",") -> str:
    buf = io.StringIO()
    csv.writer(buf, delimiter=delimiter, lineterminator="\r\n").writerows(rows)  # QUOTE_MINIMAL
    return buf.getvalue()


def resave(
    rows: list[list[str]],
    *,
    zip_mode: str,
    delimiter: str = ",",
) -> str:
    """zip_mode: 'strip' (2108), 'text' (02108, from an evaluated ="02108")."""
    header, body = rows[0], rows[1:]
    out = [header]
    for row in body:
        z = row[0]
        if zip_mode == "strip":
            z = strip_zip(z)
        elif zip_mode == "text":
            z = z[2:-1] if z.startswith('="') else z
        cells = [z]
        for cell in row[1:]:
            cells.append(excel_number(cell) if _looks_numeric(cell) else cell)
        out.append(cells)
    return render(out, delimiter)


def _looks_numeric(cell: str) -> bool:
    try:
        float(cell)
    except ValueError:
        return False
    return True


def write(name: str, text: str, encoding: str) -> None:
    (HERE / name).write_bytes(text.encode(encoding))


def main() -> None:
    boston = read_rows("boston_3mi.csv")
    boston_excel = read_rows("boston_3mi_excel.csv")
    tampa = read_rows("tampa_5mi.csv")
    pop = read_rows("synthetic_population.csv")

    write(
        "boston_3mi_resave_zeros_stripped.csv",
        resave(boston, zip_mode="strip"),
        "cp1252",
    )
    write(
        "boston_3mi_resave_utf8_bom.csv",
        resave(boston, zip_mode="strip"),
        "utf-8-sig",
    )
    write(
        "boston_3mi_excel_resave_plain_zips.csv",
        resave(boston_excel, zip_mode="text"),
        "cp1252",
    )
    write(
        "tampa_5mi_semicolon.csv",
        resave(tampa, zip_mode="text", delimiter=";"),
        "cp1252",
    )
    write(
        "synthetic_population_resave_cp1252.csv",
        resave(pop, zip_mode="strip"),
        "cp1252",
    )

    snake = ["zip", "city", "county", "state", "overlap_pct"]
    snake += [
        "area_in_radius_sq_mi",
        "zip_area_sq_mi",
        "nearest_distance_mi",
        "center_distance_mi",
        "contains_center",
    ]
    assert len(snake) == len(boston[0])
    snake_rows = [snake, *boston[1:]]
    buf = io.StringIO()
    csv.writer(buf, quoting=csv.QUOTE_NONNUMERIC, lineterminator="\r\n").writerows(
        [snake_rows[0], *[[r[0], *[_num(c) for c in r[1:]]] for r in snake_rows[1:]]]
    )
    write("boston_3mi_snake_case.csv", buf.getvalue(), "utf-8")


def _num(cell: str) -> object:
    """Keep numbers bare (QUOTE_NONNUMERIC) like the real export does."""
    try:
        return float(cell)
    except ValueError:
        return cell


if __name__ == "__main__":
    main()
