from __future__ import annotations

from .models import SymbolIdentity, SymbolScore, SymbolScoreInput


def score_symbol(identity: SymbolIdentity, inputs: SymbolScoreInput) -> SymbolScore:
    values = [
        inputs.liquidity_score,
        inputs.volume_score,
        inputs.volatility_score,
        inputs.spread_score,
        inputs.funding_score,
        inputs.open_interest_score,
        inputs.freshness_score,
        inputs.feature_completeness_score,
        inputs.exchange_availability_score,
        inputs.replay_score,
        inputs.paper_score,
        inputs.risk_score,
        inputs.manual_priority_score,
    ]
    total = sum(values) / len(values)
    reasons = []
    if inputs.freshness_score < 0.5:
        reasons.append("freshness_low")
    if inputs.feature_completeness_score < 0.5:
        reasons.append("feature_completeness_low")
    if inputs.risk_score < 0.4:
        reasons.append("risk_score_low")
    if not identity.is_trading():
        reasons.append("source_not_trading")
    confidence = "high" if total >= 0.75 and not reasons else "medium" if total >= 0.55 else "low"
    return SymbolScore(
        canonical_symbol_id=identity.canonical_symbol_id,
        total_score=round(total, 6),
        confidence=confidence,
        reason_codes=reasons,
        eligible_for_training=identity.is_trading() and total >= 0.55 and inputs.feature_completeness_score >= 0.5,
        eligible_for_paper=identity.is_trading() and total >= 0.65 and inputs.paper_score >= 0.5,
        eligible_for_shadow=identity.is_trading() and total >= 0.75 and inputs.replay_score >= 0.5,
    )

