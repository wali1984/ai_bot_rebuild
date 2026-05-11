# Old Redis Bridge Or Retire Decision

Decision: prioritize clean V2 data-plane independence while leaving old Redis trim deferred. Use a read-only bridge only for required runtime evidence until V2 durable stores and bounded streams replace legacy Redis responsibilities. If Redis pressure blocks all V2 work, choose backup durability or V2 data-plane cutover remediation; do not prompt generically.
