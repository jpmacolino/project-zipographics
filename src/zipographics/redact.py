"""Keep the Census API key out of logs, errors and files (SPEC §4.5).

The key travels as the ``key=`` query parameter, so every URL that carries it is a secret.
:func:`redact` scrubs text; :class:`RedactingFilter` scrubs log records (message, arguments and
tracebacks); :func:`install_redaction` hooks the log-record factory so that *every* record, from
any logger and any handler, is scrubbed, and quiets ``urllib3``, whose DEBUG lines print the full
request path.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import quote, quote_plus

#: Replacement for a ``key=<value>`` query parameter.
REDACTED = "key=REDACTED"
#: Replacement for a bare occurrence of the key value.
MASK = "REDACTED"

_KEY_PARAM = re.compile(r"""\bkey(?:=|%3d)[^&\s"'<>#)]*""", re.IGNORECASE)
# CENSUS_API_KEY=<value>, but not the "<your key>" placeholder in help text
_ENV_ASSIGNMENT = re.compile(r"""\bCENSUS_API_KEY\s*[=:]\s*(?!<)[^\s"']+""", re.IGNORECASE)


def _forms(secret: str) -> set[str]:
    return {secret, quote(secret), quote(secret, safe=""), quote_plus(secret)}


def redact(text: str, secrets: Iterable[str | None] = ()) -> str:
    """Replace ``key=<anything>`` and every literal occurrence of each secret (plain and
    URL-encoded) in ``text``. Safe to apply twice."""
    out = _ENV_ASSIGNMENT.sub("CENSUS_API_KEY=REDACTED", text)
    out = _KEY_PARAM.sub(REDACTED, out)
    forms: set[str] = set()
    for secret in secrets:
        if isinstance(secret, str) and secret.strip():
            forms |= _forms(secret.strip())
    for form in sorted(forms, key=len, reverse=True):  # longest first: encoded forms contain parts
        out = out.replace(form, MASK)
    return out


class RedactingFilter(logging.Filter):
    """Scrub a log record in place: message (with its arguments applied), traceback, stack."""

    def __init__(self, secrets: Iterable[str | None] = ()) -> None:
        super().__init__()
        self._secrets: list[str | None] = list(secrets)

    def add_secrets(self, secrets: Iterable[str | None]) -> None:
        self._secrets.extend(secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = f"{record.msg} {record.args}"
        record.msg = redact(message, self._secrets)
        record.args = None
        if record.exc_info and record.exc_info[0] is not None:
            text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redact(text, self._secrets)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text, self._secrets)
        if record.stack_info:
            record.stack_info = redact(record.stack_info, self._secrets)
        return True


_installed: dict[str, Any] = {}


def install_redaction(secrets: Iterable[str | None] = ()) -> RedactingFilter:
    """Scrub every log record from now on and quiet ``urllib3`` (idempotent; adds secrets)."""
    if _installed:
        flt: RedactingFilter = _installed["filter"]
        flt.add_secrets(secrets)
        return flt
    flt = RedactingFilter(secrets)
    previous: Callable[..., logging.LogRecord] = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        flt.filter(record)
        return record

    logging.setLogRecordFactory(factory)
    attached: list[logging.Handler] = []
    for name in ("", "urllib3", "requests"):
        for handler in logging.getLogger(name).handlers:
            handler.addFilter(flt)
            attached.append(handler)
    urllib3_logger = logging.getLogger("urllib3")
    old_level = urllib3_logger.level
    if old_level == logging.NOTSET or old_level < logging.WARNING:
        urllib3_logger.setLevel(logging.WARNING)
    _installed.update(filter=flt, previous=previous, handlers=attached, urllib3_level=old_level)
    return flt


def uninstall_redaction() -> None:
    """Undo :func:`install_redaction` (used by tests)."""
    if not _installed:
        return
    logging.setLogRecordFactory(_installed["previous"])
    for handler in _installed["handlers"]:
        handler.removeFilter(_installed["filter"])
    logging.getLogger("urllib3").setLevel(_installed["urllib3_level"])
    _installed.clear()
