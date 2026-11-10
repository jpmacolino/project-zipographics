"""Tests for zipographics.census_api: requests, chunking, retries, cache, errors (SPEC §4.5, §9.2).

A scripted fake session stands in for ``requests`` (so timeouts and retry sleeps can be asserted
exactly); one test uses ``responses`` to check the real HTTP stack keeps the URL shape. The clock
and sleeper are injected: nothing here ever sleeps. Only a made-up key is used.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import traceback
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import requests
import responses
from hypothesis import given
from hypothesis import strategies as st

from zipographics.census_api import (
    MISSING_KEY_MESSAGE,
    REJECTED_KEY_MESSAGE,
    CensusApiError,
    CensusClient,
    MissingKeyError,
    NetworkError,
    RejectedKeyError,
    VarRequest,
    chunk_names,
    dataset_url,
)
from zipographics.redact import uninstall_redaction

KEY = "0123456789abcdef0123456789abcdef01234567"
STATE_BODY = json.dumps(
    [["NAME", "B01003_001E", "B01003_001M", "state"], ["Florida", "100", "5", "12"]]
)


@pytest.fixture(autouse=True)
def _restore_logging() -> Any:
    yield
    uninstall_redaction()


BODIES = {
    "zcta": json.dumps(
        [["B01003_001E", "B01003_001M", "zip code tabulation area"], ["1", "1", "02108"]]
    ),
    "state": STATE_BODY,
    "county": json.dumps(
        [
            ["NAME", "B01003_001E", "B01003_001M", "state", "county"],
            ["A County, Florida", "1", "1", "12", "057"],
        ]
    ),
    "us": json.dumps(
        [["NAME", "B01003_001E", "B01003_001M", "us"], ["United States", "300", "5", "1"]]
    ),
}


class FakeResponse:
    def __init__(self, status: int = 200, text: str = STATE_BODY, url: str = "") -> None:
        self.status_code = status
        self.text = text
        self.url = url


class FakeSession:
    """Plays back a script: each GET returns the next outcome, or raises it if an exception."""

    def __init__(self, *outcomes: FakeResponse | Exception) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        assert self.outcomes, f"unexpected extra request: {url}"
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(
    tmp_path: Path, session: Any, clock: Clock | None = None, **kw: Any
) -> CensusClient:
    clock = clock or Clock()
    return CensusClient(
        KEY,
        cache_root=tmp_path / "raw",
        session=session,
        clock=clock,
        sleeper=clock.sleep,
        jitter=lambda: 0.0,
        **kw,
    )


def state_vars() -> list[VarRequest]:
    return [VarRequest("B01003_001")]


# --------------------------------------------------------------------------- missing key
@pytest.mark.parametrize("bad", [None, "", "   ", "\t\n"])
def test_a_missing_empty_or_blank_key_raises_the_exact_message(
    tmp_path: Path, bad: str | None
) -> None:
    with pytest.raises(MissingKeyError) as exc:
        CensusClient(bad, cache_root=tmp_path)
    assert str(exc.value) == MISSING_KEY_MESSAGE
    assert MISSING_KEY_MESSAGE == (
        "CENSUS_API_KEY is not set. The data build needs a free Census Data API key: request one "
        "at https://www.census.gov/data/developers/api-key.html, activate it from the email, then "
        "add the line CENSUS_API_KEY=<your key> to the .env file in the project folder (see "
        ".env.example). The app itself never needs the key."
    )


def test_the_key_is_not_in_repr_or_str(tmp_path: Path) -> None:
    client = make_client(tmp_path, FakeSession())
    assert KEY not in repr(client) and KEY not in str(client)


# --------------------------------------------------------------------------- URLs
@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("zcta", "&for=zip%20code%20tabulation%20area:*&key="),  # all ZCTAs, no in=
        ("state", "&for=state:*&key="),
        ("county", "&for=county:*&in=state:*&key="),
        ("us", "&for=us:1&key="),
    ],
)
def test_geography_urls(tmp_path: Path, level: str, expected: str) -> None:
    session = FakeSession(FakeResponse(text=BODIES[level]))
    client = make_client(tmp_path, session)
    client.fetch_table("detailed", 2024, level, state_vars())  # type: ignore[arg-type]
    url = session.calls[0][0]
    assert url.startswith("https://api.census.gov/data/2024/acs/acs5?get=")
    assert expected in url
    assert url.endswith(f"key={KEY}")  # the real request carries the key
    assert ("in=" in url) == (level == "county")
    assert ("NAME" in url) == (level != "zcta")  # NAME only for state/county/us


def test_profile_dataset_url() -> None:
    assert dataset_url(2024, "detailed") == "https://api.census.gov/data/2024/acs/acs5"
    assert dataset_url(2024, "profile") == "https://api.census.gov/data/2024/acs/acs5/profile"


def test_requests_carry_connect_and_read_timeouts(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse())
    make_client(tmp_path, session).fetch_table("detailed", 2024, "state", state_vars())
    assert session.calls[0][1]["timeout"] == (10, 120)


@responses.activate
def test_the_real_http_stack_keeps_the_url_shape(tmp_path: Path) -> None:
    body = json.dumps([["B01003_001E", "zip code tabulation area"], ["10", "02108"]])
    responses.add(
        responses.GET, re.compile(r"https://api\.census\.gov/data/2024/acs/acs5.*"), body=body
    )
    client = CensusClient(KEY, cache_root=tmp_path / "raw", sleeper=lambda s: None)
    frame = client.fetch_table("detailed", 2024, "zcta", [VarRequest("B01003_001", with_moe=False)])
    sent = responses.calls[0].request.url
    assert "for=zip%20code%20tabulation%20area:*" in sent
    assert "get=B01003_001E" in sent and f"key={KEY}" in sent
    assert list(frame["zip code tabulation area"]) == ["02108"]  # a text ZIP, zero kept


# --------------------------------------------------------------------------- chunking
def test_variables_are_requested_with_e_m_and_ea_for_medians() -> None:
    chunks = chunk_names(
        [VarRequest("B19001_002"), VarRequest("B19013_001", is_median=True)], limit=50
    )
    assert chunks == [["B19001_002E", "B19001_002M", "B19013_001E", "B19013_001M", "B19013_001EA"]]


def test_chunks_never_exceed_the_limit_and_keep_a_variables_names_together() -> None:
    reqs = [VarRequest(f"B{n:05d}_001", is_median=(n % 7 == 0)) for n in range(1, 130)]
    for reserved in (0, 1):
        chunks = chunk_names(reqs, limit=50, reserved=reserved)
        assert all(len(c) + reserved <= 50 for c in chunks)
        flat = [n for c in chunks for n in c]
        assert flat == [n for r in reqs for n in r.names()]  # nothing lost, order kept
        for r in reqs:  # E, M (and EA) of one variable are in one chunk
            homes = {i for i, c in enumerate(chunks) if r.names()[0] in c}
            assert len(homes) == 1
            assert all(n in chunks[next(iter(homes))] for n in r.names())


@given(st.lists(st.booleans(), min_size=1, max_size=200), st.integers(5, 50))
def test_chunking_property(medians: list[bool], limit: int) -> None:
    reqs = [VarRequest(f"B{i:05d}_001", is_median=m) for i, m in enumerate(medians)]
    chunks = chunk_names(reqs, limit=limit, reserved=1)
    assert all(0 < len(c) <= limit - 1 for c in chunks)
    assert sum(len(c) for c in chunks) == sum(len(r.names()) for r in reqs)


def test_a_variable_that_cannot_fit_in_a_chunk_is_an_error() -> None:
    with pytest.raises(ValueError, match="limit"):
        chunk_names([VarRequest("B19013_001", is_median=True)], limit=2)


class ServerSession:
    """Answers any ``get=`` request from a table of synthetic columns (so chunks can merge)."""

    def __init__(self, table: pd.DataFrame, keys: list[str], limit: int = 50) -> None:
        self.table, self.keys, self.limit = table, keys, limit
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(url)
        names = re.search(r"get=([^&]*)", url).group(1).split(",")  # type: ignore[union-attr]
        assert len([n for n in names if n != "NAME"]) <= self.limit, "too many variables"
        cols = [*names, *self.keys]
        rows = [cols, *self.table[cols].astype(object).values.tolist()]
        return FakeResponse(text=json.dumps(rows))


def test_chunks_are_fetched_separately_and_merged_on_the_geography_key(tmp_path: Path) -> None:
    n_vars = 60
    reqs = [VarRequest(f"B{i:05d}_001") for i in range(n_vars)]
    zips = ["02108", "00601", "33602"]
    data = {"zip code tabulation area": zips}
    for r in reqs:
        for name in r.names():
            data[name] = [f"{name[-3:]}{z}" for z in zips]
    table = pd.DataFrame(data)
    server = ServerSession(table, ["zip code tabulation area"])
    client = make_client(tmp_path, server)
    frame = client.fetch_table("detailed", 2024, "zcta", reqs)
    assert len(server.calls) == 3  # 120 names / 50 per request
    assert set(frame.columns) == set(table.columns)
    assert list(frame["zip code tabulation area"]) == zips  # strings with leading zeros
    key = "zip code tabulation area"
    cols = [c for c in table.columns if c != key]
    pd.testing.assert_frame_equal(
        frame.set_index(key)[cols],
        table.set_index(key)[cols],
        check_dtype=False,
        check_index_type=False,
        check_column_type=False,
    )


def test_state_and_county_responses_merge_on_their_geography_keys(tmp_path: Path) -> None:
    reqs = [VarRequest(f"B{i:05d}_001", with_moe=False) for i in range(60)]
    table = pd.DataFrame(
        {
            "NAME": ["A, X", "B, X", "C, Y"],
            "state": ["01", "01", "02"],
            "county": ["001", "003", "001"],
            **{r.names()[0]: ["1", "2", "3"] for r in reqs},
        }
    )
    server = ServerSession(table, ["state", "county"])
    frame = make_client(tmp_path, server).fetch_table("detailed", 2024, "county", reqs)
    assert len(server.calls) == 2 and "NAME" in frame.columns
    assert list(zip(frame["state"], frame["county"], strict=True)) == [
        ("01", "001"),
        ("01", "003"),
        ("02", "001"),
    ]


# --------------------------------------------------------------------------- retries and pacing
def test_429_is_retried_with_backoff_then_succeeds(tmp_path: Path) -> None:
    clock = Clock()
    session = FakeSession(FakeResponse(429, "slow down"), FakeResponse())
    frame = make_client(tmp_path, session, clock).fetch_table(
        "detailed", 2024, "state", state_vars()
    )
    assert len(session.calls) == 2
    assert clock.sleeps == [1.0]
    assert frame.loc[0, "NAME"] == "Florida"


def test_server_errors_are_retried_four_times_with_exponential_backoff_then_fail(
    tmp_path: Path,
) -> None:
    clock = Clock()
    session = FakeSession(*[FakeResponse(500, "boom") for _ in range(5)])
    with pytest.raises(NetworkError):
        make_client(tmp_path, session, clock).fetch_table("detailed", 2024, "state", state_vars())
    assert len(session.calls) == 5  # 1 attempt + 4 retries
    assert clock.sleeps == [1.0, 2.0, 4.0, 8.0]


def test_jitter_is_added_to_the_backoff(tmp_path: Path) -> None:
    clock = Clock()
    session = FakeSession(FakeResponse(503), FakeResponse())
    client = CensusClient(KEY, cache_root=tmp_path, session=session, clock=clock,
                          sleeper=clock.sleep, jitter=lambda: 0.5)  # fmt: skip
    client.fetch_table("detailed", 2024, "state", state_vars())
    assert clock.sleeps == [1.0 * (1 + 0.5 * 0.25)]


@pytest.mark.parametrize(
    "failure",
    [requests.Timeout("read timed out"), requests.ConnectionError("connection reset")],
)
def test_timeouts_and_connection_errors_are_retried(tmp_path: Path, failure: Exception) -> None:
    clock = Clock()
    session = FakeSession(failure, FakeResponse())
    make_client(tmp_path, session, clock).fetch_table("detailed", 2024, "state", state_vars())
    assert len(session.calls) == 2 and clock.sleeps == [1.0]


@pytest.mark.parametrize("status", [404, 410, 422])
def test_other_4xx_errors_are_not_retried(tmp_path: Path, status: int) -> None:
    session = FakeSession(FakeResponse(status, "not found"))
    with pytest.raises(CensusApiError) as exc:
        make_client(tmp_path, session).fetch_table("detailed", 2024, "state", state_vars())
    assert not isinstance(exc.value, (RejectedKeyError, NetworkError))
    assert len(session.calls) == 1


def test_requests_are_spaced_at_least_one_second_apart(tmp_path: Path) -> None:
    clock = Clock()
    session = FakeSession(
        FakeResponse(text=BODIES["state"]),
        FakeResponse(text=BODIES["county"]),
        FakeResponse(text=BODIES["us"]),
    )
    client = make_client(tmp_path, session, clock)
    for level in ("state", "county", "us"):
        client.fetch_table("detailed", 2024, level, state_vars())  # type: ignore[arg-type]
    assert len(session.calls) == 3
    assert clock.sleeps == [1.0, 1.0]  # the first request goes straight out


# --------------------------------------------------------------------------- key and network errors
def test_an_html_page_with_status_200_means_the_key_was_rejected(tmp_path: Path) -> None:
    html = "<html><head><title>Invalid Key</title></head><body>Invalid Key</body></html>"
    session = FakeSession(FakeResponse(200, html))
    with pytest.raises(RejectedKeyError) as exc:
        make_client(tmp_path, session).fetch_table("detailed", 2024, "state", state_vars())
    assert str(exc.value) == REJECTED_KEY_MESSAGE
    assert REJECTED_KEY_MESSAGE == (
        "The Census API rejected the API key. Check that it was copied completely and activated "
        "from the email."
    )
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    ("status", "body"),
    [(400, "error: invalid key"), (401, "Unauthorized: key"), (400, "The key is not activated")],
)
def test_a_4xx_that_mentions_the_key_is_a_rejected_key(
    tmp_path: Path, status: int, body: str
) -> None:
    session = FakeSession(FakeResponse(status, body))
    with pytest.raises(RejectedKeyError):
        make_client(tmp_path, session).fetch_table("detailed", 2024, "state", state_vars())


def test_a_400_about_a_variable_is_not_blamed_on_the_key(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(400, "error: unknown variable 'B99999_001E'"))
    with pytest.raises(CensusApiError) as exc:
        make_client(tmp_path, session).fetch_table("detailed", 2024, "state", state_vars())
    assert not isinstance(exc.value, RejectedKeyError)
    assert "unknown variable" in str(exc.value)


@pytest.mark.parametrize("status", [403, 407])
def test_a_proxy_403_is_a_network_problem_not_a_key_problem(tmp_path: Path, status: int) -> None:
    session = FakeSession(FakeResponse(status, "Forbidden by proxy policy"))
    with pytest.raises(NetworkError) as exc:
        make_client(tmp_path, session).fetch_table("detailed", 2024, "state", state_vars())
    assert "network" in str(exc.value).lower() and "not a problem with your key" in str(exc.value)
    assert len(session.calls) == 1  # not retried


def test_a_json_error_object_is_an_api_error(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(200, json.dumps({"error": "bad things"})))
    with pytest.raises(CensusApiError):
        make_client(tmp_path, session).fetch_table("detailed", 2024, "state", state_vars())


# --------------------------------------------------------------------------- cache
def test_a_second_identical_request_is_served_from_the_cache(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse())
    client = make_client(tmp_path, session)
    first = client.fetch_table("detailed", 2024, "state", state_vars())
    second = client.fetch_table("detailed", 2024, "state", state_vars())
    assert len(session.calls) == 1
    pd.testing.assert_frame_equal(first, second)
    other = make_client(tmp_path, FakeSession())  # a fresh client reads the same files
    pd.testing.assert_frame_equal(other.fetch_table("detailed", 2024, "state", state_vars()), first)


def test_refresh_bypasses_the_cache(tmp_path: Path) -> None:
    make_client(tmp_path, FakeSession(FakeResponse())).fetch_table(
        "detailed", 2024, "state", state_vars()
    )
    session = FakeSession(FakeResponse())
    make_client(tmp_path, session, refresh=True).fetch_table(
        "detailed", 2024, "state", state_vars()
    )
    assert len(session.calls) == 1


def test_cache_files_are_named_by_the_hash_of_the_key_free_request(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse())
    make_client(tmp_path, session).fetch_table("detailed", 2024, "state", state_vars())
    url = session.calls[0][0]
    key_free = url.removesuffix(f"&key={KEY}")
    sha = hashlib.sha256(key_free.encode()).hexdigest()
    folder = tmp_path / "raw" / "acs" / "2024"
    names = sorted(p.name for p in folder.iterdir())
    assert names == [f"{sha}.json", f"{sha}.meta.json"]
    meta = json.loads((folder / f"{sha}.meta.json").read_text(encoding="utf-8"))
    assert meta["url"] == key_free and "fetched_at" in meta
    for path in folder.iterdir():  # neither the names nor the contents hold the key
        assert KEY not in path.name and KEY not in path.read_text(encoding="utf-8")
        assert "key=" not in path.read_text(encoding="utf-8")


def test_different_requests_use_different_cache_files(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(text=BODIES["state"]), FakeResponse(text=BODIES["us"]))
    client = make_client(tmp_path, session)
    client.fetch_table("detailed", 2024, "state", state_vars())
    client.fetch_table("detailed", 2024, "us", state_vars())
    assert len(list((tmp_path / "raw" / "acs" / "2024").glob("*.meta.json"))) == 2


def test_error_pages_are_never_cached(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(200, "<html>Invalid Key</html>"))
    with pytest.raises(RejectedKeyError):
        make_client(tmp_path, session).fetch_table("detailed", 2024, "state", state_vars())
    assert not list((tmp_path / "raw").rglob("*.json"))


# --------------------------------------------------------------------------- the key never leaks
FAILURES: list[Any] = [
    lambda url: requests.ConnectionError(
        f"HTTPSConnectionPool(host='api.census.gov'): Max retries exceeded with url: {url}"
    ),
    lambda url: requests.Timeout(f"read timed out calling {url}"),
    lambda url: FakeResponse(500, f"upstream error for {url}"),
    lambda url: FakeResponse(400, f"error: invalid key {KEY}"),
    lambda url: FakeResponse(403, f"proxy refused {url}"),
    lambda url: FakeResponse(200, f"<html>Invalid Key {KEY}</html>"),
    lambda url: FakeResponse(404, f"nothing at {url}"),
]


@pytest.mark.parametrize("make_failure", range(len(FAILURES)))
def test_no_failure_path_leaks_the_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, make_failure: int
) -> None:
    url_with_key = (
        f"https://api.census.gov/data/2024/acs/acs5?get=B01003_001E&for=state:*&key={KEY}"
    )
    outcomes = [FAILURES[make_failure](url_with_key) for _ in range(5)]
    session = FakeSession(*outcomes)
    caplog.set_level(logging.DEBUG)
    exc_text = trace = ""
    try:
        make_client(tmp_path, session).fetch_table("detailed", 2024, "state", state_vars())
    except CensusApiError as exc:
        exc_text, trace = str(exc), traceback.format_exc()
        assert exc.__cause__ is None and exc.__context__ is None  # raised `from None`
    assert exc_text, "expected an error"
    everything = exc_text + trace + caplog.text
    assert KEY not in everything
    assert f"key={KEY}" not in everything
    for path in (tmp_path / "raw").rglob("*"):
        assert KEY not in path.name
        if path.is_file():
            assert KEY not in path.read_text(encoding="utf-8")


def test_log_lines_for_successful_requests_have_no_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    make_client(tmp_path, FakeSession(FakeResponse())).fetch_table(
        "detailed", 2024, "state", state_vars()
    )
    assert caplog.text and KEY not in caplog.text
    assert "api.census.gov" in caplog.text
