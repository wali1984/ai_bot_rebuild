import pytest

from app.api.v2 import monitoring_contracts


@pytest.mark.asyncio
async def test_monitoring_routes_are_available_to_authenticated_reader() -> None:
    user = {"role": "viewer", "email": "unit@example.local"}

    assert monitoring_contracts._require_monitoring_reader(user) is user

    payload = await monitoring_contracts.get_monitoring_routes(user)

    assert payload["total"] >= 1
    assert payload["source_type"] == "static_snapshot"
    assert any(route["path"] == "/markets" for route in payload["routes"])


@pytest.mark.asyncio
async def test_monitoring_data_surfaces_are_read_only_contract_metadata() -> None:
    payload = await monitoring_contracts.get_monitoring_data_surfaces({"role": "viewer"})

    assert payload["total"] >= payload["connected"]
    assert payload["source_type"] == "static_snapshot"
    assert any(surface["endpoint"] == "/api/v2/market/overview" for surface in payload["surfaces"])
