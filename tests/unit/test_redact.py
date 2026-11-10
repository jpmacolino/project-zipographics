"""Tests for zipographics.redact (SPEC §4.5, §9.2 "redaction and key handling").

Only a made-up key is ever used here, never a real one.
"""

from __future__ import annotations

import io
import logging
import traceback
from urllib.parse import quote, quote_plus

import pytest

from zipographics.redact import (
    MASK,
    REDACTED,
    RedactingFilter,
    install_redaction,
    redact,
    uninstall_redaction,
)

KEY = "0123456789abcdef0123456789abcdef01234567"
BASE = "https://api.census.gov/data/2024/acs/acs5"


# ------------------------------------------------------------------------------ redact()
@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}?key={KEY}&get=B01003_001E&for=state:*",  # first
        f"{BASE}?get=B01003_001E&key={KEY}&for=state:*",  # middle
        f"{BASE}?get=B01003_001E&for=state:*&key={KEY}",  # last
        f"{BASE}?get=B01003_001E&for=state:*&KEY={KEY}",  # upper case
        f"{BASE}?get=B01003_001E&for=state:*&key%3D{KEY}",  # encoded equals sign
    ],
)
def test_the_key_parameter_is_replaced_wherever_it_appears(url: str) -> None:
    out = redact(url)  # no secrets passed: the key= pattern alone must catch it
    assert KEY not in out
    assert "REDACTED" in out
    assert "get=B01003_001E" in out  # everything else survives


def test_only_the_key_value_is_removed_not_the_rest_of_the_url() -> None:
    out = redact(f"{BASE}?get=B01003_001E&key={KEY}&for=state:*")
    assert out == f"{BASE}?get=B01003_001E&{REDACTED}&for=state:*"


def test_the_literal_key_value_is_replaced_even_without_key_equals() -> None:
    text = f"the server said invalid key {KEY} for this request"
    out = redact(text, [KEY])
    assert KEY not in out
    assert out.startswith("the server said invalid key ")


def test_url_encoded_forms_of_the_secret_are_replaced() -> None:
    secret = "abc def+/=?&"  # a made-up secret that needs encoding
    for form in (secret, quote(secret), quote_plus(secret), quote(secret, safe="")):
        assert secret not in redact(f"x {form} y", [secret])
        assert form not in redact(f"x {form} y", [secret])


def test_a_key_in_quotes_or_html_is_replaced() -> None:
    for text in (f'"key={KEY}"', f"'key={KEY}'", f'<a href="?key={KEY}">', f"(key={KEY})"):
        assert KEY not in redact(text)


def test_an_environment_style_assignment_is_replaced_but_the_help_text_placeholder_is_not() -> None:
    assert KEY not in redact(f"CENSUS_API_KEY={KEY}")
    assert KEY not in redact(f"CENSUS_API_KEY = {KEY}")
    help_text = "add the line CENSUS_API_KEY=<your key> to the .env file"
    assert redact(help_text) == help_text


def test_several_secrets_and_empty_secrets() -> None:
    out = redact("a SECRETONE b SECRETTWO c", ["SECRETONE", "", "   ", "SECRETTWO"])
    assert out == f"a {MASK} b {MASK} c"
    assert MASK == "REDACTED" and REDACTED == "key=REDACTED"
    assert redact("nothing to hide", ["", None]) == "nothing to hide"  # type: ignore[list-item]


def test_redaction_is_idempotent_and_leaves_clean_text_alone() -> None:
    once = redact(f"{BASE}?key={KEY}", [KEY])
    assert redact(once, [KEY]) == once
    assert redact("plain text, no secrets") == "plain text, no secrets"


def test_a_key_prefix_like_word_is_not_mangled() -> None:
    text = "monkey=banana&turkey=dinner&keyboard=qwerty"
    assert redact(text) == text


def test_redaction_is_fast_on_adversarial_input() -> None:
    import time

    start = time.perf_counter()
    redact("key=" * 50_000 + "k" * 200_000, [KEY])
    assert time.perf_counter() - start < 2.0


# ------------------------------------------------------------------------------ logging filter
def _logger(secrets: list[str]) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    handler.addFilter(RedactingFilter(secrets))
    logger = logging.getLogger(f"test.redact.{id(stream)}")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, stream


def test_the_filter_redacts_the_message_and_its_arguments() -> None:
    logger, stream = _logger([KEY])
    logger.info("GET %s", f"{BASE}?get=X&key={KEY}")
    logger.info("bare %s and %d", KEY, 5)
    out = stream.getvalue()
    assert KEY not in out
    assert "REDACTED" in out and "bare" in out and "5" in out


def test_the_filter_redacts_tracebacks() -> None:
    logger, stream = _logger([KEY])
    try:
        raise RuntimeError(f"HTTPSConnectionPool: url: {BASE}?key={KEY} failed")
    except RuntimeError:
        logger.exception("request failed")
    out = stream.getvalue()
    assert "Traceback" in out and "request failed" in out
    assert KEY not in out


def test_the_filter_never_raises_on_odd_records() -> None:
    logger, stream = _logger([KEY])
    logger.info("percent %s %s", "only-one-arg")  # wrong arg count: logging reports it itself
    logger.info("object %s", object())
    logger.info(None)  # type: ignore[arg-type]
    assert KEY not in stream.getvalue()


def test_install_redaction_covers_every_logger_and_quiets_urllib3() -> None:
    root = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    urllib3_logger = logging.getLogger("urllib3")
    old_level = urllib3_logger.level
    try:
        urllib3_logger.setLevel(logging.DEBUG)
        flt = install_redaction([KEY])
        assert isinstance(flt, RedactingFilter)
        assert urllib3_logger.level >= logging.WARNING
        root.addHandler(handler)  # added AFTER install: the record factory still protects it
        # urllib3's connection-pool DEBUG line carries the full request path including the key
        logging.getLogger("urllib3.connectionpool").warning('GET /data?key=%s "200"', KEY)
        logging.getLogger("requests").warning("x %s", KEY)
        try:
            raise RuntimeError(f"url {BASE}?key={KEY}")
        except RuntimeError:
            logging.getLogger("anything.else").exception("boom")
        out = stream.getvalue()
        assert KEY not in out
        assert "REDACTED" in out and "Traceback" in out
    finally:
        root.removeHandler(handler)
        urllib3_logger.setLevel(old_level)
        uninstall_redaction()


def test_uninstall_restores_normal_logging() -> None:
    install_redaction([KEY])
    uninstall_redaction()
    stream = io.StringIO()
    logger = logging.getLogger("test.redact.after")
    logger.handlers = [logging.StreamHandler(stream)]
    logger.propagate = False
    logger.warning("plain %s", KEY)  # nothing is installed any more
    assert KEY in stream.getvalue()


def test_a_formatted_traceback_of_a_redacted_exception_has_no_key() -> None:
    # a sanitized error built from redact() carries no key even through traceback.format_exc()
    try:
        raise ValueError(redact(f"bad request {BASE}?key={KEY}", [KEY]))
    except ValueError:
        text = traceback.format_exc()
    assert KEY not in text
