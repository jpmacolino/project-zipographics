"""Census Data API client for the data build (SPEC §4.5). Build-only: the app never imports this.

Every query needs a free API key, sent as the ``key=`` URL parameter, so every URL that carries it
is a secret. This module therefore:

* reads the key from its constructor only (the build entry point takes it from the environment);
* names cache files by the hash of the *key-free* request and stores key-free URLs in sidecars;
* logs only key-free URLs;
* wraps every failure in its own :class:`CensusApiError` whose text went through
  :func:`zipographics.redact.redact`, and raises it outside any ``except`` block so no chained
  exception (whose message may embed the request URL) reaches a traceback.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import requests

from zipographics.redact import install_redaction, redact

logger = logging.getLogger(__name__)

BASE_URL = "https://api.census.gov/data"
#: Names per request, counting every ``E``, ``M`` and ``EA`` (SPEC §4.5, DECISIONS V3).
MAX_NAMES = 50
TIMEOUT = (10, 120)  # connect, read: a ZCTA-wide response can be several MB
MAX_ATTEMPTS = 5  # one try plus four retries
BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0)
MIN_INTERVAL = 1.0  # at most one request per second

MISSING_KEY_MESSAGE = (
    "CENSUS_API_KEY is not set. The data build needs a free Census Data API key: request one at "
    "https://www.census.gov/data/developers/api-key.html, activate it from the email, then add "
    "the line CENSUS_API_KEY=<your key> to the .env file in the project folder (see "
    ".env.example). The app itself never needs the key."
)
REJECTED_KEY_MESSAGE = (
    "The Census API rejected the API key. Check that it was copied completely and activated "
    "from the email."
)
_BLOCKED_MESSAGE = (
    "Could not reach the Census API: the request was blocked (HTTP {status}). This is a network "
    "or proxy problem, not a problem with your key. Check your network and proxy settings, or "
    "try another network."
)
_UNREACHABLE_MESSAGE = (
    "The Census API could not be reached after {attempts} attempts ({detail}). This is a network "
    "or server problem, not a problem with your key. Try again later."
)

Dataset = Literal["detailed", "profile"]
Level = Literal["zcta", "state", "county", "us"]


class CensusApiError(Exception):
    """A failed Census API call. The message is redacted and safe to print."""


class MissingKeyError(CensusApiError):
    """No API key was provided (exit code 3)."""


class RejectedKeyError(CensusApiError):
    """The API answered as it does for an invalid or unactivated key (exit code 3)."""


class NetworkError(CensusApiError):
    """A network, proxy or server problem, not a key problem (exit code 4)."""


@dataclass(frozen=True, slots=True)
class VarRequest:
    """One variable to fetch: its ``E`` estimate, ``M`` margin of error and, for medians, ``EA``."""

    id: str
    is_median: bool = False
    with_moe: bool = True

    def names(self) -> list[str]:
        names = [f"{self.id}E"]
        if self.with_moe or self.is_median:
            names.append(f"{self.id}M")
        if self.is_median:
            names.append(f"{self.id}EA")
        return names


def chunk_names(
    requests_: Sequence[VarRequest], limit: int = MAX_NAMES, reserved: int = 0
) -> list[list[str]]:
    """Split variables into requests of at most ``limit - reserved`` names, keeping each
    variable's names together and the order unchanged."""
    capacity = limit - reserved
    chunks: list[list[str]] = []
    current: list[str] = []
    for var in requests_:
        names = var.names()
        if len(names) > capacity:
            raise ValueError(f"{var.id} needs {len(names)} names, over the limit of {capacity}")
        if len(current) + len(names) > capacity:
            chunks.append(current)
            current = []
        current += names
    if current:
        chunks.append(current)
    return chunks


@dataclass(frozen=True, slots=True)
class _Geo:
    for_: str
    in_: str | None
    keys: tuple[str, ...]
    name: bool  # NAME is requested for state/county/us only


GEOGRAPHIES: dict[str, _Geo] = {
    # ZCTAs have no parent requirement: all of them in one call (DECISIONS V4)
    "zcta": _Geo("zip%20code%20tabulation%20area:*", None, ("zip code tabulation area",), False),
    "state": _Geo("state:*", None, ("state",), True),
    "county": _Geo("county:*", "state:*", ("state", "county"), True),
    "us": _Geo("us:1", None, ("us",), True),
}


def dataset_url(vintage: int | str, dataset: Dataset) -> str:
    base = f"{BASE_URL}/{vintage}/acs/acs5"
    return base + "/profile" if dataset == "profile" else base


class CensusClient:
    """Fetches ACS tables by geography with chunking, caching, pacing and retries."""

    def __init__(
        self,
        api_key: str | None,
        *,
        cache_root: Path,
        session: Any = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        refresh: bool = False,
        min_interval: float = MIN_INTERVAL,
    ) -> None:
        key = (api_key or "").strip()
        if not key:
            raise MissingKeyError(MISSING_KEY_MESSAGE)
        self.__key = key
        self._cache_root = Path(cache_root)
        self._session = session if session is not None else requests.Session()
        self._clock, self._sleeper, self._jitter = clock, sleeper, jitter
        self._refresh = refresh
        self._min_interval = min_interval
        self._last: float | None = None
        install_redaction([key])  # logs from any library are scrubbed from here on

    def __repr__(self) -> str:
        return "CensusClient(key=<hidden>)"

    # ------------------------------------------------------------------------- public
    def fetch_table(
        self, dataset: Dataset, vintage: int, level: Level, variables: Sequence[VarRequest]
    ) -> pd.DataFrame:
        """All geographies at ``level`` for ``variables``, as strings (ZIPs stay text)."""
        geo = GEOGRAPHIES[level]
        chunks = chunk_names(variables, MAX_NAMES, reserved=1 if geo.name else 0)
        if not chunks:
            raise ValueError("no variables to fetch")
        base = dataset_url(vintage, dataset)
        cache_dir = self._cache_root / "acs" / str(vintage)
        frames: list[pd.DataFrame] = []
        for i, names in enumerate(chunks):
            get = (["NAME"] if geo.name and i == 0 else []) + names
            url = f"{base}?get={','.join(get)}&for={geo.for_}"
            if geo.in_:
                url += f"&in={geo.in_}"
            frames.append(self._frame(self._get(url, cache_dir), geo))
        merged = frames[0]
        for other in frames[1:]:
            other = other.drop(columns=["NAME"], errors="ignore")
            if set(map(tuple, other[list(geo.keys)].values)) != set(
                map(tuple, merged[list(geo.keys)].values)
            ):
                raise CensusApiError(
                    "The Census API returned different geographies for two chunks."
                )
            merged = merged.merge(other, on=list(geo.keys), how="left", validate="one_to_one")
        return merged

    # ------------------------------------------------------------------------- internals
    def _clean(self, text: str) -> str:
        return redact(text, [self.__key])

    def _frame(self, text: str, geo: _Geo) -> pd.DataFrame:
        rows = json.loads(text)
        header = rows[0]
        missing = [k for k in geo.keys if k not in header]
        if missing:
            raise CensusApiError(f"The Census API response has no {', '.join(missing)} column.")
        return pd.DataFrame(rows[1:], columns=header, dtype=object)

    def _get(self, url: str, cache_dir: Path) -> str:
        """JSON text for a key-free request URL: from the cache, or fetched and cached."""
        sha = hashlib.sha256(url.encode("utf-8")).hexdigest()
        path = cache_dir / f"{sha}.json"
        if path.exists() and not self._refresh:
            logger.info("cache hit for %s", url)
            return path.read_text(encoding="utf-8")
        text = self._request(url)
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        meta = {"url": url, "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
        path.with_name(f"{sha}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return text

    def _pace(self) -> None:
        if self._last is not None:
            wait = self._min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleeper(wait)
        self._last = self._clock()

    def _request(self, url: str) -> str:
        """GET with retries. Errors are raised outside ``except`` blocks, so none is chained."""
        full = f"{url}&key={self.__key}"
        detail = ""
        for attempt in range(MAX_ATTEMPTS):
            self._pace()
            logger.info("GET %s", url)
            response = None
            failure: tuple[str, bool] | None = None
            try:
                response = self._session.get(full, timeout=TIMEOUT)
            except requests.RequestException as exc:
                retryable = isinstance(exc, requests.Timeout | requests.ConnectionError)
                failure = (self._clean(f"{type(exc).__name__}: {exc}"), retryable)
            if failure is not None:
                if not failure[1]:
                    raise NetworkError(
                        self._clean(f"Network error calling the Census API: {failure[0]}")
                    )
                detail = failure[0]
            else:
                assert response is not None
                outcome = self._judge(response.status_code, response.text)
                if outcome[0] == "ok":
                    return outcome[1]
                detail = outcome[1]
            if attempt < MAX_ATTEMPTS - 1:
                delay = BACKOFF_SECONDS[attempt] * (1 + 0.25 * self._jitter())
                logger.warning("retrying in %.1fs (%s)", delay, self._clean(detail))
                self._sleeper(delay)
        raise NetworkError(
            self._clean(_UNREACHABLE_MESSAGE.format(attempts=MAX_ATTEMPTS, detail=detail))
        )

    def _judge(self, status: int, body: str) -> tuple[str, str]:
        """("ok", text) or ("retry", detail); raises for errors that must not be retried."""
        if status == 200:
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
                not_json = True
            else:
                not_json = False
            if not_json:  # an HTML error page: how the API answers an invalid or unactivated key
                raise RejectedKeyError(REJECTED_KEY_MESSAGE)
            if isinstance(parsed, dict) or not isinstance(parsed, list) or not parsed:
                raise CensusApiError(self._clean(f"Unexpected Census API response: {body[:200]}"))
            if not isinstance(parsed[0], list):
                raise CensusApiError(self._clean(f"Unexpected Census API response: {body[:200]}"))
            return "ok", body
        if status in (403, 407):  # a proxy or network policy, not the key (DECISIONS V13)
            raise NetworkError(_BLOCKED_MESSAGE.format(status=status))
        if status == 429 or status >= 500:
            return "retry", f"HTTP {status}"
        if status in (400, 401) and "key" in body.lower():
            raise RejectedKeyError(REJECTED_KEY_MESSAGE)
        raise CensusApiError(self._clean(f"The Census API returned HTTP {status}: {body[:200]}"))
