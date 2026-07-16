# Low-Level System Atlas

Generated: `2026-07-16T09:38:22.668289Z`

Source commit at scan start: `2dd584d632790c54c1054f7c4453cb9d36d0987c`

Source commit at scan end: `2dd584d632790c54c1054f7c4453cb9d36d0987c`

Tracked input content stable from capture through revalidation: `True`

This atlas is a static, credential-shape-sanitized reconstruction index. It does not prove that a service is currently running; runtime observations belong in the operator manual and current-state report. Validate machine files against `ATLAS_BUILD_MANIFEST.json`; Markdown is only a navigation layer.

## Coverage

- Git-tracked paths at capture: **9,272**; cataloged paths excluding generated atlas outputs: **9,272**
- Python modules parsed: **3,213**; Python symbols including module scopes: **32,272**
- TypeScript/JavaScript symbols: **3,334**
- Swift symbols: **693** (heuristic parser; source lines retained)
- Shell functions: **116** (heuristic parser)
- Resolved/internal Python import edges: **8,708** of **25,389**
- Resolved Python call edges: **38,744** of **161,112** static call references
- Data/schema contracts: **1,807**
- API route definitions/references: **905**
- Environment keys: **2,918**
- Redis key patterns: **2,040**
- Data field names: **39,538**
- Python parse errors: **2**

## Source strata

| Stratum | Files |
|---|---:|
| `backend_adapter` | 60 |
| `backend_api` | 90 |
| `backend_cli` | 298 |
| `backend_composition` | 53 |
| `backend_core` | 32 |
| `backend_domain` | 127 |
| `backend_service` | 527 |
| `configuration` | 143 |
| `documentation` | 2,612 |
| `evidence_or_runtime_artifact` | 2,112 |
| `mobile` | 82 |
| `operational_tooling` | 272 |
| `preserved_legacy_source` | 279 |
| `repository_support` | 298 |
| `service_definition` | 131 |
| `test` | 1,645 |
| `web_frontend` | 511 |

## Languages / file kinds

| Kind | Files |
|---|---:|
| `config` | 3 |
| `ini` | 1 |
| `javascript` | 32 |
| `json` | 2,080 |
| `make` | 1 |
| `other` | 3,069 |
| `python` | 3,213 |
| `shell` | 111 |
| `swift` | 68 |
| `symlink` | 1 |
| `systemd` | 125 |
| `toml` | 2 |
| `typescript` | 554 |
| `yaml` | 12 |

## Canonical artifacts

| Artifact | Question it answers |
|---|---|
| [ATLAS_BUILD_MANIFEST.json](ATLAS_BUILD_MANIFEST.json) | Which staged artifact hashes, analyzers, source snapshot and regeneration command define this generation? |
| [FILE_MODULE_CATALOG.json](FILE_MODULE_CATALOG.json) | What files exist, what are their hashes/size/language/stratum, and which modules failed parsing? |
| [PYTHON_SYMBOL_CATALOG.json](PYTHON_SYMBOL_CATALOG.json) | What does every Python function/class/method/module scope contain and touch? |
| [TYPESCRIPT_JAVASCRIPT_ATLAS.json](TYPESCRIPT_JAVASCRIPT_ATLAS.json) | What web/JS symbols, imports, interfaces, calls, env keys, and API references exist? |
| [SWIFT_SYMBOL_CONTRACT_CATALOG.json](SWIFT_SYMBOL_CONTRACT_CATALOG.json) | What iOS/watch/CLI types, functions, imports, API references, and model fields exist? |
| [PYTHON_IMPORT_GRAPH.json](PYTHON_IMPORT_GRAPH.json) | Which Python module directly imports which module, and which imports are external/dynamic? |
| [PYTHON_CALL_GRAPH.json](PYTHON_CALL_GRAPH.json) | Which symbol calls which statically resolvable symbol; unresolved calls remain explicitly listed? |
| [CHANGE_IMPACT_INDEX.json](CHANGE_IMPACT_INDEX.json) | What file-level surfaces exist system-wide, and what direct Python reverse import/call dependents plus cross-language key/field/API/config surfaces are known? |
| [CONFIG_ENV_REGISTRY.json](CONFIG_ENV_REGISTRY.json) | Which environment/static configuration keys exist, defaults where safe, and every consumer/site? |
| [REDIS_KEY_USAGE_REGISTRY.json](REDIS_KEY_USAGE_REGISTRY.json) | Which key patterns are read, written, declared, or unresolved, with operation, file, symbol, line, and column? |
| [DATA_CONTRACT_FIELD_REGISTRY.json](DATA_CONTRACT_FIELD_REGISTRY.json) | Which schema/payload fields are declared/read/written and where? |
| [API_ROUTE_REGISTRY.json](API_ROUTE_REGISTRY.json) | Which backend route handlers and client references exist? |
| [ENTRYPOINT_SERVICE_REGISTRY.json](ENTRYPOINT_SERVICE_REGISTRY.json) | Which Python mains, shell commands, Make targets, package scripts, and systemd directives start work? |
| [EXCHANGE_MUTATION_REFERENCE_REGISTRY.json](EXCHANGE_MUTATION_REFERENCE_REGISTRY.json) | Which source symbols contain order/cancel/leverage/margin/transfer mutation references? |

## Change-impact procedure

1. Find the path in `CHANGE_IMPACT_INDEX.json.file_surfaces`; for Python, also find the module/symbol record.
2. Review proven Python callers/importers plus Redis readers/writers/declarations, shared fields, config consumers, routes, tests, side effects, and exchange references. Non-Python call/import resolution remains in its dedicated compiler/heuristic atlas and requires manual traversal.
3. Repeat recursively for each direct dependent; static analysis cannot prove dynamic imports, reflection, Redis consumers built from runtime strings, or provider-side behavior.
4. For any strategy, PPO, MASA, risk, or live-execution change, treat static impact as the lower bound and run the subsystem tests plus paper/replay validation. Never infer live approval from this atlas.

## Parser limits that must not be hidden

- Python uses the CPython AST and records all nested definitions. Calls are retained even when a target cannot be resolved; resolution confidence is explicit.
- TypeScript/JavaScript uses the repository's pinned TypeScript compiler AST.
- Swift and shell use line/brace heuristics because SwiftSyntax and a shell AST library are not repository dependencies. Every record includes its source line so ambiguous cases can be verified directly.
- Redis keys assembled through opaque runtime concatenation may appear only as partial patterns or unresolved calls. Search consumers before changing a key.
- Secret-classified paths are inventoried without reading, hashing, or sizing their contents. Credential-shaped values found in analyzable source are sanitized at every serialization boundary; key names remain for dependency mapping. This is defense in depth, not a formal DLP proof: review generated artifacts before publishing them outside the host.
- Publication stages a complete generation beside the canonical directory, then swaps the directory by same-filesystem rename. If promotion raises, restoration of the prior directory is attempted; if restoration itself fails, the recovery directory is retained and named in the raised error. Readers must still validate every manifest hash and retry if the directory is briefly absent or a process crash interrupts publication.

## Python parse failures

- `v2/legacy_preserved/full_runtime_closure/rl/microstructure_aggregator.py`: `{'type': 'IndentationError', 'message': "expected an indented block after 'except' statement on line 454 (microstructure_aggregator.py, line 455)", 'line': 455}`
- `v2/legacy_preserved/full_runtime_closure/rl/microstructure_features.py`: `{'type': 'IndentationError', 'message': "expected an indented block after 'try' statement on line 531 (microstructure_features.py, line 532)", 'line': 532}`
