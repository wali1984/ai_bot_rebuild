# 05 Signal Attribution Findings

## What is currently attributable
- Partial linkage exists at `signal_id` level in executed analysis checks.
- Streams and counters provide aggregate behavior visibility.

## What is not attributable end-to-end
- No complete chain from feature snapshot to prediction confidence to published signal to downstream decision/execution IDs.
- No robust mapping from confidence shifts to exact feature key/value contributors.
- No complete linkage matrix with `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, `execution_intent_id` in one runtime artifact.

## Runtime evidence from snapshots
- `executed_analysis.missing_signal_id` stayed non-zero across run (74–81 in sample).
- `executed_analysis.missing_confidence` stayed non-zero across run (58–63 in sample).

## Conclusion
- Attribution quality is not yet production-forensic complete.
- This supports NO-GO for V2 build at this time.
