# Validation and limitations — 2026-07-16 reverse engineering

## 1. Outcome

The documentation and static-atlas deliverables are suitable as the current
source-navigation and reconstruction baseline. They do **not** make the trading
system live-ready, prove clean learning evidence, or make the deployed host
reproducible from Git alone.

The system verdict remains:

- documentation/static reconstruction: accepted at the recorded source snapshot;
- live trading: **NO-GO**;
- current paper outcomes as promotion evidence: **NO-GO**;
- clean-host deployment reproducibility: **NO-GO**;
- destructive retention repair: **NO-GO without an approved authority/migration plan**.

## 2. Snapshot integrity

The final full atlas regeneration recorded in
[`atlas/ATLAS_METADATA.json`](atlas/ATLAS_METADATA.json) recorded the same Git
commit at scan start and end:
`2dd584d632790c54c1054f7c4453cb9d36d0987c`. It also
revalidated an unchanged 9,272-path tracked list and every captured regular-file
hash/symlink/nonregular input, and reported no TypeScript cross-builder hash
mismatch. `snapshot_consistent` and `content_inputs_unchanged` were true. The scan
deliberately records dirty tracked files; stable content during the scan does not
imply a clean working tree or continued stability after generation. Validate
artifacts against `atlas/ATLAS_BUILD_MANIFEST.json` and regenerate after edits.

The deployed host is independently mutable. During this single audit window:

- active timers changed from 36 to 35;
- running services later changed from 81 to 80;
- failed services later changed from 3 to 2;
- installed unit-basename comparison changed;
- the replay tree was observed near 259 GiB and later near 247 GiB;
- resident automation advanced Git HEAD after the first atlas scan.

These are point-in-time observations. The audit does not attribute each state
change to a specific process. Refresh runtime evidence before acting.

## 3. Static atlas validation

The generated atlas at the final source snapshot contains:

| Surface | Records |
|---|---:|
| Tracked paths | 9,272 |
| Python modules | 3,213 |
| Python symbols | 32,272 |
| TypeScript/JavaScript symbols | 3,334 |
| Swift declarations | 693 |
| Python imports | 25,389 |
| Python call references | 161,112 |
| Data/schema contracts | 1,807 |
| Data field names | 39,538 |
| Environment-key names | 2,918 |
| Redis patterns | 2,040 |
| API definition/reference records | 905 |
| Exchange-mutation review references | 37 |

The two Python parse failures are preserved legacy microstructure files. They are
listed explicitly in the file/module catalog; the generator does not silently
drop them.

Focused tooling validation:

| Check | Result |
|---|---|
| Python compile of generator and tests | Passed |
| Node syntax check of TypeScript helper | Passed |
| TypeScript helper self-test | Passed; 9 symbols, 4 contracts and 3 API references recognized |
| Atlas pytest | 22 passed |
| Inconsistent-snapshot publication gate | Passed; an observed tracked-file mutation returned failure and preserved the prior canonical atlas |
| Full atlas generation | Passed; successful final passes took approximately 41–44 seconds |
| Start/end commit equality | Passed |

The large JSON catalogs are deterministic, regeneratable local artifacts and are
ignored by Git because they occupy hundreds of megabytes. The generator,
human-readable summary and one-row-per-module index are retained in the change
set. Regenerate JSON after any material source change.

## 4. Scoped product validation

Only tests judged isolated enough for this documentation audit were run.

| Scope | Result | Boundary |
|---|---|---|
| Frontend TypeScript typecheck | Passed | Does not prove build, browser, service worker, Cloudflare route or deployed `dist`. |
| Swift Core tests | 32 passed | `AIBOT_SPM_EXCLUDE_APP_TARGETS=1`; iOS/watch application targets and real server compatibility excluded. |
| Middleware-order contract | 1 passed, 2 failed | Expectations are stale relative to eleven registered layers including CORS. |
| Canonical candle + pipeline trust group | 66 passed, 6 failed | Six publisher tests stop on stale synthetic tensor fixtures before intended assertions. |

All six pipeline failures have the same contract-drift cause:

```text
publisher._trusted_replay_snapshot reads tensor.missing_mask
test example() supplies a SimpleNamespace without missing_mask
AttributeError occurs before the publisher/trust assertion
```

Source anchors are
`v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py:562`
and
`v2/backend/tests/unit/test_pipeline_trust_runtime_enforcement.py:653-670`.
This is not evidence that canonical candle or temporal gates failed, but it means
six intended publisher/trust assertions currently provide no protection.

## 5. Documentation validation

The canonical set is checked for:

- balanced fenced code blocks;
- trailing whitespace and `git diff --check` errors;
- resolvable Markdown links;
- existence and line bounds for explicitly repo-qualified source anchors;
- manual disambiguation of scoped shorthand source anchors;
- internally consistent Markdown table column counts;
- stale atlas/API/WebSocket counts;
- `TODO`, `TBD`, placeholder-document and missing-component markers;
- known plaintext credential recurrence and secret-like literal assignments;
- canonical timestamp terminology and point-in-time inequalities;
- contradiction between snapshot values and design constants.

Old component audits now carry a superseded banner rather than being deleted.
They remain historical evidence but are not current operating instructions.

## 6. Secret-safety validation

The static generator excludes secret-bearing artifacts by path and never emits
environment values. Secret-named source-code modules remain analyzable so their
call/import impact is not hidden; non-code credential/auth artifacts are excluded.

The canonical documentation contains credential **names**, storage locations,
permission findings and required rotation actions, but no discovered credential
value. The previously documented plaintext operator password was removed. The
raw local Codex session ledgers can contain sensitive source/output context and
must not be published without a separate sanitization pass.

`gitleaks` was not installed on the workstation, and the existing repository
wrapper exits successfully when it is absent. That wrapper is not accepted as a
secret-scan proof.

## 7. Tests intentionally not run

The full backend/integration/browser/deployment suite was not run because:

- repository history documents a prior integration test overwriting real paper
  state and losing closed-trade history;
- isolation is not globally proven for Redis, local auth, paper files, runtime
  artifacts or subprocess routes;
- Playwright blocks service workers and several tests mock authentication;
- the current frontend dependency tree is incomplete;
- system/service and exchange-touching exercises would exceed this
  documentation-only authorization.

No real or paper order was intentionally submitted, modified or cancelled. No
service/timer was started, stopped, restarted, enabled or disabled. Redis keys,
checkpoints, release gates and retention data were not mutated by this audit.

## 8. Static-analysis limitations

The atlas is a conservative lower bound. Manual review is still required for:

- dynamic imports and reflection;
- dependency injection/framework callbacks;
- overloaded or monkey-patched calls;
- Redis keys assembled from runtime values;
- shell/systemd indirection and installed drop-ins;
- TypeScript computed routes and runtime JSON;
- Swift conditional compilation and generated Xcode projects;
- provider-side Cloudflare routing and external API behavior;
- native extensions, CUDA kernels and behavior inside dependencies;
- runtime data-dependent branches and cross-process races.

An unresolved call or absent static edge means “not statically proven,” not “no
dependency.” Use the change-impact workflow in
`components/CONFIG_KEYS_CONTRACTS_AND_CHANGE_IMPACT.md` and inspect runtime
authorities before a change.

## 9. Revalidation trigger

Regenerate and re-audit when any of these changes:

- Git commit or dirty runtime source;
- feature order/count, tensor layout, action schema or model architecture;
- timestamp/lineage semantics;
- replay labels, costs, reward, PPO/MASA or checkpoint identity;
- orchestrator/risk/paper/live admission logic;
- Redis key/schema/TTL/eviction policy;
- installed unit/drop-in, environment, worker count or release mode;
- API/auth route, middleware, TypeScript or Swift contract;
- storage, backup, archive or retention authority.

The complete verbatim command and tool evidence is indexed in
`COMMANDS_RUN.md`.
