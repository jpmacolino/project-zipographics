"""ZIP token normalization and paste parsing (SPEC §5.2).

ZIPs are 5-character *strings* everywhere. Nothing here converts a ZIP to ``int``; digit checks
use explicit ``[0-9]`` classes because ``str.isdigit()`` and ``\\d`` accept non-ASCII digits.

Invisible characters are written as ``\\N{...}`` names so they stay visible in review.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from zipographics.models import ParsedInput, Source, ZipToken

_NBSP = "\N{NO-BREAK SPACE}"
_BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"
_ZWSP = "\N{ZERO WIDTH SPACE}"
_QUOTES = (
    "\"'"
    "\N{LEFT SINGLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}"
    "\N{LEFT DOUBLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}"
)

# Stripped from both ends of a token: quotes (straight and typographic), whitespace (incl.
# non-breaking), a stray BOM and a zero-width space.
_STRIP_CHARS = " \t\r\n" + _NBSP + _BOM + _ZWSP + _QUOTES
_FLOAT_TAIL = re.compile(r"(?<=[0-9])\.0+$")

_PLAIN = re.compile(r"[0-9]{5}")
_SHORT = re.compile(r"[0-9]{3,4}")
_PLUS4 = re.compile(r"([0-9]{5})-[0-9]{4}")
_NINE = re.compile(r"([0-9]{5})[0-9]{4}")
_MANGLED_HYPHEN = re.compile(r"([0-9]{3,4})-[0-9]{4}")
_MANGLED_DIGITS = re.compile(r"[0-9]{7,8}")

_SEPARATORS = re.compile(rf"[,;|\s{_BOM}{_ZWSP}]+")
_HEADER_AT_START = re.compile(
    rf"""^[\s"'={_BOM}]*
        (?:zip[ \t]*code|zipcode|zip_code|zip5|zip|postal[ \t]*code|postalcode|zcta5|zcta)
        [\s"']*(?=[,;|\s]|$)""",
    re.IGNORECASE | re.VERBOSE,
)


def clean_token(raw: str) -> str:
    """Strip quotes, whitespace, Excel's ``=`` text formula and a trailing ``.0``."""
    s = raw
    while True:
        t = s.strip(_STRIP_CHARS)
        if t.startswith("="):
            t = t[1:]
        if t == s:
            break
        s = t
    return _FLOAT_TAIL.sub("", s)


def normalize_token(raw: str) -> ZipToken:
    """Apply the SPEC §5.2 token rules to one token. Never raises."""
    t = clean_token(raw)
    if _PLAIN.fullmatch(t):
        return ZipToken(raw, t, "ok")
    if _SHORT.fullmatch(t):
        return ZipToken(raw, t.zfill(5), "repaired")
    if m := _PLUS4.fullmatch(t) or _NINE.fullmatch(t):
        return ZipToken(raw, m.group(1), "truncated")
    if m := _MANGLED_HYPHEN.fullmatch(t):
        return ZipToken(raw, m.group(1).zfill(5), "repaired_truncated")
    if _MANGLED_DIGITS.fullmatch(t):
        return ZipToken(raw, t.zfill(9)[:5], "repaired_truncated")
    return ZipToken(raw, None, "invalid")


class Added(NamedTuple):
    token: ZipToken
    #: True when the ZIP was valid and not seen before (it was appended to the result).
    new: bool


class ZipCollector:
    """Accumulates tokens into the parts of a ParsedInput: order, dedupe, repairs, invalid."""

    def __init__(self) -> None:
        self._kept: dict[str, ZipToken] = {}
        self._invalid: list[str] = []
        self.duplicates = 0

    def __contains__(self, zip_code: object) -> bool:
        return zip_code in self._kept

    def add(self, raw: str) -> Added | None:
        """Normalize and record one token; blank input is ignored (returns None)."""
        if not raw.strip(_STRIP_CHARS):
            return None
        tok = normalize_token(raw)
        if tok.zip is None:
            self._invalid.append(raw.strip())
            return Added(tok, False)
        if tok.zip in self._kept:
            self.duplicates += 1
            return Added(tok, False)
        self._kept[tok.zip] = tok
        return Added(tok, True)

    def build(self, source: Source, **extra: object) -> ParsedInput:
        kept = tuple(self._kept.values())
        return ParsedInput(
            zips=tuple(self._kept),
            repaired=tuple(t for t in kept if t.repaired),
            truncated=tuple(t for t in kept if t.truncated),
            invalid=tuple(self._invalid),
            duplicates=self.duplicates,
            source=source,
            **extra,  # type: ignore[arg-type]
        )


def parse_paste(text: str) -> ParsedInput:
    """Parse pasted or typed text: any run of commas, semicolons, pipes, whitespace separates."""
    body = _HEADER_AT_START.sub("", text, count=1)
    collector = ZipCollector()
    for raw in _SEPARATORS.split(body):
        collector.add(raw)
    return collector.build("paste")
