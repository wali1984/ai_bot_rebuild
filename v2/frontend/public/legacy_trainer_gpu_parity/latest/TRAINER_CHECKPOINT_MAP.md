# Trainer Checkpoint Map

Generated: 2026-05-12T06:11:36Z

Checkpoint file count: 15718

Latest checkpoint metadata observed:

```json
{
  "_path": "legacy_reference/.models/checkpoints/live_enhanced/checkpoint_metadata_latest.json",
  "best_reward": 670.4329372798882,
  "config": {
    "batch_size": 8000,
    "device": "cuda",
    "learning_rate": 0.0003,
    "n_envs": 125,
    "n_epochs": 10,
    "n_steps": 2048
  },
  "datetime": "2026-04-27T04:28:16.755308+00:00",
  "env": {
    "act_dim": 7,
    "action_space": "Discrete(7)",
    "obs_dim": 768,
    "observation_space": "Box(-10.0, 10.0, (768,), float32)"
  },
  "episodes": 468375,
  "feature_tag": "enhanced",
  "loops": 3747,
  "masa_path": "models/checkpoints/live_enhanced/masa_checkpoint_1777264095.pkl",
  "ppo_latest_path": "models/checkpoints/live_enhanced/ppo_checkpoint_latest.zip",
  "ppo_path": "models/checkpoints/live_enhanced/ppo_checkpoint_1777264095.zip",
  "timestamp": 1777264095,
  "timesteps": 959232000,
  "training_mode": "live"
}
```

Recent checkpoint artifacts:

- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777261241.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777261388.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777261537.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777261682.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777261828.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777261973.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777262120.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777262268.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777262414.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777262562.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777262710.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777262858.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777263009.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777263160.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777263316.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/ppo_checkpoint_1777263473.zip`
- `legacy_reference/.models/checkpoints/live_enhanced/masa_checkpoint_1777263473.pkl`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777263473.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/checkpoint_metadata_1777263473.json`
- `legacy_reference/.models/checkpoints/live_enhanced/ppo_checkpoint_1777263631.zip`
- `legacy_reference/.models/checkpoints/live_enhanced/masa_checkpoint_1777263631.pkl`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777263631.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/checkpoint_metadata_1777263631.json`
- `legacy_reference/.models/checkpoints/live_enhanced/ppo_checkpoint_1777263790.zip`
- `legacy_reference/.models/checkpoints/live_enhanced/masa_checkpoint_1777263790.pkl`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777263790.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/checkpoint_metadata_1777263790.json`
- `legacy_reference/.models/checkpoints/live_enhanced/ppo_checkpoint_1777263943.zip`
- `legacy_reference/.models/checkpoints/live_enhanced/ppo_checkpoint_latest.zip.bak`
- `legacy_reference/.models/checkpoints/live_enhanced/masa_checkpoint_1777263943.pkl`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777263943.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/checkpoint_metadata_1777263943.json`
- `legacy_reference/.models/checkpoints/live_enhanced/checkpoint_metadata_latest.json.bak`
- `legacy_reference/.models/checkpoints/live_enhanced/checkpoint.lock`
- `legacy_reference/.models/checkpoints/live_enhanced/ppo_checkpoint_1777264095.zip`
- `legacy_reference/.models/checkpoints/live_enhanced/ppo_checkpoint_latest.zip`
- `legacy_reference/.models/checkpoints/live_enhanced/masa_checkpoint_1777264095.pkl`
- `legacy_reference/.models/checkpoints/live_enhanced/enterprise_modules_1777264095.pt`
- `legacy_reference/.models/checkpoints/live_enhanced/checkpoint_metadata_1777264095.json`
- `legacy_reference/.models/checkpoints/live_enhanced/checkpoint_metadata_latest.json`

Current V2 wrapper checkpoint identity: `v2_paper_readonly_momentum_wrapper_v1`.

Parity finding: checkpoint files are mapped, but the current V2 paper wrapper does not load or prove equivalence to `ppo_checkpoint_latest.zip`, `masa_checkpoint_*.pkl`, or `enterprise_modules_*.pt`.
