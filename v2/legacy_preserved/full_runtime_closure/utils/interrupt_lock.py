import os
import sys
import psutil
from pathlib import Path

def exit_if_already_running(script_name: str = None, name: str = None, ttl_if_stale_seconds: int = None):
    """
    Check if another instance of the script is already running.
    Exit if found to prevent multiple instances.
    
    Args:
        script_name: Legacy parameter name
        name: Service name (new parameter)
        ttl_if_stale_seconds: TTL for stale processes (ignored for now)
    """
    # Handle both old and new parameter names
    service_name = script_name or name
    if not service_name:
        print("[INTERRUPT_LOCK] ERROR: No service name provided")
        return
    current_pid = os.getpid()
    current_cmd = ' '.join(sys.argv)
    
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.info['pid'] == current_pid:
                continue
                
            cmdline = proc.info.get('cmdline', [])
            if not cmdline:
                continue
                
            # Check if this is the same script
            cmdline_str = ' '.join(cmdline)
            
            # Map service names to their actual script names for precise matching
            script_mapping = {
                'binance': 'live_binance.py',
                'binance-liq': 'live_binance_liquidations.py',
                'kucoin': 'live_kucoin.py',
                'coinank': 'live_coinank.py',
                'tokenmetrics': 'live_tokenmetrics.py',
                'alphavantage': 'live_alphavantage_news.py'
            }
            
            # Get the exact script name for this service
            actual_script = script_mapping.get(service_name, f'{service_name}.py')
            script_path = Path(__file__).parent.parent / 'ingest' / actual_script

            # More specific matching - ONLY match actual Python processes running the exact script
            # Must be: python3 <script_path>/<actual_script> (not partial matches like live_binance_liquidations)
            is_actual_python = cmdline_str.startswith(('python3 ', 'python '))
            candidate_script = None
            if len(cmdline) >= 2:
                candidate_script = Path(cmdline[1]).name
            is_same_script = candidate_script == actual_script
            is_timeout_wrapper = 'timeout' in cmdline_str.lower()
            
            # Only match actual Python processes for the exact script, not bash wrappers or similarly named scripts
            if is_actual_python and is_same_script and not is_timeout_wrapper:
                print(f"[INTERRUPT_LOCK] Another instance of {service_name} is already running (PID: {proc.info['pid']})")
                print(f"[INTERRUPT_LOCK] Command line: {cmdline_str}")
                print(f"[INTERRUPT_LOCK] Exiting to prevent conflicts")
                sys.exit(1)
                
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    
    print(f"[INTERRUPT_LOCK] No existing instance found for {service_name}, proceeding...")
