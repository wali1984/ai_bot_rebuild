# AGENTS.md — Coding Agent Rules for This Repository

These rules apply to all coding agents (VS Code Copilot, Codex, Codex Spark,
and any automated tool) operating in this trading bot repository.

---

1. **Never make broad refactors unless explicitly requested.**
   Scope every change to the minimum set of files needed to satisfy the task.

2. **Never change live execution behavior without approval.**
   Exchange-touching code paths, order submission, cancellation, and modification
   require explicit operator approval before any edit is made.

3. **Never modify strategy, PPO, MASA, or risk logic unless the task explicitly
   asks for it.**
   This includes loss functions, reward shaping, action masking, position sizing,
   cooldown windows, and risk cap parameters.

4. **For pipeline/training tasks, always check point-in-time safety.**
   Confirm that no future-leaking data enters the training window before writing
   or modifying any data-loading, feature-assembly, or replay path.

5. **Always distinguish `event_time`, `ingested_at`, `available_at`,
   `generated_at`, `feature_cutoff`, `decision_time`, and `execution_time`.**
   These are not interchangeable. Name them correctly in code, logs, and payloads.

6. **Never use unfinished higher-timeframe candles as final.**
   A candle is only final after its close time has passed. Partially-formed
   candles must be excluded from feature inputs and training samples.

7. **Never allow `feature available_at > decision_time`.**
   A feature used in a decision must have been fully available before the
   decision was made. Violations are look-ahead leakage.

8. **Never allow `MASA feature_cutoff > PPO decision_time`.**
   The MASA model's feature cutoff must precede the PPO model's decision
   timestamp. Cross-model temporal ordering must be enforced.

9. **Never allow dirty samples into training.**
   Dirty samples include: partially-formed candles, stale features, missing
   price targets, invalid lineage, NaN-filled required fields, and any row
   flagged by the data-coverage or feature-freshness gate.

10. **Never allow invalid position transitions to submit orders.**
    The position state machine must be validated before any order path is
    reached. An invalid transition (e.g. LONG → LONG without close) must
    fail closed, not silently proceed.

11. **Every change must include tests or explain why tests are not possible.**
    New functions, gate logic, and data-path changes require at minimum a
    unit test or a documented reason why one cannot be written (e.g. hardware
    dependency, live exchange I/O).

12. **Keep diffs scoped.**
    Do not touch files unrelated to the task. If a file must be read for
    context but not changed, do not write it.

13. **Report exact files changed and commands run.**
    At the end of every task, list every file that was modified, created, or
    deleted, and every shell command that was executed.
