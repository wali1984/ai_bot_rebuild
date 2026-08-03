"""Builders for Redis-backed enterprise UI snapshots."""

from __future__ import annotations

from typing import Any

from app.services.realtime import build_ui_snapshot
from app.services.realtime.resource_registry import resource_names


def build_ui_snapshot_for_resource(client: Any, resource: str) -> dict[str, Any]:
    return build_ui_snapshot(client, resource, use_materialized=False)


def build_all_ui_snapshots(client: Any) -> dict[str, dict[str, Any]]:
    return {
        resource: build_ui_snapshot(client, resource, use_materialized=False)
        for resource in resource_names()
    }
