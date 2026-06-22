from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


BRAND_MODULE_PATH = (
    Path(__file__).resolve().parents[3] / "app" / "api" / "v2" / "brand.py"
)


def load_brand_module():
    module_name = "nervyx_brand_endpoint"
    spec = importlib.util.spec_from_file_location(module_name, BRAND_MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_brand_metadata_is_additive_read_only_presentation_endpoint() -> None:
    brand_module = load_brand_module()
    app = FastAPI()
    app.include_router(brand_module.router, prefix="/api/v2")
    client = TestClient(app)

    response = client.get("/api/v2/brand")

    assert response.status_code == 200
    body = response.json()
    assert body["product_name"] == "NERVYX ONE"
    assert body["descriptor"] == "Adaptive Market Intelligence"
    assert body["tagline"] == "Sense. Decide. Adapt."
    assert body["module_display_names"]["guard"] == "NERVYX GUARD"
    assert body["theme_policy"]["admin_only"] == "Ops Terminal"
    assert body["theme_policy"]["role_source"] == "backend_authoritative"
    assert body["module_route_mapping"]["trade"] == "execute"
    assert body["compatibility_policy"]["renames_payload_keys"] is False
    assert body["data_contract_policy"]["preserve_existing_fields"] is True
    assert body["live_trading_enabled"] is False
    assert body["places_real_order"] is False
    assert "/rebranding" not in response.text


def test_brand_endpoint_imports_no_live_runtime_clients() -> None:
    source = BRAND_MODULE_PATH.read_text(encoding="utf-8")
    banned = (
        "import redis",
        "from redis",
        "import ccxt",
        "from ccxt",
        "subprocess",
        "get_redis",
        "requests",
    )
    assert [needle for needle in banned if needle in source] == []
