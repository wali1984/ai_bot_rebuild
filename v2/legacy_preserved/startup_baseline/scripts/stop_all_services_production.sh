#!/bin/bash
# AI Trading System - PRODUCTION STOP SCRIPT
# Gracefully stops all services started by start_all_services_production.sh
# Sends Telegram notifications and cleans up Redis locks

set -e

BASE_DIR="/home/wali/Desktop/AI BOT"
cd "$BASE_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   🛑 AI Trading System - PRODUCTION SHUTDOWN                 ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ============================================================================
# PRE-SHUTDOWN SNAPSHOT (Audit-Jan5-Fixes)
# ----------------------------------------------------------------------------
# Capture current health before stopping anything. These are read-only checks.
# Never block shutdown if they fail.
# ============================================================================
if [ -f "scripts/paralysis_detectors.py" ]; then
    echo -e "${YELLOW}🧯 Pre-shutdown: Paralysis Detectors (last 5 minutes)...${NC}"
    echo "════════════════════════════════════════════════════════════════"
    set +e
    python3 scripts/paralysis_detectors.py --minutes 5
    set -e
    echo ""
fi

if [ -f "scripts/validate_symbol_universe_data.py" ]; then
    echo -e "${YELLOW}🧪 Pre-shutdown: Universe Data Validation (config.SYMBOLS/TIMEFRAMES)...${NC}"
    echo "════════════════════════════════════════════════════════════════"
    set +e
    python3 scripts/validate_symbol_universe_data.py
    set -e
    echo ""
fi

# Telegram notification function
send_telegram_notification() {
    local message="$1"
    local severity="${2:-INFO}"
    
    # Try to send via Python script if available
    python3 -c "
import sys
import os
sys.path.insert(0, '$BASE_DIR')
try:
    from telegram_alerts import TelegramNotifier
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN') or ''
    bot_chat_id = os.getenv('TELEGRAM_CHAT_ID') or ''
    channel_id = os.getenv('PRIVATE_CHANNEL_ID') or os.getenv('TELEGRAM_CHANNEL_ID') or bot_chat_id
    portfolio_channel_id = os.getenv('PORTFOLIO_CHANNEL_ID') or channel_id
    trade_channel_id = os.getenv('TRADE_CHANNEL_ID') or channel_id
    ai_signals_channel_id = os.getenv('AI_SIGNALS_CHANNEL_ID') or channel_id

    if not bot_token or not bot_chat_id or not channel_id:
        # Silent skip when Telegram isn't configured (common in headless/ops shells)
        print('ℹ️ Telegram not configured; skipping send')
    else:
        notifier = TelegramNotifier(
            bot_token,
            bot_chat_id,
            channel_id,
            portfolio_channel_id=portfolio_channel_id,
            trade_channel_id=trade_channel_id,
            ai_signals_channel_id=ai_signals_channel_id,
            redis_client=None,
        )
        # Use sync wrapper (safe even if no running event loop)
        ok = notifier.send_message_sync('$message')
        print('✅ Telegram notification sent' if ok else '⚠️ Telegram send failed')
except Exception as e:
    print(f'⚠️  Telegram notification failed: {e}')
" 2>/dev/null || echo -e "[TELEGRAM] $message"
}

# Send start notification
send_telegram_notification "🛑 Production shutdown initiated at $(date)" "WARNING"

echo -e "${YELLOW}📊 PHASE 1: Stopping Portfolio Monitors...${NC}"
echo "════════════════════════════════════════════════════════════════"
pkill -f "monitor_portfolio_primary.py" 2>/dev/null && echo "   ✅ Primary portfolio monitor stopped" || echo "   ⚠️  Primary monitor not running"
pkill -f "monitor_portfolio_asjad.py" 2>/dev/null && echo "   ✅ Asjad portfolio monitor stopped" || echo "   ⚠️  Asjad monitor not running"
pkill -f "monitor_system_memory.py" 2>/dev/null && echo "   ✅ System memory monitor stopped" || echo "   ⚠️  System memory monitor not running"
pkill -f "ohlcv_resampler_hotfix.py" 2>/dev/null && echo "   ✅ OHLCV resampler stopped" || echo "   ⚠️  OHLCV resampler not running"
sleep 1
echo ""

echo -e "${YELLOW}💰 PHASE 2: Stopping Traders...${NC}"
echo "════════════════════════════════════════════════════════════════"
# Stop traders and send notifications
if pgrep -f "trading/trader.py" > /dev/null; then
    send_telegram_notification "⏸️  Stopping primary trader..." "WARNING"
    pkill -TERM -f "trading/trader.py"
    sleep 3
    pkill -KILL -f "trading/trader.py" 2>/dev/null || true
    echo "   ✅ Primary trader stopped"
    send_telegram_notification "✅ Primary trader stopped" "INFO"
else
    echo "   ⚠️  Primary trader not running"
fi

if pgrep -f "trading/trader-asjad.py" > /dev/null; then
    send_telegram_notification "⏸️  Stopping asjad trader..." "WARNING"
    pkill -TERM -f "trading/trader-asjad.py"
    sleep 3
    pkill -KILL -f "trading/trader-asjad.py" 2>/dev/null || true
    echo "   ✅ Asjad trader stopped"
    send_telegram_notification "✅ Asjad trader stopped" "INFO"
else
    echo "   ⚠️  Asjad trader not running"
fi
sleep 1
echo ""

echo -e "${YELLOW}🎯 PHASE 3: Stopping Signal Router...${NC}"
echo "════════════════════════════════════════════════════════════════"
if pgrep -f "signal_router.py" > /dev/null; then
    pkill -TERM -f "signal_router.py"
    sleep 2
    pkill -KILL -f "signal_router.py" 2>/dev/null || true
    echo "   ✅ Signal router stopped"
else
    echo "   ⚠️  Signal router not running"
fi
sleep 1
echo ""

echo -e "${YELLOW}🧠 PHASE 4: Stopping Hybrid Trainer...${NC}"
echo "════════════════════════════════════════════════════════════════"
if pgrep -f "hybrid_trainer.py" > /dev/null; then
    send_telegram_notification "⏸️  Stopping hybrid trainer (AI model)..." "WARNING"
    pkill -KILL -f "hybrid_trainer.py" 2>/dev/null || true
    sleep 2
    echo "   ✅ Hybrid trainer force stopped"
    send_telegram_notification "✅ Hybrid trainer stopped" "INFO"
else
    echo "   ⚠️  Hybrid trainer not running"
fi
sleep 1
echo ""

echo -e "${YELLOW}📊 PHASE 5: Stopping Technical Analysis Service...${NC}"
echo "════════════════════════════════════════════════════════════════"
if pgrep -f "live_technical_analysis.py" > /dev/null; then
    pkill -TERM -f "live_technical_analysis.py"
    sleep 2
    pkill -KILL -f "live_technical_analysis.py" 2>/dev/null || true
    echo "   ✅ Technical analysis stopped"
else
    echo "   ⚠️  Technical analysis not running"
fi
sleep 1
echo ""

echo -e "${YELLOW}🔄 PHASE 6: Stopping Feature Pipeline...${NC}"
echo "════════════════════════════════════════════════════════════════"
if pgrep -f "feature_pipeline.py" > /dev/null; then
    pkill -TERM -f "feature_pipeline.py"
    sleep 2
    pkill -KILL -f "feature_pipeline.py" 2>/dev/null || true
    echo "   ✅ Feature pipeline stopped"
else
    echo "   ⚠️  Feature pipeline not running"
fi
sleep 1
echo ""

echo -e "${YELLOW}📡 PHASE 7: Stopping Data Ingestors...${NC}"
echo "════════════════════════════════════════════════════════════════"
# Stop all ingestors (including CoinAPI V1 and DS)
for ingestor in "live_binance" "live_binance_liquidations" "live_coinank" "live_coinank_global_aggregator" "live_kucoin" "live_token_metrics" "live_coinapi_wsds" "live_coinapi_v1" "live_coinapi_rest" "live_ccxt" "liquidation_bridge" "liquidation_levels_engine" "realtime_price_provider"; do
    if pgrep -f "$ingestor" > /dev/null; then
        pkill -TERM -f "$ingestor"
        sleep 1
        pkill -KILL -f "$ingestor" 2>/dev/null || true
        echo "   ✅ ${ingestor} stopped"
    else
        echo "   ⚠️  ${ingestor} not running"
    fi
done
sleep 1
echo ""

echo -e "${YELLOW}🔒 PHASE 8: Stopping VPN Monitor...${NC}"
echo "════════════════════════════════════════════════════════════════"
if pgrep -f "vpn_monitor.py" > /dev/null; then
    pkill -TERM -f "vpn_monitor.py"
    sleep 2
    pkill -KILL -f "vpn_monitor.py" 2>/dev/null || true
    echo "   ✅ VPN monitor stopped"
else
    echo "   ⚠️  VPN monitor not running"
fi
sleep 1
echo ""

echo -e "${YELLOW}🧹 PHASE 9: Cleaning Redis Data...${NC}"
echo "════════════════════════════════════════════════════════════════"

# Clear trading signals stream
echo -n "   Clearing trading signals stream... "
SIGNAL_COUNT=$(redis-cli XLEN signals:trading 2>/dev/null || echo "0")
if [ "$SIGNAL_COUNT" -gt 0 ]; then
    redis-cli DEL signals:trading >/dev/null 2>&1 && echo "✅ ($SIGNAL_COUNT signals cleared)" || echo "❌ Failed"
else
    echo "✅ (stream empty)"
fi

# Clear trainer prediction stream
echo -n "   Clearing trainer predictions stream... "
PRED_COUNT=$(redis-cli XLEN wma:trainer:predictions 2>/dev/null || echo "0")
if [ "$PRED_COUNT" -gt 0 ]; then
    redis-cli DEL wma:trainer:predictions >/dev/null 2>&1 && echo "✅ ($PRED_COUNT predictions cleared)" || echo "❌ Failed"
else
    echo "✅ (stream empty)"
fi

# Remove Redis locks
echo -n "   Removing Redis locks... "
redis-cli DEL lock:live_binance lock:live_binance_liq lock:live_coinank lock:live_coinapi_v1 lock:live_coinapi_wsds >/dev/null 2>&1
echo "✅ (live_binance, live_binance_liq, live_coinank, coinapi_v1, coinapi_wsds)"

# Clear stale position sync data
echo -n "   Clearing stale position data... "
redis-cli DEL positions:sync:last >/dev/null 2>&1 && echo "✅" || echo "⚠️  (optional)"

echo ""

echo -e "${YELLOW}📱 PHASE 10: Final Telegram Notification...${NC}"
echo "════════════════════════════════════════════════════════════════"

# Count stopped services
REMAINING=$(ps aux | grep -E "python3.*(vpn_monitor|system_telegram|live_|feature_|hybrid_|trader|signal_router|monitor_portfolio|monitor_system_memory|ohlcv_resampler_hotfix)" | grep -v grep | wc -l)

if [ "$REMAINING" -eq 0 ]; then
    send_telegram_notification "✅ AI Trading System successfully shutdown at $(date)

🛑 Shutdown Summary:
• All traders stopped
• All data feeds stopped
• Hybrid trainer stopped
• Redis locks cleared
• Trading signals purged

📊 System Status: OFFLINE
⏳ Ready for restart or maintenance

To restart: bash scripts/start_all_services_production.sh" "SUCCESS"
    echo "   ✅ Shutdown notification sent"
else
    send_telegram_notification "⚠️  AI Trading System shutdown completed with warnings at $(date)

🛑 Shutdown Summary:
• $REMAINING services still running
• Check manually: ps aux | grep python3

To force kill all: pkill -9 -f 'python3.*(live_|feature_|hybrid_|trader|watchdog)'

📊 System Status: PARTIAL SHUTDOWN" "WARNING"
    echo "   ⚠️  Warning notification sent ($REMAINING services still running)"
fi

echo ""

# Stop system telegram monitor last (so it can send notifications)
echo -e "${YELLOW}📱 PHASE 11: Stopping System Telegram Monitor (Last)...${NC}"
echo "════════════════════════════════════════════════════════════════"
sleep 3  # Give time for notification to send
if pgrep -f "system_telegram_monitor.py" > /dev/null; then
    pkill -TERM -f "system_telegram_monitor.py"
    sleep 2
    pkill -KILL -f "system_telegram_monitor.py" 2>/dev/null || true
    echo "   ✅ System telegram monitor stopped"
else
    echo "   ⚠️  System telegram monitor not running"
fi
echo ""

# Final status
echo -e "${BLUE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   ✅ PRODUCTION SHUTDOWN COMPLETE                            ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""

FINAL_COUNT=$(ps aux | grep -E "python3.*(vpn_monitor|system_telegram|live_|feature_|hybrid_|trader|signal_router|monitor_portfolio|monitor_system_memory|ohlcv_resampler_hotfix)" | grep -v grep | wc -l)

if [ "$FINAL_COUNT" -eq 0 ]; then
    echo -e "${GREEN}✅ All services stopped successfully${NC}"
    echo ""
    echo -e "${BLUE}System Status:${NC}"
    echo "   • Trading: OFFLINE"
    echo "   • Data Feeds: OFFLINE"
    echo "   • AI Model: OFFLINE"
    echo "   • Redis Locks: CLEARED"
    echo ""
    echo -e "${BLUE}To restart:${NC}"
    echo "   bash scripts/start_all_services_production.sh"
else
    echo -e "${YELLOW}⚠️  $FINAL_COUNT services still running${NC}"
    echo ""
    echo "Remaining processes:"
    ps aux | grep -E "python3.*(vpn_monitor|system_telegram|live_|feature_|hybrid_|trader|signal_router|monitor_portfolio)" | grep -v grep | \
        awk '{printf "   • PID %s - %s\n", $2, $11}'
    echo ""
    echo "To force kill all:"
    echo "   pkill -9 -f 'python3.*(live_|feature_|hybrid_|trader|signal_router|monitor_portfolio|watchdog)'"
fi

echo ""
