"""Contract test: middleware stack matches MIDDLEWARE_ORDER per 04 §3.

`app.user_middleware` is the Starlette source of truth. Because
`add_middleware()` does `insert(0, ...)`, the registered list is the
reverse of the declared outermost→innermost order. This test asserts:

1. `MIDDLEWARE_ORDER` enumerates the EXACT 10 middleware listed in the
   015D task spec.
2. `create_app()` registers them so `app.user_middleware` is the reverse
   of `MIDDLEWARE_ORDER` — which proves request-time wrapping puts
   `RequestIdMiddleware` outermost and `DbErrorTranslatorMiddleware`
   innermost.

Any drift in either direction reopens the §3 contract.
"""

from __future__ import annotations

from app.api.middleware import MIDDLEWARE_ORDER
from app.main import create_app


REQUIRED_NAMES: tuple[str, ...] = (
    "RequestIdMiddleware",
    "IpAllowlistMiddleware",
    "RateLimitMiddleware",
    "StepUpMfaMiddleware",
    "RbacMiddleware",
    "IdempotencyMiddleware",
    "LineageValidatorMiddleware",
    "ApprovalMiddleware",
    "LiveBlockGuardMiddleware",
    "DbErrorTranslatorMiddleware",
)


def test_middleware_order_matches_required_names() -> None:
    actual = tuple(cls.__name__ for cls in MIDDLEWARE_ORDER)
    assert actual == REQUIRED_NAMES, (
        f"MIDDLEWARE_ORDER drifted from §3 contract. "
        f"Expected {REQUIRED_NAMES}, got {actual}."
    )


def test_app_registration_reverses_middleware_order() -> None:
    app = create_app()
    actual = tuple(m.cls for m in app.user_middleware)
    expected = tuple(reversed(MIDDLEWARE_ORDER))
    assert actual == expected, (
        f"app.user_middleware does not match reverse(MIDDLEWARE_ORDER). "
        f"Expected {[c.__name__ for c in expected]}, "
        f"got {[c.__name__ for c in actual]}."
    )


def test_middleware_count_is_ten() -> None:
    assert len(MIDDLEWARE_ORDER) == 10
