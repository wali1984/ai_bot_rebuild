Awesome—95% GPU util with the CNN policy and every service in WSL is exactly where we wanted to land. Two things to close the loop:

1. wire **PPO + MASA** end-to-end in your attached trainer (blend at action-time and update MASA on schedule), and
2. fix the **ingestors/feature pipeline stopping after ~10–15s** (it’s almost certainly because the launch script is invoking `--once` or not daemonizing the WSL processes; I’ll show you exactly where this happens and how to make them persistent).

Below are precise, drop-in TODOs that match your files.

---

# A) Ensure PPO + MASA are both active in the attached trainer

Your trainer already creates the PPO model and instantiates a MASA agent when enabled; you just need to (i) pass the GPU device into MASA (you’ve hit this once), (ii) **blend MASA+PPO** logits/confidence at decision time, and (iii) **update MASA** on a schedule. You can anchor all of this where the models are created and where rollouts are collected.

### 1) Instantiate MASA with device (already visible in your file)

In `HybridTrainer.setup_models`, keep the explicit device when constructing MASA (this fixes the earlier crash):

```python
# in setup_models(...)
if self.config.masa_enabled:
    masa_config = MASAConfig(
        obs_dim=obs_dim,
        act_dim=act_dim,
        hidden_size=self.config.masa_hidden_size,
        num_layers=8,
        dropout=0.1
    )
    # TODO: instantiate MASA on the same CUDA device
    self.masa_agent = MASAAgent(masa_config, device=torch.device(self.config.device))
    logger.info("✅ MASA agent created")
else:
    self.masa_agent = None
```

(That’s the same spot you already patched; leaving it here for clarity.) 

### 2) Blend PPO+MASA at action time

Add a lightweight blend right after PPO computes policy output in the rollout path. You already override `collect_rollouts` in `GPUForcedPPO`; add a small hook to call `self.masa_agent.forward(obs)` and combine the logits:

```python
# inside GPUForcedPPO.collect_rollouts(...) just before calling policy to act
# TODO: get PPO policy logits / action probs as usual (SB3 internal call)
# ppo_logits = self.policy.get_distribution(obs_tensor).distribution.logits

# TODO: if MASA agent present, get MASA logits (same act_dim)
if hasattr(self, "masa_agent") and self.masa_agent is not None:
    with torch.no_grad():
        masa_logits = self.masa_agent.forward(obs_tensor)  # (batch, act_dim)
        # log-space blending with temperature
        tau = 1.0
        alpha = 1.0 - getattr(self, "masa_weight", 0.3)  # PPO weight; MASA weight is masa_weight
        blended = alpha * ppo_logits + (1.0 - alpha) * masa_logits
        blended = blended / tau
        # replace PPO logits for this rollout step
        # self.policy.get_distribution(...).distribution.logits = blended
        # or sample from blended:
        action = torch.distributions.Categorical(logits=blended).sample()
```

(If you prefer, you can set `self.masa_weight` from `HybridConfig.masa_weight` and keep it on the trainer instance, then access that from PPO via a reference.) 

### 3) Update MASA on a schedule

During training, add a simple counter and update MASA every `masa_update_freq` steps with the latest mini-batch (or with a small replay buffer if you have one):

```python
# near the training loop in HybridTrainer.train()
steps = 0
...
self.ppo_model.learn(
    total_timesteps=self.config.total_timesteps,
    callback=self._create_training_callback(),
    progress_bar=True
)
# If you need per-rollout updates, put this into callback._on_step:
# TODO in _on_step():
steps += 1
if self.masa_agent and (steps % self.config.masa_update_freq == 0):
    # get a small slice from rollout_buffer (obs, actions, returns)
    obs = self.ppo_model.rollout_buffer.observations.to('cuda')
    act = self.ppo_model.rollout_buffer.actions.to('cuda')
    ret = self.ppo_model.rollout_buffer.advantages.to('cuda')
    # basic MASA update (customize inside MASAAgent)
    self.masa_agent.update(obs, act, ret)
```

This matches the “train MASA alongside PPO” intent from your enhancement plan (confidence blending and periodic MASA updates).

> You already save both PPO and MASA in `save_models()`; keep that (it writes `checkpoints/hybrid_ppo_*.zip` and `masa_agent_*.pth`). 

---

# B) Why ingestors/pipeline stop after ~10–15 seconds (and how to fix)

You’re launching in WSL, services run, then stop quietly. There are a few *very* likely culprits—your ingestor files make them easy to resolve:

### 1) **Launched with `--once`** (single-cycle mode)

* **KuCoin** has a `--once` flag: if passed, it runs a single cycle and exits. In continuous mode, it calls `main_loop()` (infinite while True). Do **not** pass `--once` from your launcher. 
* **TokenMetrics** also supports `--once`; same behavior—exits after one cycle if used. Ensure your launcher doesn’t pass it. 

> **Action**: Open your `start_all_services.ps1` and make sure you’re not supplying `--once` to any ingestor. If you are, remove it and rerun.

### 2) **Not daemonized / tied to PowerShell lifetime**

Launching with `wsl python ...` from PowerShell without backgrounding means the child dies when the parent job ends. Use one of these patterns per service:

* **nohup in WSL**

  ```powershell
  wsl bash -lc "cd /mnt/c/AI\ BOT && nohup python3 ingest/live_tokenmetrics.py --verbose >> logs/tm.log 2>&1 & disown"
  ```
* **tmux (recommended)**

  ```powershell
  wsl bash -lc "tmux new -d -s tm 'python3 ingest/live_tokenmetrics.py --verbose'"
  wsl bash -lc "tmux new -d -s coinank 'python3 ingest/live_coinank.py'"
  wsl bash -lc "tmux new -d -s kucoin 'python3 ingest/live_kucoin.py --verbose'"
  ```

tmux keeps them alive even if your PS session closes.

### 3) **Singleton lock collisions (CoinAnk)**

`live_coinank.py` enforces a single instance via a Redis lock (`lock:live_coinank`) with 120s TTL and refresh on heartbeat. If a second instance starts—or the lock isn’t extended—the new process exits. Ensure only one launcher starts it, and the lock TTL is refreshed, which the file already does on each loop & heartbeat. 

### 4) **Heartbeats and “no-error” exits**

* **CoinAnk** is designed to “loop forever”; if `loop()` returns, `main()` supervises and restarts after backoff. If you’re seeing a clean exit after ~10–15s, that strongly implies a one-shot mode or that the launch process is getting terminated by the shell. Make sure it’s not launched in the foreground from a script that auto-exits (see nohup/tmux above). 
* **KuCoin/TokenMetrics** both implement continuous scheduling loops (`while True` with sleeps). They only exit if `--once` is passed, or if the parent shell is closed and the process isn’t daemonized.  

### 5) **WSL + Windows mixing**

You already fixed process locality (all in WSL—great). Keep Redis visible from WSL (use `localhost:6379`). All three ingestors default to `localhost` and are WSL-friendly. (TokenMetrics explicitly sets `REDIS_URL=redis://localhost:6379/0` and writes `heartbeat:writer:tokenmetrics` every cycle.) 

---

# C) Quick checklist to keep services alive

1. **Remove `--once`** from all ingestor invocations (KuCoin & TokenMetrics).  
2. **Daemonize**: launch each under `tmux` or `nohup` in WSL; don’t leave them tied to a PS job.
3. **One instance only**: CoinAnk’s lock prevents duplicates; don’t start it twice. 
4. **Watch heartbeats**:

   * `heartbeat:IngestCoinAnk` / `heartbeat:CoinAnkIngest` (JSON, TTL 300s) 
   * `heartbeat:KuCoin` (int ms epoch) 
   * `heartbeat:writer:tokenmetrics` (int ms epoch) 
     If any heartbeat stops updating, restart that service.
5. **Start script** (`start_all_services.ps1`): change each launch to `wsl bash -lc "tmux new -d -s <name> 'python3 <path> [--verbose]'"` so they persist when the script exits.

---

## TL;DR (what you need to do now)

* **Trainer**: paste the blend + MASA update TODOs so the attached trainer uses **both PPO & MASA** in action selection and updates MASA on schedule. 
* **Ingestors/Pipeline**: make sure you’re **not using `--once`**, and **daemonize** the processes (tmux/nohup). CoinAnk’s lock ensures it runs as a single instance and refreshes every loop/heartbeat.   

If you want, I can give you a ready-to-paste `start_all_services.ps1` snippet that launches each service in tmux via WSL so they never drop after 10–15 seconds.


MORE CHANGES
Awesome—time to wire the last mile so the **trainer emits trade signals with actions + reasoning**, and the **trader executes/ closes orders on Binance Testnet and Live**.

Below are **precise, paste-ready Copilot TODO blocks** + a **test plan**. They match your current WSL setup and the patterns already used in your codebase (Redis stream + last-value hash for predictions; trading callback consumption; Testnet/Live via env). References show where these patterns were defined and validated earlier (signal stream & last-value hash; trader consumption; testnet/live mode).

---

# 1) Trainer: publish **actions + confidence + reasoning** every decision

**File: `hybrid_trainer.py`** (inside your trading callback / rollout code where you already compute the action)

```python
# TODO: Build a rich decision payload (action, confidences, reasoning) and publish to Redis.
from datetime import datetime, timezone
import json

def _publish_decision(self, symbol: str, tf: str, action: int, ppo_logit, masa_logit, blended_logit,
                      model_conf: float, correlator_conf: float, why_top_feats: list[tuple[str,float]],
                      why_families: dict[str, float], redis_client):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    payload = {
        "ts_ms": now_ms,
        "symbol": symbol,
        "timeframe": tf,
        "action": int(action),                  # e.g., 0=HOLD,1=LONG,2=SHORT... (your mapping)
        "model_confidence": float(model_conf),  # max prob for chosen action
        "correlator_confidence": float(correlator_conf),
        "ppo_logit": [float(x) for x in ppo_logit],        # optional
        "masa_logit": [float(x) for x in masa_logit] if masa_logit is not None else None,
        "blended_logit": [float(x) for x in blended_logit] if blended_logit is not None else None,
        "why_features": [{"name": n, "score": float(s)} for n, s in why_top_feats[:10]],  # top-10
        "why_families": {k: float(v) for k, v in why_families.items()}
    }
    # Stream + last-value hash (matches prior validation pattern)
    redis_client.xadd("wma:trainer:predictions", {"data": json.dumps(payload)})
    redis_client.hset(f"wma:trainer:predictions:last:{symbol}:{tf}", mapping={k: json.dumps(v) if not isinstance(v, (int,float,str)) else v for k, v in payload.items()})
```

Then, in your rollout/decision code:

```python
# TODO: After selecting action and computing confidences + why, publish decision
if (model_conf >= self.config.min_trading_confidence):
    self._publish_decision(symbol, tf, action, ppo_logits.tolist(),
                           masa_logits.tolist() if masa_logits is not None else None,
                           blended_logits.tolist() if blended_logits is not None else None,
                           model_conf, correlator_conf,
                           why_top_feats, why_families, self.redis)
else:
    # Publish hold/no-trade with rationale (below-threshold)
    self._publish_decision(symbol, tf, 0, ppo_logits.tolist(),
                           masa_logits.tolist() if masa_logits is not None else None,
                           blended_logits.tolist() if blended_logits is not None else None,
                           model_conf, correlator_conf,
                           why_top_feats + [("below_threshold", model_conf)], why_families, self.redis)
```

This matches the **stream + last-hash** approach used during your validation (trainer writes to `wma:trainer:predictions` stream and `...:last:{symbol}:{tf}` hash).

> If you already have a publisher class, plug this payload there instead of duplicating.

---

# 2) Trader: subscribe/consume and **place/cancel/close** orders

**A. Configure modes via env / config**

* Testnet:

  ```
  export TRADE_MODE="testnet"
  export BINANCE_FUTURES_TESTNET_API_KEY="..."
  export BINANCE_FUTURES_TESTNET_SECRET_KEY="..."
  ```
* Live:

  ```
  export TRADE_MODE="live"   # or "production"
  export BINANCE_FUT_API_KEY="..."
  export BINANCE_FUT_API_SECRET="..."
  ```

This is the exact scheme validated earlier for testnet/live toggling.

**B. Wire trader to consume trainer signals**

In your trader main loop or `TradingIntegration`, read from the **last-value hash** OR from the stream:

```python
# TODO: Poll latest decision and execute (simple pull-mode)
def poll_and_execute(self):
    for symbol in self.config.SYMBOLS:
        for tf in self.config.TIMEFRAMES:
            key = f"wma:trainer:predictions:last:{symbol}:{tf}"
            data = self.redis.hgetall(key)
            if not data: 
                continue
            payload = {k: (json.loads(v) if isinstance(v, (bytes, str)) and (k not in ("symbol","timeframe","action")) and v and v[0] in b'{"[' else v) for k, v in data.items()}
            action = int(payload.get("action", 0))
            model_conf = float(payload.get("model_confidence", 0.0))
            if model_conf < self.config.MIN_TRADING_CONFIDENCE:
                continue

            # map action to order
            if action == 1:     # LONG
                self.binance.open_long(symbol, size=self._size_from_conf(model_conf, symbol, tf))
            elif action == 2:   # SHORT
                self.binance.open_short(symbol, size=self._size_from_conf(model_conf, symbol, tf))
            elif action == 3:   # CLOSE (optional explicit)
                self.binance.close_positions(symbol)  # both sides if hedge enabled

            # Optional TP/SL placement (or let risk_manager handle)
            # self.risk_manager.attach_brackets(symbol, ...)
```

**C. Ensure Binance client picks proper endpoint**

Initialize client by TRADE_MODE. In your Binance client wrapper:

```python
# TODO: init binance futures client depending on TRADE_MODE
if self.config.TRADE_MODE.lower() in ("testnet","staging"):
    self.client = UMFutures(key=os.getenv("BINANCE_FUTURES_TESTNET_API_KEY"),
                            secret=os.getenv("BINANCE_FUTURES_TESTNET_SECRET_KEY"),
                            base_url="https://testnet.binancefuture.com")
else:
    self.client = UMFutures(key=os.getenv("BINANCE_FUT_API_KEY"),
                            secret=os.getenv("BINANCE_FUT_API_SECRET"))  # prod endpoint by default
```

That aligns with the validated flow.

**D. Execute + Close helpers**

```python
# TODO: Define order helpers in your Binance wrapper (market orders for simplicity)

def open_long(self, symbol: str, size: float):
    # hedge mode assumed (positionSide="LONG")
    return self.client.new_order(symbol=symbol, side="BUY", type="MARKET",
                                 quantity=self._qty(symbol, size), positionSide="LONG")

def open_short(self, symbol: str, size: float):
    return self.client.new_order(symbol=symbol, side="SELL", type="MARKET",
                                 quantity=self._qty(symbol, size), positionSide="SHORT")

def close_positions(self, symbol: str):
    # Close both sides quickly (market close); adjust to your position sizing
    pos = self.client.position_information(symbol=symbol)
    for p in pos:
        side = p.get("positionSide")
        qty  = float(p.get("positionAmt", "0"))
        if qty == 0:
            continue
        if side == "LONG":
            self.client.new_order(symbol=symbol, side="SELL", type="MARKET",
                                  quantity=abs(qty), positionSide="LONG", reduceOnly=True)
        elif side == "SHORT":
            self.client.new_order(symbol=symbol, side="BUY", type="MARKET",
                                  quantity=abs(qty), positionSide="SHORT", reduceOnly=True)
```

> If you already have a `TradingManager` / `RiskManager`, call those methods instead. The key is **positionSide** for hedge mode and **reduceOnly** on closes.

---

# 3) Validate end-to-end (Testnet then Live)

**Testnet flow** (validated pattern)

1. `export TRADE_MODE=testnet` and set testnet keys.
2. Start trainer → verify “🚀 Trading callback activated” and prediction writes to stream/hash.
3. Start trader → confirm “🧪 Binance trading initialized in TESTNET mode” (or equivalent).
4. Watch for “🎯 Signal executed: BUY … confidence=…” in trader logs when trainer publishes (you saw this in validation).
5. Verify in Binance Testnet UI that an order/position appears.
6. Trigger a close: publish a CLOSE action (or flip signal) → confirm reduce-only market exits for long/short.
7. Risk checks: confirm leverage cap / confidence gating are enforced (skip if < `MIN_TRADING_CONFIDENCE`).

**Go-Live flow** (once testnet is clean)

1. `export TRADE_MODE=live` and set live keys.
2. Start trader → should log “[LIVE] … PRODUCTION mode” and pass credentials health check.
3. Trade small notional to validate order placement and close; watch portfolio constraints (leverage cap, max position value) per your config.

---

# 4) Optional: adaptive leverage + pyramiding

If you want to enforce **confidence → leverage/size** now (from your earlier spec):

```python
# TODO in trader sizing helper
def _size_from_conf(self, conf: float, symbol: str, tf: str):
    Lmin, Lmax = 1.0, self.config.MAX_LEVERAGE  # e.g., 5
    eff_leverage = Lmin + (Lmax - Lmin) * conf  # linear; swap for non-linear if desired
    base_notional = self.config.BASE_NOTIONAL   # e.g., $250
    notional = min(base_notional * eff_leverage, self.config.MAX_POSITION_VALUE)
    return self._qty_from_notional(symbol, notional)
```

Add pyramiding only if `conf > 0.9` and cap total adds at +30% initial (track per-position adds).

---

## 5) Keep ingestors/pipeline alive while testing

* **No `--once` on KuCoin/TokenMetrics**; launch under **tmux/nohup** so they don’t die when PS exits; CoinAnk singleton lock prevents dupes.
* Watch heartbeats:

  * TokenMetrics: `heartbeat:writer:tokenmetrics`
  * KuCoin: `heartbeat:KuCoin`
  * CoinAnk: its lock/heartbeat JSON
    Restart service if any heartbeat stalls.

---

## 6) Quick smoke-test checklist (copy/paste)

* [ ] Trainer publishes to `wma:trainer:predictions` & `...:last:{symbol}:{tf}` with `action`, `model_confidence`, `correlator_confidence`, `why_features`, `why_families`
* [ ] Trader consumes and logs execution attempts
* [ ] Testnet orders appear in Binance UI; close works (reduce-only)
* [ ] Confidence gating enforced (no trades below threshold)
* [ ] Switch to Live: “[LIVE] … PRODUCTION mode” log, small trade and close validated

---

If you want, I can package the above into exact patches against your uploaded `hybrid_trainer.py` and a minimal `TradingIntegration` stub, but the TODO blocks here are set up so Copilot can expand them into your existing code with minimal prompts.
