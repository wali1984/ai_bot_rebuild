"""
ACTION ONTOLOGY - Single Source of Truth for Action Mappings
=============================================================

This module provides the CANONICAL action mappings and categorization logic.
ALL code that converts action IDs to names or categorizes actions MUST use this module.

Layer A: RL Action Space (0-6)
------------------------------
The model outputs a Discrete(7) action index. This module maps it to action names.

Layer B: Action Intent + Category
---------------------------------
Action names are categorized into OPEN_RISK, HEDGE, or PROTECTIVE for governance.

DO NOT create ad-hoc action mappings elsewhere. Import from here.
"""

from typing import Dict, List, Optional, Set
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# CANONICAL ACTION ID TO NAME MAPPING (Layer A)
# =============================================================================
# NOTE: The canonical source of truth is trading/action_constants.py:ActionMapping
# This module provides RL-specific views and categorization logic.
# Version: v1_aligned (2024-12-27)

ACTION_MAP_VERSION = "v1_aligned"

# Standard 7-action space mapping (Discrete(7)) - ALIGNED WITH action_constants.py
# This matches ActionMapping.ID2ACTION_EXTENDED from trading/action_constants.py
ACTION_ID_TO_NAME: Dict[int, str] = {
    0: "HOLD",
    1: "OPEN_LONG",
    2: "OPEN_SHORT",
    3: "CLOSE_LONG",
    4: "CLOSE_SHORT",
    5: "CLOSE_SHORT_OPEN_LONG",    # Flip to LONG (close short, open long)
    6: "CLOSE_LONG_OPEN_SHORT",    # Flip to SHORT (close long, open short)
}

# Reverse mapping for validation
ACTION_NAME_TO_ID: Dict[str, int] = {v: k for k, v in ACTION_ID_TO_NAME.items()}

# Legacy mappings (for backward compatibility when loading old checkpoints)
LEGACY_ACTION_MAPS = {
    "legacy_v0": {
        0: "OPEN_SHORT",
        1: "HOLD",
        2: "OPEN_LONG",
        -1: "OPEN_SHORT",  # Alternate
    },
    "legacy_3action": {
        -1: "OPEN_SHORT",
        0: "HOLD",
        1: "OPEN_LONG",
    },
    # Hedge reward functions used different mapping
    "hedge_reward_v0": {
        0: "OPEN_LONG",
        1: "OPEN_SHORT",
        2: "INCREASE_LONG",
        3: "INCREASE_SHORT",
        4: "DECREASE_LONG",
        5: "DECREASE_SHORT",
        6: "CLOSE_ALL",
    }
}

# Extended action names (used in signal payloads, may be derived from context)
EXTENDED_ACTION_NAMES: Set[str] = {
    # Base actions (from ACTION_ID_TO_NAME)
    "HOLD",
    "OPEN_LONG", "OPEN_SHORT",
    "CLOSE_LONG", "CLOSE_SHORT", "CLOSE_ALL", "CLOSE",
    
    # Increase/Decrease (from hedge_reward)
    "INCREASE_LONG", "INCREASE_SHORT",
    "DECREASE_LONG", "DECREASE_SHORT",
    
    # Side-specific closes
    "CLOSE_LONG", "CLOSE_SHORT",
    
    # Partial closes
    "PARTIAL_CLOSE_LONG", "PARTIAL_CLOSE_SHORT",
    
    # Flips (composite actions - close one side, open opposite)
    # Standard format (from action_constants.py)
    "CLOSE_SHORT_OPEN_LONG", "CLOSE_LONG_OPEN_SHORT",
    # With _AND_ separator
    "CLOSE_SHORT_AND_OPEN_LONG", "CLOSE_LONG_AND_OPEN_SHORT",
    # CLOSE_AND_* shorthand
    "CLOSE_AND_LONG", "CLOSE_AND_SHORT",
    # CLOSE_AND_FLIP_* format
    "CLOSE_AND_FLIP_LONG", "CLOSE_AND_FLIP_SHORT",
    # FLIP_* shorthand
    "FLIP_LONG", "FLIP_SHORT",
    
    # Hedge actions
    "OPEN_HEDGE_LONG", "OPEN_HEDGE_SHORT",
    "REBALANCE_HEDGE",
    
    # Exit signals
    "STOP_LOSS", "TAKE_PROFIT",
    
    # Control signals
    "HOLD", "NONE", "NO_ACTION", "UNKNOWN",
}

# =============================================================================
# ACTION CATEGORIES (Layer B - Governance)
# =============================================================================

# OPEN_RISK: Net-new risk / risk-increasing exposure
#   - Subject to margin caps, hourly budgets, HTF alignment gating
#   - INCLUDES composite flips (they create new exposure)
OPEN_RISK_ACTIONS: Set[str] = {
    "OPEN_LONG", "OPEN_SHORT",
    "INCREASE_LONG", "INCREASE_SHORT",
    # ADD_* aliases (returned by should_open_position) - mapped to INCREASE_*
    "ADD_LONG", "ADD_SHORT", "ADD_TO_LONG", "ADD_TO_SHORT",
    "FLIP_LONG", "FLIP_SHORT",
    # Composite flips - ALL ALIASES ARE OPEN_RISK (create new exposure)
    # Standard format (from action_constants.py)
    "CLOSE_SHORT_OPEN_LONG", "CLOSE_LONG_OPEN_SHORT",
    # With _AND_ separator
    "CLOSE_SHORT_AND_OPEN_LONG", "CLOSE_LONG_AND_OPEN_SHORT",
    # CLOSE_AND_* shorthand
    "CLOSE_AND_LONG", "CLOSE_AND_SHORT",
    # CLOSE_AND_FLIP_* format
    "CLOSE_AND_FLIP_LONG", "CLOSE_AND_FLIP_SHORT",
}

# HEDGE: Risk-reducing opposite-side exposure / hedge management
#   - Draws from separate margin slice
#   - More lenient gating than OPEN_RISK
HEDGE_ACTIONS: Set[str] = {
    "OPEN_HEDGE_LONG", "OPEN_HEDGE_SHORT",
    "ADD_HEDGE_LONG", "ADD_HEDGE_SHORT",
    "SCALE_HEDGE", "UNWIND_HEDGE",
    "REBALANCE_HEDGE",
    "HEDGE_LONG", "HEDGE_SHORT", "HEDGE",  # Short-form hedge actions
}

# PROTECTIVE: Exit/reduction actions that should NEVER be blocked
#   - Unlimited budget, no cooldowns, no gating
#   - Pure exits only (no new exposure)
#   - Also includes passive/no-op actions
PROTECTIVE_ACTIONS: Set[str] = {
    "HOLD", "NO_ACTION", "NONE", "UNKNOWN",  # Passive actions - never block
    "CLOSE_LONG", "CLOSE_SHORT", "CLOSE_ALL", "CLOSE",
    "DECREASE_LONG", "DECREASE_SHORT",
    "STOP_LOSS", "TAKE_PROFIT", "TAKE_PROFIT_PARTIAL",
    "PARTIAL_CLOSE_LONG", "PARTIAL_CLOSE_SHORT", "PARTIAL_CLOSE",
}

# For backward compatibility with config.py format
ACTION_CATEGORIES: Dict[str, List[str]] = {
    "OPEN_RISK": list(OPEN_RISK_ACTIONS),
    "HEDGE": list(HEDGE_ACTIONS),
    "PROTECTIVE": list(PROTECTIVE_ACTIONS),
}


# =============================================================================
# FLIP ACTION ALIASES (Normalize different naming conventions)
# =============================================================================
FLIP_ACTION_ALIASES: Dict[str, str] = {
    # Standard names (canonical)
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


# =============================================================================
# CORE FUNCTIONS
# =============================================================================

def get_action_name(action_id: int, version: str = None) -> str:
    """
    Convert action ID to canonical action name.
    
    Args:
        action_id: Integer action index from model output (0-6)
        version: Optional version string for legacy checkpoint compatibility
        
    Returns:
        Canonical action name string
    """
    if version and version in LEGACY_ACTION_MAPS:
        return LEGACY_ACTION_MAPS[version].get(action_id, "UNKNOWN")
    return ACTION_ID_TO_NAME.get(action_id, "UNKNOWN")


def get_action_id(action_name: str) -> Optional[int]:
    """
    Convert action name to canonical action ID.
    
    Args:
        action_name: Action name string
        
    Returns:
        Action ID (0-6) or None if not a base action
    """
    return ACTION_NAME_TO_ID.get(action_name.upper())


def normalize_flip_action(action_name: str) -> str:
    """Normalize flip action aliases to canonical form"""
    if not action_name:
        return action_name
    upper = action_name.upper()
    return FLIP_ACTION_ALIASES.get(upper, upper)


def get_action_category(action_name: str) -> str:
    """
    Get the governance category for an action name.
    
    Categories:
    - OPEN_RISK: New/increased exposure (margin caps, gating apply)
    - HEDGE: Risk-reducing hedges (separate margin slice)
    - PROTECTIVE: Exits/reductions (never blocked)
    
    CRITICAL: Composite flip actions (CLOSE_AND_*, *_AND_OPEN_*) are OPEN_RISK,
              NOT PROTECTIVE, because they create new exposure.
    
    Args:
        action_name: Action name string
        
    Returns:
        Category string: "OPEN_RISK", "HEDGE", or "PROTECTIVE"
    """
    # Prefer config.py as the canonical source of truth (single mapping for trainer + traders).
    # This prevents drift between RL-side helper logic and live execution gating.
    try:
        from config import get_action_category as _cfg_get_action_category
        return _cfg_get_action_category(action_name)
    except Exception:
        pass

    action_upper = action_name.upper() if action_name else ""
    
    # 1) Check explicit OPEN_RISK set first (includes composite flips)
    if action_upper in OPEN_RISK_ACTIONS:
        return "OPEN_RISK"
    
    # 2) Check HEDGE set
    if action_upper in HEDGE_ACTIONS:
        return "HEDGE"
    
    # 3) Check PROTECTIVE set
    if action_upper in PROTECTIVE_ACTIONS:
        return "PROTECTIVE"
    
    # 4) Pattern-based detection for composite flips (MUST be OPEN_RISK)
    #    These patterns indicate "close + open" = new exposure
    if ("AND_OPEN" in action_upper) or ("_AND_LONG" in action_upper) or ("_AND_SHORT" in action_upper):
        return "OPEN_RISK"
    if ("CLOSE" in action_upper and "OPEN" in action_upper):
        return "OPEN_RISK"
    if "FLIP" in action_upper:
        return "OPEN_RISK"
    
    # 5) Pattern-based for hedge
    if "HEDGE" in action_upper:
        return "HEDGE"
    
    # 6) Pattern-based for protective (pure exits only)
    if any(x in action_upper for x in ["CLOSE", "DECREASE", "STOP", "TAKE_PROFIT", "PARTIAL"]):
        # Double-check no OPEN/FLIP patterns (those would be caught above)
        if not any(y in action_upper for y in ["OPEN", "FLIP", "_AND_"]):
            return "PROTECTIVE"
    
    # 7) Pattern-based for open risk (new exposure)
    if any(x in action_upper for x in ["OPEN", "INCREASE", "ADD"]):
        return "OPEN_RISK"
    
    # 8) SAFETY DEFAULT: Unknown actions → PROTECTIVE (no-op, not exposure creation)
    # This prevents unknown/malformed actions from accidentally opening positions
    return "PROTECTIVE"


def normalize_action_name(raw_action, payload: dict = None) -> str:
    """
    Normalize any action representation to canonical action_name string.
    
    CRITICAL: Uses payload['action_space'] to determine which mapping to use.
    - action_space="trade" → 0=HOLD, 1=OPEN_LONG, 2=OPEN_SHORT, etc.
    - action_space="hedge_rl" → 0=OPEN_LONG, 1=OPEN_SHORT, 2=INCREASE_LONG, etc.
    - missing/unknown → returns HOLD (safest default)
    
    Args:
        raw_action: Integer action ID, or string action name
        payload: Signal payload dict (may contain action_space, action_name)
        
    Returns:
        Canonical action name string
    """
    payload = payload or {}
    
    # 1. Try string action_name first (always most reliable)
    action_name = payload.get('action_name') or payload.get('predicted_action')
    if action_name and isinstance(action_name, str) and action_name.upper() not in ('NONE', 'UNKNOWN', ''):
        return str(action_name).upper()
    
    # 2. If raw_action is already a valid string, use it
    if isinstance(raw_action, str) and not raw_action.lstrip('-').isdigit():
        return raw_action.upper().strip()
    
    # 3. For numeric actions, we MUST know the action space
    if isinstance(raw_action, (int, float)) or (isinstance(raw_action, str) and raw_action.lstrip('-').isdigit()):
        action_idx = int(raw_action)
        action_space = str(payload.get('action_space', '')).lower()
        
        if action_space == 'trade':
            return ACTION_ID_TO_NAME.get(action_idx, 'HOLD')
        elif action_space in ('hedge_rl', 'hedge', 'rl'):
            return LEGACY_ACTION_MAPS.get('hedge_reward_v0', {}).get(action_idx, 'HOLD')
        else:
            # UNKNOWN ACTION SPACE - default to HOLD (safest)
            logger.warning(f"⚠️ [ACTION_SPACE_UNKNOWN] Numeric action {action_idx} without action_space - defaulting to HOLD")
            return 'HOLD'
    
    return 'HOLD'  # Safest default for unrecognized input


def is_flip_action(action_name: str) -> bool:
    """
    Check if action is a flip (close + open opposite side).
    
    Flips are treated as OPEN_RISK for governance but have special
    execution semantics (atomic close + open).
    """
    a = action_name.upper() if action_name else ""
    
    flip_patterns = [
        "CLOSE_AND_LONG", "CLOSE_AND_SHORT",
        "CLOSE_LONG_AND_OPEN_SHORT", "CLOSE_SHORT_AND_OPEN_LONG",
        "CLOSE_AND_FLIP_LONG", "CLOSE_AND_FLIP_SHORT",
        "FLIP_LONG", "FLIP_SHORT",
    ]
    
    if a in flip_patterns:
        return True
    
    # Pattern detection
    if ("CLOSE" in a and "OPEN" in a) or ("_AND_" in a and ("LONG" in a or "SHORT" in a)):
        return True
    
    return False


def is_open_risk_action(action_name: str) -> bool:
    """
    Check if action creates new exposure (requires sizing contract).
    
    Returns True for:
    - OPEN_LONG/OPEN_SHORT
    - INCREASE_LONG/INCREASE_SHORT
    - All flip actions (close + open)
    """
    return get_action_category(action_name) == "OPEN_RISK"


def is_protective_action(action_name: str) -> bool:
    """
    Check if action is purely protective (exit/reduce only).
    
    These actions should NEVER be blocked by governance.
    """
    return get_action_category(action_name) == "PROTECTIVE"


def is_hedge_action(action_name: str) -> bool:
    """Check if action is a hedge action."""
    return get_action_category(action_name) == "HEDGE"


def is_hold_action(action_name: str) -> bool:
    """Check if action is a hold/no-op."""
    a = action_name.upper() if action_name else ""
    return a in {"HOLD", "NONE", "NO_ACTION", "UNKNOWN", ""}


def get_action_side(action_name: str) -> Optional[str]:
    """
    Extract side (LONG/SHORT) from action name.
    
    Returns:
        "LONG", "SHORT", or None if no clear side
    """
    a = action_name.upper() if action_name else ""
    
    # For flips, the side is what we're opening, not closing
    if is_flip_action(a):
        if "AND_LONG" in a or "AND_OPEN_LONG" in a or a == "FLIP_LONG":
            return "LONG"
        if "AND_SHORT" in a or "AND_OPEN_SHORT" in a or a == "FLIP_SHORT":
            return "SHORT"
        if "CLOSE_LONG" in a:  # CLOSE_LONG_AND_OPEN_SHORT -> SHORT
            return "SHORT"
        if "CLOSE_SHORT" in a:  # CLOSE_SHORT_AND_OPEN_LONG -> LONG
            return "LONG"
    
    if "LONG" in a:
        return "LONG"
    if "SHORT" in a:
        return "SHORT"
    
    return None


def validate_action_name(action_name: str) -> bool:
    """Check if action name is in the known action set."""
    return action_name.upper() in EXTENDED_ACTION_NAMES


# =============================================================================
# LOGGING HELPERS
# =============================================================================

def log_action_mapping_info():
    """Log the current action mapping configuration."""
    logger.info(f"[ACTION_ONTOLOGY] Version: {ACTION_MAP_VERSION}")
    logger.info(f"[ACTION_ONTOLOGY] Base actions: {len(ACTION_ID_TO_NAME)}")
    logger.info(f"[ACTION_ONTOLOGY] OPEN_RISK: {len(OPEN_RISK_ACTIONS)} actions")
    logger.info(f"[ACTION_ONTOLOGY] HEDGE: {len(HEDGE_ACTIONS)} actions")
    logger.info(f"[ACTION_ONTOLOGY] PROTECTIVE: {len(PROTECTIVE_ACTIONS)} actions")


# =============================================================================
# TESTING/VALIDATION
# =============================================================================

def _validate_category_assignments():
    """Validate that all action categories are correctly assigned."""
    errors = []
    
    # Ensure no action is in multiple categories
    all_categorized = OPEN_RISK_ACTIONS | HEDGE_ACTIONS | PROTECTIVE_ACTIONS
    or_hedge = OPEN_RISK_ACTIONS & HEDGE_ACTIONS
    or_prot = OPEN_RISK_ACTIONS & PROTECTIVE_ACTIONS
    hedge_prot = HEDGE_ACTIONS & PROTECTIVE_ACTIONS
    
    if or_hedge:
        errors.append(f"Actions in both OPEN_RISK and HEDGE: {or_hedge}")
    if or_prot:
        errors.append(f"Actions in both OPEN_RISK and PROTECTIVE: {or_prot}")
    if hedge_prot:
        errors.append(f"Actions in both HEDGE and PROTECTIVE: {hedge_prot}")
    
    # Ensure flip patterns are in OPEN_RISK
    flip_patterns = ["CLOSE_AND_LONG", "CLOSE_AND_SHORT", "CLOSE_LONG_AND_OPEN_SHORT", "CLOSE_SHORT_AND_OPEN_LONG"]
    for fp in flip_patterns:
        if fp not in OPEN_RISK_ACTIONS:
            errors.append(f"Flip action {fp} not in OPEN_RISK")
    
    return errors


if __name__ == "__main__":
    # Self-test
    logging.basicConfig(level=logging.INFO)
    log_action_mapping_info()
    
    print("\n=== Category Tests ===")
    test_actions = [
        ("OPEN_LONG", "OPEN_RISK"),
        ("OPEN_SHORT", "OPEN_RISK"),
        ("CLOSE_LONG", "PROTECTIVE"),
        ("CLOSE_SHORT", "PROTECTIVE"),
        ("CLOSE_AND_LONG", "OPEN_RISK"),
        ("CLOSE_AND_SHORT", "OPEN_RISK"),
        ("CLOSE_LONG_AND_OPEN_SHORT", "OPEN_RISK"),
        ("CLOSE_SHORT_AND_OPEN_LONG", "OPEN_RISK"),
        ("OPEN_HEDGE_LONG", "HEDGE"),
        ("DECREASE_LONG", "PROTECTIVE"),
        ("STOP_LOSS", "PROTECTIVE"),
    ]
    
    for action, expected in test_actions:
        actual = get_action_category(action)
        status = "✓" if actual == expected else "✗"
        print(f"  {status} {action}: {actual} (expected {expected})")
    
    print("\n=== Flip Detection Tests ===")
    flip_tests = [
        ("CLOSE_AND_LONG", True),
        ("CLOSE_LONG", False),
        ("CLOSE_LONG_AND_OPEN_SHORT", True),
        ("OPEN_LONG", False),
    ]
    
    for action, expected in flip_tests:
        actual = is_flip_action(action)
        status = "✓" if actual == expected else "✗"
        print(f"  {status} {action}: is_flip={actual} (expected {expected})")
    
    print("\n=== Validation ===")
    errors = _validate_category_assignments()
    if errors:
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print("  ✓ All validations passed")
