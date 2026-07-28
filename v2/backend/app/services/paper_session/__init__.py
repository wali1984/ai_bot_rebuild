"""PaperAccountEpochV1 — clean paper-session rotation + read-side session scoping.

See claude_worklog/paper_account_epoch/PAPER_ACCOUNT_EPOCH_V1_DESIGN.md.
Nothing here mutates paper state except `epoch.rotate(..., execute=True)`, which is
preflight-gated and never touches the immutable global history keys.
"""
