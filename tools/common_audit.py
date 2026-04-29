#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEGACY_ROOT = REPO_ROOT / "legacy_reference"

_SECRET_NAME_PATTERNS = [
    re.compile(r"^\.env(\..*)?$", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"apikey", re.IGNORECASE),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"private[_-]?key", re.IGNORECASE),
    re.compile(r"credentials", re.IGNORECASE),
]

_REDACT_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|apikey|secret|token|password|private[_-]?key)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\b(BINANCE|TELEGRAM|COINANK|OPENAI|ANTHROPIC)\b"),
]

TEXT_EXTENSIONS = {
    ".py", ".sh", ".bash", ".zsh", ".env.example", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf", ".service", ".md", ".txt", ".sql", ".js", ".jsx", ".ts",
    ".tsx", ".dockerfile", "", ".make", ".mk", ".properties", ".csv", ".log",
}


def resolve_path(raw: str | Path, base: Path | None = None) -> Path:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (base or Path.cwd()) / p
    return p.resolve()


def is_secret_path(path: Path) -> bool:
    name = path.name
    for pat in _SECRET_NAME_PATTERNS:
        if pat.search(name):
            return True
    for part in path.parts:
        if part.lower() in {"secrets", "secret", ".aws", ".ssh"}:
            return True
    return False


def ensure_allowed_file(path: Path, legacy_root: Path | None = None) -> None:
    p = path.resolve()
    roots = [REPO_ROOT]
    if legacy_root:
        roots.append(legacy_root.resolve())
    if not any(str(p).startswith(str(r)) for r in roots):
        raise ValueError(f"Path outside allowed roots: {p}")
    if is_secret_path(p):
        raise ValueError(f"Refusing secret-like path: {p}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def read_text_safely(path: Path, max_bytes: int = 10_000_000) -> str:
    ensure_allowed_file(path)
    data = path.read_bytes()[:max_bytes]
    return data.decode("utf-8", errors="replace")


def repo_relative(path: Path) -> str:
    p = path.resolve()
    for root in (REPO_ROOT,):
        try:
            return str(p.relative_to(root)).replace(os.sep, "/")
        except Exception:
            pass
    return str(p)


def relative_to(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace(os.sep, "/")
    except Exception:
        return str(path.resolve())


def iter_files(root: Path) -> Iterator[Path]:
    root = root.resolve()
    for p in root.rglob("*"):
        if not p.is_file() and not p.is_symlink():
            continue
        rel = relative_to(root, p)
        if rel.startswith(".git/"):
            continue
        if is_secret_path(p):
            continue
        yield p


def classify_language(path: Path) -> str:
    name = path.name.lower()
    ext = path.suffix.lower()
    if name in {"dockerfile"} or "dockerfile" in name:
        return "dockerfile"
    if name in {"makefile"} or ext in {".mk"}:
        return "make"
    if ext == ".py":
        return "python"
    if ext in {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    if ext in {".ts", ".tsx"}:
        return "typescript"
    if ext in {".sh", ".bash", ".zsh"}:
        return "shell"
    if ext in {".json"}:
        return "json"
    if ext in {".yaml", ".yml"}:
        return "yaml"
    if ext in {".toml", ".ini", ".cfg", ".conf", ".service", ".properties"}:
        return "config"
    if ext in {".md", ".rst", ".txt"}:
        return "docs"
    return "unknown"


def classify_category(path: Path, language: str | None = None) -> str:
    p = str(path).lower()
    ext = path.suffix.lower()
    language = language or classify_language(path)
    if any(k in p for k in ["/models", "/checkpoints", "tensorboard", "weights", ".pt", ".pth"]):
        return "model"
    if any(k in p for k in ["/data", "dataset", "replay_data"]) or ext in {".parquet", ".feather", ".csv", ".npy", ".npz"}:
        return "data"
    if language in {"python", "javascript", "typescript"}:
        return "code"
    if language in {"shell", "make"}:
        return "shell"
    if language in {"json", "yaml", "config", "dockerfile"}:
        return "config" if language != "dockerfile" else "docker"
    if language == "docs":
        return "docs"
    if ext in {".so", ".dll", ".dylib", ".bin", ".exe", ".o", ".a", ".jpg", ".jpeg", ".png", ".gif", ".pdf", ".zip", ".tar", ".gz"}:
        return "binary"
    return "unknown"


def verification_command(file_rel_or_abs: str, start: int = 1, end: int = 20) -> str:
    return f'python3 tools/show_file_range.py --file "{file_rel_or_abs}" --start {start} --end {end}'


def redact_text(text: str | None) -> str | None:
    if text is None:
        return None
    out = text
    for pat in _REDACT_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def evidence_record(file: str, line: Optional[int], text: Optional[str], kind: str, reason: str = "") -> Dict[str, Any]:
    safe_text = redact_text(text)
    return {
        "source_file": file,
        "line": line,
        "matched_text": safe_text,
        "kind": kind,
        "classification_reason": reason,
        "verification_command": verification_command(file, max(1, line or 1), max(1, (line or 1) + 2)),
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def scan_lines(path: Path, patterns: List[Tuple[str, re.Pattern[str]]], case_insensitive: bool = True) -> List[Dict[str, Any]]:
    text = read_text_safely(path)
    matches: List[Dict[str, Any]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        for label, pat in patterns:
            if pat.search(line):
                matches.append({"line": i, "label": label, "text": line.strip()[:500]})
    return matches


def is_text_file(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return True
    try:
        b = path.read_bytes()[:1024]
        return b"\x00" not in b
    except Exception:
        return False


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def find_line_matches(text: str, regex: re.Pattern[str]) -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if regex.search(line):
            out.append((i, line.rstrip("\n")))
    return out
