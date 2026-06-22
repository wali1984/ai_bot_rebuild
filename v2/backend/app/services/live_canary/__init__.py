"""V2 live-canary bring-up scaffolding (fail-closed by default).

Default state: ``live_gate=blocked_human_only``, ``live_symbols=[]``,
``dry_run=true``, ``live_enabled=false``. Every transition to a less
restrictive state requires explicit operator approval files and a
Codex review marker. The real-order submission path is intentionally
absent from this packet and is replaced by an explicit
``NotImplementedError`` sentinel; a separate operator-approved packet
must wire the actual exchange call.
"""
