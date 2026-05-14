#!/usr/bin/env pwsh
# AI BOT - Start Trading Engine (PowerShell Version)
# Launches the trading engine with risk management

$ErrorActionPreference = "Stop"

# Get script directory and project root
$ScriptDir = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$ProjectRoot = Split-Path -Path $ScriptDir -Parent

Write-Host "AI BOT - Starting Trading Engine" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot" -ForegroundColor Gray

# Ensure logs directory exists
$LogsDir = Join-Path $ProjectRoot "logs"
if (!(Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}

# Function to log with timestamp
function Write-Log {
    param([string]$Message, [string]$Color = "White")
    $Timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-Host "[$Timestamp] $Message" -ForegroundColor $Color
}

# Check if trader is already running
Write-Log "Checking for existing trader processes..." "Blue"

$ExistingProcess = Get-Process | Where-Object { 
    $_.ProcessName -eq "python" -and 
    $_.CommandLine -like "*trading/trader.py*" 
} -ErrorAction SilentlyContinue

if ($ExistingProcess) {
    Write-Log "Warning: Trading engine is already running (PID: $($ExistingProcess.Id))" "Yellow"
    $Response = Read-Host "Do you want to stop the existing trader and start a new one? (y/N)"
    if ($Response -eq "y" -or $Response -eq "Y") {
        Write-Log "Stopping existing trader..." "Yellow"
        Stop-Process -Id $ExistingProcess.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    } else {
        Write-Log "Keeping existing trader running. Exiting." "Green"
        exit 0
    }
}

# Check if trader script exists
$TraderScript = Join-Path $ProjectRoot "trading\trader.py"
if (!(Test-Path $TraderScript)) {
    Write-Log "ERROR: Trader script not found at: $TraderScript" "Red"
    exit 1
}

# Check Redis connection
Write-Log "Checking Redis connection..." "Blue"
try {
    $RedisTest = "import redis; r = redis.Redis(host='localhost', port=6379, decode_responses=True); r.ping(); print('Redis OK')"
    $TestResult = wsl -d Ubuntu -- bash -c "cd /mnt/c/AI\ BOT && python3 -c '$RedisTest'" 2>&1
    
    if ($LASTEXITCODE -eq 0 -and $TestResult -like "*Redis OK*") {
        Write-Log "Redis is running" "Green"
    } else {
        Write-Log "Redis connection failed: $TestResult" "Red"
        Write-Log "Please ensure Redis is running with: docker run -d --name redis -p 6379:6379 redis:latest" "Yellow"
        exit 1
    }
} catch {
    Write-Log "Redis check failed: $($_.Exception.Message)" "Red"
    exit 1
}

# Start trader in external detached terminal with raw output
Write-Log "Starting trading engine in external terminal..." "Blue"

$LogFile = Join-Path $LogsDir "trader.log"

# Create command for external PowerShell terminal with raw trading data output
$Command = @"
cd '$ProjectRoot'
Write-Host 'WMA AI Bot - Trading Engine' -ForegroundColor Cyan
Write-Host '$(('=' * 50))' -ForegroundColor Cyan
Write-Host 'Project: $ProjectRoot' -ForegroundColor Gray
Write-Host 'Script: trading/trader.py' -ForegroundColor Gray
Write-Host 'Log: $LogFile' -ForegroundColor Gray
Write-Host ''
Write-Host '🚀 Starting trading engine...' -ForegroundColor Green
Write-Host '📈 Raw trading data and decisions will be shown below' -ForegroundColor Yellow
Write-Host '⚠️  LIVE TRADING MODE - Monitor carefully!' -ForegroundColor Red
Write-Host '⏹️  Press Ctrl+C to stop trading' -ForegroundColor Gray
Write-Host ''

try {
    wsl -d Ubuntu -- bash -c \'cd /mnt/c/AI\ BOT && python3 "trading/trader.py"\' 2>&1 | Tee-Object '$LogFile'
} catch {
    Write-Host '' -ForegroundColor Red
    Write-Host '❌ Error running trading engine: `$(`$_.Exception.Message)' -ForegroundColor Red
} finally {
    Write-Host ''
    Write-Host '⏹️  Trading engine stopped.' -ForegroundColor Yellow
    Write-Host 'Press any key to close this terminal...' -ForegroundColor Gray
    Read-Host
}
"@

try {
    # Start in external PowerShell window with full raw output visibility
    $process = Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile", "-Command", $Command -WindowStyle Normal -PassThru
    
    Start-Sleep -Seconds 3
    Write-Log "Trading engine launched in external terminal with raw output" "Green"
    
    # Check if trader started successfully
    Start-Sleep -Seconds 2
    $NewProcess = Get-Process | Where-Object { 
        $_.ProcessName -eq "python" -and 
        $_.CommandLine -like "*trading/trader.py*" 
    } -ErrorAction SilentlyContinue
    
    if ($NewProcess) {
        Write-Log "Trading engine started successfully (PID: $($NewProcess.Id))" "Green"
    } else {
        Write-Log "Warning: Trading engine process not detected (may still be starting)" "Yellow"
        Write-Log "Check the terminal window for startup status" "Gray"
    }
    
} catch {
    Write-Log "Failed to start trading engine: $($_.Exception.Message)" "Red"
    exit 1
}

Write-Host ""
Write-Host "=================================" -ForegroundColor Cyan
Write-Log "Trading engine launched successfully!" "Green"
Write-Host ""
Write-Host "Monitor the dedicated terminal window for live trading activity" -ForegroundColor Cyan
Write-Host "Logs are saved to: $LogFile" -ForegroundColor Gray
Write-Host "Use 'scripts\stop_trader.ps1' to stop the trading engine" -ForegroundColor Yellow
Write-Host ""
Write-Host "Press any key to close this launcher window..." -ForegroundColor Gray
Read-Host
