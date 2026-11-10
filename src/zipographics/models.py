"""Plain data types shared by the library (SPEC §8). No logic beyond trivial properties."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

#: Where a ParsedInput came from.
Source = Literal["paste", "csv", "zipcator"]

#: Outcome of normalizing one token (SPEC §5.2 token rules).
TokenStatus = Literal["ok", "repaired", "truncated", "repaired_truncated", "invalid"]

#: How the ZIP column of a CSV was found.
ColumnDetection = Literal["zipcator", "header", "content", "single", "choice"]


@dataclass(frozen=True, slots=True)
class ZipToken:
    """One user-supplied token and what became of it. ``zip`` is a 5-char string or None."""

    raw: str
    zip: str | None
    status: TokenStatus

    @property
    def valid(self) -> bool:
        return self.status != "invalid"

    @property
    def repaired(self) -> bool:
        return self.status in ("repaired", "repaired_truncated")

    @property
    def truncated(self) -> bool:
        return self.status in ("truncated", "repaired_truncated")


@dataclass(frozen=True, slots=True)
class RejectedRow:
    """A Zipcator row dropped because its overlap was out of range or unparseable."""

    zip: str
    raw_overlap: str
    reason: str


@dataclass(frozen=True)
class ParsedInput:
    """Everything the parsers learned from a paste box or a CSV (SPEC §5.2).

    ``zips`` are the accepted, de-duplicated 5-character strings in input order. Repairs and
    truncations are reported for the *retained* occurrence of each ZIP only; later duplicates only
    add to ``duplicates``.
    """

    zips: tuple[str, ...] = ()
    repaired: tuple[ZipToken, ...] = ()
    truncated: tuple[ZipToken, ...] = ()
    invalid: tuple[str, ...] = ()
    duplicates: int = 0
    #: zip -> overlap % in (0, 100], Zipcator input only; ZIPs with a blank overlap are absent.
    overlaps: Mapping[str, float] = field(default_factory=dict)
    blank_overlap: tuple[str, ...] = ()
    rejected_rows: tuple[RejectedRow, ...] = ()
    #: ZIPs repeated with a different overlap (first value kept).
    overlap_conflicts: tuple[str, ...] = ()
    source: Source = "paste"
    #: CSV only: the header of the ZIP column (None for a header-less single column) and how found.
    zip_column: str | None = None
    detected_by: ColumnDetection | None = None

    @property
    def is_zipcator(self) -> bool:
        return self.source == "zipcator"


@dataclass(frozen=True, slots=True)
class UsePolicy:
    """The Step-1 answers that decide restricted mode (SPEC §5.7).

    Phase 5 (``verticals``/``restricted``) builds these; the review screen only reads them.
    ``answer`` is "Yes", "Yes (set by industry)" or "No".
    """

    restricted: bool
    vertical: str | None = None
    answer: str | None = None


@dataclass(frozen=True)
class ReviewSummary:
    """Validation summary for the review screen (SPEC §5.4). All counts come from the library."""

    entered: int
    recognized: tuple[str, ...]
    not_found: tuple[str, ...]
    no_residents: tuple[str, ...]
    repaired: tuple[ZipToken, ...]
    #: (zip, its state, the state of the rest) for repaired ZIPs that look like typos.
    repaired_unexpected_state: tuple[tuple[str, str, str], ...]
    truncated: tuple[ZipToken, ...]
    invalid: tuple[str, ...]
    duplicates: int
    small_population: tuple[str, ...]
    zipcator: bool
    blank_overlap: tuple[str, ...]
    rejected_rows: tuple[RejectedRow, ...]
    overlap_conflicts: tuple[str, ...]
    states: tuple[str, ...]
    benchmark_state: str | None
    blocking: tuple[str, ...]
    industry: str | None
    project_name: str | None
    restricted: bool | None

    @property
    def can_continue(self) -> bool:
        return not self.blocking
