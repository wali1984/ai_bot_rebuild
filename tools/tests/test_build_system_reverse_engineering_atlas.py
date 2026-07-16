from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "build_system_reverse_engineering_atlas.py"
SPEC = importlib.util.spec_from_file_location("system_atlas_builder", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
atlas = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = atlas
SPEC.loader.exec_module(atlas)


def test_python_atlas_captures_nested_symbols_routes_keys_fields_and_side_effects() -> None:
    source = '''
import os
from app.services.worker import helper
from pydantic import BaseModel

STATUS_KEY = "v2:worker:status:{symbol}"

class Payload(BaseModel):
    event_time: str
    available_at: str
    price: float = 0.0

class Worker:
    def local(self, row: dict) -> float:
        return row.get("price", 0.0)

    async def run(self, redis_client, row: dict) -> None:
        token = os.getenv("PROVIDER_TOKEN")
        value = self.local(row)
        redis_client.set(STATUS_KEY, {"event_time": row["event_time"], "value": value})
        helper(value)

@router.get("/api/v2/worker")
def read_worker() -> dict:
    return {"available_at": "now"}
'''
    result = atlas.parse_python("v2/backend/app/services/example.py", source)
    assert result["parse_status"] == "ok"
    symbols = {item["qualname"]: item for item in result["symbols"]}
    assert {"Payload", "Worker.local", "Worker.run", "read_worker"} <= set(symbols)
    assert symbols["Worker.run"]["env_reads"] == ["PROVIDER_TOKEN"]
    assert symbols["Worker.run"]["redis_writes"] == ["v2:worker:status:{symbol}"]
    assert "redis_write" in symbols["Worker.run"]["side_effects"]
    assert "event_time" in symbols["Worker.run"]["temporal_fields"]
    assert result["api_routes"][0]["path"] == "/api/v2/worker"
    contract = next(item for item in result["contracts"] if item["name"] == "Payload")
    assert [item["name"] for item in contract["fields"]] == ["event_time", "available_at", "price"]
    env = result["env_refs"][0]
    assert env["key"] == "PROVIDER_TOKEN"
    assert env["default"] == {"state": "redacted"}


def test_import_and_call_resolution_preserve_unresolved_edges() -> None:
    helper_source = "def helper(value: int) -> int:\n    return value + 1\n"
    caller_source = "from v2.backend.app.services.helper import helper\n\ndef run():\n    return helper(1)\n"
    helper = atlas.parse_python("v2/backend/app/services/helper.py", helper_source)
    caller = atlas.parse_python("v2/backend/app/services/caller.py", caller_source)
    modules = [helper, caller]
    edges, reverse = atlas.resolve_import_graph(modules, {item["path"] for item in modules})
    resolved = [item for item in edges if item["resolved"]]
    assert resolved and resolved[0]["to_path"] == "v2/backend/app/services/helper.py"
    assert "v2/backend/app/services/caller.py" in reverse["v2/backend/app/services/helper.py"]
    call_edges, callers, callees = atlas.resolve_python_calls(modules, edges)
    helper_id = "v2/backend/app/services/helper.py:helper@1"
    run_id = "v2/backend/app/services/caller.py:run@3"
    assert run_id in callers[helper_id]
    assert helper_id in callees[run_id]
    assert any(item["callee_symbol_id"] == helper_id for item in call_edges)


def test_secret_paths_and_static_config_values_are_redacted() -> None:
    assert atlas.is_secret_path("v2/.env.local")
    assert atlas.is_secret_path("v2/secrets/provider.json")
    assert atlas.is_secret_path("v2/backend/auth_users.json")
    parsed = atlas.parse_static_config(
        "v2/config/example.json",
        '{"timeout": 5, "api_key": "do-not-record", "nested": {"enabled": true}}',
        "json",
    )
    assert parsed is not None
    values = {item["key"]: item["value"] for item in parsed["entries"]}
    assert values["timeout"] == 5
    assert values["api_key"] == "<redacted>"
    assert values["nested.enabled"] is True


def test_swift_and_shell_heuristics_keep_source_locations() -> None:
    swift = atlas.parse_swift(
        "v2/mobile/Sources/AIBotV2Core/Fixture.swift",
        '''
import Foundation
struct Quote: Codable {
    let event_time: String
    let price: Double
    func normalized() -> Double { price }
}
let route = "/api/v2/quote"
''',
    )
    assert any(item["qualname"] == "Quote" for item in swift["symbols"])
    assert any(item["qualname"].endswith("normalized") for item in swift["symbols"])
    assert swift["contracts"][0]["fields"][0]["name"] == "event_time"
    assert swift["api_refs"][0]["path"] == "/api/v2/quote"
    assert len({item["symbol_id"] for item in swift["symbols"]}) == len(swift["symbols"])
    assert all(f"@{item['line_start']}" in item["symbol_id"] for item in swift["symbols"])

    shell = atlas.parse_shell(
        "scripts/example.sh",
        """#!/usr/bin/env bash
run_worker() {
  python3 -m app.worker --url "${API_URL}"
}
""",
    )
    assert shell["symbols"][0]["qualname"] == "run_worker"
    assert shell["env_refs"][0]["key"] == "API_URL"
    assert shell["commands"][0]["command"].startswith("python3")


def test_swift_conditional_declarations_and_extensions_have_unique_ids() -> None:
    swift = atlas.parse_swift(
        "v2/mobile/Sources/AIBotV2Core/Conditional.swift",
        '''\
#if FIRST
struct Quote {
    let price: Double
}
#else
struct Quote {
    let price: Double
}
#endif
extension Quote {
    func normalized() -> Double { price }
}
extension Quote {
    func rounded() -> Double { price.rounded() }
}
''',
    )
    symbol_ids = [item["symbol_id"] for item in swift["symbols"]]
    contract_ids = [item["contract_id"] for item in swift["contracts"]]
    assert len(symbol_ids) == len(set(symbol_ids))
    assert len(contract_ids) == len(set(contract_ids))
    assert all("@" in item for item in symbol_ids + contract_ids)


def test_output_boundary_redacts_credentials_and_defaults_are_json_safe() -> None:
    sentinel_password = "correct-horse-battery-staple"
    sentinel_token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    sentinel_aws = "AKIA" + "ABCDEFGHIJKLMNOP"
    source = f'''\
from pydantic import BaseModel

DATABASE_URL = "postgresql://audit:{sentinel_password}@db.internal/aibot"
API_TOKEN = "{sentinel_token}"
AWS_KEY = "{sentinel_aws}"

class Credentials(BaseModel):
    password: str = "{sentinel_password}"

def connect(password: str = "{sentinel_password}") -> str:
    """Use postgresql://audit:{sentinel_password}@db.internal/aibot."""
    return API_TOKEN
'''
    parsed = atlas.parse_python("v2/backend/app/fixture.py", source)
    systemd = atlas.parse_systemd(
        "ops/fixture.service",
        f'''[Service]
Environment="API_TOKEN={sentinel_token}" "MODE=paper"
EnvironmentFile=-/run/secrets/aibot.env
ExecStart=/usr/bin/worker --password {sentinel_password}
''',
    )
    static = atlas.parse_static_config(
        "config/fixture.json",
        json.dumps(
            {
                "database_url": f"postgresql://audit:{sentinel_password}@db.internal/aibot",
                "api_token": sentinel_token,
            }
        ),
        "json",
    )
    contextual = {
        "record": {
            "name": "ConfigEntry",
            "key": "api_token",
            "value": sentinel_password,
        },
        "numeric": {"api_token": 731934},
        "tokens": [sentinel_password],
        "username_only_uri": "https://opaque-user@example.invalid/private",
        "webhook": "https://hooks.slack.com/services/" + "T00000000/B00000000/" + "X" * 24,
        "secret_shaped_key": {sentinel_token: sentinel_password},
        "benign_metadata": {"signature": "sha256", "token_count": 812345},
    }
    output = atlas.json_safe_value(
        {"python": parsed, "systemd": systemd, "static": static, "contextual": contextual}
    )
    rendered = json.dumps(output, sort_keys=True)
    assert sentinel_password not in rendered
    assert sentinel_token not in rendered
    assert sentinel_aws not in rendered
    assert not atlas.contains_secret_shape(output)
    assert "<redacted>" in rendered
    assert "<redacted-userinfo>" in rendered
    assert "opaque-user" not in rendered
    assert "731934" not in rendered
    assert "hooks.slack.com/services/T00000000" not in rendered
    assert '"signature": "sha256"' in rendered
    assert '"token_count": 812345' in rendered
    assert atlas.is_sensitive_label("providerApiToken")
    assert atlas.is_sensitive_label("credentials")
    assert not atlas.is_sensitive_label("signature")
    assert not atlas.is_sensitive_label("token_count")
    assert {item["key"] for item in systemd["env_refs"]} == {"API_TOKEN", "MODE"}

    defaults = [
        atlas.safe_default(__import__("ast").parse("{3, 1}", mode="eval").body),
        atlas.safe_default(__import__("ast").parse("b'secret bytes'", mode="eval").body),
        atlas.safe_default(__import__("ast").parse("1 + 2j", mode="eval").body),
        atlas.safe_default(__import__("ast").parse("...", mode="eval").body),
        atlas.safe_default(__import__("ast").parse("1e999", mode="eval").body),
    ]
    rendered_defaults = json.dumps(defaults, allow_nan=False)
    assert "positive_infinity" in rendered_defaults
    nonfinite_complex = atlas.json_safe_value(complex(float("inf"), float("nan")))
    assert "positive_infinity" in json.dumps(nonfinite_complex, allow_nan=False)
    collision = atlas.json_safe_value(
        {
            sentinel_token: "first",
            "ghp_ZYXWVUTSRQPONMLKJIHGFEDCBA987654": "second",
            "<redacted-secret-like-value>#sanitized-collision-2": "third",
        }
    )
    assert len(collision) == 3
    assert len(set(collision)) == 3
    assert sentinel_token not in json.dumps(collision)


def test_call_resolution_does_not_resolve_unrelated_dotted_receivers() -> None:
    source = '''\
import subprocess

def run() -> None:
    return None

def caller() -> None:
    run()
    subprocess.run(["true"])
'''
    module = atlas.parse_python("fixture.py", source)
    edges, _ = atlas.resolve_import_graph([module], {"fixture.py"})
    call_edges, _, _ = atlas.resolve_python_calls([module], edges)
    by_raw = {item["raw_call"]: item for item in call_edges if item["caller_symbol_id"].endswith("caller@6")}
    assert by_raw["run"]["callee_symbol_id"] == "fixture.py:run@3"
    assert by_raw["subprocess.run"]["callee_symbol_id"] is None
    assert by_raw["subprocess.run"]["resolution_reason"] == "dynamic_or_external"


def test_duplicate_python_definitions_have_unique_ids_and_are_not_guessed() -> None:
    source = '''\
def duplicate():
    return 1

def duplicate():
    return 2

def caller():
    return duplicate()
'''
    module = atlas.parse_python("duplicate.py", source)
    duplicate_ids = [item["symbol_id"] for item in module["symbols"] if item["qualname"] == "duplicate"]
    assert duplicate_ids == ["duplicate.py:duplicate@1", "duplicate.py:duplicate@4"]
    assert len(duplicate_ids) == len(set(duplicate_ids))
    import_edges, _ = atlas.resolve_import_graph([module], {"duplicate.py"})
    call_edges, _, _ = atlas.resolve_python_calls([module], import_edges)
    edge = next(item for item in call_edges if item["raw_call"] == "duplicate")
    assert edge["callee_symbol_id"] is None


def test_function_signatures_preserve_benign_defaults_and_redact_sensitive_ones() -> None:
    parsed = atlas.parse_python(
        "defaults.py",
        '''\
def configure(timeout: int = 30, mode: str = "paper", password: str = "opaque-value"):
    return timeout, mode, password
''',
    )
    signature = next(
        item["signature"] for item in parsed["symbols"] if item["qualname"] == "configure"
    )
    assert "timeout: int=30" in signature
    assert "mode: str='paper'" in signature
    assert "password: str=<default:redacted>" in signature
    assert "opaque-value" not in signature


def test_redis_operational_sites_are_not_duplicated_or_misclassified() -> None:
    source = '''\
STATUS_KEY = "v2:worker:status:{symbol}"

def work(redis_client):
    first = redis_client.get("v2:worker:status:{symbol}")
    redis_client.set("v2:worker:status:{symbol}", first)
'''
    parsed = atlas.parse_python("worker.py", source)
    reads = [item for item in parsed["redis_ops"] if item["access"] == "read"]
    writes = [item for item in parsed["redis_ops"] if item["access"] == "write"]
    unknown = [item for item in parsed["redis_ops"] if item["access"] == "declared_unknown"]
    assert len(reads) == 1
    assert len(writes) == 1
    assert len(unknown) == 1
    assert unknown[0]["operation"] == "literal_reference"
    assert all(isinstance(item["column"], int) for item in parsed["redis_ops"])
    assert all(isinstance(item["end_line"], int) for item in parsed["redis_ops"])
    assert all(isinstance(item["end_column"], int) for item in parsed["redis_ops"])

    same_line = atlas.parse_python(
        "patterns.py",
        'patterns = {"v2:*": count(redis_client, "v2:*")}\n',
    )
    sites = atlas.aggregate_sites(same_line["redis_ops"], "key_pattern")[0]["sites"]
    assert len(sites) == 2
    assert len({item["column"] for item in sites}) == 2


def test_relative_package_imports_and_ambiguous_aliases_are_deterministic() -> None:
    package = atlas.parse_python(
        "pkg/subpkg/__init__.py",
        "from .child import helper\n",
    )
    child = atlas.parse_python("pkg/subpkg/child.py", "def helper():\n    return 1\n")
    edges, _ = atlas.resolve_import_graph(
        [package, child],
        {"pkg/subpkg/__init__.py", "pkg/subpkg/child.py"},
    )
    edge = next(item for item in edges if item["from_path"] == "pkg/subpkg/__init__.py")
    assert edge["external_module"] is None
    assert edge["to_path"] == "pkg/subpkg/child.py"
    assert edge["candidate_paths"] == ["pkg/subpkg/child.py"]

    aliases = atlas.module_aliases("v2/backend/app/mod.py")
    assert aliases == {"v2.backend.app.mod", "backend.app.mod", "app.mod"}


def test_environment_and_filesystem_side_effect_detection_is_specific() -> None:
    source = '''\
import json
import os

def inspect(file_handle):
    required = os.environ["REQUIRED_MODE"]
    text = json.dumps({"mode": required})
    json.dump({"mode": required}, file_handle)
    return text
'''
    parsed = atlas.parse_python("fixture.py", source)
    symbol = next(item for item in parsed["symbols"] if item["qualname"] == "inspect")
    assert symbol["env_reads"] == ["REQUIRED_MODE"]
    assert symbol["side_effects"] == ["filesystem_write"]


def _initialize_fixture_repo(
    tmp_path: Path,
    *,
    mutate_during_typescript: bool = False,
    mutate_analyzer_during_typescript: bool = False,
) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "source.py"
    source.write_text(
        "from pydantic import BaseModel\n\nclass Event(BaseModel):\n    event_time: str\n",
        encoding="utf-8",
    )
    (repo / "auth_users.json").write_text(
        '{"username":"operator","password":"NEVER-SERIALIZE-THIS"}\n',
        encoding="utf-8",
    )
    (repo / "source_link.py").symlink_to("source.py")
    (repo / "package-lock.json").write_text(
        '{"name":"atlas-fixture","lockfileVersion":3,"packages":{}}\n',
        encoding="utf-8",
    )
    builder = repo / "fake_typescript_builder.cjs"
    mutation = (
        'require("fs").appendFileSync(require("path").join(repo, "source.py"), "\\n# changed during build\\n");\n'
        if mutate_during_typescript
        else ""
    )
    analyzer_mutation = (
        'fs.appendFileSync(builderPath, "\\n// changed during build\\n");\n'
        if mutate_analyzer_during_typescript
        else ""
    )
    builder.write_text(
        '''const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const args = process.argv.slice(2);
const out = args[args.indexOf("--out") + 1];
const repo = args[args.indexOf("--repo-root") + 1];
'''
        + mutation
        + '''const builderPath = path.join(repo, "fake_typescript_builder.cjs");
const builderSha = crypto.createHash("sha256").update(fs.readFileSync(builderPath)).digest("hex");
'''
        + analyzer_mutation
        + '''const lockPath = path.join(repo, "package-lock.json");
const lockSha = crypto.createHash("sha256").update(fs.readFileSync(lockPath)).digest("hex");
const provenance = {
  verified: true, version: "fixture-1.0.0", lockfile: "package-lock.json",
  lockfile_version: 3, lockfile_sha256: lockSha,
  package_path: "node_modules/typescript",
  package_manifest_sha256: "a".repeat(64), compiler_sha256: "b".repeat(64),
  integrity: null
};
const moduleSymbol = {
  symbol_id: "fake_typescript_builder.cjs:<module>",
  path: "fake_typescript_builder.cjs",
  qualname: "<module>"
};
const modules = [{
  path: "fake_typescript_builder.cjs", sha256: builderSha, symbols: [moduleSymbol], contracts: [],
  calls: [], imports: [], env_references: [], api_references: [], route_definitions: [],
  parse_diagnostics: []
}];
fs.writeFileSync(out, JSON.stringify({
  metadata: {
    parser: "typescript@fixture-1.0.0", tracked_source_files: modules.length,
    typescript_compiler_snapshot_consistent: true,
    typescript_compiler: provenance, typescript_compiler_end: {...provenance}
  }, modules,
  symbols: [moduleSymbol], contracts: [], calls: [], imports: [],
  api_references: [], env_references: [], route_definitions: [], parse_diagnostics: []
}));
''',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Atlas Test",
            "-c",
            "user.email=atlas@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=repo,
        check=True,
    )
    return repo, builder


def test_build_excludes_secret_contents_handles_symlinks_and_emits_integrity_manifest(tmp_path: Path) -> None:
    repo, builder = _initialize_fixture_repo(tmp_path)
    out = repo / "atlas"
    result = atlas.build(repo, out, typescript_builder=builder)
    assert result["metadata"]["snapshot_consistent"] is True
    assert result["published"] is True
    assert result["metadata"]["working_tree_status_scope"] == (
        "tracked_and_untracked_paths_excluding_generated_output_and_staging_prefixes"
    )
    assert result["metadata"]["working_tree_status_unchanged"] is True
    assert result["metadata"]["git_tracked_path_count"] == 5
    assert result["metadata"]["secret_paths_excluded"] == ["auth_users.json"]

    catalog = json.loads((out / "FILE_MODULE_CATALOG.json").read_text(encoding="utf-8"))
    by_path = {item["path"]: item for item in catalog["files"]}
    secret = by_path["auth_users.json"]
    assert secret["size_bytes"] is None
    assert secret["sha256"] is None
    assert secret["content_state"] == "excluded_secret_path_not_read_or_hashed"
    symlink = by_path["source_link.py"]
    assert symlink["path_kind"] == "symlink"
    assert symlink["sha256"] is None

    fields = json.loads((out / "DATA_CONTRACT_FIELD_REGISTRY.json").read_text(encoding="utf-8"))["fields"]
    event_time = next(item for item in fields if item["field"] == "event_time")
    declarations = [
        item for item in event_time["write_or_declaration_sites"] if item["access"] == "contract_declaration"
    ]
    assert len(declarations) == 1

    manifest = json.loads((out / "ATLAS_BUILD_MANIFEST.json").read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        data = (out / artifact["name"]).read_bytes()
        assert len(data) == artifact["size_bytes"]
        assert atlas.sha256_bytes(data) == artifact["sha256"]
    all_output = "".join(path.read_text(encoding="utf-8") for path in out.iterdir())
    assert "NEVER-SERIALIZE-THIS" not in all_output


def test_build_detects_a_tracked_input_mutated_during_analysis(tmp_path: Path) -> None:
    repo, builder = _initialize_fixture_repo(tmp_path, mutate_during_typescript=True)
    out = repo / "atlas"
    out.mkdir()
    prior = out / "ATLAS_METADATA.json"
    prior.write_text('{"generation":"prior"}\n', encoding="utf-8")
    result = atlas.build(repo, out, typescript_builder=builder)
    assert result["metadata"]["snapshot_consistent"] is False
    assert result["published"] is False
    assert result["metadata"]["content_snapshot_validation"]["content_inputs_unchanged"] is False
    assert {item["path"] for item in result["metadata"]["content_snapshot_validation"]["changed_inputs"]} == {
        "source.py"
    }
    assert prior.read_text(encoding="utf-8") == '{"generation":"prior"}\n'


def test_build_detects_an_analyzer_mutated_during_analysis(tmp_path: Path) -> None:
    repo, builder = _initialize_fixture_repo(
        tmp_path,
        mutate_analyzer_during_typescript=True,
    )
    out = repo / "atlas"
    out.mkdir()
    prior = out / "ATLAS_METADATA.json"
    prior.write_text('{"generation":"prior"}\n', encoding="utf-8")

    result = atlas.build(repo, out, typescript_builder=builder)

    assert result["metadata"]["snapshot_consistent"] is False
    assert result["published"] is False
    assert result["metadata"]["analyzer_inputs_unchanged"] is False
    assert prior.read_text(encoding="utf-8") == '{"generation":"prior"}\n'


def test_build_rejects_an_analyzer_that_omits_tracked_typescript(tmp_path: Path) -> None:
    repo, builder = _initialize_fixture_repo(tmp_path)
    builder.write_text(
        '''const fs = require("fs");
const args = process.argv.slice(2);
const out = args[args.indexOf("--out") + 1];
fs.writeFileSync(out, JSON.stringify({
  metadata: {parser: "faulty-fixture", tracked_source_files: 0},
  modules: [], symbols: [], contracts: [], api_references: [], env_references: []
}));
''',
        encoding="utf-8",
    )
    result = atlas.build(repo, repo / "atlas", typescript_builder=builder)
    reasons = {
        item["reason"] for item in result["metadata"]["typescript_snapshot_hash_mismatches"]
    }
    assert result["metadata"]["snapshot_consistent"] is False
    assert result["published"] is False
    assert reasons == {
        "missing_typescript_module",
        "typescript_reported_source_count_mismatch",
    }


def test_build_rejects_a_hash_complete_but_structurally_empty_typescript_module(
    tmp_path: Path,
) -> None:
    repo, builder = _initialize_fixture_repo(tmp_path)
    builder.write_text(
        '''const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const args = process.argv.slice(2);
const out = args[args.indexOf("--out") + 1];
const repo = args[args.indexOf("--repo-root") + 1];
const builderPath = path.join(repo, "fake_typescript_builder.cjs");
const builderSha = crypto.createHash("sha256").update(fs.readFileSync(builderPath)).digest("hex");
const lockPath = path.join(repo, "package-lock.json");
const lockSha = crypto.createHash("sha256").update(fs.readFileSync(lockPath)).digest("hex");
const provenance = {
  verified: true, version: "fixture-1.0.0", lockfile: "package-lock.json",
  lockfile_version: 3, lockfile_sha256: lockSha,
  package_path: "node_modules/typescript",
  package_manifest_sha256: "a".repeat(64), compiler_sha256: "b".repeat(64),
  integrity: null
};
const modules = [{
  path: "fake_typescript_builder.cjs", sha256: builderSha, symbols: [], contracts: [],
  calls: [], imports: [], env_references: [], api_references: [], route_definitions: [],
  parse_diagnostics: []
}];
fs.writeFileSync(out, JSON.stringify({
  metadata: {
    parser: "typescript@fixture-1.0.0", tracked_source_files: 1,
    typescript_compiler_snapshot_consistent: true,
    typescript_compiler: provenance, typescript_compiler_end: {...provenance}
  }, modules, symbols: [], contracts: [], calls: [], imports: [],
  api_references: [], env_references: [], route_definitions: [], parse_diagnostics: []
}));
''',
        encoding="utf-8",
    )

    result = atlas.build(repo, repo / "atlas", typescript_builder=builder)
    hash_reasons = {
        item["reason"] for item in result["metadata"]["typescript_snapshot_hash_mismatches"]
    }
    structure_reasons = {
        item["reason"] for item in result["metadata"]["typescript_structure_mismatches"]
    }
    assert hash_reasons == set()
    assert structure_reasons == {"missing_typescript_module_scope_symbol"}
    assert result["metadata"]["snapshot_consistent"] is False
    assert result["published"] is False


def test_build_rejects_false_compiler_snapshot_provenance(tmp_path: Path) -> None:
    repo, builder = _initialize_fixture_repo(tmp_path)
    builder.write_text(
        builder.read_text(encoding="utf-8").replace(
            "typescript_compiler_snapshot_consistent: true",
            "typescript_compiler_snapshot_consistent: false",
        ),
        encoding="utf-8",
    )
    result = atlas.build(repo, repo / "atlas", typescript_builder=builder)
    reasons = {
        item["reason"] for item in result["metadata"]["typescript_provenance_mismatches"]
    }
    assert reasons == {"typescript_compiler_snapshot_not_revalidated"}
    assert result["metadata"]["snapshot_consistent"] is False
    assert result["published"] is False


def test_build_rejects_false_tampered_or_parser_mismatched_compiler_provenance(
    tmp_path: Path,
) -> None:
    repo, builder = _initialize_fixture_repo(tmp_path)
    source = builder.read_text(encoding="utf-8")
    source = source.replace("verified: true", "verified: false", 1)
    source = source.replace(
        'parser: "typescript@fixture-1.0.0"',
        'parser: "typescript@fixture-2.0.0"',
        1,
    )
    source = source.replace(
        "typescript_compiler_end: {...provenance}",
        'typescript_compiler_end: {...provenance, compiler_sha256: "c".repeat(64)}',
        1,
    )
    builder.write_text(source, encoding="utf-8")

    result = atlas.build(repo, repo / "atlas", typescript_builder=builder)
    reasons = {
        item["reason"] for item in result["metadata"]["typescript_provenance_mismatches"]
    }
    assert reasons == {
        "typescript_compiler_provenance_schema_invalid",
        "typescript_parser_version_mismatch",
        "typescript_compiler_start_end_provenance_mismatch",
    }
    assert result["metadata"]["snapshot_consistent"] is False
    assert result["published"] is False


def test_failed_analyzer_does_not_publish_partial_artifacts(tmp_path: Path) -> None:
    repo, builder = _initialize_fixture_repo(tmp_path)
    builder.write_text('process.exit(17);\n', encoding="utf-8")
    out = repo / "atlas"
    out.mkdir()
    prior = out / "ATLAS_METADATA.json"
    prior.write_text('{"generation":"prior"}\n', encoding="utf-8")

    with pytest.raises(subprocess.CalledProcessError):
        atlas.build(repo, out, typescript_builder=builder)

    assert prior.read_text(encoding="utf-8") == '{"generation":"prior"}\n'
    assert sorted(path.name for path in out.iterdir()) == ["ATLAS_METADATA.json"]


def test_directory_publication_restores_prior_generation_when_swap_fails(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "atlas"
    destination.mkdir()
    (destination / "ATLAS_METADATA.json").write_text(
        '{"generation":"prior"}\n',
        encoding="utf-8",
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "ATLAS_METADATA.json").write_text(
        '{"generation":"new"}\n',
        encoding="utf-8",
    )
    calls = 0

    def fail_new_generation_once(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected directory swap failure")
        os.replace(source, target)

    with pytest.raises(OSError, match="injected directory swap failure"):
        atlas.publish_staged_atlas(
            staging,
            destination,
            replace=fail_new_generation_once,
        )

    assert (destination / "ATLAS_METADATA.json").read_text(encoding="utf-8") == (
        '{"generation":"prior"}\n'
    )
    assert staging.exists()
    assert not list(tmp_path.glob(".atlas-rollback-*"))


def test_directory_publication_preserves_recovery_copy_when_restore_fails(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "atlas"
    destination.mkdir()
    (destination / "ATLAS_METADATA.json").write_text(
        '{"generation":"prior"}\n',
        encoding="utf-8",
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "ATLAS_METADATA.json").write_text(
        '{"generation":"new"}\n',
        encoding="utf-8",
    )
    calls = 0

    def fail_promotion_and_restore(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise OSError(f"injected replace failure {calls}")
        os.replace(source, target)

    with pytest.raises(RuntimeError, match="preserved for manual recovery"):
        atlas.publish_staged_atlas(
            staging,
            destination,
            replace=fail_promotion_and_restore,
        )

    recovery_directories = list(tmp_path.glob(".atlas-rollback-*"))
    assert not destination.exists()
    assert staging.exists()
    assert len(recovery_directories) == 1
    assert (
        recovery_directories[0] / "ATLAS_METADATA.json"
    ).read_text(encoding="utf-8") == '{"generation":"prior"}\n'
