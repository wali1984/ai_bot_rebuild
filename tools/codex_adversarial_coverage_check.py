#!/usr/bin/env python3
"""Evidence-backed Codex adversarial coverage checker.

Builds a per-entry coverage view for Tier A review entries using multiple
evidence sources (direct grep, exchange map, redis map, trainer atlas,
script registry, and raw Tier A plan fields), then emits JSON and Markdown
reports with pass/fail decision.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple


ROOT = Path(__file__).resolve().parents[1]

TIER_A_PATH = ROOT / "claude_worklog/coverage/TIER_A_RAW_REVIEW_PLAN.json"
EXCHANGE_MAP_PATH = ROOT / "claude_worklog/coverage/EXCHANGE_ACTION_MAP.json"
REDIS_MAP_PATH = ROOT / "claude_worklog/coverage/REDIS_USAGE_MAP.json"
SCRIPT_REGISTRY_PATH = ROOT / "claude_worklog/coverage/SCRIPT_REGISTRY.json"
TRAINER_ATLAS_DIR = ROOT / "claude_worklog/trainer_atlas"

CODEX_DIR = ROOT / "claude_worklog/codex"
TARGETED_GREP_FILES = [
	CODEX_DIR / "CODEX_TARGETED_EXCHANGE_GREP.txt",
	CODEX_DIR / "CODEX_TARGETED_REDIS_GREP.txt",
	CODEX_DIR / "CODEX_TARGETED_TRAINER_GREP.txt",
]

OUT_JSON = CODEX_DIR / "CODEX_ADVERSARIAL_COVERAGE_CHECK.json"
OUT_MD = CODEX_DIR / "CODEX_ADVERSARIAL_COVERAGE_CHECK.md"

LINE_RE = re.compile(r"([^:]+):(\d+):")


def _read_json(path: Path) -> dict:
	return json.loads(path.read_text())


def _norm_file(path: str) -> str:
	p = str(path).strip()
	if p.startswith("legacy_reference/"):
		return p
	return "legacy_reference/" + p.lstrip("./")


def _load_direct_grep_lines(files: Iterable[Path]) -> Dict[str, Set[int]]:
	out: Dict[str, Set[int]] = defaultdict(set)
	for file in files:
		if not file.exists():
			continue
		for line in file.read_text(errors="ignore").splitlines():
			m = LINE_RE.match(line)
			if not m:
				continue
			path, line_s = m.group(1), m.group(2)
			try:
				line_no = int(line_s)
			except ValueError:
				continue
			out[_norm_file(path)].add(line_no)
	return out


def _index_line_matches(matches: List[dict], line_key: str = "line") -> Dict[str, Set[int]]:
	idx: Dict[str, Set[int]] = defaultdict(set)
	for m in matches:
		file_path = m.get("file")
		line_no = m.get(line_key)
		if not file_path or not isinstance(line_no, int):
			continue
		idx[_norm_file(file_path)].add(line_no)
	return idx


def _index_script_registry(scripts: List[dict]) -> Dict[str, dict]:
	idx = {}
	for s in scripts:
		p = s.get("path")
		if not p:
			continue
		idx[_norm_file(p)] = s
	return idx


def _load_trainer_atlas_lines(atlas_dir: Path) -> Dict[str, Set[int]]:
	lines: Dict[str, Set[int]] = defaultdict(set)
	trainer_file = "legacy_reference/rl/hybrid_trainer.py"
	if not atlas_dir.exists():
		return lines
	for jf in atlas_dir.glob("*.json"):
		try:
			data = _read_json(jf)
		except Exception:
			continue
		matches = data.get("matches") if isinstance(data, dict) else None
		if not isinstance(matches, list):
			continue
		for m in matches:
			line_no = m.get("line")
			if isinstance(line_no, int):
				lines[trainer_file].add(line_no)
	return lines


def _range_hit(line_set: Set[int], start: int, end: int) -> bool:
	if not line_set:
		return False
	if end < start:
		end = start
	for n in line_set:
		if start <= n <= end:
			return True
	return False


def _phase1_raw_review_coverage(entry: dict) -> bool:
	required = ["file", "start_line", "end_line", "verification_command", "category", "reason"]
	return all(entry.get(k) not in (None, "") for k in required)


def _category_group(category: str) -> str:
	c = str(category or "")
	if c in {"exchange_execution", "leverage_margin", "stops_take_profit"}:
		return "exchange_mutation"
	if c == "redis_write":
		return "redis_writer"
	if c.startswith("trainer_"):
		return "trainer"
	if c == "exchange_unresolved_tier_a_review":
		return "exchange_unresolved"
	return "general"


def main() -> int:
	tier_a = _read_json(TIER_A_PATH)
	exchange_map = _read_json(EXCHANGE_MAP_PATH)
	redis_map = _read_json(REDIS_MAP_PATH)
	script_registry = _read_json(SCRIPT_REGISTRY_PATH)

	entries: List[dict] = tier_a.get("entries", [])
	direct_idx = _load_direct_grep_lines(TARGETED_GREP_FILES)
	exchange_idx = _index_line_matches(exchange_map.get("matches", []), line_key="line")
	redis_idx = _index_line_matches(redis_map.get("matches", []), line_key="line")
	trainer_idx = _load_trainer_atlas_lines(TRAINER_ATLAS_DIR)
	script_idx = _index_script_registry(script_registry.get("scripts", []))

	covered = 0
	uncovered = 0
	critical_uncovered = 0

	uncovered_by_category: Counter = Counter()
	uncovered_by_file: Counter = Counter()

	unresolved_total = 0
	unresolved_covered = 0

	per_entry = []

	for e in entries:
		file_path = _norm_file(str(e.get("file", "")))
		start = int(e.get("start_line") or 0)
		end = int(e.get("end_line") or start)
		category = str(e.get("category") or "")
		group = _category_group(category)

		flags = {
			"direct_grep_coverage": _range_hit(direct_idx.get(file_path, set()), start, end),
			"exchange_map_coverage": _range_hit(exchange_idx.get(file_path, set()), start, end),
			"redis_map_coverage": _range_hit(redis_idx.get(file_path, set()), start, end),
			"trainer_atlas_coverage": _range_hit(trainer_idx.get(file_path, set()), start, end),
			"script_registry_coverage": bool(script_idx.get(file_path)),
			"phase1_raw_review_coverage": _phase1_raw_review_coverage(e),
		}

		# Category-specific coverage standard
		if group == "exchange_mutation":
			rule_ok = flags["direct_grep_coverage"] or flags["exchange_map_coverage"]
			is_critical = True
		elif group == "redis_writer":
			rule_ok = flags["direct_grep_coverage"] or flags["redis_map_coverage"]
			is_critical = True
		elif group == "trainer":
			rule_ok = flags["trainer_atlas_coverage"] or flags["direct_grep_coverage"]
			is_critical = True
		elif group == "exchange_unresolved":
			rule_ok = flags["exchange_map_coverage"] and flags["phase1_raw_review_coverage"]
			is_critical = True
			unresolved_total += 1
			if rule_ok:
				unresolved_covered += 1
		else:
			rule_ok = flags["script_registry_coverage"] and flags["phase1_raw_review_coverage"]
			is_critical = False

		status = "covered" if rule_ok else "uncovered"
		if rule_ok:
			covered += 1
		else:
			uncovered += 1
			uncovered_by_category[category] += 1
			uncovered_by_file[file_path] += 1
			if is_critical:
				critical_uncovered += 1

		per_entry.append(
			{
				"review_id": e.get("review_id"),
				"file": file_path,
				"start_line": start,
				"end_line": end,
				"category": category,
				"coverage_group": group,
				"coverage_flags": flags,
				"status": status,
			}
		)

	total = len(entries)
	pct = round((covered / total) * 100.0, 4) if total else 0.0

	# Cross-artifact global safety gates
	unknown_exchange_use = int(exchange_map.get("unknown_exchange_use_count_after", 0) or 0)
	unsafe_unknown = int(
		exchange_map.get("class_counts", {}).get("unsafe_unknown", 0)
		or exchange_map.get("blocking_unknown_exchange_use_count", 0)
		or 0
	)

	pass_checks = {
		"critical_uncovered_zero": critical_uncovered == 0,
		"unknown_exchange_use_zero": unknown_exchange_use == 0,
		"unsafe_unknown_zero": unsafe_unknown == 0,
		"exchange_unresolved_fully_covered": unresolved_total == unresolved_covered,
	}
	decision = "CODEX_COVERAGE_CHECK_PASS" if all(pass_checks.values()) else "CODEX_COVERAGE_CHECK_FAIL"

	result = {
		"decision": decision,
		"summary": {
			"total_tier_a_entries": total,
			"entries_covered": covered,
			"entries_uncovered": uncovered,
			"coverage_percentage": pct,
			"critical_uncovered_count": critical_uncovered,
			"unknown_exchange_use_count": unknown_exchange_use,
			"unsafe_unknown_count": unsafe_unknown,
			"exchange_unresolved_total": unresolved_total,
			"exchange_unresolved_covered": unresolved_covered,
		},
		"pass_checks": pass_checks,
		"uncovered_by_category": dict(uncovered_by_category),
		"uncovered_by_file": dict(uncovered_by_file),
		"entries": per_entry,
	}

	OUT_JSON.write_text(json.dumps(result, indent=2))

	md = []
	md.append("# Codex adversarial coverage check")
	md.append("")
	md.append(f"**Decision:** {decision}")
	md.append("")
	md.append("## Summary")
	md.append(f"- Total Tier A entries: **{total}**")
	md.append(f"- Entries covered: **{covered}**")
	md.append(f"- Entries uncovered: **{uncovered}**")
	md.append(f"- Coverage percentage: **{pct}%**")
	md.append(f"- Critical uncovered count: **{critical_uncovered}**")
	md.append(f"- unknown_exchange_use count: **{unknown_exchange_use}**")
	md.append(f"- unsafe_unknown count: **{unsafe_unknown}**")
	md.append(
		f"- exchange_unresolved_tier_a_review covered: **{unresolved_covered}/{unresolved_total}**"
	)
	md.append("")
	md.append("## Pass checks")
	for k, v in pass_checks.items():
		md.append(f"- {k}: **{'PASS' if v else 'FAIL'}**")

	md.append("")
	md.append("## Uncovered by category")
	if uncovered_by_category:
		for k, v in uncovered_by_category.most_common():
			md.append(f"- {k}: **{v}**")
	else:
		md.append("- None")

	md.append("")
	md.append("## Uncovered by file (top 100)")
	if uncovered_by_file:
		for k, v in uncovered_by_file.most_common(100):
			md.append(f"- {k}: **{v}**")
	else:
		md.append("- None")

	OUT_MD.write_text("\n".join(md) + "\n")
	print(decision)
	print(f"wrote {OUT_JSON}")
	print(f"wrote {OUT_MD}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
