#!/usr/bin/env python3
"""Comprehensive diagnostic of paper loop signal flow and all blockers.

Traces a signal from evaluation through all gates to execution.
Identifies every blocker, threshold, and gate that could stop candidates.
"""
import json
import redis
import sys
from datetime import datetime, timezone

r = redis.Redis(decode_responses=True)

def diagnostic():
    print("\n" + "="*80)
    print("COMPREHENSIVE PAPER LOOP DIAGNOSTIC")
    print("="*80 + "\n")

    # 1. PAPER LOOP EXECUTION
    print("1. PAPER LOOP EXECUTION STATUS")
    print("-" * 80)
    try:
        status = r.get("v2:paper:runtime:heartbeat")
        if status:
            status = json.loads(status)
            print(f"  Status: {status.get('cycle_state', 'UNKNOWN')}")
            print(f"  Last cycle: {status.get('cycle_started_at', 'UNKNOWN')}")
        else:
            print("  ⚠ No heartbeat - loop may not be running")
    except Exception as e:
        print(f"  ✗ Error reading heartbeat: {e}")

    # 2. SIGNAL SUPPLY
    print("\n2. SIGNAL SUPPLY")
    print("-" * 80)
    signals = r.keys("v2:signals:paper:*")
    print(f"  Total signals available: {len(signals)}")

    # 3. PREDICTION SUPPLY
    print("\n3. PREDICTION SUPPLY")
    print("-" * 80)
    predictions = r.keys("v2:prediction:*")
    print(f"  Total predictions available: {len(predictions)}")

    # 4. PREEMPTIVE EDGE CONTROL
    print("\n4. PREEMPTIVE EDGE CONTROL GATE")
    print("-" * 80)
    preemptive_decisions = {}
    for key in r.keys("v2:intent:*:preemptive_decision"):
        decision = r.get(key)
        preemptive_decisions[decision] = preemptive_decisions.get(decision, 0) + 1
    if preemptive_decisions:
        for decision, count in sorted(preemptive_decisions.items()):
            status = "✓" if decision != "NO_TRADE" else "✗"
            print(f"  {status} {decision}: {count}")
    else:
        print(f"  ⚠ No preemptive decisions found (candidates not evaluated)")

    # 5. ALLOCATOR GATE
    print("\n5. ALLOCATOR GATE")
    print("-" * 80)
    allocator_decisions = {}
    for key in r.keys("v2:intent:*:allocator_decision"):
        decision = r.get(key)
        allocator_decisions[decision] = allocator_decisions.get(decision, 0) + 1
    if allocator_decisions:
        for decision, count in sorted(allocator_decisions.items()):
            status = "✓" if "ACCEPT" in decision else "✗"
            print(f"  {status} {decision}: {count}")
    else:
        print(f"  ⚠ No allocator decisions (candidates not reaching allocator)")

    # 6. RISK GATEWAY
    print("\n6. RISK GATEWAY")
    print("-" * 80)
    risk_decisions = {}
    for key in r.keys("v2:risk:decisions:*"):
        decision = r.get(key)
        if decision:
            try:
                decision = json.loads(decision)
                status = decision.get("risk_decision_status", "UNKNOWN")
                risk_decisions[status] = risk_decisions.get(status, 0) + 1
            except:
                pass
    if risk_decisions:
        for decision, count in sorted(risk_decisions.items()):
            status = "✓" if "ALLOW" in decision else "✗"
            print(f"  {status} {decision}: {count}")
    else:
        print(f"  ⚠ No risk gateway decisions")

    # 7. A+ GATE STATUS
    print("\n7. A+ GATE STATUS")
    print("-" * 80)
    try:
        a_plus_status = r.get("v2:a_plus:gate:status")
        if a_plus_status:
            a_plus_status = json.loads(a_plus_status)
            print(f"  Gate status: {a_plus_status.get('status', 'UNKNOWN')}")
            print(f"  Candidates evaluated: {a_plus_status.get('total_evaluated', 0)}")
            print(f"  Candidates passed: {a_plus_status.get('passed_count', 0)}")
    except Exception as e:
        print(f"  ✗ Error reading A+ gate: {e}")

    # 8. PAPER TRADES OUTPUT
    print("\n8. PAPER TRADES OUTPUT")
    print("-" * 80)
    try:
        closed_trades_raw = r.get("v2:paper:closed_trades")
        if closed_trades_raw:
            closed_trades = json.loads(closed_trades_raw)
            print(f"  Closed trades: {len(closed_trades)}")
            if closed_trades:
                latest = closed_trades[-1]
                print(f"  Latest trade: {latest.get('symbol')} {latest.get('side')} pnl=${latest.get('realized_pnl_usd', 0):.2f}")
        else:
            print(f"  No closed trades")
    except Exception as e:
        print(f"  ✗ Error reading closed trades: {e}")

    # 9. TRAINER STATUS
    print("\n9. TRAINER STATUS")
    print("-" * 80)
    try:
        trainer_status = r.get("v2:trainer:hybrid_cuda:status")
        if trainer_status:
            trainer_status = json.loads(trainer_status)
            print(f"  Mode: {trainer_status.get('effective_trainer_mode', 'UNKNOWN')}")
            print(f"  Checkpoint: {trainer_status.get('checkpoint_id', 'UNKNOWN')[:20]}...")
            print(f"  Promotion allowed: {trainer_status.get('checkpoint_promotion_allowed', False)}")
            print(f"  Promotion this cycle: {trainer_status.get('checkpoint_promoted_this_cycle', False)}")
    except Exception as e:
        print(f"  ✗ Error reading trainer status: {e}")

    # 10. CHECKPOINT EVIDENCE
    print("\n10. CHECKPOINT PROMOTION EVIDENCE")
    print("-" * 80)
    try:
        checkpoint_evidence = r.get("v2:trainer:checkpoint:evidence")
        if checkpoint_evidence:
            evidence = json.loads(checkpoint_evidence)
            print(f"  Active checkpoint: {evidence.get('active_checkpoint_id', 'UNKNOWN')}")
            print(f"  Native checkpoint: {evidence.get('native_checkpoint_id', 'UNKNOWN')[:20]}...")
            print(f"  Native load status: {evidence.get('native_checkpoint_load_status', 'UNKNOWN')}")
            print(f"  Blockers: {evidence.get('missing_checkpoint_blockers', [])}")
    except Exception as e:
        print(f"  ✗ Error reading checkpoint evidence: {e}")

    # 11. PERFORMANCE CIRCUIT BREAKER
    print("\n11. PERFORMANCE CIRCUIT BREAKER")
    print("-" * 80)
    try:
        cb_status = r.get("v2:paper:performance_circuit_breaker_status")
        if cb_status:
            cb_status = json.loads(cb_status)
            print(f"  Status: {cb_status.get('circuit_status', 'UNKNOWN')}")
            print(f"  Win rate: {cb_status.get('win_rate_percent', 0):.1f}%")
            print(f"  Profit factor: {cb_status.get('profit_factor', 0):.2f}")
            print(f"  Net PnL: ${cb_status.get('net_pnl_usd', 0):.2f}")
            if cb_status.get('is_halted'):
                print(f"  ✗ HALTED: {cb_status.get('halt_reason', 'UNKNOWN')}")
    except Exception as e:
        print(f"  ✗ Error reading circuit breaker: {e}")

    # 12. GUARDIAN STATUS
    print("\n12. CONTINUOUS EDGE GUARDIAN")
    print("-" * 80)
    try:
        guardian_status = r.get("v2:continuous_edge_guardian:status")
        if guardian_status:
            guardian_status = json.loads(guardian_status)
            print(f"  Status: {guardian_status.get('guardian_status', 'UNKNOWN')}")
            print(f"  Halted: {guardian_status.get('is_halted', False)}")
            if guardian_status.get('is_halted'):
                print(f"  Reason: {guardian_status.get('halt_reason', 'UNKNOWN')}")
    except Exception as e:
        print(f"  ✗ Error reading guardian: {e}")

    # 13. INTENTS
    print("\n13. INTENTS CREATED THIS CYCLE")
    print("-" * 80)
    intents = r.keys("v2:intent:*")
    print(f"  Total intents: {len(intents)}")
    if intents:
        # Sample a few intents to see their status
        for key in list(intents)[:3]:
            try:
                intent_data = r.get(key)
                if intent_data:
                    intent = json.loads(intent_data)
                    print(f"\n  Intent: {key[-40:]}")
                    print(f"    Status: {intent.get('intent_status', 'UNKNOWN')}")
                    print(f"    Preemptive: {intent.get('preemptive_decision', 'UNKNOWN')}")
                    print(f"    Allocator: {intent.get('allocator_decision', 'UNKNOWN')}")
            except:
                pass

    print("\n" + "="*80)
    print("DIAGNOSTIC COMPLETE")
    print("="*80 + "\n")

if __name__ == "__main__":
    diagnostic()
