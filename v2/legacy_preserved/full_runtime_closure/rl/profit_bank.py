"""
Profit Bank (No-Loss Equity Growth)
=================================

Purpose:
- Maintain a per-account "profit bank" sourced ONLY from realized, net-positive exits.
- The bank is used as a conservative allocator for recovery and sizing governors:
  you can spend *earned* profits to add margin to underwater legs (hedged-only),
  without ever realizing losses.

Data source:
- Redis Stream: executed_signals (published by traders)
  Requires payload fields:
    - account_id
    - action (CLOSE_*/DECREASE_*/PARTIAL_CLOSE_* etc)
    - success/executed flags
    - realized_pnl_usd (best-effort), fee_usd (optional)

Storage:
- profit_bank:state:{account_id} (JSON, TTL-free)
- profit_bank:last_id:{account_id} (last processed stream id)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)
PROFIT_BANK_LOG_VERBOSE = os.getenv("PROFIT_BANK_LOG_VERBOSE", "true").lower() in ("1", "true", "yes")


def _f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _is_close_like(action: str) -> bool:
    au = str(action or "").upper()
    return any(tok in au for tok in ("CLOSE", "DECREASE", "PARTIAL_CLOSE", "TAKE_PROFIT"))


@dataclass
class ProfitBankState:
    balance_usd: float = 0.0
    credited_usd: float = 0.0
    debited_usd: float = 0.0
    last_update_ts: float = 0.0


class ProfitBank:
    def __init__(self, redis_client: Any, *, account_id: str):
        self.redis = redis_client
        self.account_id = str(account_id or "").strip().lower()
        self._state_key = f"profit_bank:state:{self.account_id}"
        self._last_id_key = f"profit_bank:last_id:{self.account_id}"

    def load(self) -> ProfitBankState:
        try:
            raw = self.redis.get(self._state_key)
            raw = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
            data = json.loads(raw) if raw else {}
            return ProfitBankState(
                balance_usd=_f(data.get("balance_usd"), 0.0),
                credited_usd=_f(data.get("credited_usd"), 0.0),
                debited_usd=_f(data.get("debited_usd"), 0.0),
                last_update_ts=_f(data.get("last_update_ts"), 0.0),
            )
        except Exception:
            return ProfitBankState()

    def save(self, st: ProfitBankState) -> None:
        try:
            payload = {
                "account_id": self.account_id,
                "balance_usd": float(st.balance_usd),
                "credited_usd": float(st.credited_usd),
                "debited_usd": float(st.debited_usd),
                "last_update_ts": float(st.last_update_ts),
            }
            self.redis.set(self._state_key, json.dumps(payload, separators=(",", ":")))
        except Exception:
            pass

    def credit(self, amount_usd: float, *, reason: str = "") -> ProfitBankState:
        st = self.load()
        amt = max(0.0, float(amount_usd or 0.0))
        if amt <= 0:
            return st
        st.balance_usd += amt
        st.credited_usd += amt
        st.last_update_ts = time.time()
        self.save(st)
        if PROFIT_BANK_LOG_VERBOSE:
            logger.info(f"💰 [PROFIT_BANK] CREDIT | acct={self.account_id} | +${amt:.2f} | balance=${st.balance_usd:.2f} | reason={reason}")
        return st

    def debit(self, amount_usd: float, *, reason: str = "") -> Tuple[ProfitBankState, float]:
        st = self.load()
        amt = max(0.0, float(amount_usd or 0.0))
        if amt <= 0:
            return st, 0.0
        used = min(float(st.balance_usd), amt)
        st.balance_usd -= used
        st.debited_usd += used
        st.last_update_ts = time.time()
        self.save(st)
        if PROFIT_BANK_LOG_VERBOSE and used > 0:
            logger.info(f"💸 [PROFIT_BANK] DEBIT | acct={self.account_id} | -${used:.2f} | balance=${st.balance_usd:.2f} | reason={reason}")
        return st, float(used)

    def ingest_executed_signals(self, *, stream: str = "executed_signals", max_read: int = 5000) -> Dict[str, Any]:
        """
        Read executed_signals since last id and credit profit bank for net-positive realized exits.
        """
        if not self.redis or not self.account_id:
            return {"processed": 0, "credited_usd": 0.0, "last_id": None}

        last_id = self.redis.get(self._last_id_key) or "0-0"
        processed = 0
        credited = 0.0
        newest_id = None

        try:
            # XRANGE is ok because we persist last_id; keep bounded per cycle.
            rows = self.redis.xrange(stream, min=last_id, max="+", count=max_read) or []
        except Exception:
            rows = []

        for sid, fields in rows:
            # skip the last_id itself when using inclusive xrange
            if str(sid) == str(last_id):
                continue
            newest_id = sid
            raw = fields.get("data") or "{}"
            try:
                p = json.loads(raw)
            except Exception:
                continue

            acct = str(p.get("account_id") or "").strip().lower()
            if acct != self.account_id:
                continue

            action = str(p.get("action") or p.get("action_name") or "")
            if not _is_close_like(action):
                continue

            ok = bool(p.get("success") or p.get("executed") or p.get("ok"))
            if not ok:
                continue

            realized = _f(p.get("realized_pnl_usd"), 0.0)
            fee = _f(p.get("fee_usd"), 0.0)
            net = float(realized) - float(fee)
            # Only bank strict net-positive closes (no-loss + fee-aware)
            if net > 0.0:
                credited += float(net)
                self.credit(net, reason=f"executed_signals_close_net_profit|{action}")
                if PROFIT_BANK_LOG_VERBOSE:
                    logger.info(f"💰 [PROFIT_BANK] INGEST | acct={self.account_id} | net_profit=${net:.2f} | action={action} | realized=${realized:.2f} | fee=${fee:.2f}")
            processed += 1

        if newest_id is not None:
            try:
                self.redis.set(self._last_id_key, str(newest_id))
            except Exception:
                pass

        # Ensure state exists even if no credits (observability)
        try:
            if self.redis.get(self._state_key) is None:
                self.save(self.load())
        except Exception:
            pass

        return {"processed": int(processed), "credited_usd": float(credited), "last_id": str(newest_id) if newest_id else None}

    def ingest_profit_exit_feedback(self, *, stream: str = "wma:trader:execution_feedback", max_read: int = 2000) -> Dict[str, Any]:
        """
        Ingest PROFIT_EXIT events (profit_intent closes) and credit the bank.
        This is the most reliable source for realized_pnl_usd in the no-loss system.
        """
        if not self.redis or not self.account_id:
            return {"processed": 0, "credited_usd": 0.0, "last_id": None}

        last_id_key = f"{self._last_id_key}:profit_exit"
        last_id = self.redis.get(last_id_key) or "0-0"
        processed = 0
        credited = 0.0
        newest_id = None

        try:
            rows = self.redis.xrange(stream, min=last_id, max="+", count=max_read) or []
        except Exception:
            rows = []

        for sid, fields in rows:
            if str(sid) == str(last_id):
                continue
            newest_id = sid
            raw = fields.get("data") or "{}"
            try:
                p = json.loads(raw)
            except Exception:
                continue
            if str(p.get("event_type") or "").upper() != "PROFIT_EXIT":
                continue
            acct = str(p.get("account_id") or "").strip().lower()
            if acct != self.account_id:
                continue
            realized = _f(p.get("realized_pnl_usd"), 0.0)
            # fee not always present here; treat realized as net-positive driver
            if realized > 0.0:
                credited += float(realized)
                self.credit(realized, reason="profit_exit_feedback")
            processed += 1

        if newest_id is not None:
            try:
                self.redis.set(last_id_key, str(newest_id))
            except Exception:
                pass

        try:
            if self.redis.get(self._state_key) is None:
                self.save(self.load())
        except Exception:
            pass

        return {"processed": int(processed), "credited_usd": float(credited), "last_id": str(newest_id) if newest_id else None}

