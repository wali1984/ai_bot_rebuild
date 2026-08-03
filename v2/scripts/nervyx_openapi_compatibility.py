#!/usr/bin/env python3
"""Capture and compare NERVYX OpenAPI surfaces.

This tool is intentionally read-only against the worktree. It archives the
merge-base tree into a temp directory, captures current OpenAPI from the live
worktree, and tries a clearly-labelled shimmed baseline capture when the
archived base imports route modules that are absent in that same base tree.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
DOCS_DIR = REPO_ROOT / "docs"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
BASE_BRANCH = os.environ.get("NERVYX_OPENAPI_BASE_BRANCH", "codex/nervyx-one-rebrand")


CAPTURE_CODE = r"""
import json
import sys
from pathlib import Path

backend = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(backend))

from app.main import create_app

app = create_app()
print(json.dumps(app.openapi(), sort_keys=True))
"""

STUB_BODY = """\
from fastapi import APIRouter

class _Stub:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return None

router = APIRouter()
stream_router = APIRouter()
public_status_router = APIRouter()

class UserRecord:
    pass

def optional_auth(*args, **kwargs):
    return None

def require_auth(*args, **kwargs):
    return None

def safe_exchange_accounts(*args, **kwargs):
    return []

def safe_user(*args, **kwargs):
    return {}

def __getattr__(name):
    return _Stub
"""

SERVICE_STUB_BODY = """\
class _Stub:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return None

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False

def derive_gates(*args, **kwargs):
    return []

def optional_auth(*args, **kwargs):
    return None

def require_auth(*args, **kwargs):
    return None

def safe_exchange_accounts(*args, **kwargs):
    return []

def safe_user(*args, **kwargs):
    return {}

def __getattr__(name):
    return _Stub
"""


@dataclass
class CaptureResult:
    ok: bool
    spec: dict[str, Any] | None
    stdout: str
    stderr: str
    returncode: int
    shims: list[str]


def run(cmd: list[str], cwd: Path = REPO_ROOT, *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def git_text(args: list[str]) -> str:
    proc = run(["git", *args])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    return proc.stdout.decode("utf-8", "replace").strip()


def capture_openapi(backend_path: Path, *, shims: list[str] | None = None) -> CaptureResult:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_path)
    proc = subprocess.run(
        [sys.executable, "-c", CAPTURE_CODE, str(backend_path)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if proc.returncode != 0:
        return CaptureResult(False, None, proc.stdout, proc.stderr, proc.returncode, shims or [])
    try:
        return CaptureResult(True, json.loads(proc.stdout), proc.stdout, proc.stderr, proc.returncode, shims or [])
    except json.JSONDecodeError as exc:
        return CaptureResult(False, None, proc.stdout, f"{proc.stderr}\nJSON decode failed: {exc}", proc.returncode, shims or [])


def archive_base(base: str, dest: Path) -> Path:
    # The repository root is one directory above this v2 workspace, so running
    # git from REPO_ROOT uses the current `v2/` prefix. The pathspec `backend`
    # therefore archives the historical `v2/backend` tree for both current and
    # merge-base commits without assuming a top-level layout.
    proc = run(["git", "archive", "--format=tar", base, "backend"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as archive:
        archive.extractall(dest)
    return dest / "backend"


def module_to_file(backend_path: Path, module: str) -> Path:
    rel = Path(*module.split("."))
    return backend_path / f"{rel}.py"


def ensure_package(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    init = path / "__init__.py"
    if not init.exists():
        init.write_text(SERVICE_STUB_BODY, encoding="utf-8")


def create_stub(backend_path: Path, module: str, shims: list[str]) -> None:
    allowed_prefixes = ("app.api.", "app.auth", "app.domain", "app.services")
    if not module.startswith(allowed_prefixes):
        return
    package_modules = {"app.auth", "app.domain", "app.services"}
    if module in package_modules:
        package_path = backend_path / Path(*module.split("."))
        if not package_path.exists():
            ensure_package(package_path)
            shims.append(module)
        return
    target = module_to_file(backend_path, module)
    if target.exists():
        return
    parts = module.split(".")
    for index in range(1, len(parts)):
        ensure_package(backend_path / Path(*parts[:index]))
    ensure_package(target.parent)
    target.write_text(SERVICE_STUB_BODY if module.startswith("app.services.") else STUB_BODY, encoding="utf-8")
    shims.append(module)


def referenced_api_modules(backend_path: Path) -> list[str]:
    modules: set[str] = {"app.api.auth_rbac"}
    v2_init = backend_path / "app" / "api" / "v2" / "__init__.py"
    if v2_init.exists():
        text = v2_init.read_text(encoding="utf-8")
        match = re.search(r"from\s+app\.api\.v2\s+import\s+\((.*?)\)", text, flags=re.S)
        if match:
            for name in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", match.group(1)):
                modules.add(f"app.api.v2.{name}")
    return sorted(modules)


def referenced_support_modules(backend_path: Path) -> list[str]:
    modules: set[str] = set()
    import_re = re.compile(r"^\s*from\s+(app\.(?:auth|domain|services)(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s+import\s+", re.M)
    direct_import_re = re.compile(r"^\s*import\s+(app\.(?:auth|domain|services)(?:\.[A-Za-z_][A-Za-z0-9_]*)*)", re.M)
    for file_path in sorted((backend_path / "app").rglob("*.py")):
        text = file_path.read_text(encoding="utf-8", errors="replace")
        modules.update(import_re.findall(text))
        modules.update(direct_import_re.findall(text))
    return sorted(modules)


def capture_base_with_shims(backend_path: Path) -> CaptureResult:
    shims: list[str] = []
    raw = capture_openapi(backend_path, shims=shims)
    if raw.ok:
        return raw

    for module in referenced_api_modules(backend_path):
        create_stub(backend_path, module, shims)
    for module in referenced_support_modules(backend_path):
        create_stub(backend_path, module, shims)

    # Retry, then iteratively shim missing app.api.* / app.services.* imports
    # found deeper in the tree.
    result = capture_openapi(backend_path, shims=shims)
    for _ in range(30):
        if result.ok:
            return result
        missing = re.search(r"No module named '([^']+)'", result.stderr)
        if not missing:
            missing = re.search(r"cannot import name '([^']+)' from '(app\.(?:api|auth|domain|services)(?:\.[^']+)*)'", result.stderr)
            if missing:
                module = f"{missing.group(2)}.{missing.group(1)}"
            else:
                break
        else:
            module = missing.group(1)
        before = len(shims)
        create_stub(backend_path, module, shims)
        if len(shims) == before:
            break
        result = capture_openapi(backend_path, shims=shims)
    result.shims = shims
    return result


def operations(spec: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not spec:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method.lower() not in {"get", "put", "post", "delete", "patch", "options", "head"}:
                continue
            if isinstance(op, dict):
                out[f"{method.upper()} {path}"] = op
    return out


def schema_fields(spec: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    fields: dict[str, dict[str, str]] = {}
    if not spec:
        return fields
    schemas = spec.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        return fields
    for schema_name, schema in schemas.items():
        if not isinstance(schema, dict):
            continue
        props = schema.get("properties", {})
        if not isinstance(props, dict):
            continue
        fields[schema_name] = {}
        for prop_name, prop in props.items():
            if isinstance(prop, dict):
                fields[schema_name][prop_name] = json.dumps(
                    {
                        "type": prop.get("type"),
                        "format": prop.get("format"),
                        "ref": prop.get("$ref"),
                        "anyOf": prop.get("anyOf"),
                        "items": prop.get("items"),
                    },
                    sort_keys=True,
                )
            else:
                fields[schema_name][prop_name] = type(prop).__name__
    return fields


def static_route_inventory(backend_path: Path) -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    decorator = re.compile(r"@(?P<router>[A-Za-z_][A-Za-z0-9_]*)\.(?P<method>get|post|put|patch|delete|options|head)\((?P<args>.*?)\)", re.S)
    for file_path in sorted((backend_path / "app").rglob("*.py")):
        text = file_path.read_text(encoding="utf-8", errors="replace")
        for match in decorator.finditer(text):
            args = match.group("args")
            path_match = re.search(r"['\"]([^'\"]+)['\"]", args)
            routes.append(
                {
                    "file": str(file_path.relative_to(backend_path)),
                    "router": match.group("router"),
                    "method": match.group("method").upper(),
                    "path_literal": path_match.group(1) if path_match else None,
                }
            )
    return {"routes": routes, "route_count": len(routes)}


def compare_specs(base_spec: dict[str, Any] | None, current_spec: dict[str, Any] | None) -> dict[str, Any]:
    base_ops = operations(base_spec)
    current_ops = operations(current_spec)
    removed_ops = sorted(set(base_ops) - set(current_ops))
    added_ops = sorted(set(current_ops) - set(base_ops))
    shared_ops = sorted(set(base_ops) & set(current_ops))

    security_changes = []
    for key in shared_ops:
        before = base_ops[key].get("security")
        after = current_ops[key].get("security")
        if before != after:
            security_changes.append({"operation": key, "before": before, "after": after})

    before_fields = schema_fields(base_spec)
    after_fields = schema_fields(current_spec)
    removed_schemas = sorted(set(before_fields) - set(after_fields))
    added_schemas = sorted(set(after_fields) - set(before_fields))
    removed_fields = []
    type_changes = []
    for schema_name in sorted(set(before_fields) & set(after_fields)):
        before_schema = before_fields[schema_name]
        after_schema = after_fields[schema_name]
        for field in sorted(set(before_schema) - set(after_schema)):
            removed_fields.append({"schema": schema_name, "field": field, "before": before_schema[field]})
        for field in sorted(set(before_schema) & set(after_schema)):
            if before_schema[field] != after_schema[field]:
                type_changes.append(
                    {
                        "schema": schema_name,
                        "field": field,
                        "before": before_schema[field],
                        "after": after_schema[field],
                    }
                )

    return {
        "base_paths": len((base_spec or {}).get("paths", {})),
        "base_operations": len(base_ops),
        "current_paths": len((current_spec or {}).get("paths", {})),
        "current_operations": len(current_ops),
        "removed_operations": removed_ops,
        "added_operations": added_ops,
        "shared_operations": len(shared_ops),
        "removed_component_schemas": removed_schemas,
        "added_component_schemas": added_schemas,
        "removed_component_fields": removed_fields,
        "component_type_changes": type_changes,
        "operation_security_changes": security_changes,
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    DOCS_DIR.mkdir(exist_ok=True)
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    head = git_text(["rev-parse", "HEAD"])
    branch = git_text(["branch", "--show-current"])
    base = git_text(["merge-base", "HEAD", BASE_BRANCH])

    current = capture_openapi(REPO_ROOT / "backend")

    with tempfile.TemporaryDirectory(prefix="nervyx-openapi-base-") as tmp_name:
        base_backend = archive_base(base, Path(tmp_name))
        base_raw = capture_openapi(base_backend)
        base_capture = base_raw if base_raw.ok else capture_base_with_shims(base_backend)
        before_static = static_route_inventory(base_backend)

    current_static = static_route_inventory(REPO_ROOT / "backend")

    before_doc: dict[str, Any]
    if base_capture.ok and base_capture.spec:
        before_doc = base_capture.spec
        before_doc["x-nervyx-capture"] = {
            "generated_at": generated_at,
            "branch": branch,
            "head": head,
            "base": base,
            "base_branch": BASE_BRANCH,
            "status": "captured_with_shims" if base_capture.shims else "captured",
            "shims": base_capture.shims,
            "raw_capture_failed": not base_raw.ok,
            "raw_capture_error": base_raw.stderr if not base_raw.ok else None,
        }
    else:
        before_doc = {
            "status": "capture_failed",
            "generated_at": generated_at,
            "branch": branch,
            "head": head,
            "base": base,
            "base_branch": BASE_BRANCH,
            "result": {
                "returncode": base_capture.returncode,
                "stdout": base_capture.stdout,
                "stderr": base_capture.stderr,
                "shims": base_capture.shims,
            },
        }

    after_doc: dict[str, Any]
    if current.ok and current.spec:
        after_doc = current.spec
        after_doc["x-nervyx-capture"] = {
            "generated_at": generated_at,
            "branch": branch,
            "head": head,
            "status": "captured",
        }
    else:
        after_doc = {
            "status": "capture_failed",
            "generated_at": generated_at,
            "branch": branch,
            "head": head,
            "result": {"returncode": current.returncode, "stdout": current.stdout, "stderr": current.stderr},
        }

    diff = compare_specs(base_capture.spec, current.spec)
    static_removed = []
    before_static_keys = {
        f"{row['method']} {row['path_literal']} {row['file']}" for row in before_static["routes"]
    }
    current_static_keys = {
        f"{row['method']} {row['path_literal']} {row['file']}" for row in current_static["routes"]
    }
    static_removed = sorted(before_static_keys - current_static_keys)

    proof_status = "UNPROVEN"
    if current.ok and base_capture.ok:
        if base_capture.shims:
            proof_status = "PARTIAL_SHIMMED_BASE_UNPROVEN"
        elif diff["removed_operations"] or diff["removed_component_fields"] or diff["component_type_changes"]:
            proof_status = "INCOMPATIBLE_CHANGES_DETECTED"
        else:
            proof_status = "NO_REMOVALS_DETECTED_IN_CAPTURED_OPENAPI"

    summary = {
        "generated_at": generated_at,
        "branch": branch,
        "head": head,
        "base": base,
        "base_branch": BASE_BRANCH,
        "status": proof_status,
        "current_openapi_capture_ok": current.ok,
        "base_openapi_raw_capture_ok": base_raw.ok,
        "base_openapi_capture_ok": base_capture.ok,
        "base_capture_shims": base_capture.shims,
        "base_openapi_error": None if base_capture.ok else base_capture.stderr,
        "diff": diff,
        "before_static_route_count": before_static["route_count"],
        "after_static_route_count": current_static["route_count"],
        "static_removed_route_keys": static_removed,
    }

    write_json(DOCS_DIR / "nervyx-openapi-before.json", before_doc)
    write_json(DOCS_DIR / "nervyx-openapi-after.json", after_doc)
    write_json(ARTIFACTS_DIR / "nervyx-openapi-before-static-routes.json", {
        "generated_at": generated_at,
        "base": base,
        **before_static,
    })
    write_json(ARTIFACTS_DIR / "nervyx-openapi-after-static-routes.json", {
        "generated_at": generated_at,
        "head": head,
        **current_static,
    })
    write_json(ARTIFACTS_DIR / "nervyx-openapi-compatibility-summary.json", summary)

    report = textwrap.dedent(
        f"""\
        # NERVYX OpenAPI Compatibility Report

        - Generated at: `{generated_at}`
        - Status: `{proof_status}`
        - Current branch: `{branch}`
        - Current HEAD: `{head}`
        - Merge base with `{BASE_BRANCH}`: `{base}`
        - Current capture: `{'PASS' if current.ok else 'FAIL'}` with `{diff['current_paths']}` paths and `{diff['current_operations']}` operations.
        - Baseline raw capture: `{'PASS' if base_raw.ok else 'FAIL'}`
        - Baseline shimmed capture: `{'PASS' if base_capture.ok else 'FAIL'}` with `{diff['base_paths']}` paths and `{diff['base_operations']}` operations.
        - Baseline shims: `{', '.join(base_capture.shims) if base_capture.shims else 'none'}`

        ## Diff Summary

        - Removed operations from captured baseline: `{len(diff['removed_operations'])}`
        - Added operations versus captured baseline: `{len(diff['added_operations'])}`
        - Removed component schemas: `{len(diff['removed_component_schemas'])}`
        - Removed component fields: `{len(diff['removed_component_fields'])}`
        - Component type changes: `{len(diff['component_type_changes'])}`
        - Operation security changes: `{len(diff['operation_security_changes'])}`
        - Static fallback removed route keys: `{len(static_removed)}`

        ## Compatibility Verdict

        """
    )
    if proof_status == "PARTIAL_SHIMMED_BASE_UNPROVEN":
        report += (
            "UNPROVEN. The current OpenAPI capture is valid, and the archived merge-base "
            "can be captured only after adding temp-directory shims for route modules that "
            "the merge-base imports but does not contain. The shimmed comparison is useful "
            "diagnostic evidence, but it cannot prove complete endpoint, field, type, or "
            "permission compatibility because missing baseline routers had to be replaced "
            "with empty APIRouter stubs.\n"
        )
    elif proof_status == "NO_REMOVALS_DETECTED_IN_CAPTURED_OPENAPI":
        report += (
            "PASS for captured OpenAPI. No removed operations, component fields, or type "
            "changes were detected in the captured baseline/current comparison. Permission "
            "weakening still requires route-auth inspection beyond OpenAPI security metadata.\n"
        )
    elif proof_status == "INCOMPATIBLE_CHANGES_DETECTED":
        report += (
            "FAIL. Captured OpenAPI comparison detected removals or type changes. Inspect "
            "`artifacts/nervyx-openapi-compatibility-summary.json` before claiming compatibility.\n"
        )
    else:
        report += (
            "UNPROVEN. One or both OpenAPI captures failed. Inspect the JSON artifacts for "
            "the capture errors.\n"
        )
    report += textwrap.dedent(
        """

        ## Artifacts

        - `docs/nervyx-openapi-before.json`
        - `docs/nervyx-openapi-after.json`
        - `artifacts/nervyx-openapi-before-static-routes.json`
        - `artifacts/nervyx-openapi-after-static-routes.json`
        - `artifacts/nervyx-openapi-compatibility-summary.json`
        """
    )
    (DOCS_DIR / "nervyx-openapi-compatibility-report.md").write_text(report, encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if current.ok and base_capture.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
