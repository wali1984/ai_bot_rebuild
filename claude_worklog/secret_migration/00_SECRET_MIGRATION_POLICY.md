# Secret Migration Policy

## Objective
Preserve all existing legacy secrets/settings needed by the V2 rebuild without exposing them in Git, logs, prompts, or committed files.

## Sources
Legacy sources may be read locally only:
- /home/wali/Desktop/AI BOT/.env
- /home/wali/Desktop/AI BOT/config.py
- any explicitly referenced legacy config files discovered by config.py or startup scripts

## Rules
- Do not print secret values.
- Do not commit secret values.
- Do not send secret values to Claude, Codex, or Ollama.
- Do not import/execute legacy config.py.
- Parse or copy files locally only.
- Local secret copies must be ignored by Git.
- Use `umask 077` and chmod 600 for local secret files.
- Committed files may contain key names, source paths, migration status, and validation results only.
- Committed files must never contain raw values.

## Local secret storage
Use ignored local paths:
- .local_secrets/
- v2/.env.local
- v2/secrets/

## V2 loading rule
V2 code should load secrets from environment/local secret provider only. V2 source code must not hard-code credentials.

## Validation
Validate:
- required keys exist
- local secret files exist
- file permissions are restrictive
- no secret values are committed
- no secret values appear in Claude/Codex/Ollama prompts

SECRET_MIGRATION_POLICY_READY
