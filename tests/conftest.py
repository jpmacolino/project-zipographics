"""Shared test configuration.

Unit, property and UI tests must never touch the network (see CLAUDE.md). This autouse fixture
blocks outbound socket connections to anything except loopback for every test that is not marked
``network``. Loopback stays allowed because asyncio (used by Streamlit's AppTest) opens local
socket pairs on Windows.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Iterator
from typing import Any

import pytest
from hypothesis import HealthCheck, settings

_real_connect = socket.socket.connect


def _is_loopback(address: Any) -> bool:
    host = address[0] if isinstance(address, tuple) else address
    if not isinstance(host, str):
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if request.node.get_closest_marker("network") is not None:
        yield
        return

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        if _is_loopback(address):
            return _real_connect(self, address)
        raise RuntimeError(
            f"Network access attempted in a non-network test: {address!r}. "
            "Mock HTTP with `responses`, or mark the test @pytest.mark.network."
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    yield


# Hypothesis profiles: a quick local default, more examples in CI, a thorough one on demand.
#   HYPOTHESIS_PROFILE=thorough uv run pytest      (or ci); CI=true selects "ci" automatically.
# Tests set no max_examples of their own, so the profile decides how hard they search.
_COMMON = {"deadline": None, "suppress_health_check": [HealthCheck.too_slow]}
settings.register_profile("default", max_examples=25, **_COMMON)
settings.register_profile("ci", max_examples=150, **_COMMON)
settings.register_profile("thorough", max_examples=600, **_COMMON)
settings.load_profile(
    os.environ.get("HYPOTHESIS_PROFILE", "ci" if os.environ.get("CI") else "default")
)
