#!/usr/bin/env pwsh
# Start WMA AI Bot Hybrid Trainer - Production Stable

$ProjectRoot = "C:\AI BOT"
Set-Location $ProjectRoot

Write-Host "🚀 Starting WMA AI Bot Hybrid Trainer (Production Stable)" -ForegroundColor Green
Write-Host "RTX 5080 with 17.1GB VRAM - Optimized for Maximum GPU Utilization" -ForegroundColor Cyan
Write-Host "Working directory: $ProjectRoot" -ForegroundColor Gray

# Ensure required directories exist
if (!(Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" -Force | Out-Null
}
if (!(Test-Path "checkpoints")) {
    New-Item -ItemType Directory -Path "checkpoints" -Force | Out-Null
    Write-Host "✅ Created checkpoints directory" -ForegroundColor Green
}
if (!(Test-Path "tensorboard_logs")) {
    New-Item -ItemType Directory -Path "tensorboard_logs" -Force | Out-Null
    Write-Host "✅ Created tensorboard_logs directory" -ForegroundColor Green
}

# Clear Python cache to avoid path conflicts
Write-Host "🗑️ Clearing Python cache..." -ForegroundColor Yellow
Get-ChildItem -Recurse __pycache__ -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Get-ChildItem -Recurse *.pyc -ErrorAction SilentlyContinue | Remove-Item -Force

# Clear any Redis locks
try {
    wsl -d Ubuntu -- bash -c "cd /mnt/c/AI\ BOT && python3 -c 'from utils.redis_client import get_redis; r = get_redis(); r.delete(\"lock:hybrid_trainer\"); print(\"Cleared locks\")'"
    Write-Host "✅ Cleared trainer locks" -ForegroundColor Green
} catch {
    Write-Host "Could not clear locks (Redis may not be running)" -ForegroundColor Yellow
}

# Set PYTHONPATH to ensure correct imports
$env:PYTHONPATH = $ProjectRoot

# Start Production Hybrid Trainer with auto-restart protection
Write-Host "`n=== Production Trainer Launch ===" -ForegroundColor Cyan
Write-Host "⚡ RTX 5080 GPU Training - Maximum Performance Mode" -ForegroundColor Yellow
Write-Host "🎯 64 environments, 8192 batch size for optimal GPU utilization" -ForegroundColor Yellow

# Start Hybrid Trainer with production stability and auto-restart
Write-Host "Starting Hybrid Trainer with auto-restart protection..." -ForegroundColor Yellow
$trainerProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", @"
Set-Location '$ProjectRoot';
Write-Host '🔥 WMA AI Bot Hybrid Trainer - PRODUCTION STABLE' -ForegroundColor Green;
Write-Host 'RTX 5080 GPU Training Active - Auto-Restart Enabled' -ForegroundColor Cyan;
while (`$true) {
    try {
        Write-Host '🚀 Starting training session...' -ForegroundColor Green;
        wsl -d Ubuntu -- bash -c 'cd /mnt/c/AI\ BOT `&`& python3 rl/hybrid_trainer.py';
        Write-Host '⚠️ Training session ended - restarting in 10 seconds...' -ForegroundColor Yellow;
        Start-Sleep 10;
    } catch {
        Write-Host 'Training crashed - restarting in 15 seconds...' -ForegroundColor Red;
        Write-Host `$_.Exception.Message -ForegroundColor Red;
        Start-Sleep 15;
    }
}
"@ -WindowStyle Normal -PassThru

Write-Host "`n✅ Hybrid Trainer launched in separate window!" -ForegroundColor Green
Write-Host "🔥 PRODUCTION TRAINING ACTIVE!" -ForegroundColor Yellow
Write-Host "🎯 RTX 5080 optimized for 70-90% GPU utilization" -ForegroundColor Cyan

Write-Host "`nProduction Training Features:" -ForegroundColor Cyan
Write-Host "   - Auto-restart on crashes (10s delay)" -ForegroundColor Gray
Write-Host "   - 64 parallel environments for maximum GPU usage" -ForegroundColor Gray
Write-Host "   - 8192 batch size optimized for RTX 5080" -ForegroundColor Gray
Write-Host "   - Automatic model checkpointing" -ForegroundColor Gray
Write-Host "   - TensorBoard logging for monitoring" -ForegroundColor Gray

Write-Host "`nMonitoring:" -ForegroundColor Yellow
Write-Host "   - Training window shows real-time progress" -ForegroundColor Gray
Write-Host "   - Models saved to checkpoints/ directory" -ForegroundColor Gray
Write-Host "   - Logs available in logs/trainer.log" -ForegroundColor Gray
Write-Host "   - GPU usage: wsl nvidia-smi" -ForegroundColor Gray
Write-Host "   - Close window or Ctrl+C to stop training" -ForegroundColor Gray

Write-Host "`n🎉 Production training session active!" -ForegroundColor Green
Write-Host "GPU utilization optimized for RTX 5080 with CUDA in WSL" -ForegroundColor Yellow
Write-Host "Logs are saved to: logs\hybrid_trainer.log" -ForegroundColor Gray
Write-Host "Use Ctrl+C in the training terminal to stop" -ForegroundColor Yellow
Write-Host ""
Write-Host "Press any key to close this launcher window..." -ForegroundColor Gray
Read-Host
