# Commands Run — System Audit 2026

All commands below are read-only. No mutations performed.

## Repository Exploration
```
find "/home/wali/Desktop/AI BOT REBUILD" -maxdepth 3 -type d
ls "/home/wali/Desktop/AI BOT REBUILD/v2/"
find v2/backend/app/cli -name "*.py" | wc -l
find v2/backend/app/services -name "*.py" | wc -l
find v2/backend/app/api -name "*.py" | wc -l
find v2/frontend/src -name "*.tsx" -o -name "*.ts" | wc -l
find v2/backend/tests -name "*.py" | wc -l
cat v2/backend/app/main.py | head -80
```

## Systemd Inspection
```
systemctl --user list-units 'ai-bot-v2-*' --no-legend
systemctl --user --failed --no-legend | grep 'ai-bot'
ls ~/.config/systemd/user/ | grep 'ai-bot' | wc -l
```

## Redis Inspection (read-only)
```
redis-cli --no-auth-warning keys "v2:*" | wc -l  # → 1,135,176 total keys
redis-cli --no-auth-warning get "v2:paper:heartbeat"
redis-cli --no-auth-warning get "v2:trainer:hybrid_cuda:heartbeat"
redis-cli --no-auth-warning get "v2:risk:gateway:heartbeat"
redis-cli --no-auth-warning get "v2:orchestrator:heartbeat"
redis-cli --no-auth-warning keys "v2:paper:*"
redis-cli --no-auth-warning keys "v2:prediction:*"
redis-cli --no-auth-warning keys "v2:signal:*"
redis-cli --no-auth-warning keys "v2:risk:*"
redis-cli --no-auth-warning keys "v2:orchestrator:*"
redis-cli --no-auth-warning keys "v2:trainer:*"
redis-cli --no-auth-warning keys "v2:ingestor:*"
redis-cli --no-auth-warning keys "v2:market:*"
redis-cli --no-auth-warning keys "v2:liq:*"
```

## File Metadata Collection
```
find v2/backend/app/cli -name "*.py" | while read f; do stat + wc -l; done
```

## Frontend Route Discovery
```
find v2/frontend/src/pages -name "*.tsx" | sort
```

## API File Discovery
```
find v2/backend/app/api -name "*.py" | sort
```
