#!/bin/bash
# Flash Hedge Protection - End-to-End Validation Script
# Purpose: Verify flash hedge system is working correctly from detection → publication → execution
# Run this after every restart or code change to flash protection logic

cd "/home/wali/Desktop/AI BOT"

echo "=========================================="
echo "Flash Hedge Protection System Validation"
echo "=========================================="
echo ""
echo "Run date: $(date)"
echo "Trainer PID: $(pgrep -f hybrid_trainer.py || echo 'NOT RUNNING')"
echo "Trader PIDs: $(pgrep -f 'trader.*\.py' | tr '\n' ' ' || echo 'NONE')"
echo ""

# ============================================================================
# 1) CONFIG VALIDATION
# ============================================================================
echo "=== 1. CONFIG VALIDATION ==="
echo ""
echo "Checking for duplicate config variables..."
python3 - << 'PY'
import re, collections
p="config.py"
txt=open(p,"r",encoding="utf-8",errors="ignore").read().splitlines()
assign=re.compile(r'^\s*([A-Z][A-Z0-9_]+)\s*=')
flash_vars = ["FLASH_MOVE_PROTECTION_ENABLED", "FLASH_MOVE_THRESHOLD_PCT", "FLASH_MOVE_WINDOW_SECONDS", "FLASH_HEDGE_MIN_PNL_PCT", "FLASH_HEDGE_COOLDOWN_SECONDS"]
duplicates = []
for var in flash_vars:
    lines = []
    for i, l in enumerate(txt, 1):
        m = assign.match(l)
        if m and m.group(1) == var:
            lines.append((i, l.strip()))
    if len(lines) > 1:
        duplicates.append((var, [x[0] for x in lines]))
    elif len(lines) == 1:
        # Get value
        val = lines[0][1].split('=', 1)[1].strip()
        print(f"  ✅ {var} = {val}")
    else:
        print(f"  ❌ {var}: NOT FOUND")

if duplicates:
    print("\n⚠️  WARNING: DUPLICATES FOUND!")
    for var, line_nums in duplicates:
        print(f"  {var}: lines {line_nums}")
    exit(1)
else:
    print("\n✅ No flash-related duplicates found")
PY

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ VALIDATION FAILED: Config has duplicates"
    echo "Fix duplicates before continuing"
    exit 1
fi

echo ""

# ============================================================================
# 2) FLASH DETECTION LOGS
# ============================================================================
echo "=== 2. FLASH DETECTION + HEDGE INTENT LOGS ==="
echo ""
echo "Searching for flash move detection in last 500 lines..."

FLASH_DETECTIONS=$(grep -a "⚡💥 \[FLASH_MOVE\]" logs/hybrid_trainer.log 2>/dev/null | tail -20)
FLASH_HEDGE_INTENTS=$(grep -a "🚨 \[FLASH_HEDGE\]" logs/hybrid_trainer.log 2>/dev/null | tail -20)

if [ -z "$FLASH_DETECTIONS" ]; then
    echo "⚠️  No flash move detections found yet"
    echo "   (This is normal if no 2%+ moves occurred recently)"
else
    echo "✅ Flash move detections found:"
    echo "$FLASH_DETECTIONS" | tail -5
fi

echo ""

if [ -z "$FLASH_HEDGE_INTENTS" ]; then
    echo "⚠️  No flash hedge intents found yet"
    echo "   (This is normal if no flash moves triggered hedge logic)"
else
    echo "✅ Flash hedge intents found:"
    echo "$FLASH_HEDGE_INTENTS" | tail -5
fi

echo ""

# Check if flash hedges are being generated
FLASH_HEDGE_COUNT=$(grep -ac "flash_hedge.*true" logs/hybrid_trainer.log 2>/dev/null || echo "0")
echo "Flash hedge signals generated (all-time): $FLASH_HEDGE_COUNT"

echo ""

# ============================================================================
# 3) GOVERNANCE LAYER VALIDATION (Suppression Tracking)
# ============================================================================
echo "=== 3. GOVERNANCE LAYERS (Aggregation/Budget/Cooldown/Microstructure) ==="
echo ""

echo "3.1 Flash Hedge Suppression Logs:"
FLASH_SUPPRESSED=$(grep -a "FLASH_HEDGE_SUPPRESSED" logs/hybrid_trainer.log 2>/dev/null | tail -20)

if [ -z "$FLASH_SUPPRESSED" ]; then
    echo "  ✅ No flash hedges suppressed (or none attempted)"
else
    echo "  ⚠️  Flash hedges were SUPPRESSED:"
    echo "$FLASH_SUPPRESSED" | while IFS= read -r line; do
        # Extract reason
        if echo "$line" | grep -q "reason=duplicate"; then
            echo "    - DUPLICATE: $line"
        elif echo "$line" | grep -q "reason=cooldown"; then
            echo "    - COOLDOWN: $line"
        elif echo "$line" | grep -q "reason=budget"; then
            echo "    - BUDGET: $line"
        elif echo "$line" | grep -q "reason=hedge_build"; then
            echo "    - HEDGE_BUILD: $line"
        elif echo "$line" | grep -q "reason=microstructure"; then
            echo "    - MICROSTRUCTURE: $line"
        else
            echo "    - UNKNOWN: $line"
        fi
    done
fi

echo ""

echo "3.2 Flash Hedge Publication Logs:"
FLASH_PUBLISHED=$(grep -a "FLASH_HEDGE_PUBLISHED" logs/hybrid_trainer.log 2>/dev/null | tail -20)

if [ -z "$FLASH_PUBLISHED" ]; then
    echo "  ⚠️  No flash hedges published yet"
else
    echo "  ✅ Flash hedges PUBLISHED:"
    echo "$FLASH_PUBLISHED" | tail -5
fi

echo ""

echo "3.3 Aggregation Stats (last 50 lines):"
grep -a "ACTION_AGGREGATION" logs/hybrid_trainer.log 2>/dev/null | tail -50 | awk '
BEGIN {
    total_in=0; total_out=0; total_hedge=0; total_suppressed=0; count=0
}
{
    if (match($0, /Aggregated ([0-9]+) → ([0-9]+)/, arr)) {
        total_in += arr[1]
        total_out += arr[2]
        count++
    }
    if (match($0, /hedge=([0-9]+)/, arr)) {
        total_hedge += arr[1]
    }
    if (match($0, /suppressed=([0-9]+)/, arr)) {
        total_suppressed += arr[1]
    }
}
END {
    if (count > 0) {
        printf "  Total aggregation cycles: %d\n", count
        printf "  Signals in: %d (avg %.1f/cycle)\n", total_in, total_in/count
        printf "  Signals out: %d (avg %.1f/cycle)\n", total_out, total_out/count
        printf "  Hedge signals: %d\n", total_hedge
        printf "  Suppressed: %d (%.1f%%)\n", total_suppressed, (total_suppressed*100.0)/total_in
    } else {
        print "  ⚠️  No aggregation logs found"
    }
}
'

echo ""

# ============================================================================
# 4) TRADER EXECUTION VALIDATION
# ============================================================================
echo "=== 4. TRADER EXECUTION PIPELINE ==="
echo ""

echo "Searching trader logs for flash hedge execution..."

TRADER_FLASH_EXEC=$(grep -a "flash_hedge\|FLASH_HEDGE" logs/trader*.log 2>/dev/null | tail -20)

if [ -z "$TRADER_FLASH_EXEC" ]; then
    echo "⚠️  No trader flash hedge execution logs found yet"
    echo "   (This is normal if no flash hedges were published)"
else
    echo "✅ Trader flash hedge activity found:"
    echo "$TRADER_FLASH_EXEC" | tail -10
fi

echo ""

echo "Trader rejection analysis (last 100 signals):"
grep -a "REJECTED\|SKIP\|BLOCK" logs/trader*.log 2>/dev/null | tail -100 | awk '
BEGIN {
    min_notional=0; margin=0; hedge_mode=0; reduce_only=0; confidence=0; other=0
}
{
    if ($0 ~ /MIN_NOTIONAL|min.*notional/) min_notional++
    else if ($0 ~ /MARGIN|insufficient.*margin/) margin++
    else if ($0 ~ /HEDGE_MODE|hedge.*mode/) hedge_mode++
    else if ($0 ~ /REDUCE_ONLY|reduce.*only/) reduce_only++
    else if ($0 ~ /CONFIDENCE|confidence/) confidence++
    else other++
}
END {
    total = min_notional + margin + hedge_mode + reduce_only + confidence + other
    if (total > 0) {
        printf "  Total rejections: %d\n", total
        printf "    Min notional: %d\n", min_notional
        printf "    Margin: %d\n", margin
        printf "    Hedge mode: %d\n", hedge_mode
        printf "    Reduce only: %d\n", reduce_only
        printf "    Confidence: %d\n", confidence
        printf "    Other: %d\n", other
    } else {
        print "  ✅ No rejections found"
    }
}
'

echo ""

# ============================================================================
# 5) PROFIT EXIT / REVERSAL WATCH VALIDATION
# ============================================================================
echo "=== 5. PROFIT EXIT / REVERSAL WATCH LOGS ==="
echo ""

echo "Flash hedge profit-taking:"
FLASH_PROFIT=$(grep -a "FLASH_HEDGE_PROFIT" logs/hybrid_trainer.log 2>/dev/null | tail -10)

if [ -z "$FLASH_PROFIT" ]; then
    echo "  ⚠️  No flash hedge profit-taking events yet"
else
    echo "  ✅ Flash hedge profit-taking found:"
    echo "$FLASH_PROFIT"
fi

echo ""

echo "Reversal watch activity:"
REVERSAL_WATCH=$(grep -a "REVERSAL_WATCH_ENTER\|REVERSAL_WATCH_EXIT" logs/hybrid_trainer.log 2>/dev/null | tail -10)

if [ -z "$REVERSAL_WATCH" ]; then
    echo "  ⚠️  No reversal watch activity yet"
else
    echo "  ✅ Reversal watch activity:"
    echo "$REVERSAL_WATCH"
fi

echo ""

echo "Swing protection events:"
SWING_PROTECT=$(grep -a "SWING.*PROTECT\|swing.*consolidation" logs/hybrid_trainer.log 2>/dev/null | tail -10)

if [ -z "$SWING_PROTECT" ]; then
    echo "  ⚠️  No swing protection events logged"
else
    echo "  ✅ Swing protection active:"
    echo "$SWING_PROTECT" | tail -5
fi

echo ""

# ============================================================================
# 6) SUMMARY + RECOMMENDATIONS
# ============================================================================
echo "=========================================="
echo "VALIDATION SUMMARY"
echo "=========================================="
echo ""

# Count key metrics
FLASH_DETECTED_COUNT=$(grep -ac "⚡💥 \[FLASH_MOVE\]" logs/hybrid_trainer.log 2>/dev/null || echo "0")
FLASH_PUBLISHED_COUNT=$(grep -ac "FLASH_HEDGE_PUBLISHED" logs/hybrid_trainer.log 2>/dev/null || echo "0")
FLASH_SUPPRESSED_COUNT=$(grep -ac "FLASH_HEDGE_SUPPRESSED" logs/hybrid_trainer.log 2>/dev/null || echo "0")
FLASH_PROFIT_COUNT=$(grep -ac "FLASH_HEDGE_PROFIT" logs/hybrid_trainer.log 2>/dev/null || echo "0")

echo "Flash Move Detection:     $FLASH_DETECTED_COUNT events"
echo "Flash Hedges Published:   $FLASH_PUBLISHED_COUNT signals"
echo "Flash Hedges Suppressed:  $FLASH_SUPPRESSED_COUNT signals"
echo "Flash Hedge Profit Exits: $FLASH_PROFIT_COUNT events"

echo ""

# Status determination
if [ "$FLASH_DETECTED_COUNT" -eq 0 ]; then
    echo "STATUS: 🟡 WAITING"
    echo "  No flash moves detected yet (2%+ in <2min)"
    echo "  System is armed and monitoring"
elif [ "$FLASH_PUBLISHED_COUNT" -eq 0 ] && [ "$FLASH_SUPPRESSED_COUNT" -gt 0 ]; then
    echo "STATUS: ⚠️  ISSUE DETECTED"
    echo "  Flash moves detected but ALL hedges suppressed"
    echo "  Check suppression reasons in section 3.1 above"
    echo "  Common causes: duplicate, budget, cooldown, microstructure gate"
elif [ "$FLASH_PUBLISHED_COUNT" -gt 0 ]; then
    echo "STATUS: ✅ WORKING"
    echo "  Flash hedges are being detected and published"
    echo "  Check trader logs (section 4) for execution confirmation"
else
    echo "STATUS: 🟡 MONITORING"
    echo "  Flash detection active, waiting for market events"
fi

echo ""
echo "=========================================="
echo "NEXT STEPS"
echo "=========================================="
echo ""

if [ "$FLASH_SUPPRESSED_COUNT" -gt 0 ]; then
    echo "1. Review suppression reasons in section 3.1"
    echo "2. Check if budgets/cooldowns are too restrictive for HEDGE category"
    echo "3. Verify microstructure gate is bypassing HEDGE (not blocking)"
fi

if [ "$FLASH_PUBLISHED_COUNT" -gt 0 ] && [ -z "$TRADER_FLASH_EXEC" ]; then
    echo "1. Signals published but not executed by traders"
    echo "2. Check trader logs for rejection reasons (min_notional, margin, etc.)"
    echo "3. Verify trader is consuming from correct Redis stream"
fi

if [ "$FLASH_DETECTED_COUNT" -gt 0 ] && [ "$FLASH_PROFIT_COUNT" -eq 0 ]; then
    echo "1. Flash hedges opened but none closed profitably yet"
    echo "2. Wait for price reversal to test profit-taking logic"
    echo "3. Monitor for FLASH_HEDGE_PROFIT logs when hedge hits 1.5%+ PnL"
fi

echo ""
echo "To simulate a flash move for testing, trigger a 2%+ move in <120 seconds on any symbol"
echo "Or wait for natural market maker activity (stop hunts, liquidation cascades)"
echo ""
echo "Validation complete: $(date)"
