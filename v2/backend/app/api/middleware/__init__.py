"""Middleware stack for the V2 API.

`MIDDLEWARE_ORDER` is the canonical outermost→innermost order per §3 of
`claude_worklog/v2_scaffold_planning/04_API_ROUTE_SCAFFOLD_PLAN.md`. The
contract test `tests/contract/test_middleware_order.py` introspects
`app.user_middleware` after `create_app()` and asserts this order has not
drifted. Reordering this tuple without also updating the §3 plan is a
contract break that fails CI.

The `auth_session` step listed in §3.4 of the plan is intentionally not
materialized in the milestone D skeleton; session resolution lands with
the auth router behavior in milestone D proper.
"""

from app.api.middleware.approval import ApprovalMiddleware
from app.api.middleware.cors import CORSMiddleware
from app.api.middleware.db_error_translator import DbErrorTranslatorMiddleware
from app.api.middleware.idempotency import IdempotencyMiddleware
from app.api.middleware.ip_allowlist import IpAllowlistMiddleware
from app.api.middleware.lineage_validator import LineageValidatorMiddleware
from app.api.middleware.live_block_guard import LiveBlockGuardMiddleware
from app.api.middleware.rate_limit import RateLimitMiddleware
from app.api.middleware.rbac import RbacMiddleware
from app.api.middleware.request_id import RequestIdMiddleware
from app.api.middleware.step_up_mfa import StepUpMfaMiddleware

MIDDLEWARE_ORDER: tuple[type, ...] = (
    CORSMiddleware,
    RequestIdMiddleware,
    IpAllowlistMiddleware,
    RateLimitMiddleware,
    StepUpMfaMiddleware,
    RbacMiddleware,
    IdempotencyMiddleware,
    LineageValidatorMiddleware,
    ApprovalMiddleware,
    LiveBlockGuardMiddleware,
    DbErrorTranslatorMiddleware,
)

__all__ = [
    "ApprovalMiddleware",
    "CORSMiddleware",
    "DbErrorTranslatorMiddleware",
    "IdempotencyMiddleware",
    "IpAllowlistMiddleware",
    "LineageValidatorMiddleware",
    "LiveBlockGuardMiddleware",
    "MIDDLEWARE_ORDER",
    "RateLimitMiddleware",
    "RbacMiddleware",
    "RequestIdMiddleware",
    "StepUpMfaMiddleware",
]
