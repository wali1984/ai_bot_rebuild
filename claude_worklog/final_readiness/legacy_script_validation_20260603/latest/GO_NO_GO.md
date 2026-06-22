# Legacy Script Validation GO/NO-GO

Generated UTC: 2026-06-03T22:55:42Z
Verdict: `NO_GO_FOR_BLANKET_LEGACY_EXECUTION`

- GO for static syntax coverage of Python and shell scripts.
- GO for dependency availability: static scan reports no missing third-party imports.
- GO for V2-covered adapter/native runtime probes: 5/5 passed.
- NO-GO for blanket direct execution: 184 operator-gated script(s) contain trading, destructive maintenance, paid/keyed provider, or legacy runtime markers.
- NOTE: 2 PowerShell launchers were inventoried/classified but not syntax-checked because `pwsh` is not installed; both remain runtime-gated launchers.
- LIVE_GATE remains `blocked_human_only`; `live_symbols=[]`.
