# NERVYX Old Brand Reference Inventory

Generated after the current rebrand pass. Visible public/trader/admin branding is removed from searched UI files. Remaining old-brand strings are compatibility aliases, backend table/header names, or historical local paths and must not be blindly renamed.

| File | Line | Match | Classification | Action |
| --- | ---: | --- | --- | --- |
| `v2/backend/app/api/v1/live_gate.py` | 115 | `    return Path(os.environ.get(_REPO_ROOT_ENV, "/home/wali/Desktop/AI BOT REBUILD")).resolve()` | internal compatibility identifier | preserve unless a compatibility-safe migration is approved |
| `v2/frontend/src/components/layout/ThemeToggle.tsx` | 7 | `const LEGACY_STORAGE_KEY = 'ai_bot_v2_theme';` | migration alias | preserve migration read/removal for old localStorage keys |
| `v2/backend/app/api/auth_rbac.py` | 504 | `    step_up_code: str \| None = Header(default=None, alias="X-AlphaForge-Step-Up-Code"),` | compatibility request header | preserve existing clients; add alias only with API review |
| `v2/backend/app/api/v2/alerts_contracts.py` | 70 | `    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))` | database compatibility table | preserve existing storage contract |
| `v2/backend/app/api/v2/alerts_contracts.py` | 131 | `                CREATE TABLE IF NOT EXISTS alphaforge_alerts (` | database compatibility table | preserve existing storage contract |
| `v2/backend/app/api/v2/alerts_contracts.py` | 148 | `            rows = connection.execute(text("SELECT payload_json FROM alphaforge_alerts")).fetchall()` | database compatibility table | preserve existing storage contract |
| `v2/backend/app/api/v2/alerts_contracts.py` | 167 | `            connection.execute(text("DELETE FROM alphaforge_alerts"))` | database compatibility table | preserve existing storage contract |
| `v2/backend/app/api/v2/alerts_contracts.py` | 172 | `                        INSERT INTO alphaforge_alerts (id, trader_id, paper_account_id, payload_json, updated_at)` | database compatibility table | preserve existing storage contract |
| `v2/backend/app/api/v1/chart.py` | 57 | `    repo_root = pathlib.Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))` | internal compatibility identifier | preserve unless a compatibility-safe migration is approved |
| `v2/backend/app/api/v2/market_contracts.py` | 96 | `    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))` | internal compatibility identifier | preserve unless a compatibility-safe migration is approved |
| `v2/backend/app/api/v2/market_contracts.py` | 593 | `        headers={"User-Agent": "alphaforge-v2-public-market-readonly/1.0"},` | internal compatibility identifier | preserve unless a compatibility-safe migration is approved |
| `v2/backend/app/api/v2/market_contracts.py` | 5740 | `    "/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python3",` | internal compatibility identifier | preserve unless a compatibility-safe migration is approved |
| `v2/backend/app/api/v2/market_contracts.py` | 5744 | `    "/home/wali/Desktop/AI BOT REBUILD/v2/backend",` | internal compatibility identifier | preserve unless a compatibility-safe migration is approved |
| `v2/backend/app/api/v2/monitoring_contracts.py` | 26 | `    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))` | internal compatibility identifier | preserve unless a compatibility-safe migration is approved |
| `v2/backend/app/api/v1/paper_fill_gate.py` | 73 | `    return Path(os.environ.get(_REPO_ROOT_ENV, "/home/wali/Desktop/AI BOT REBUILD")).resolve()` | internal compatibility identifier | preserve unless a compatibility-safe migration is approved |
