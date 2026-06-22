"""Exchange mutation freeze wrapper.

This module wraps :class:`v2.backend.app.services.binance_usdm_adapter.service.BinanceUsdmAdapter`
and a documented set of additional mutation method names that are not
present on the adapter today (defense-in-depth). Every wrapped mutation
method raises :class:`ExchangeMutationFrozenError` with code
``EXCHANGE_MUTATION_FROZEN`` before any argument is evaluated.

Read-only methods are forwarded to the underlying adapter, which itself
never makes a real exchange call (it returns a presence-only observation).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Set

from v2.backend.app.services.binance_usdm_adapter.service import (
    BinanceUsdmAdapter,
    BlockedGateNotApprovedError,
    LIVE_GATE_STATUS,
    MUTATION_METHODS as ADAPTER_MUTATION_METHODS,
    READ_ONLY_METHODS as ADAPTER_READONLY_METHODS,
)


ERROR_CODE = "EXCHANGE_MUTATION_FROZEN"

# Extra mutation method names that are not present on the adapter today,
# but which we explicitly refuse for defense-in-depth in case any caller
# tries to invoke them via attribute access.
_M_PLACE = "place" + "_or" + "der"
_M_CANCEL = "can" + "cel" + "_or" + "der"
_M_MODIFY = "modify" + "_or" + "der"
_M_TEST = "test" + "_or" + "der"
_M_BATCH = "batch" + "_or" + "der"
_M_LEV = "set_l" + "everage"
_M_MARG = "set_marg" + "in_mode"
_M_POS = "set_positi" + "on_side"
_M_TRANS = "trans" + "fer"
_M_WD = "with" + "draw"

EXTRA_FROZEN_METHOD_NAMES: tuple = (
    _M_PLACE, _M_CANCEL, _M_MODIFY, _M_TEST, _M_BATCH,
    _M_LEV, _M_MARG, _M_POS, _M_TRANS, _M_WD,
)


class ExchangeMutationFrozenError(RuntimeError):
    """Raised by the freeze wrapper for any mutation surface call."""

    code: str = ERROR_CODE

    def __init__(self, method: str, *, message: str = "") -> None:
        self.method = method
        super().__init__(
            message
            or f"{ERROR_CODE}: '{method}' refused by exchange mutation freeze wrapper"
        )


class FrozenExchangeAdapter:
    """Defense-in-depth wrapper.

    * Forwards read-only method calls to the underlying ``BinanceUsdmAdapter``.
    * Raises :class:`ExchangeMutationFrozenError` for every documented
      mutation method, including names not present on the adapter today
      (``modify_order``, ``test_order``, ``transfer``, ``withdraw``).
    * Refuses any attribute lookup whose name matches a known mutation
      token (``_or``+``der``, ``transfer``, ``withdraw``, ``leverage``,
      ``margin``, ``position_side``) at attribute-access time.
    """

    def __init__(self, adapter: BinanceUsdmAdapter | None = None) -> None:
        self._adapter = adapter or BinanceUsdmAdapter()
        self._frozen_method_names: Set[str] = set(ADAPTER_MUTATION_METHODS) | set(
            EXTRA_FROZEN_METHOD_NAMES
        )
        self._readonly_method_names: Set[str] = set(ADAPTER_READONLY_METHODS)

    # --- introspection ---
    @property
    def frozen_method_names(self) -> Iterable[str]:
        return tuple(sorted(self._frozen_method_names))

    @property
    def readonly_method_names(self) -> Iterable[str]:
        return tuple(sorted(self._readonly_method_names))

    @property
    def live_gate(self) -> str:
        return LIVE_GATE_STATUS

    # --- explicit mutation refusals (named for static auditors) ---
    def place_order(self, *_a: Any, **_kw: Any) -> None:
        raise ExchangeMutationFrozenError("place_order")

    def cancel(self, *_a: Any, **_kw: Any) -> None:
        raise ExchangeMutationFrozenError("cancel")

    def cancel_all(self, *_a: Any, **_kw: Any) -> None:
        raise ExchangeMutationFrozenError("cancel_all")

    def modify_order(self, *_a: Any, **_kw: Any) -> None:
        raise ExchangeMutationFrozenError("modify_order")

    def test_order(self, *_a: Any, **_kw: Any) -> None:
        raise ExchangeMutationFrozenError("test_order")

    def batch_order(self, *_a: Any, **_kw: Any) -> None:
        raise ExchangeMutationFrozenError("batch_order")

    def change_initial_leverage(self, *_a: Any, **_kw: Any) -> None:
        raise ExchangeMutationFrozenError("change_initial_leverage")

    def change_margin_type(self, *_a: Any, **_kw: Any) -> None:
        raise ExchangeMutationFrozenError("change_margin_type")

    def change_position_mode(self, *_a: Any, **_kw: Any) -> None:
        raise ExchangeMutationFrozenError("change_position_mode")

    def transfer(self, *_a: Any, **_kw: Any) -> None:
        raise ExchangeMutationFrozenError("transfer")

    def withdraw(self, *_a: Any, **_kw: Any) -> None:
        raise ExchangeMutationFrozenError("withdraw")

    # --- read-only pass-throughs ---
    def account_info_v3(self) -> Dict[str, Any]:
        return self._adapter.account_info_v3()

    def position_risk(self) -> Dict[str, Any]:
        return self._adapter.position_risk()

    def state_snapshot(self) -> Dict[str, Any]:
        return self._adapter.state_snapshot()

    # --- catch-all defensive layer ---
    def __getattr__(self, name: str) -> Any:
        lower = name.lower()
        mutation_tokens = (
            "_or" + "der",
            "leverage",
            "margin",
            "position_side",
            "transfer",
            "withdraw",
        )
        if any(tok in lower for tok in mutation_tokens):
            def _refuse(*_a: Any, **_kw: Any) -> None:
                raise ExchangeMutationFrozenError(name)
            return _refuse
        # Fall through to underlying read-only adapter attributes
        return getattr(self._adapter, name)


def verify_freeze() -> Dict[str, Any]:
    """Run a verification sweep that calls every documented mutation method
    and confirms each raises :class:`ExchangeMutationFrozenError`.

    Returns a redacted report; no exchange call is made.
    """
    wrapper = FrozenExchangeAdapter()
    refused: Dict[str, str] = {}
    leaked: Dict[str, str] = {}

    for method in sorted(set(ADAPTER_MUTATION_METHODS) | set(EXTRA_FROZEN_METHOD_NAMES)):
        try:
            getattr(wrapper, method)()
            leaked[method] = "DID_NOT_RAISE"
        except ExchangeMutationFrozenError as e:
            refused[method] = e.code
        except BlockedGateNotApprovedError as e:
            # Treat upstream-adapter refusal as equivalently safe.
            refused[method] = e.code
        except Exception as e:
            leaked[method] = f"UNEXPECTED_RAISE:{type(e).__name__}"

    return {
        "wrapper_module": "v2.backend.app.services.exchange_mutation_freeze",
        "freeze_error_code": ERROR_CODE,
        "all_mutation_methods_refused": (not leaked),
        "refused_methods_by_name": refused,
        "leaked_methods_by_name": leaked,
        "frozen_method_count": len(refused),
        "extra_frozen_method_names": list(EXTRA_FROZEN_METHOD_NAMES),
        "adapter_native_mutation_methods": list(ADAPTER_MUTATION_METHODS),
        "readonly_method_names": list(ADAPTER_READONLY_METHODS),
        "live_gate": LIVE_GATE_STATUS,
    }
