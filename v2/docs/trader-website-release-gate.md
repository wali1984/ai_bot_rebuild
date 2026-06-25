# Trader Website Release Gate

Generated: 2026-06-24T00:52:09.167Z
Base URL: https://dashboard.wajidali.us
Release gate pass: false

## Checks

| Check | Status | Evidence | Blocker |
|---|---|---|---|
| real backend login succeeds | PASS | method=login_form authenticated=true |  |
| every trader route opens through menu navigation | BLOCKED | pages=19 direct_fallbacks=8 | visible menu path failed for one or more required routes |
| all cross-page field comparisons pass | PASS | phase=after missing=0 mismatches=0 navigation_errors=0 | field comparison artifact still has missing, mismatched, or navigation-blocked fields |
| all required core fields have rendered metadata | PASS | cross_observations=59 live_values=71 | deployed pages did not expose required data-field-id metadata in before artifact |
| no failed request | BLOCKED | audit_http_failures=24 cross_failed_requests=22 | production audit recorded failed requests |
| no console error | BLOCKED | audit_console_errors=0 cross_console_errors=1 | production consistency run recorded console errors |
| no clipping or overflow | BLOCKED | text_clipping=243 | production before screenshots detected clipped text |
| all four viewport screenshots pass | PASS | screenshots=76 expected=76 |  |
| frontend typecheck passes | PASS | npm run --prefix frontend typecheck passed locally |  |
| frontend build passes | PASS | npm run --prefix frontend build passed locally |  |
| trader tests pass | BLOCKED | cross_page_release_blocker=true | deployed trader cross-page test is currently blocking |
| relevant backend tests pass | PASS | backend/tests/integration/api/v2/test_trader_snapshot.py passed locally |  |
| deployed-domain audit passes | BLOCKED | artifact=after status=OPEN | deployed audit is not VERIFIED and records field/navigation/network blockers |

## Trader Lane State

Current phase artifact: after
Cross-page missing comparisons: 0
Cross-page mismatches: 0
Production HTTP failures: 24
Production console errors: 0
Screenshots captured: 76

Live execution remains blocked. This gate evaluates trader-facing website readiness only.
