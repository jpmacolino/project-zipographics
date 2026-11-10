"""Live Census API checks (marker ``network``): run manually and sparingly (SPEC §9.1).

    uv run pytest -m network

They need the free API key for the data calls: the key is read from the environment (or the
repository's ``.env`` through python-dotenv, exactly as ``scripts/build_data.py`` does). A missing
key skips the keyed tests; nothing here prints the key.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from zipographics import config, metrics
from zipographics.census_api import CensusClient, VarRequest
from zipographics.data_build import resolve_variables
from zipographics.metrics import MedianSpec

pytestmark = pytest.mark.network
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> CensusClient:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    key = os.environ.get("CENSUS_API_KEY", "")
    if not key.strip():
        pytest.skip("CENSUS_API_KEY is not set (see .env.example)")
    return CensusClient(key, cache_root=tmp_path_factory.mktemp("live_raw"))


@pytest.fixture(scope="module")
def variables(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, dict[str, str]]]:
    """variables.json needs no key, so this works without one."""
    holder = CensusClient("unused-for-metadata", cache_root=tmp_path_factory.mktemp("live_meta"))
    vintage = config.DEFAULT_VINTAGE
    return {
        "detailed": holder.fetch_variables(vintage, "detailed"),
        "profile": holder.fetch_variables(vintage, "profile"),
    }


def test_the_real_registry_resolves_against_the_real_variables_json(variables: dict) -> None:
    brackets = [m.spec for m in metrics.REGISTRY if isinstance(m.spec, MedianSpec)]
    resolved = resolve_variables(metrics.VARIABLES, variables, brackets)
    assert set(resolved) == set(metrics.VARIABLES)
    moved = sorted(k for k, v in resolved.items() if v.moved)
    assert moved == [], f"IDs whose label moved: {moved}"


def test_one_national_row_comes_back_for_total_population(client: CensusClient) -> None:
    frame = client.fetch_table("detailed", config.DEFAULT_VINTAGE, "us", [VarRequest("B01003_001")])
    assert len(frame) == 1 and frame.loc[0, "us"] == "1"
    assert int(frame.loc[0, "B01003_001E"]) > 300_000_000


def test_states_include_puerto_rico_only_in_the_state_level_not_the_nation(
    client: CensusClient,
) -> None:
    states = client.fetch_table(
        "detailed", config.DEFAULT_VINTAGE, "state", [VarRequest("B01003_001", with_moe=False)]
    )
    assert "72" in set(states["state"]) and len(states) >= 52
