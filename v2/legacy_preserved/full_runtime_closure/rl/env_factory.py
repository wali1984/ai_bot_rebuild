"""
Pickable Environment Factory for SubprocVecEnv
Fixes thread lock pickling issues in WSL
"""
import sys
sys.path.insert(0, '/mnt/c/AI BOT')

from rl.gymnasium_wrapper import TradingEnvironmentWrapper
from stable_baselines3.common.monitor import Monitor

def make_trading_env(rank=0):
    """
    Factory function to create trading environment
    This function is pickle-able for SubprocVecEnv
    """
    def _init():
        # Create environment without any shared state
        env = TradingEnvironmentWrapper()
        
        # Wrap with Monitor for logging (optional filename for rank)
        env = Monitor(env, filename=None, allow_early_resets=True)
        
        return env
    
    return _init

# For compatibility
def create_env(rank=0):
    """Alternative entry point"""
    return make_trading_env(rank)()
