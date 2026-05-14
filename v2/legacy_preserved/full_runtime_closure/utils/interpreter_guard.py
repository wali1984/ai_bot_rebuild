import sys
import os
from pathlib import Path

def ensure_correct_interpreter(strict=False):
    """
    Ensure we're running with the correct Python interpreter.
    In the new setup, we expect to be in the virtual environment.
    """
    current_exec = sys.executable
    
    # Check if we're in the virtual environment
    if 'wma-bot-venv' in current_exec:
        print(f"[INTERPRETER] Using venv Python: {current_exec}")
        return True
    
    # For backwards compatibility, don't force exit unless strict=True
    if strict:
        print(f"[INTERPRETER ERROR] Not using venv Python: {current_exec}")
        print("[INTERPRETER ERROR] Please activate the virtual environment first")
        sys.exit(1)
    else:
        print(f"[INTERPRETER WARNING] Running with: {current_exec}")
        return False
