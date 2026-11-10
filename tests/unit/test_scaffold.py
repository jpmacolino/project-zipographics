"""Phase 0 smoke tests: the package imports and the network guard works."""

from __future__ import annotations

import re
import socket

import pytest

import zipographics


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", zipographics.__version__)


def test_network_is_blocked_in_unit_tests() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s, pytest.raises(RuntimeError):
        s.connect(("203.0.113.1", 443))  # TEST-NET-3, never routable
