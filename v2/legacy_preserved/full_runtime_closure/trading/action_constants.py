"""
Unified Action Mapping Constants for Trading System
Ensures consistency across Trainer and live execution traders
"""

# ============================================================================
# UNIFIED ACTION MAPPING SYSTEM
# ============================================================================

class ActionMapping:
    """
    Unified action mapping for all trading components.
    
    CRITICAL: All traders and the trainer MUST use these exact mappings.
    
    Two-tier system:
    1. LEGACY_FORMAT: Used by trainer output (-1, 0, 1)
    2. EXTENDED_FORMAT: Used by advanced position management (0-6)
    """
    
    # === LEGACY FORMAT (Trainer Output) ===
    # Used by trainer in signals: convention: -1 short/sell, 0 flat/hold, 1 long/buy
    LEGACY_SHORT = -1      # SHORT/SELL signal from trainer
    LEGACY_HOLD = 0        # HOLD/FLAT signal from trainer  
    LEGACY_LONG = 1        # LONG/BUY signal from trainer
    
    # === EXTENDED FORMAT (Advanced Position Management) ===
    # Used by traders for complex position management
    HOLD = 0               # Hold current position (no action)
    OPEN_LONG = 1          # Open new long position
    OPEN_SHORT = 2         # Open new short position  
    CLOSE_LONG = 3         # Close existing long position
    CLOSE_SHORT = 4        # Close existing short position
    CLOSE_SHORT_OPEN_LONG = 5   # Close short and open long (flip)
    CLOSE_LONG_OPEN_SHORT = 6   # Close long and open short (flip)
    
    # === LEGACY TO EXTENDED MAPPING ===
    LEGACY_TO_EXTENDED = {
        LEGACY_SHORT: OPEN_SHORT,   # -1 -> 2 (Open Short)
        LEGACY_HOLD: HOLD,          #  0 -> 0 (Hold)
        LEGACY_LONG: OPEN_LONG,     #  1 -> 1 (Open Long)
    }
    
    # === ACTION NAMES FOR LOGGING ===
    LEGACY_NAMES = {
        LEGACY_SHORT: "SELL/SHORT",
        LEGACY_HOLD: "HOLD",
        LEGACY_LONG: "BUY/LONG"
    }
    
    EXTENDED_NAMES = {
        HOLD: "HOLD",
        OPEN_LONG: "OPEN_LONG",
        OPEN_SHORT: "OPEN_SHORT", 
        CLOSE_LONG: "CLOSE_LONG",
        CLOSE_SHORT: "CLOSE_SHORT",
        CLOSE_SHORT_OPEN_LONG: "CLOSE_SHORT_OPEN_LONG",
        CLOSE_LONG_OPEN_SHORT: "CLOSE_LONG_OPEN_SHORT"
    }
    
    # === ID TO ACTION MAPPINGS (Single Source of Truth) ===
    # EXTENDED: Primary 7-action space for position management
    ID2ACTION_EXTENDED = {
        0: "HOLD",
        1: "OPEN_LONG",
        2: "OPEN_SHORT",
        3: "CLOSE_LONG",
        4: "CLOSE_SHORT",
        5: "CLOSE_SHORT_OPEN_LONG",    # Flip to LONG
        6: "CLOSE_LONG_OPEN_SHORT",    # Flip to SHORT
    }
    
    # LEGACY: Old 3-action format for backward compatibility
    ID2ACTION_LEGACY = {
        -1: "OPEN_SHORT",
        0: "HOLD",
        1: "OPEN_LONG",
    }
    
    # Aliases for flip actions (support multiple naming conventions)
    FLIP_ACTION_ALIASES = {
        # Standard names
        "CLOSE_SHORT_OPEN_LONG": "CLOSE_SHORT_OPEN_LONG",
        "CLOSE_LONG_OPEN_SHORT": "CLOSE_LONG_OPEN_SHORT",
        # With _AND_ separator
        "CLOSE_SHORT_AND_OPEN_LONG": "CLOSE_SHORT_OPEN_LONG",
        "CLOSE_LONG_AND_OPEN_SHORT": "CLOSE_LONG_OPEN_SHORT",
        # CLOSE_AND_* shorthand
        "CLOSE_AND_LONG": "CLOSE_SHORT_OPEN_LONG",
        "CLOSE_AND_SHORT": "CLOSE_LONG_OPEN_SHORT",
        # FLIP_* shorthand
        "FLIP_LONG": "CLOSE_SHORT_OPEN_LONG",
        "FLIP_SHORT": "CLOSE_LONG_OPEN_SHORT",
        # CLOSE_AND_FLIP_* format
        "CLOSE_AND_FLIP_LONG": "CLOSE_SHORT_OPEN_LONG",
        "CLOSE_AND_FLIP_SHORT": "CLOSE_LONG_OPEN_SHORT",
    }
    
    @staticmethod
    def normalize_flip_action(action_name: str) -> str:
        """Normalize flip action aliases to canonical form"""
        if not action_name:
            return action_name
        upper = action_name.upper()
        return ActionMapping.FLIP_ACTION_ALIASES.get(upper, upper)
    
    @staticmethod
    def is_legacy_action(action):
        """Check if action is in legacy format (-1, 0, 1)"""
        return action in [ActionMapping.LEGACY_SHORT, ActionMapping.LEGACY_HOLD, ActionMapping.LEGACY_LONG]
    
    @staticmethod
    def is_extended_action(action):
        """Check if action is in extended format (0-6)"""
        return action in range(7)
    
    @staticmethod
    def convert_legacy_to_extended(legacy_action):
        """Convert legacy action (-1,0,1) to extended action (0-6)"""
        return ActionMapping.LEGACY_TO_EXTENDED.get(legacy_action, ActionMapping.HOLD)
    
    @staticmethod
    def get_action_name(action, prefer_extended=True):
        """
        Get human-readable name for any action format
        
        Args:
            action: The action to get name for
            prefer_extended: If True, prefer extended names for overlapping actions (0,1)
        """
        # For overlapping actions (0,1), prefer extended format unless explicitly requesting legacy
        if prefer_extended and ActionMapping.is_extended_action(action):
            return ActionMapping.EXTENDED_NAMES.get(action, f"UNKNOWN_EXTENDED_{action}")
        elif ActionMapping.is_legacy_action(action):
            return ActionMapping.LEGACY_NAMES.get(action, f"UNKNOWN_LEGACY_{action}")
        elif ActionMapping.is_extended_action(action):
            return ActionMapping.EXTENDED_NAMES.get(action, f"UNKNOWN_EXTENDED_{action}")
        else:
            return f"INVALID_ACTION_{action}"
    
    @staticmethod
    def get_legacy_action_name(action):
        """Get legacy action name specifically"""
        return ActionMapping.get_action_name(action, prefer_extended=False)

# ============================================================================
# HOLD TYPES (Position Context)
# ============================================================================

class HoldType:
    """
    Hold sub-types for position-aware holding
    Used when action=HOLD but we need to specify what we're holding
    """
    FLAT = "FLAT"           # No position (truly flat)
    HOLD_LONG = "HOLD_LONG" # Holding existing long position
    HOLD_SHORT = "HOLD_SHORT" # Holding existing short position

# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_action_consistency():
    """
    Validate that all action mappings are consistent and complete.
    Call this during system startup to catch configuration errors.
    """
    errors = []
    
    # Check legacy mapping completeness
    expected_legacy = [ActionMapping.LEGACY_SHORT, ActionMapping.LEGACY_HOLD, ActionMapping.LEGACY_LONG]
    for legacy in expected_legacy:
        if legacy not in ActionMapping.LEGACY_TO_EXTENDED:
            errors.append(f"Missing legacy mapping for action {legacy}")
    
    # Check extended range completeness  
    expected_extended = list(range(7))  # 0-6
    for extended in expected_extended:
        if extended not in ActionMapping.EXTENDED_NAMES:
            errors.append(f"Missing extended name for action {extended}")
    
    # Check no duplicate mappings
    extended_values = list(ActionMapping.LEGACY_TO_EXTENDED.values())
    if len(extended_values) != len(set(extended_values)):
        errors.append("Duplicate mappings found in LEGACY_TO_EXTENDED")
    
    if errors:
        raise ValueError(f"Action mapping validation failed: {errors}")
    
    return True

# ============================================================================
# REDIS ACTION ENCODING/DECODING
# ============================================================================

def encode_action_for_redis(action, hold_type=None):
    """
    Encode action for Redis storage with optional hold type context.
    Returns dict with action metadata.
    """
    result = {
        'action': action,
        'action_name': ActionMapping.get_action_name(action),
        'is_legacy': ActionMapping.is_legacy_action(action),
        'is_extended': ActionMapping.is_extended_action(action)
    }
    
    if action == ActionMapping.HOLD or action == ActionMapping.LEGACY_HOLD:
        result['hold_type'] = hold_type or HoldType.FLAT
    
    return result

def decode_action_from_redis(redis_data):
    """
    Decode action from Redis data, handling both legacy and extended formats.
    Returns standardized action in extended format.
    """
    if isinstance(redis_data, dict):
        action = redis_data.get('action')
        if action is None:
            return ActionMapping.HOLD
    else:
        action = redis_data
    
    # Convert to int if needed
    try:
        action = int(action)
    except (ValueError, TypeError):
        return ActionMapping.HOLD
    
    # Convert legacy to extended if needed
    if ActionMapping.is_legacy_action(action):
        return ActionMapping.convert_legacy_to_extended(action)
    
    # Return extended action directly
    if ActionMapping.is_extended_action(action):
        return action
    
    # Invalid action, default to hold
    return ActionMapping.HOLD