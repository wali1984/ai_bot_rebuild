# Legacy Startup Script Map

Generated: 2026-05-06T20:09:51.788438+00:00

Script: `/home/wali/Desktop/AI BOT/scripts/start_all_services_production.sh`

## Relevant phase/service lines
```text
28: BOT_PY_PATTERN="python3.*(vpn_monitor|system_telegram_monitor|monitor_system_memory|memory_monitor|monitor_trainer_predictions|ingest/live_|feature_pipeline\\.py|ohlcv_resampler_hotfix\\.py|live_technical_analysis\\.py|rl\\.hybrid_trainer|hybrid_trainer\\.py|rl\\.orchestrator_worker|orchestrator_worker\\.py|trading/trader|monitor_portfolio_|liquidation_bridge\\.py|liquidation_levels_engine\\.py|realtime_price_provider\\.py)"
44:     pkill -9 -f "python3.*(vpn_monitor|system_telegram_monitor|monitor_system_memory|memory_monitor|monitor_trainer_predictions|live_|feature_|ohlcv_resampler_hotfix|live_technical_analysis|hybrid_|trader|monitor_portfolio|liquidation_bridge|liquidation_levels_engine|realtime_price_provider)" || true
46:     # Clear Redis/file locks (single-instance ingestors)
47:     redis-cli DEL lock:live_binance lock:live_binance_liq lock:live_coinank lock:live_coinapi_v1 lock:live_coinapi_wsds >/dev/null 2>&1 || true
144: # PHASE 0: PRE-FLIGHT CHECKS
146: echo -e "${YELLOW}🔍 PHASE 0: Pre-Flight System Checks...${NC}"
164:     pkill -f "hybrid_trainer.py" || true
201: # Check if Redis is running
202: if ! pgrep -x "redis-server" > /dev/null; then
203:     echo -e "${RED}❌ CRITICAL: Redis not running!${NC}"
204:     echo "   Starting Redis..."
205:     sudo systemctl start redis-server
208: echo -e "   ${GREEN}✅ Redis: Running${NC}"
214: # PHASE 0.5: START MONITORING SERVICES (FIRST!)
216: echo -e "${YELLOW}📱 PHASE 0.5: Starting Monitoring Services...${NC}"
260:             ps aux | grep python3 | grep -v grep | awk '{printf \"%-9s %-5s %-5s \", \$2, \$4, \$3; system(\"ps -p \"\$2\" -o etime= | tr -d \\\" \\\"\"); printf \" %s\\n\", substr(\$0, index(\$0,\$11))}' | head -20
296:     nohup python3 vpn_monitor.py \
315:     nohup python3 system_telegram_monitor.py \
332:     nohup python3 monitor_system_memory.py \
351:     nohup python3 scripts/memory_monitor.py \
366:     nohup python3 scripts/monitor_trainer_predictions.py \
380: # PHASE 1: START DATA INGESTORS (Lightweight, No GPU)
382: echo -e "${YELLOW}📡 PHASE 1: Starting Data Ingestors (core services)...${NC}"
386: start_ingestor() {
393:     nohup nice -n 10 taskset -c 0-7 python3 "$script" \
409: start_ingestor "binance" "ingest/live_binance.py"
412: start_ingestor "kucoin" "ingest/live_kucoin.py"
413: start_ingestor "coinank" "ingest/live_coinank.py"
414: start_ingestor "coinank_global" "ingest/live_coinank_global_aggregator.py"
415: start_ingestor "liquidations" "ingest/live_binance_liquidations.py"
416: start_ingestor "liq_bridge" "ingest/liquidation_bridge.py"
417: start_ingestor "liq_levels" "ingest/liquidation_levels_engine.py"
418: start_ingestor "price_provider" "ingest/realtime_price_provider.py"
423:     nohup nice -n 10 python3 -m ingest.live_coinapi_wsds \
442:         nohup nice -n 10 taskset -c 0-7 python3 -m ingest.live_coinapi_v1 \
497:     python3 scripts/paralysis_detectors.py --minutes 5
529: # PHASE 2: START FEATURE PIPELINE & RESAMPLER
531: echo -e "${YELLOW}🔧 PHASE 2: Starting Feature Pipeline...${NC}"
535: nohup nice -n 5 python3 ohlcv_resampler_hotfix.py \
546: nohup python3 feature_pipeline.py \
574: # PHASE 2.5: START TECHNICAL ANALYSIS SERVICE (TIER-1)
576: echo -e "${YELLOW}📊 PHASE 2.5: Starting Technical Analysis Service...${NC}"
579: # Preflight: Verify Redis is responding
580: if ! redis-cli PING >/dev/null 2>&1; then
581:     echo -e "   ${RED}❌ Redis not reachable - aborting TA start${NC}"
586: if ! redis-cli GET "market:ETHUSDT:1m" >/dev/null 2>&1; then
591: nohup nice -n 5 python3 ingest/live_technical_analysis.py \
606:     if redis-cli HGET "ta:ETHUSDT:1m" timestamp >/dev/null 2>&1; then
635:         python3 scripts/validate_symbol_universe_data.py
675: # PHASE 3: START TRAINER (GPU Heavy - Start Alone)
677: echo -e "${YELLOW}🧠 PHASE 3: Starting Hybrid Trainer (GPU)...${NC}"
685: source venv/bin/activate && nohup python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features \
686:     > logs/hybrid_trainer.log 2>&1 &
724:     SIGNAL_COUNT_CANON=$(redis-cli XLEN "${SIGNAL_STREAM_CANON}" 2>/dev/null || echo "0")
725:     SIGNAL_COUNT_PRIMARY=$(redis-cli XLEN "signals:trading:primary" 2>/dev/null || echo "0")
726:     SIGNAL_COUNT_ASJAD=$(redis-cli XLEN "signals:trading:asjad" 2>/dev/null || echo "0")
735:     echo "   Check logs/hybrid_trainer.log for errors"
741: # PHASE 3B: START ORCHESTRATOR WORKER (Single Publisher)
743: echo -e "${YELLOW}🎯 PHASE 3B: Starting Orchestrator Worker...${NC}"
751: ORCH_ENABLED=$(python3 -c "from config import ORCHESTRATOR_WORKER_ENABLED; print(ORCHESTRATOR_WORKER_ENABLED)" 2>/dev/null | tail -1 || echo "False")
752: ORCH_MODE=$(python3 -c "from config import ORCHESTRATOR_WORKER_MODE; print(ORCHESTRATOR_WORKER_MODE)" 2>/dev/null | tail -1 || echo "shadow")
762:         nohup python3 -m rl.orchestrator_worker --shadow \
763:             > logs/orchestrator_worker.log 2>&1 &
765:         nohup python3 -m rl.orchestrator_worker \
766:             > logs/orchestrator_worker.log 2>&1 &
773:         echo "   Consumer group: orchestrator_workers"
778:         echo "   Check logs/orchestrator_worker.log for errors"
782:     echo -e "${YELLOW}   ⏭️  Orchestrator Worker disabled (ORCHESTRATOR_WORKER_ENABLED=false)${NC}"
787: # PHASE 4B: START TRADERS (After Signals Available)
789: echo -e "${YELLOW}💰 PHASE 4B: Starting Traders...${NC}"
792: echo -n "   Starting Primary Trader... "
793: nohup python3 trading/trader.py \
794:     > logs/trader.log 2>&1 &
795: TRADER_PID=$!
797: if ps -p $TRADER_PID > /dev/null; then
798:     echo -e "${GREEN}✅ PID $TRADER_PID${NC}"
803: echo -n "   Starting Asjad Trader... "
804: nohup python3 trading/trader-asjad.py \
805:     > logs/trader-asjad.log 2>&1 &
806: TRADER_ASJAD_PID=$!
808: if ps -p $TRADER_ASJAD_PID > /dev/null; then
809:     echo -e "${GREEN}✅ PID $TRADER_ASJAD_PID${NC}"
817: # PHASE 4C: START PORTFOLIO MONITORS (After Traders)
819: echo -e "${YELLOW}📊 PHASE 4C: Starting Portfolio Monitors...${NC}"
822: echo "   Waiting for traders to sync positions (10s)..."
826: nohup python3 monitor_portfolio_primary.py \
837: nohup python3 monitor_portfolio_asjad.py \
850: # PHASE 5: HEALTH VALIDATION
852: echo -e "${YELLOW}🏥 PHASE 5: System Health Validation...${NC}"
858: python3 scripts/health_probe.py > /tmp/health_check.log 2>&1
878: ps aux | grep -E "python3.*(vpn_monitor|system_telegram|monitor_trainer_predictions|live_|feature_|ohlcv_|hybrid_|trader|monitor_portfolio)" | grep -v grep | \
893: echo "   Kill all:            pkill -f 'python3.*(vpn_monitor|system_telegram|monitor_trainer_predictions|live_|feature_|hybrid_|trader|monitor_portfolio)'"
894: echo "   Health check:        python3 scripts/health_probe.py"
903: SERVICE_COUNT=$(ps aux | grep -E "python3.*(vpn_monitor|system_telegram|monitor_trainer_predictions|live_|feature_|ohlcv_|hybrid_|trader)" | grep -v grep | wc -l)
924: • Health: python3 scripts/health_probe.py
```

## Start command lines
```text
28: BOT_PY_PATTERN="python3.*(vpn_monitor|system_telegram_monitor|monitor_system_memory|memory_monitor|monitor_trainer_predictions|ingest/live_|feature_pipeline\\.py|ohlcv_resampler_hotfix\\.py|live_technical_analysis\\.py|rl\\.hybrid_trainer|hybrid_trainer\\.py|rl\\.orchestrator_worker|orchestrator_worker\\.py|trading/trader|monitor_portfolio_|liquidation_bridge\\.py|liquidation_levels_engine\\.py|realtime_price_provider\\.py)"
44:     pkill -9 -f "python3.*(vpn_monitor|system_telegram_monitor|monitor_system_memory|memory_monitor|monitor_trainer_predictions|live_|feature_|ohlcv_resampler_hotfix|live_technical_analysis|hybrid_|trader|monitor_portfolio|liquidation_bridge|liquidation_levels_engine|realtime_price_provider)" || true
202: if ! pgrep -x "redis-server" > /dev/null; then
205:     sudo systemctl start redis-server
260:             ps aux | grep python3 | grep -v grep | awk '{printf \"%-9s %-5s %-5s \", \$2, \$4, \$3; system(\"ps -p \"\$2\" -o etime= | tr -d \\\" \\\"\"); printf \" %s\\n\", substr(\$0, index(\$0,\$11))}' | head -20
296:     nohup python3 vpn_monitor.py \
315:     nohup python3 system_telegram_monitor.py \
332:     nohup python3 monitor_system_memory.py \
351:     nohup python3 scripts/memory_monitor.py \
366:     nohup python3 scripts/monitor_trainer_predictions.py \
393:     nohup nice -n 10 taskset -c 0-7 python3 "$script" \
423:     nohup nice -n 10 python3 -m ingest.live_coinapi_wsds \
442:         nohup nice -n 10 taskset -c 0-7 python3 -m ingest.live_coinapi_v1 \
497:     python3 scripts/paralysis_detectors.py --minutes 5
535: nohup nice -n 5 python3 ohlcv_resampler_hotfix.py \
546: nohup python3 feature_pipeline.py \
591: nohup nice -n 5 python3 ingest/live_technical_analysis.py \
635:         python3 scripts/validate_symbol_universe_data.py
685: source venv/bin/activate && nohup python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features \
751: ORCH_ENABLED=$(python3 -c "from config import ORCHESTRATOR_WORKER_ENABLED; print(ORCHESTRATOR_WORKER_ENABLED)" 2>/dev/null | tail -1 || echo "False")
752: ORCH_MODE=$(python3 -c "from config import ORCHESTRATOR_WORKER_MODE; print(ORCHESTRATOR_WORKER_MODE)" 2>/dev/null | tail -1 || echo "shadow")
762:         nohup python3 -m rl.orchestrator_worker --shadow \
765:         nohup python3 -m rl.orchestrator_worker \
793: nohup python3 trading/trader.py \
804: nohup python3 trading/trader-asjad.py \
826: nohup python3 monitor_portfolio_primary.py \
837: nohup python3 monitor_portfolio_asjad.py \
858: python3 scripts/health_probe.py > /tmp/health_check.log 2>&1
878: ps aux | grep -E "python3.*(vpn_monitor|system_telegram|monitor_trainer_predictions|live_|feature_|ohlcv_|hybrid_|trader|monitor_portfolio)" | grep -v grep | \
893: echo "   Kill all:            pkill -f 'python3.*(vpn_monitor|system_telegram|monitor_trainer_predictions|live_|feature_|hybrid_|trader|monitor_portfolio)'"
894: echo "   Health check:        python3 scripts/health_probe.py"
903: SERVICE_COUNT=$(ps aux | grep -E "python3.*(vpn_monitor|system_telegram|monitor_trainer_predictions|live_|feature_|ohlcv_|hybrid_|trader)" | grep -v grep | wc -l)
924: • Health: python3 scripts/health_probe.py
```
