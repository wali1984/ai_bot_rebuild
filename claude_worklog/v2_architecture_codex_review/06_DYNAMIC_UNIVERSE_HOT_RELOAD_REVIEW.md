# 06 Dynamic Universe and Hot Reload Review

## Scope
Adversarial review of passive discovery, adaptive selection, and restart-free propagation.

## Coverage status
- Passive all-market source set is explicitly listed (Binance Futures, CoinAnk, CoinAPI, KuCoin, future exchanges/ingestors).
- Four universe layers are defined.
- Manual include/exclude and force-state controls are described.
- Hot-reload state machine and propagation targets are defined.
- Component acknowledgment and rollback concepts exist.

## Adversarial findings
1. **Ack reliability contract incomplete (HIGH blocker)**
   - Ack envelope exists, but missing: timeout policy, retry policy, dead-letter/escalation model, and required rollback trigger thresholds.

2. **Partial-apply behavior not formally constrained (HIGH)**
   - No explicit rule for mixed state when some components are `applied` and others fail validation.

3. **Selection policy version pinning is under-specified (MEDIUM)**
   - Universe versioning is defined, but architecture does not explicitly require score-policy and capacity-policy version IDs in every selection output.

4. **Override conflict resolution lacks deterministic ordering (MEDIUM)**
   - Include/exclude/force states are present, but precedence (e.g., force_disabled vs force_train_only) is not explicitly fixed.

## Implementability verdict
Restart-free architecture is directionally correct but not yet fully implementable without operational semantics closure.
