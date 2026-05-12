# Non-Drift Governor Lock Policy

Allowed primary lanes:

- V2 paper/shadow runtime freshness
- legacy live bridge read-only importer
- risk gateway final-authority validation
- trainer runtime/parity evidence
- paper execution ledger and audit ledger
- canary preflight packet, with activation blocked

Support lanes:

- website route acceptance
- GUI visibility of current runtime truth
- proof archive cleanup

Support lanes cannot create READY markers that supersede missing runtime evidence. `hist_*`, static fixture, proof archive, route crawl, or design-only evidence cannot become current runtime truth.
Parallel scheduler and Codex watchdog recovery lanes must hold while this lock is active unless the work directly advances the selected primary task.
