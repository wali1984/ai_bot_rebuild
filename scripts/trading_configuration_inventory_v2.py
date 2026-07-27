#!/usr/bin/env python3
"""Discover and classify trading-affecting configuration authority.

This scanner is intentionally read-only.  It turns Python source into a
deterministic candidate set, joins human-reviewed A-E classifications by stable
configuration ID, and emits exact coverage counters.  An unreviewed candidate
is never silently treated as safe or non-policy: it remains unclassified and
keeps Phase 1 fail-closed.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

SCHEMA_VERSION = "adaptive_system_final_pass_trading_configuration_inventory_v2"
SCANNER_VERSION = "trading_configuration_inventory_scanner_v2"
CLASSIFICATION_SCHEMA_VERSION = (
    "adaptive_system_final_pass_trading_configuration_classifications_v1"
)

_CATEGORY_SET = frozenset({"A", "B", "C", "D", "E"})
_CONFIG_CLASS_TERMS = (
    "config",
    "constraint",
    "envelope",
    "limit",
    "option",
    "parameter",
    "policy",
    "setting",
    "threshold",
)
_TRADING_TERMS = (
    "action",
    "admission",
    "allocation",
    "capital",
    "confidence",
    "cooldown",
    "correlation",
    "cost",
    "drawdown",
    "duration",
    "edge",
    "entry",
    "execution",
    "exit",
    "exposure",
    "fee",
    "fill",
    "funding",
    "fvg",
    "hedge",
    "hold",
    "horizon",
    "leverage",
    "liquidation",
    "liquidity",
    "loss",
    "mae",
    "margin",
    "market",
    "mfe",
    "microstructure",
    "notional",
    "order",
    "outcome",
    "paper",
    "portfolio",
    "position",
    "prediction",
    "profit",
    "regime",
    "reward",
    "risk",
    "side",
    "signal",
    "size",
    "slippage",
    "spread",
    "score",
    "stop",
    "strategy",
    "symbol",
    "tail",
    "timeframe",
    "trade",
    "turnover",
    "volatility",
)


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    configuration_id: str
    name: str
    path: str
    line_start: int
    line_end: int
    column: int
    symbol: str
    kind: str
    expression: str
    source_sha256: str
    declared_default: Any
    unit: str | None
    affects: tuple[str, ...]
    decision_stage: str


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _attribute_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _attribute_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _literal_value(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError):
        return None
    return _json_safe_literal(value)


def _json_safe_literal(value: Any) -> Any:
    if value is None or type(value) in {str, int, float, bool}:
        return value
    if isinstance(value, tuple | list):
        return [_json_safe_literal(item) for item in value]
    if isinstance(value, set | frozenset):
        return [
            _json_safe_literal(item)
            for item in sorted(value, key=lambda item: repr(item))
        ]
    if isinstance(value, dict):
        return {
            key if type(key) is str else repr(key): _json_safe_literal(item)
            for key, item in value.items()
        }
    return repr(value)


def _infer_unit(name: str) -> str | None:
    normalized = name.lower()
    for token, unit in (
        ("_bps", "bps"),
        ("_ms", "milliseconds"),
        ("_seconds", "seconds"),
        ("_minutes", "minutes"),
        ("_hours", "hours"),
        ("_usd", "USD"),
        ("notional", "USD"),
        ("leverage", "ratio"),
        ("quantity", "base_asset_quantity"),
        ("price", "quote_asset_per_base_asset"),
        ("probability", "probability_0_1"),
        ("confidence", "probability_0_1"),
        ("fraction", "fraction_0_1"),
        ("ratio", "ratio"),
        ("count", "count"),
    ):
        if token in normalized:
            return unit
    return None


def _infer_affects(text: str) -> tuple[str, ...]:
    normalized = text.lower()
    mapping = (
        ("symbol", "symbol"),
        ("timeframe", "timeframe"),
        ("side", "side"),
        ("entry", "entry"),
        ("notional", "notional"),
        ("size", "size"),
        ("quantity", "size"),
        ("leverage", "leverage"),
        ("margin", "margin"),
        ("hedge", "hedging"),
        ("stop", "stop"),
        ("exit", "exit"),
        ("hold", "holding_period"),
        ("duration", "holding_period"),
        ("reject", "trade_rejection"),
        ("block", "trade_rejection"),
        ("confidence", "trade_selection"),
        ("risk", "trade_selection"),
        ("loss", "trade_selection"),
        ("market", "trade_selection"),
        ("trade", "trade_selection"),
    )
    values = {effect for token, effect in mapping if token in normalized}
    if not values:
        values.add("trade_selection")
    return tuple(sorted(values))


def _infer_decision_stage(path: str, text: str) -> str:
    normalized = f"{path} {text}".lower()
    for token, stage in (
        ("serving", "prediction_serving"),
        ("orchestrator", "orchestration"),
        ("microstructure", "market_evidence"),
        ("entry", "entry_admission"),
        ("allocation", "allocation"),
        ("capital", "allocation"),
        ("risk", "risk"),
        ("execution", "execution"),
        ("fill", "execution"),
        ("exit", "lifecycle"),
        ("lifecycle", "lifecycle"),
        ("position", "portfolio_state"),
        ("account", "accounting"),
        ("training", "training"),
        ("trainer", "training"),
    ):
        if token in normalized:
            return stage
    return "trade_decision"


def _is_trading_relevant(path: str, name: str, symbol: str, expression: str) -> bool:
    del path
    haystack = f"{name} {symbol} {expression}".lower()
    return any(term in haystack for term in _TRADING_TERMS)


class _CandidateVisitor(ast.NodeVisitor):
    def __init__(self, *, relative_path: str, source: str, source_sha256: str) -> None:
        self.relative_path = relative_path
        self.source = source
        self.source_sha256 = source_sha256
        self.scope: list[str] = []
        self.class_modes: list[tuple[bool, bool]] = []
        self.class_scope_depths: list[int] = []
        self._occurrences: Counter[tuple[str, str, str, str]] = Counter()
        self.candidates: list[SourceCandidate] = []

    @property
    def symbol(self) -> str:
        return ".".join(self.scope) or "<module>"

    def _record(
        self,
        *,
        node: ast.AST,
        name: str,
        kind: str,
        value_node: ast.AST | None,
        expression_node: ast.AST | None = None,
    ) -> None:
        expression_target = expression_node or value_node or node
        try:
            expression = ast.unparse(expression_target)
        except (ValueError, TypeError):
            expression = ast.dump(expression_target, annotate_fields=False)
        expression = " ".join(expression.split())
        if not _is_trading_relevant(
            self.relative_path,
            name,
            self.symbol,
            expression,
        ):
            return
        occurrence_key = (self.symbol, kind, name, expression)
        occurrence = self._occurrences[occurrence_key]
        self._occurrences[occurrence_key] += 1
        identity = {
            "path": self.relative_path,
            "symbol": self.symbol,
            "kind": kind,
            "name": name,
            "expression": expression,
            "occurrence": occurrence,
        }
        configuration_id = f"cfg_{_sha256_text(json.dumps(identity, sort_keys=True))[:24]}"
        text = f"{name} {self.symbol} {expression}"
        self.candidates.append(
            SourceCandidate(
                configuration_id=configuration_id,
                name=name,
                path=self.relative_path,
                line_start=getattr(node, "lineno", 0),
                line_end=getattr(node, "end_lineno", getattr(node, "lineno", 0)),
                column=getattr(node, "col_offset", 0),
                symbol=self.symbol,
                kind=kind,
                expression=expression,
                source_sha256=self.source_sha256,
                declared_default=_literal_value(value_node),
                unit=_infer_unit(name),
                affects=_infer_affects(text),
                decision_stage=_infer_decision_stage(self.relative_path, text),
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        base_names = {_attribute_name(base).lower() for base in node.bases}
        lowered = node.name.lower()
        config_class = any(term in lowered for term in _CONFIG_CLASS_TERMS)
        enum_class = any(
            base_name.rsplit(".", maxsplit=1)[-1] in {"enum", "strenum", "intenum"}
            for base_name in base_names
        )
        self.scope.append(node.name)
        self.class_modes.append((config_class, enum_class))
        self.class_scope_depths.append(len(self.scope))
        self.generic_visit(node)
        self.class_scope_depths.pop()
        self.class_modes.pop()
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        positional = [*node.args.posonlyargs, *node.args.args]
        positional_defaults = zip(
            positional[-len(node.args.defaults) :] if node.args.defaults else (),
            node.args.defaults,
            strict=True,
        )
        for argument, default in positional_defaults:
            self._record(
                node=default,
                name=argument.arg,
                kind="function_default",
                value_node=default,
            )
        for argument, default in zip(
            node.args.kwonlyargs,
            node.args.kw_defaults,
            strict=True,
        ):
            if default is not None:
                self._record(
                    node=default,
                    name=argument.arg,
                    kind="function_default",
                    value_node=default,
                )
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if not self.scope and name.isupper():
                self._record(node=node, name=name, kind="constant", value_node=node.value)
            elif self.class_modes and len(self.scope) == self.class_scope_depths[-1]:
                config_class, enum_class = self.class_modes[-1]
                if enum_class or config_class or _literal_value(node.value) is not None:
                    kind = "enum" if enum_class else "config_field"
                    self._record(node=node, name=name, kind=kind, value_node=node.value)
            elif _literal_value(node.value) is not None:
                self._record(
                    node=node,
                    name=name,
                    kind="local_policy_value",
                    value_node=node.value,
                )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            name = node.target.id
            if not self.scope and name.isupper():
                self._record(node=node, name=name, kind="constant", value_node=node.value)
            elif self.class_modes and len(self.scope) == self.class_scope_depths[-1]:
                self._record(
                    node=node,
                    name=name,
                    kind="config_field",
                    value_node=node.value,
                )
            elif _literal_value(node.value) is not None:
                self._record(
                    node=node,
                    name=name,
                    kind="local_policy_value",
                    value_node=node.value,
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        function_name = _attribute_name(node.func)
        environment_read = function_name == "os.getenv" or function_name.endswith(
            "environ.get"
        )
        if environment_read and node.args:
            key = _literal_value(node.args[0])
            if isinstance(key, str):
                default_node = node.args[1] if len(node.args) > 1 else None
                self._record(
                    node=node,
                    name=key,
                    kind="environment",
                    value_node=default_node,
                    expression_node=node,
                )
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        operands = [node.left, *node.comparators]
        for index, operand in enumerate(operands):
            literal = _literal_value(operand)
            if literal is None or isinstance(literal, (list, dict)):
                continue
            other_index = 1 if index == 0 and len(operands) > 1 else max(0, index - 1)
            other_name = _attribute_name(operands[other_index]) or "comparison_operand"
            self._record(
                node=node,
                name=other_name,
                kind="inline_comparison",
                value_node=operand,
                expression_node=node,
            )
        self.generic_visit(node)


def discover_candidates(repo_root: Path, scan_roots: Sequence[Path]) -> tuple[SourceCandidate, ...]:
    candidates: list[SourceCandidate] = []
    files: set[Path] = set()
    for scan_root in scan_roots:
        resolved = scan_root if scan_root.is_absolute() else repo_root / scan_root
        if resolved.is_file() and resolved.suffix == ".py":
            files.add(resolved)
        elif resolved.is_dir():
            files.update(resolved.rglob("*.py"))
    for path in sorted(files):
        if any(part in {"__pycache__", ".venv", "tests"} for part in path.parts):
            continue
        source = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(repo_root).as_posix()
        visitor = _CandidateVisitor(
            relative_path=relative_path,
            source=source,
            source_sha256=_sha256_text(source),
        )
        visitor.visit(ast.parse(source, filename=relative_path))
        candidates.extend(visitor.candidates)
    return tuple(sorted(candidates, key=lambda item: item.configuration_id))


def _load_classifications(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != CLASSIFICATION_SCHEMA_VERSION:
        raise ValueError("invalid classification schema_version")
    records = payload.get("classifications")
    if not isinstance(records, list):
        raise ValueError("classifications must be a list")
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("classification must be an object")
        configuration_id = record.get("configuration_id")
        category = record.get("category")
        if not isinstance(configuration_id, str) or not configuration_id:
            raise ValueError("classification configuration_id must be non-empty")
        if configuration_id in result:
            raise ValueError(f"duplicate classification: {configuration_id}")
        if category not in _CATEGORY_SET:
            raise ValueError(f"invalid category for {configuration_id}")
        rationale = record.get("classification_rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(f"classification rationale missing for {configuration_id}")
        final_authority = record.get("manual_static_final_authority")
        if not isinstance(final_authority, bool):
            raise ValueError(f"manual authority flag missing for {configuration_id}")
        if category != "E" and final_authority:
            raise ValueError(f"non-E classification cannot be manual authority: {configuration_id}")
        result[configuration_id] = record
    return result


def build_inventory(
    *,
    repo_root: Path,
    scan_roots: Sequence[Path],
    classifications: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidates = discover_candidates(repo_root, scan_roots)
    candidate_ids = {item.configuration_id for item in candidates}
    unknown_classification_ids = sorted(set(classifications) - candidate_ids)
    values: list[dict[str, Any]] = []
    category_counts = {category: 0 for category in sorted(_CATEGORY_SET)}
    unclassified_ids: list[str] = []
    manual_authority_ids: list[str] = []
    for candidate in candidates:
        classification = classifications.get(candidate.configuration_id)
        record = asdict(candidate)
        record["affects"] = list(candidate.affects)
        if classification is None:
            record.update(
                {
                    "category": None,
                    "classification_rationale": None,
                    "classification_evidence": [],
                    "operator_mandate_receipt": None,
                    "manual_static_final_authority": None,
                    "replacement_required": None,
                }
            )
            unclassified_ids.append(candidate.configuration_id)
        else:
            category = classification["category"]
            category_counts[category] += 1
            final_authority = classification["manual_static_final_authority"]
            record.update(
                {
                    "category": category,
                    "classification_rationale": classification[
                        "classification_rationale"
                    ],
                    "classification_evidence": classification.get(
                        "classification_evidence", []
                    ),
                    "operator_mandate_receipt": classification.get(
                        "operator_mandate_receipt"
                    ),
                    "manual_static_final_authority": final_authority,
                    "replacement_required": category == "E",
                }
            )
            if final_authority:
                manual_authority_ids.append(candidate.configuration_id)
        values.append(record)
    source_paths = sorted({item.path for item in candidates})
    source_tree_material = [
        {"path": path, "sha256": _sha256_text((repo_root / path).read_text())}
        for path in source_paths
    ]
    all_candidates_classified = not unclassified_ids
    confirmed_manual_authorities = len(manual_authority_ids)
    coverage = {
        "discovered_values": len(candidates),
        "classified_values": len(candidates) - len(unclassified_ids),
        "unclassified_trading_values": len(unclassified_ids),
        "unclassified_configuration_ids": unclassified_ids,
        "category_counts": category_counts,
        "reachable_category_e_ids": [
            item["configuration_id"] for item in values if item["category"] == "E"
        ],
        "manual_static_trading_authority_ids": manual_authority_ids,
        "confirmed_manual_static_trading_authorities": confirmed_manual_authorities,
        "manual_static_trading_authorities": (
            confirmed_manual_authorities if all_candidates_classified else None
        ),
        "unknown_classification_ids": unknown_classification_ids,
        "duplicate_rows": len(candidates) - len(candidate_ids),
    }
    phase1_complete = (
        coverage["unclassified_trading_values"] == 0
        and coverage["manual_static_trading_authorities"] == 0
        and not coverage["unknown_classification_ids"]
        and coverage["duplicate_rows"] == 0
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "scanner_version": SCANNER_VERSION,
        "repository": {
            "root": str(repo_root),
            "source_tree_sha256": _sha256_text(
                json.dumps(source_tree_material, sort_keys=True, separators=(",", ":"))
            ),
        },
        "scan_manifest": {
            "included_roots": [
                path.relative_to(repo_root).as_posix() if path.is_absolute() else path.as_posix()
                for path in scan_roots
            ],
            "source_kinds": [
                "constant",
                "environment",
                "config_field",
                "enum",
                "function_default",
                "inline_comparison",
                "local_policy_value",
            ],
            "files_with_candidates": len(source_paths),
            "candidate_relevance_rule": "name/symbol/expression contains a declared trading term; path alone is never sufficient",
        },
        "values": values,
        "coverage": coverage,
        "acceptance_status": {
            "phase1_complete": phase1_complete,
            "unclassified_trading_values": coverage["unclassified_trading_values"],
            "manual_static_trading_authorities": coverage[
                "manual_static_trading_authorities"
            ],
        },
    }


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--scan-root",
        type=Path,
        action="append",
        default=None,
        help="Python file or directory to scan; repeatable (default: v2/backend/app)",
    )
    parser.add_argument("--classifications", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = args.repo_root.resolve()
    scan_roots = args.scan_root or [Path("v2/backend/app")]
    inventory = build_inventory(
        repo_root=repo_root,
        scan_roots=scan_roots,
        classifications=_load_classifications(args.classifications),
    )
    print(json.dumps(inventory, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "CLASSIFICATION_SCHEMA_VERSION",
    "SCANNER_VERSION",
    "SCHEMA_VERSION",
    "SourceCandidate",
    "build_inventory",
    "discover_candidates",
    "main",
)
