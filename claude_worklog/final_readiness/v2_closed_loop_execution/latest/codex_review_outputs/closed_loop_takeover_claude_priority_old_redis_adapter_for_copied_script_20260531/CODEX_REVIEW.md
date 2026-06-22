# Codex Review: closed_loop_takeover_claude_priority_old_redis_adapter_for_copied_script_20260531

GO/NO-GO: `CLOSED_LOOP_TAKEOVER_CLAUDE_PRIORITY_OLD_REDIS_ADAPTER_FOR_COPIED_SCRIPT_20260531_CODEX_FAIL`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Blockers

- 1. Every write the copied scripts emit targets a key beginning with the
- 1. Walk the AST of each copied script.
- 1. Find the `V2_REDIS_PREFIX = os.getenv("V2_REDIS_PREFIX", DEFAULT)`
- BLOCKER: The paired Claude task did not emit the required `old_redis_writer_proof_missing` evidence triplet (`REPORT.md`, `STATUS.json`, `GO_NO_GO.md`) under `claude_worklog/final_readiness/priority_autoseed_20260531/old_redis_writer_proof_missing`, so V2-side canary/liveness proof evidence is incomplete and cannot be independently verified.
- BLOCKER: The proposed "'`LegacyNamespaceGuard` enforces only the first key for commands in `_WRITE_KEY_AT_ARG1` (e.g., `RENAME`, `COPY`, `SMOVE`), so a V2 process using those commands can still write to a legacy destination key and bypass the guard. This can silently violate `no old-Redis writes` even when sources are v2-prefixed.
- BLOCKER: The proposed `LegacyNamespaceGuard` enforces only the first key for commands in `_WRITE_KEY_AT_ARG1` (e.g., `RENAME`, `COPY`, `SMOVE`), so a V2 process using those commands can still write to a legacy destination key and bypass the guard. This can silently violate `no old-Redis writes` even when sources are v2-prefixed.
- BLOCKER: The proposed `LegacyNamespaceGuard` enforces only the first key for commands in `_WRITE_KEY_AT_ARG1` (e.g., `RENAME`, `COPY`, `SMOVE`), so a V2 process using those commands can still write to a legacy destination key and bypass the guard. This can silently violate `no old-Redis writes` even when sources are v2-prefixed.
- 1. Every write the copied scripts emit targets a key beginning with the
- 1. Walk the AST of each copied script.
- 1. Find the `V2_REDIS_PREFIX = os.getenv("V2_REDIS_PREFIX", DEFAULT)`
- BLOCKER: The proposed `LegacyNamespaceGuard` enforces only the first key for commands in `_WRITE_KEY_AT_ARG1` (e.g., `RENAME`, `COPY`, `SMOVE`), so a V2 process using those commands can still write to a legacy destination key and bypass the guard. This can silently violate `no old-Redis writes` even when sources are v2-prefixed.

## Raw Output (tail)

```text
218:             break
219:     assert isinstance(found_default, str) and found_default != "", (
220:         f"{script_path.name}: V2_REDIS_PREFIX must have a non-empty default "
221:         f"so the namespace separator cannot silently collapse"
222:     )
223:     assert found_default.endswith(":"), (
224:         f"{script_path.name}: V2_REDIS_PREFIX default {found_default!r} "
225:         f"should end with ':' to avoid prefix-collision (e.g. 'v2foo:bar')"
226:     )
227: 
228: 
229: # --- Runtime fail-closed proof ---------------------------------------
230: 
231: 
232: def test_guard_rejects_set_on_legacy_key() -> None:
233:     with pytest.raises(LegacyNamespaceWriteRejected) as exc:
234:         assert_v2_namespace(("SET", "features:coinank:BTCUSDT", "1"), v2_prefix="v2:")
235:     assert exc.value.command == "SET"
236:     assert exc.value.key == "features:coinank:BTCUSDT"
237: 
238: 
239: def test_guard_accepts_set_on_v2_key() -> None:
240:     assert_v2_namespace(("SET", "v2:cursor:liq_bridge:foo", "1"), v2_prefix="v2:")

exec
/bin/bash -lc 'find claude_worklog/final_readiness/priority_autoseed_20260531 -type f | grep copied_script_old_redis_adapter' in /home/wali/Desktop/AI BOT REBUILD
 exited 1 in 0ms:
exec
/bin/bash -lc "python - <<'PY'
import ast

def _is_v2_safe_expr(node, safe_names):
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == '_v2_key':
            return True
        return False
    if isinstance(node, ast.Constant) and isinstance(node.value,str):
        return node.value.startswith('v2:')
    if isinstance(node, ast.Name):
        return node.id in safe_names
    if isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value,str):
                if part.value == '':
                    continue
                return part.value.startswith('v2:')
            if isinstance(part, ast.FormattedValue):
                inner = part.value
                if isinstance(inner, ast.Name) and inner.id in safe_names:
                    return True
                if isinstance(inner, ast.JoinedStr) and _is_v2_safe_expr(inner,safe_names):
                    return True
                return False
            return False
        return False

    return False

def collect(tree):
    safe=set()
    while True:
        new=set(safe)
        for node in ast.walk(tree):
            if not isinstance(node,ast.Assign):
                continue
            if len(node.targets)"'!=1: continue
            tgt=node.targets[0]
            if not isinstance(tgt,ast.Name):
                continue
            if tgt.id in new:
                continue
            if _is_v2_safe_expr(node.value,new):
                new.add(tgt.id)
        if new==safe: return safe
        safe=new

source='"'''\\na = _v2_key(\"x\")\\na = \"legacy:bad\"\\nr.set(a, 1)\\n'''
tree=ast.parse(source)
print(collect(tree))
PY" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
{'a'}

 succeeded in 151564ms:
PLANNER_TURN_2I_OPEN_2I_B_AFTER_2I_A_CODEX_PASS.md
PLANNER_TURN_2I_OPEN_2I_C_AFTER_2I_B_CODEX_PASS.md

exec
/bin/bash -lc 'cat claude_worklog/final_readiness/v2_closed_loop_execution/latest/codex_review_outputs/closed_loop_takeover_claude_priority_old_redis_adapter_for_copied_script_20260531/CODEX_GO_NO_GO.md' in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
CLOSED_LOOP_TAKEOVER_CLAUDE_PRIORITY_OLD_REDIS_ADAPTER_FOR_COPIED_SCRIPT_20260531_CODEX_FAIL

BLOCKER: The proposed `LegacyNamespaceGuard` enforces only the first key for commands in `_WRITE_KEY_AT_ARG1` (e.g., `RENAME`, `COPY`, `SMOVE`), so a V2 process using those commands can still write to a legacy destination key and bypass the guard. This can silently violate `no old-Redis writes` even when sources are v2-prefixed.

Policy reminders: `live_gate=blocked_human_only`, `live_symbols=[]`. Do not approve live, canary, legacy shutdown, or Redis trim from this scope.

exec
/bin/bash -lc "python - <<'PY'
from pathlib import Path
text=Path('claude_worklog/final_readiness/v2_closed_loop_execution/latest/logs/closed_loop_takeover_claude_priority_old_redis_adapter_for_copied_script_20260531_codex.log').read_text()
start=text.index('BEGIN_FILE: v2/backend/tests/contract/test_copied_script_redis_namespace_contract.py')
end=text.index('END_FILE', start)
lines=text[start:end].splitlines()
for idx,l in enumerate(lines,1):
    if 70<=idx<=140:
        print(f\"{idx:3d}: {l}\")
PY" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
 70:     "lpush", "lpushx", "rpush", "rpushx", "lpop", "rpop",
 71:     "lrem", "lset", "ltrim", "linsert",
 72:     "sadd", "srem", "spop", "smove",
 73:     "zadd", "zrem", "zincrby", "zpopmin", "zpopmax",
 74:     "xadd", "xack", "xdel", "xtrim", "xclaim", "xautoclaim",
 75:     "xgroup_create", "xgroup_destroy", "xgroup_setid",
 76:     "xgroup_createconsumer", "xgroup_delconsumer",
 77:     "publish",
 78:     "delete", "unlink", "mset", "msetnx",
 79:     "flushdb", "flushall",
 80: })
 81: 
 82: 
 83: def _is_v2_safe_expr(node: ast.AST, safe_names: set[str]) -> bool:
 84:     if isinstance(node, ast.Call):
 85:         if isinstance(node.func, ast.Name) and node.func.id == "_v2_key":
 86:             return True
 87:         return False
 88:     if isinstance(node, ast.Constant) and isinstance(node.value, str):
 89:         return node.value.startswith("v2:")
 90:     if isinstance(node, ast.Name):
 91:         return node.id in safe_names
 92:     if isinstance(node, ast.JoinedStr):
 93:         return _joined_str_is_v2_safe(node, safe_names)
 94:     return False
 95: 
 96: 
 97: def _joined_str_is_v2_safe(node: ast.JoinedStr, safe_names: set[str]) -> bool:
 98:     for part in node.values:
 99:         if isinstance(part, ast.Constant) and isinstance(part.value, str):
100:             if part.value == "":
101:                 continue
102:             return part.value.startswith("v2:")
103:         if isinstance(part, ast.FormattedValue):
104:             inner = part.value
105:             if isinstance(inner, ast.Name) and inner.id in safe_names:
106:                 return True
107:             if isinstance(inner, ast.JoinedStr) and _joined_str_is_v2_safe(
108:                 inner, safe_names
109:             ):
110:                 return True
111:             return False
112:         return False
113:     return False
114: 
115: 
116: def _collect_safe_names(tree: ast.AST) -> set[str]:
117:     """Iterate to fixed point collecting names whose every binding is
118:     a v2-safe expression."""
119:     safe: set[str] = set()
120:     while True:
121:         new_safe = set(safe)
122:         for node in ast.walk(tree):
123:             if not isinstance(node, ast.Assign):
124:                 continue
125:             if len(node.targets) != 1:
126:                 continue
127:             tgt = node.targets[0]
128:             if not isinstance(tgt, ast.Name):
129:                 continue
130:             if tgt.id in new_safe:
131:                 continue
132:             if _is_v2_safe_expr(node.value, new_safe):
133:                 new_safe.add(tgt.id)
134:         if new_safe == safe:
135:             return safe
136:         safe = new_safe
137: 
138: 
139: def _collect_write_call_sites(tree: ast.AST) -> list[ast.Call]:
140:     sites: list[ast.Call] = []

codex
The guard leaves an exploitable write path via commands with destination keys, so the core no-old-namespace enforcement claim is not fully met. The additional static-analysis skip on reassignment further weakens proof coverage, so tests can miss unsafe key writes.

Full review comments:

- [P2] Check destination keys for rename/copy/move commands — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/adapters/redis_v2/legacy_namespace_guard.py:106-110
  `assert_v2_namespace` only validates `args[1]` for `_WRITE_KEY_AT_ARG1`, so commands like `RENAME`, `COPY`, and `SMOVE` are treated as safe if their source key is prefixed, even when the destination key is legacy (for example `RENAME v2:src legacy:dst`). In V2 runtime this would still mutate legacy Redis keys through a valid destination argument and silently violate the no-old-Redis-write contract this guard is meant to enforce.

- [P3] Revalidate reassigned keys in static safe-name analysis — /home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/contract/test_copied_script_redis_namespace_contract.py:130-133
  `_collect_safe_names` skips re-checking a name once it is in `new_safe`, so a variable marked safe from one assignment can be overwritten later with a non-v2-safe value and still remain trusted. A copied-script write that uses that variable as a key would then pass as “provably v2 namespaced,” creating a false negative in the contract test and masking a real regression.
The guard leaves an exploitable write path via commands with destination keys, so the core no-old-namespace enforcement claim is not fully met. The additional static-analysis skip on reassignment further weakens proof coverage, so tests can miss unsafe key writes.

Full review comments:

- [P2] Check destination keys for rename/copy/move commands — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/adapters/redis_v2/legacy_namespace_guard.py:106-110
  `assert_v2_namespace` only validates `args[1]` for `_WRITE_KEY_AT_ARG1`, so commands like `RENAME`, `COPY`, and `SMOVE` are treated as safe if their source key is prefixed, even when the destination key is legacy (for example `RENAME v2:src legacy:dst`). In V2 runtime this would still mutate legacy Redis keys through a valid destination argument and silently violate the no-old-Redis-write contract this guard is meant to enforce.

- [P3] Revalidate reassigned keys in static safe-name analysis — /home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/contract/test_copied_script_redis_namespace_contract.py:130-133
  `_collect_safe_names` skips re-checking a name once it is in `new_safe`, so a variable marked safe from one assignment can be overwritten later with a non-v2-safe value and still remain trusted. A copied-script write that uses that variable as a key would then pass as “provably v2 namespaced,” creating a false negative in the contract test and masking a real regression.
2026-05-31T06:28:19.567477Z ERROR codex_core::session: failed to record rollout items: thread 019e7cb4-7c37-7fa3-9387-91dca4f83901 not found
```
