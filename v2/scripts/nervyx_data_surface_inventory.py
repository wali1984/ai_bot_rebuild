#!/usr/bin/env python3
"""Build a read-only NERVYX data-surface inventory.

This is an evidence generator for the NERVYX field-parity gate. It does not
import backend services, contact Redis, call exchanges, or mutate runtime state.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "artifacts"
DOCS_DIR = ROOT / "docs"
OPENAPI_AFTER = DOCS_DIR / "nervyx-openapi-after.json"

MAX_RUNTIME_JSON_FILES = 500
MAX_RUNTIME_JSON_BYTES = 2_000_000


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def json_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        return f"ref:{str(schema['$ref']).rsplit('/', 1)[-1]}"
    if "type" in schema:
        value = schema["type"]
        if isinstance(value, list):
            return "|".join(str(v) for v in value)
        return str(value)
    if "anyOf" in schema:
        return "anyOf:" + "|".join(json_type(s) for s in schema.get("anyOf", []) if isinstance(s, dict))
    if "oneOf" in schema:
        return "oneOf:" + "|".join(json_type(s) for s in schema.get("oneOf", []) if isinstance(s, dict))
    if "allOf" in schema:
        return "allOf:" + "|".join(json_type(s) for s in schema.get("allOf", []) if isinstance(s, dict))
    return "unknown"


def walk_openapi_properties(
    schema: dict[str, Any],
    *,
    schema_name: str,
    prefix: str = "",
    required: set[str] | None = None,
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    props = schema.get("properties")
    if not isinstance(props, dict):
        return fields
    required = required or set(schema.get("required") or [])
    for field_name, field_schema in sorted(props.items()):
        if not isinstance(field_schema, dict):
            continue
        field_path = f"{prefix}.{field_name}" if prefix else field_name
        fields.append(
            {
                "schema": schema_name,
                "field_path": field_path,
                "type": json_type(field_schema),
                "required": field_name in required,
            }
        )
        nested_required = set(field_schema.get("required") or [])
        fields.extend(
            walk_openapi_properties(
                field_schema,
                schema_name=schema_name,
                prefix=field_path,
                required=nested_required,
            )
        )
        items = field_schema.get("items")
        if isinstance(items, dict):
            fields.extend(
                walk_openapi_properties(
                    items,
                    schema_name=schema_name,
                    prefix=f"{field_path}[]",
                    required=set(items.get("required") or []),
                )
            )
    return fields


def load_openapi_inventory() -> dict[str, Any]:
    if not OPENAPI_AFTER.exists():
        return {"available": False, "component_fields": [], "operation_responses": []}
    doc = json.loads(OPENAPI_AFTER.read_text(encoding="utf-8"))
    schemas = doc.get("components", {}).get("schemas", {})
    component_fields: list[dict[str, Any]] = []
    for schema_name, schema in sorted(schemas.items()):
        if isinstance(schema, dict):
            component_fields.extend(walk_openapi_properties(schema, schema_name=schema_name))

    operation_responses: list[dict[str, Any]] = []
    for path, path_item in sorted(doc.get("paths", {}).items()):
        if not isinstance(path_item, dict):
            continue
        for method, op in sorted(path_item.items()):
            if method.lower() not in {"get", "post", "put", "patch", "delete"} or not isinstance(op, dict):
                continue
            responses = op.get("responses") or {}
            ok_response = responses.get("200") or responses.get("201") or {}
            content = ok_response.get("content") if isinstance(ok_response, dict) else {}
            json_content = (content or {}).get("application/json", {})
            schema = json_content.get("schema") if isinstance(json_content, dict) else None
            operation_responses.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operation_id": op.get("operationId"),
                    "response_type": json_type(schema) if isinstance(schema, dict) else "unknown",
                }
            )
    return {
        "available": True,
        "path_count": len(doc.get("paths", {})),
        "component_schema_count": len(schemas),
        "component_fields": component_fields,
        "operation_responses": operation_responses,
    }


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def extract_realtime_resources() -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    pattern = re.compile(r"useRealtimeResource\s*<(?P<generic>.*?)>\s*\(\s*\{", re.DOTALL)
    for path in sorted((ROOT / "frontend/src").rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if "/generated/" in rel:
            continue
        text = read_text(path)
        for match in pattern.finditer(text):
            window = text[match.start() : min(len(text), match.start() + 2600)]
            def find_value(name: str) -> str | None:
                value_match = re.search(rf"\b{name}\s*:\s*['\"]([^'\"]+)['\"]", window)
                return value_match.group(1) if value_match else None

            def find_bool(name: str) -> bool | None:
                value_match = re.search(rf"\b{name}\s*:\s*(true|false)", window)
                if not value_match:
                    return None
                return value_match.group(1) == "true"

            def find_int(name: str) -> int | None:
                value_match = re.search(rf"\b{name}\s*:\s*([0-9][0-9_]*)", window)
                if not value_match:
                    return None
                return int(value_match.group(1).replace("_", ""))

            resources.append(
                {
                    "file": rel,
                    "line": line_number(text, match.start()),
                    "generic": re.sub(r"\s+", " ", match.group("generic")).strip(),
                    "url": find_value("url"),
                    "source": find_value("source"),
                    "source_type": find_value("source_type"),
                    "poll_interval_ms": find_int("pollIntervalMs"),
                    "stale_threshold_ms": find_int("staleThresholdMs"),
                    "initial_fetch": find_bool("initialFetch"),
                    "http_fallback": find_bool("httpFallback"),
                    "mode": find_value("mode"),
                }
            )
    return resources


def collect_block(text: str, start: int) -> str:
    brace = text.find("{", start)
    if brace < 0:
        return ""
    depth = 0
    for idx in range(brace, len(text)):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1 : idx]
    return text[brace + 1 :]


def extract_ts_interfaces() -> list[dict[str, Any]]:
    interfaces: list[dict[str, Any]] = []
    interface_pattern = re.compile(r"(?:export\s+)?interface\s+([A-Za-z_][A-Za-z0-9_]*)")
    field_pattern = re.compile(r"^\s*(?:readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)\??\s*:", re.MULTILINE)
    for path in sorted((ROOT / "frontend/src").rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if "/generated/" in rel:
            continue
        text = read_text(path)
        for match in interface_pattern.finditer(text):
            body = collect_block(text, match.start())
            fields = sorted({field.group(1) for field in field_pattern.finditer(body)})
            interfaces.append(
                {
                    "file": rel,
                    "line": line_number(text, match.start()),
                    "name": match.group(1),
                    "field_count": len(fields),
                    "fields": fields,
                }
            )
    return interfaces


def extract_swift_codable_models() -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    struct_pattern = re.compile(r"(?:public\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^{]+)\{")
    prop_pattern = re.compile(r"\b(?:public\s+)?(?:let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*:")
    for base in [ROOT / "mobile/Sources/AIBotV2", ROOT / "mobile/Sources/AIBotV2Core"]:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.swift")):
            rel = path.relative_to(ROOT).as_posix()
            text = read_text(path)
            for match in struct_pattern.finditer(text):
                inheritance = match.group(2)
                if not any(proto in inheritance for proto in ["Codable", "Decodable", "Encodable"]):
                    continue
                body = collect_block(text, match.start())
                fields = sorted({field.group(1) for field in prop_pattern.finditer(body)})
                models.append(
                    {
                        "file": rel,
                        "line": line_number(text, match.start()),
                        "name": match.group(1),
                        "protocols": [part.strip() for part in inheritance.split(",")],
                        "field_count": len(fields),
                        "fields": fields,
                    }
                )
    return models


def extract_backend_route_surfaces() -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    route_pattern = re.compile(
        r"@(?P<router>[A-Za-z_][A-Za-z0-9_]*?)\.(?P<method>get|post|put|patch|delete|websocket)\(\s*['\"](?P<path>[^'\"]+)['\"]",
        re.MULTILINE,
    )
    for base in [ROOT / "backend/app/api", ROOT / "backend/app/main.py"]:
        files = [base] if base.is_file() else sorted(base.rglob("*.py")) if base.exists() else []
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            text = read_text(path)
            for match in route_pattern.finditer(text):
                routes.append(
                    {
                        "file": rel,
                        "line": line_number(text, match.start()),
                        "router": match.group("router"),
                        "method": "WEBSOCKET" if match.group("method") == "websocket" else match.group("method").upper(),
                        "path": match.group("path"),
                    }
                )
    return routes


def extract_backend_read_model_keys() -> list[dict[str, Any]]:
    keys: list[dict[str, Any]] = []
    key_pattern = re.compile(
        r"['\"](?P<key>(?:(?:v2|audit):[A-Za-z0-9_:/{}*?.\\-]+|readonly_market_exchange_data_plane[A-Za-z0-9_:/{}*?.\\-]*))['\"]"
    )
    for base in [ROOT / "backend/app/api", ROOT / "backend/app/services", ROOT / "backend/app/cli"]:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            text = read_text(path)
            seen_in_file: set[str] = set()
            for match in key_pattern.finditer(text):
                key = match.group("key")
                if key in seen_in_file:
                    continue
                seen_in_file.add(key)
                keys.append(
                    {
                        "file": rel,
                        "line": line_number(text, match.start()),
                        "key": key,
                        "category": key.split(":", 2)[1] if key.startswith("v2:") and ":" in key[3:] else key.split(":", 1)[0],
                    }
                )
    return keys


def extract_swift_api_endpoints() -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    endpoint_file = ROOT / "mobile/Sources/AIBotV2/Networking/APIEndpoints.swift"
    if not endpoint_file.exists():
        return endpoints
    text = read_text(endpoint_file)
    endpoint_pattern = re.compile(r"public\s+static\s+let\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"]([^'\"]+)['\"]")
    for match in endpoint_pattern.finditer(text):
        value = match.group(2)
        endpoints.append(
            {
                "file": endpoint_file.relative_to(ROOT).as_posix(),
                "line": line_number(text, match.start()),
                "name": match.group(1),
                "path": value,
                "transport": "websocket" if value.startswith("/ws") or "/ws/" in value else "http",
            }
        )
    return endpoints


def flatten_top_level_json_fields(value: Any) -> list[str]:
    if isinstance(value, dict):
        return sorted(str(k) for k in value.keys())
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return sorted(str(k) for k in value[0].keys())
    return []


def extract_runtime_snapshot_samples() -> dict[str, Any]:
    roots = [
        ROOT / "frontend/public/operator_runtime",
        ROOT / "frontend/public/v2_adaptive_capital_productivity",
        ROOT / "frontend/public/v2_persistent_cuda_trainer_resource_utilization_and_paper_drawdown_guard",
    ]
    rows: list[dict[str, Any]] = []
    skipped_large = 0
    skipped_invalid = 0
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            if len(rows) >= MAX_RUNTIME_JSON_FILES:
                break
            rel = path.relative_to(ROOT).as_posix()
            size = path.stat().st_size
            if size > MAX_RUNTIME_JSON_BYTES:
                skipped_large += 1
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                skipped_invalid += 1
                continue
            fields = flatten_top_level_json_fields(payload)
            rows.append(
                {
                    "file": rel,
                    "bytes": size,
                    "top_level_field_count": len(fields),
                    "top_level_fields": fields,
                }
            )
        if len(rows) >= MAX_RUNTIME_JSON_FILES:
            break
    return {
        "sample_limit": MAX_RUNTIME_JSON_FILES,
        "sample_count": len(rows),
        "skipped_large": skipped_large,
        "skipped_invalid": skipped_invalid,
        "samples": rows,
    }


def main() -> int:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    openapi = load_openapi_inventory()
    realtime_resources = extract_realtime_resources()
    ts_interfaces = extract_ts_interfaces()
    swift_models = extract_swift_codable_models()
    backend_routes = extract_backend_route_surfaces()
    backend_read_model_keys = extract_backend_read_model_keys()
    swift_api_endpoints = extract_swift_api_endpoints()
    runtime_samples = extract_runtime_snapshot_samples()
    artifact = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "status": "IN_PROGRESS_NOT_FULL_PARITY",
        "scope": {
            "openapi_after": OPENAPI_AFTER.relative_to(ROOT).as_posix(),
            "frontend_source": "frontend/src",
            "swift_sources": ["mobile/Sources/AIBotV2", "mobile/Sources/AIBotV2Core"],
            "runtime_snapshot_roots": [
                "frontend/public/operator_runtime",
                "frontend/public/v2_adaptive_capital_productivity",
                "frontend/public/v2_persistent_cuda_trainer_resource_utilization_and_paper_drawdown_guard",
            ],
        },
        "counts": {
            "openapi_component_fields": len(openapi.get("component_fields", [])),
            "openapi_operation_responses": len(openapi.get("operation_responses", [])),
            "realtime_resource_subscriptions": len(realtime_resources),
            "frontend_interfaces": len(ts_interfaces),
            "frontend_interface_fields": sum(row["field_count"] for row in ts_interfaces),
            "swift_codable_models": len(swift_models),
            "swift_codable_fields": sum(row["field_count"] for row in swift_models),
            "swift_api_endpoints": len(swift_api_endpoints),
            "backend_route_surfaces": len(backend_routes),
            "backend_read_model_keys": len(backend_read_model_keys),
            "backend_read_model_key_categories": len({row["category"] for row in backend_read_model_keys}),
            "runtime_snapshot_samples": runtime_samples["sample_count"],
            "runtime_snapshot_top_level_fields": sum(row["top_level_field_count"] for row in runtime_samples["samples"]),
        },
        "openapi": openapi,
        "realtime_resources": realtime_resources,
        "frontend_interfaces": ts_interfaces,
        "swift_codable_models": swift_models,
        "swift_api_endpoints": swift_api_endpoints,
        "backend_route_surfaces": backend_routes,
        "backend_read_model_keys": backend_read_model_keys,
        "runtime_snapshot_samples": runtime_samples,
        "known_gaps": [
            "Does not yet classify every field by permission, destination, formatter, unit, null behavior, freshness threshold, and test status.",
            "Does not execute live WebSocket frames or verify rendered field values.",
            "Enumerates backend Redis/read-model key literals but does not yet expand every live Redis value field.",
            "Does not prove iOS/watchOS rendered parity because native macOS validation is blocked.",
        ],
    }
    summary = {
        "generated_at_utc": artifact["generated_at_utc"],
        "status": artifact["status"],
        "counts": artifact["counts"],
        "known_gaps": artifact["known_gaps"],
    }
    inventory_path = ARTIFACTS_DIR / "nervyx-data-surface-inventory.json"
    summary_path = ARTIFACTS_DIR / "nervyx-data-surface-inventory-summary.json"
    inventory_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
