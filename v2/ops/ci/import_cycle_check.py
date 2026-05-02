"""Import-cycle and forbidden-edge enforcement.

Required from milestone B per 07_TEST_AND_CI_PLAN.md §4.

Enforces the forbidden edges declared in 02_PACKAGE_AND_MODULE_MAP.md §3:
  - app/api/**            -> app/adapters/db/**          (must go via services)
  - app/domain/**         -> app/adapters/**             (domain is pure)
  - app/domain/**         -> {redis, sqlalchemy, httpx, requests, psycopg, asyncpg, ccxt}
  - app/adapters/trainer/** -> legacy_reference/** or AI BOT/**  (subprocess only)
  - any module            -> dotenv (outside app/settings.py)
  - frontend/src/pages/** -> frontend/src/api/client.ts

Also runs Tarjan strongly-connected-component detection over the app.* graph
to catch import cycles. Frontend cycle scan is delegated to madge when
v2/frontend/node_modules/.bin/madge is present (advisory otherwise).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = V2_ROOT / "backend"
FRONTEND_ROOT = V2_ROOT / "frontend"

FORBIDDEN_DOMAIN_EXTERNALS = (
    "redis",
    "sqlalchemy",
    "httpx",
    "requests",
    "psycopg",
    "asyncpg",
    "ccxt",
)


def _build_graph():
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        import grimp  # type: ignore
    except ImportError as e:
        print(f"[import-cycle] FAIL: grimp not installed: {e}", file=sys.stderr)
        sys.exit(2)
    return grimp.build_graph("app", include_external_packages=True)


def _modules_under(graph, package: str) -> set[str]:
    if package not in graph.modules:
        return set()
    return set(graph.find_descendants(package)) | {package}


def _direct_imports(graph, importer: str) -> frozenset[str]:
    try:
        return graph.find_modules_directly_imported_by(importer)
    except Exception:
        return frozenset()


def _check_forbidden_edge(graph, src_pkg: str, dst_pkg: str, label: str, errors: list[str]) -> None:
    sources = _modules_under(graph, src_pkg)
    targets = _modules_under(graph, dst_pkg)
    if not sources or not targets:
        return
    for src in sources:
        for tgt in _direct_imports(graph, src):
            if tgt in targets:
                errors.append(f"{label}: {src} -> {tgt}")


def _check_domain_externals(graph, errors: list[str]) -> None:
    sources = _modules_under(graph, "app.domain")
    for src in sources:
        for ext in FORBIDDEN_DOMAIN_EXTERNALS:
            try:
                if graph.direct_import_exists(importer=src, imported=ext):
                    errors.append(f"forbidden domain external: {src} -> {ext}")
            except Exception:
                continue


def _check_dotenv(errors: list[str]) -> None:
    pat = re.compile(r"^\s*(from\s+dotenv|import\s+dotenv)\b")
    settings_path = (BACKEND_ROOT / "app" / "settings.py").resolve()
    for path in BACKEND_ROOT.rglob("*.py"):
        if path.resolve() == settings_path:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if pat.search(line):
                rel = path.relative_to(BACKEND_ROOT).as_posix()
                errors.append(f"forbidden dotenv import: {rel}")
                break


def _check_trainer_legacy(errors: list[str]) -> None:
    trainer_dir = BACKEND_ROOT / "app" / "adapters" / "trainer"
    if not trainer_dir.exists():
        return
    pat = re.compile(r"^\s*(from\s+|import\s+)(legacy_reference|AI[_ ]BOT)\b")
    for path in trainer_dir.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if pat.search(line):
                rel = path.relative_to(BACKEND_ROOT).as_posix()
                errors.append(f"forbidden trainer->legacy import: {rel}")
                break


def _check_frontend_pages(errors: list[str]) -> None:
    pages_dir = FRONTEND_ROOT / "src" / "pages"
    if not pages_dir.exists():
        return
    import_pat = re.compile(r"""(?:from|import)\s+['\"]([^'\"]+)['\"]""")
    for path in pages_dir.rglob("*.ts*"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            m = import_pat.search(line)
            if not m:
                continue
            spec = m.group(1)
            tail = spec.split("/")[-1]
            if tail in ("client", "client.ts") and "api" in spec.split("/"):
                rel = path.relative_to(FRONTEND_ROOT).as_posix()
                errors.append(f"forbidden frontend pages->api/client.ts: {rel} ({spec})")
                break


def _detect_cycles(graph, errors: list[str]) -> None:
    modules = sorted(_modules_under(graph, "app"))
    if not modules:
        return
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 5000))
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = [0]

    def strongconnect(v: str) -> None:
        indices[v] = counter[0]
        lowlinks[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in _direct_imports(graph, v):
            if not (w == "app" or w.startswith("app.")):
                continue
            if w not in indices:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], indices[w])
        if lowlinks[v] == indices[v]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                errors.append("import cycle: " + " -> ".join(reversed(scc)))

    for m in modules:
        if m not in indices:
            strongconnect(m)


def _frontend_madge(errors: list[str]) -> None:
    bin_path = FRONTEND_ROOT / "node_modules" / ".bin" / "madge"
    if not bin_path.exists():
        print("[import-cycle] madge not installed; frontend cycle scan skipped (advisory)")
        return
    rc = subprocess.run(
        [str(bin_path), "--circular", "--ts-config", "tsconfig.json", "src"],
        cwd=str(FRONTEND_ROOT),
        check=False,
    )
    if rc.returncode != 0:
        errors.append("madge reported circular imports under frontend/src")


def main() -> int:
    errors: list[str] = []
    graph = _build_graph()

    _check_forbidden_edge(graph, "app.api", "app.adapters.db", "api->adapters.db", errors)
    _check_forbidden_edge(graph, "app.domain", "app.adapters", "domain->adapters", errors)
    _check_domain_externals(graph, errors)
    _check_dotenv(errors)
    _check_trainer_legacy(errors)
    _check_frontend_pages(errors)
    _detect_cycles(graph, errors)
    _frontend_madge(errors)

    if errors:
        for e in errors:
            print(f"[import-cycle] FAIL: {e}", file=sys.stderr)
        return 1
    print("[import-cycle] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
