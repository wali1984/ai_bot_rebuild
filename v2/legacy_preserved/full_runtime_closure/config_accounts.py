"""
Multi-Account Configuration for WMA AI Bot (LIVE ONLY)
======================================================
Defines account-specific settings, API keys, and risk limits for the live system.

Live accounts:
- primary
- asjad
"""
import os
from typing import Dict, Any, Optional

# Account configurations
ACCOUNTS = {
    'primary': {
        'name': 'Wajid (Binance)',
        'description': 'Wajid main trading account on Binance',
        'api_key_env': 'BINANCE_API_KEY',
        'api_secret_env': 'BINANCE_API_SECRET',
        'mode': 'live',
        'enabled': True,
        
        # Risk limits
        'risk_limits': {
            'max_position_size_pct': 0.30,  # Max 30% of balance per position
            'max_leverage': 20,              # Max 20× leverage
            'daily_loss_limit_pct': 0.20,   # Stop trading at 20% daily loss
            'max_open_positions': 5,         # Max 5 concurrent positions
            'max_total_exposure': 1.0,       # Max 100% total exposure
        },
        
        # Trading preferences
        'preferences': {
            'default_leverage': 10,
            'min_confidence': 0.75,          # Minimum signal confidence
            'use_stop_loss': True,
            'use_take_profit': True,
            'trailing_stop': True,
        },
        
        # Notification settings
        'notifications': {
            'telegram_enabled': True,
            'alert_on_fill': True,
            'alert_on_stop_loss': True,
            'alert_on_circuit_breaker': True,
            'daily_summary': True,
        }
    },
    
    'brother': {
        'name': 'Asjad (Binance)',
        'description': 'Asjad trading account on Binance - more conservative settings',
        'api_key_env': 'BINANCE_API_KEY_BROTHER',
        'api_secret_env': 'BINANCE_API_SECRET_BROTHER',
        'mode': 'live',
        'enabled': True,
        
        # More conservative risk limits
        'risk_limits': {
            'max_position_size_pct': 0.25,  # Max 25% per position
            'max_leverage': 15,              # Max 15× leverage
            'daily_loss_limit_pct': 0.15,   # Stop at 15% daily loss (more conservative)
            'max_open_positions': 3,         # Max 3 concurrent positions
            'max_total_exposure': 0.75,      # Max 75% total exposure
        },
        
        # Trading preferences
        'preferences': {
            'default_leverage': 8,           # Lower default leverage
            'min_confidence': 0.80,          # Higher confidence threshold
            'use_stop_loss': True,
            'use_take_profit': True,
            'trailing_stop': True,
        },
        
        # Notification settings
        'notifications': {
            'telegram_enabled': True,
            'alert_on_fill': True,
            'alert_on_stop_loss': True,
            'alert_on_circuit_breaker': True,
            'daily_summary': True,
        }
    },
    
    'asjad': {
        'name': 'Asjad (Binance)',
        'description': 'Asjad trading account on Binance',
        'api_key_env': 'BINANCE_API_KEY_ASJAD',
        'api_secret_env': 'BINANCE_API_SECRET_ASJAD',
        'mode': 'live',
        'enabled': True,
        
        # Risk limits
        'risk_limits': {
            'max_position_size_pct': 0.30,  # Max 30% per position
            'max_leverage': 20,              # Max 20× leverage
            'daily_loss_limit_pct': 0.20,   # Stop at 20% daily loss
            'max_open_positions': 5,         # Max 5 concurrent positions
            'max_total_exposure': 1.0,       # Max 100% total exposure
        },
        
        # Trading preferences
        'preferences': {
            'default_leverage': 10,
            'min_confidence': 0.75,          # Minimum signal confidence
            'use_stop_loss': True,
            'use_take_profit': True,
            'trailing_stop': True,
        },
        
        # Notification settings
        'notifications': {
            'telegram_enabled': True,
            'alert_on_fill': True,
            'alert_on_stop_loss': True,
            'alert_on_circuit_breaker': True,
            'daily_summary': True,
        }
    }
}


def get_account_config(account_id: str) -> Optional[Dict[str, Any]]:
    """
    Get configuration for a specific account
    
    Args:
        account_id: Account identifier ('primary', 'asjad')
    
    Returns:
        Account configuration dictionary or None if not found
    """
    return ACCOUNTS.get(account_id)


def get_enabled_accounts() -> list:
    """
    Get list of enabled account IDs
    
    Returns:
        List of account IDs that are enabled
    """
    return [account_id for account_id, config in ACCOUNTS.items() if config.get('enabled', False)]


def get_live_accounts() -> list:
    """
    Get list of live trading accounts
    
    Returns:
        List of live account IDs
    """
    return [
        account_id for account_id, config in ACCOUNTS.items() 
        if config.get('enabled', False) and config.get('mode') == 'live'
    ]


def get_preferences(account_id: str) -> Optional[Dict[str, Any]]:
    """
    Get trading preferences for an account
    
    Args:
        account_id: Account identifier
    
    Returns:
        Dictionary with trading preferences or None
    """
    config = get_account_config(account_id)
    if not config:
        return None
    
    return config.get('preferences', {})


def get_api_credentials(account_id: str) -> Optional[Dict[str, str]]:
    """
    Get API credentials for an account from environment variables
    
    Args:
        account_id: Account identifier
    
    Returns:
        Dictionary with 'api_key' and 'api_secret' or None
    """
    config = get_account_config(account_id)
    if not config:
        return None
    
    api_key = os.getenv(config['api_key_env'])
    api_secret = os.getenv(config['api_secret_env'])
    
    if not api_key or not api_secret:
        return None
    
    return {
        'api_key': api_key,
        'api_secret': api_secret,
        'mode': config.get('mode', 'live')
    }


def validate_account_config(account_id: str) -> tuple[bool, str]:
    """
    Validate account configuration
    
    Args:
        account_id: Account identifier
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    config = get_account_config(account_id)
    
    if not config:
        return False, f"Account '{account_id}' not found in configuration"
    
    if not config.get('enabled', False):
        return False, f"Account '{account_id}' is disabled"
    
    # Check API credentials
    credentials = get_api_credentials(account_id)
    if not credentials:
        return False, f"API credentials not found for account '{account_id}'"
    
    # Validate risk limits
    risk_limits = config.get('risk_limits', {})
    if not risk_limits:
        return False, f"Risk limits not configured for account '{account_id}'"
    
    required_limits = ['max_position_size_pct', 'max_leverage', 'daily_loss_limit_pct']
    for limit in required_limits:
        if limit not in risk_limits:
            return False, f"Missing risk limit '{limit}' for account '{account_id}'"
    
    return True, "Configuration valid"


def get_risk_limits(account_id: str) -> Optional[Dict[str, float]]:
    """
    Get risk limits for an account
    
    Args:
        account_id: Account identifier
    
    Returns:
        Risk limits dictionary or None
    """
    config = get_account_config(account_id)
    if not config:
        return None
    
    return config.get('risk_limits')


def get_preferences(account_id: str) -> Optional[Dict[str, Any]]:
    """
    Get trading preferences for an account
    
    Args:
        account_id: Account identifier
    
    Returns:
        Preferences dictionary or None
    """
    config = get_account_config(account_id)
    if not config:
        return None
    
    return config.get('preferences')


def should_send_notification(account_id: str, notification_type: str) -> bool:
    """
    Check if a specific notification should be sent for an account
    
    Args:
        account_id: Account identifier
        notification_type: Type of notification ('alert_on_fill', 'alert_on_stop_loss', etc.)
    
    Returns:
        True if notification should be sent
    """
    config = get_account_config(account_id)
    if not config:
        return False
    
    notifications = config.get('notifications', {})
    
    # Check if Telegram is enabled first
    if not notifications.get('telegram_enabled', False):
        return False
    
    return notifications.get(notification_type, False)


# Example usage and validation
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info("MULTI-ACCOUNT CONFIGURATION VALIDATION")
    logger.info("=" * 80)
    
    # List all accounts
    logger.info(f"\nConfigured accounts: {list(ACCOUNTS.keys())}")
    logger.info(f"Enabled accounts: {get_enabled_accounts()}")
    logger.info(f"Live accounts: {get_live_accounts()}")
    
    # Validate each account
    logger.info("\nAccount Validation:")
    for account_id in ACCOUNTS.keys():
        is_valid, message = validate_account_config(account_id)
        status = "✅" if is_valid else "❌"
        logger.info(f"{status} {account_id}: {message}")
        
        if is_valid:
            config = get_account_config(account_id)
            logger.info(f"   Mode: {config['mode']}")
            logger.info(f"   Max Leverage: {config['risk_limits']['max_leverage']}×")
            logger.info(f"   Max Position Size: {config['risk_limits']['max_position_size_pct']*100}%")
            logger.info(f"   Daily Loss Limit: {config['risk_limits']['daily_loss_limit_pct']*100}%")
    
    logger.info("\n" + "=" * 80)
