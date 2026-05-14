#!/usr/bin/env python3
"""
Position Manager - Close Positions on Both Binance Accounts
============================================================
Manages and closes positions on both trader accounts (Asjad and Brother).

Features:
- Close ALL positions
- Close ALL Long positions only
- Close ALL Short positions only
- Close ALL positions in Profit
- Close ALL positions in Loss
- Close Half of Long positions
- Close Half of Short positions

Usage:
    python3 scripts/close_all_positions.py

Safety Features:
- Shows all positions before closing
- Interactive menu for operation selection
- Requires confirmation for destructive actions
- Handles hedge mode properly (LONG/SHORT position sides)
- Reports success/failure for each position
"""

import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv(project_root / '.env')


class PositionCloser:
    """Handles closing positions on Binance Futures"""
    
    def __init__(self, api_key: str, api_secret: str, account_name: str):
        self.account_name = account_name
        self.client = Client(api_key, api_secret)
        self.dual_side_position = None  # Will be detected
        
    def detect_position_mode(self) -> str:
        """Detect if account is using Hedge Mode (dual side) or One-Way Mode"""
        try:
            response = self.client.futures_get_position_mode()
            self.dual_side_position = response.get('dualSidePosition', False)
            mode = "Hedge Mode" if self.dual_side_position else "One-Way Mode"
            print(f"  📌 {self.account_name} is using: {mode}")
            return mode
        except Exception as e:
            print(f"  ⚠️  Could not detect position mode for {self.account_name}: {e}")
            self.dual_side_position = True  # Default to Hedge Mode for safety
            return "Unknown (assuming Hedge Mode)"
        
    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions (non-zero position amount) - FRESH from Binance"""
        try:
            all_positions = self.client.futures_position_information()
            open_positions = [
                pos for pos in all_positions 
                if float(pos['positionAmt']) != 0
            ]
            return open_positions
        except BinanceAPIException as e:
            print(f"❌ Error fetching positions for {self.account_name}: {e}")
            return []
    
    def filter_positions(
        self, 
        positions: List[Dict[str, Any]], 
        side: Optional[str] = None,
        profit_only: bool = False,
        loss_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Filter positions by criteria.
        
        Args:
            positions: List of position dicts
            side: 'LONG' or 'SHORT' or None for all
            profit_only: Only include positions with positive PnL
            loss_only: Only include positions with negative PnL
        """
        filtered = positions.copy()
        
        if side == 'LONG':
            filtered = [p for p in filtered if float(p['positionAmt']) > 0]
        elif side == 'SHORT':
            filtered = [p for p in filtered if float(p['positionAmt']) < 0]
        
        if profit_only:
            filtered = [p for p in filtered if float(p['unRealizedProfit']) > 0]
        elif loss_only:
            filtered = [p for p in filtered if float(p['unRealizedProfit']) < 0]
        
        return filtered
    
    def display_positions(self, positions: List[Dict[str, Any]], title: str = "Open Positions") -> float:
        """Display positions in a readable format and return total PnL"""
        if not positions:
            print(f"\n✅ No {title.lower()} on {self.account_name}")
            return 0.0
        
        print(f"\n📊 {title} on {self.account_name}:")
        print("=" * 100)
        
        total_unrealized_pnl = 0.0
        
        for pos in positions:
            symbol = pos['symbol']
            amt = float(pos['positionAmt'])
            entry_price = float(pos['entryPrice'])
            mark_price = float(pos['markPrice'])
            unrealized_pnl = float(pos['unRealizedProfit'])
            leverage = int(pos.get('leverage', 0))
            
            side = 'LONG' if amt > 0 else 'SHORT'
            total_unrealized_pnl += unrealized_pnl
            
            pnl_symbol = "📈" if unrealized_pnl > 0 else "📉"
            
            lev_str = f"{leverage}x" if leverage > 0 else "N/A"
            print(f"{pnl_symbol} {symbol:12} | {side:5} | Qty: {abs(amt):>12.6f} | "
                  f"Entry: ${entry_price:>10.4f} | Mark: ${mark_price:>10.4f} | "
                  f"PnL: ${unrealized_pnl:>10.2f} | Lev: {lev_str}")
        
        print("=" * 100)
        total_symbol = "💰" if total_unrealized_pnl > 0 else "⚠️"
        print(f"{total_symbol} Total Unrealized PnL: ${total_unrealized_pnl:>10.2f}")
        print()
        
        return total_unrealized_pnl
    
    def get_symbol_precision(self, symbol: str) -> int:
        """Get quantity precision for a symbol"""
        try:
            info = self.client.futures_exchange_info()
            for s in info['symbols']:
                if s['symbol'] == symbol:
                    for f in s['filters']:
                        if f['filterType'] == 'LOT_SIZE':
                            step_size = float(f['stepSize'])
                            # Calculate precision from step size
                            if step_size >= 1:
                                return 0
                            precision = 0
                            while step_size < 1:
                                step_size *= 10
                                precision += 1
                            return precision
            return 3  # Default precision
        except Exception:
            return 3  # Default precision on error
    
    def close_positions(
        self, 
        positions: List[Dict[str, Any]], 
        close_fraction: float = 1.0
    ) -> Dict[str, int]:
        """
        Close positions (full or partial).
        
        Args:
            positions: List of positions to close
            close_fraction: 1.0 for full close, 0.5 for half, etc.
        
        Returns:
            Dict with success/failed/total counts
        """
        if not positions:
            return {"success": 0, "failed": 0, "total": 0}
        
        results = {"success": 0, "failed": 0, "total": len(positions)}
        fraction_str = f"{int(close_fraction * 100)}%" if close_fraction < 1.0 else "FULL"
        
        print(f"\n🔄 Closing positions ({fraction_str}) on {self.account_name}...")
        
        for pos in positions:
            symbol = pos['symbol']
            amt = float(pos['positionAmt'])
            
            # Determine order side and position side based on mode
            if amt > 0:
                order_side = 'SELL'
                position_side = 'LONG'
            else:
                order_side = 'BUY'
                position_side = 'SHORT'
            
            # Calculate quantity to close
            full_qty = abs(amt)
            close_qty = full_qty * close_fraction
            
            # Get precision for this symbol and round properly
            precision = self.get_symbol_precision(symbol)
            close_qty = round(close_qty, precision)
            
            # Ensure we don't close more than we have
            if close_qty > full_qty:
                close_qty = full_qty
            
            # Ensure minimum quantity (avoid dust)
            if close_qty == 0:
                print(f"  ⏭️  Skipped {position_side:5} {symbol:12} | Qty too small after rounding")
                results["failed"] += 1
                continue
            
            try:
                # Create order parameters based on position mode
                order_params = {
                    'symbol': symbol,
                    'side': order_side,
                    'type': 'MARKET',
                    'quantity': close_qty
                }
                
                # Add positionSide for Hedge Mode
                if self.dual_side_position:
                    order_params['positionSide'] = position_side
                
                # Place market order to close position
                order = self.client.futures_create_order(**order_params)
                
                close_type = "Partial" if close_fraction < 1.0 else "Closed"
                print(f"  ✅ {close_type} {position_side:5} {symbol:12} | Qty: {close_qty:>12.6f} / {full_qty:.6f} | Order: #{order['orderId']}")
                results["success"] += 1
                
                # Small delay to avoid rate limits
                time.sleep(0.3)
                
            except BinanceAPIException as e:
                print(f"  ❌ Failed to close {position_side:5} {symbol:12} | Error: {e.message}")
                results["failed"] += 1
            except Exception as e:
                print(f"  ❌ Failed to close {position_side:5} {symbol:12} | Error: {str(e)}")
                results["failed"] += 1
        
        return results


def print_menu():
    """Print interactive menu"""
    print("\n" + "=" * 60)
    print("📋 POSITION MANAGEMENT MENU")
    print("=" * 60)
    print("  1. Close ALL positions")
    print("  2. Close ALL LONG positions")
    print("  3. Close ALL SHORT positions")
    print("  4. Close ALL positions in PROFIT")
    print("  5. Close ALL positions in LOSS")
    print("  6. Close HALF of LONG positions")
    print("  7. Close HALF of SHORT positions")
    print("  8. Refresh positions (query Binance)")
    print("  0. Exit")
    print("=" * 60)


def get_confirmation(action_desc: str, position_count: int) -> bool:
    """Get user confirmation for an action"""
    print(f"\n⚠️  WARNING: You are about to {action_desc}")
    print(f"   This will affect {position_count} position(s)")
    print("   This action is IRREVERSIBLE and will execute MARKET orders immediately.")
    print()
    
    confirm_text = f"CONFIRM"
    response = input(f"Type '{confirm_text}' to proceed (case-sensitive): ")
    
    return response == confirm_text


def execute_action(
    accounts: List[PositionCloser],
    all_positions: Dict[str, List[Dict[str, Any]]],
    action: int
) -> Tuple[Dict[str, int], Dict[str, List[Dict[str, Any]]]]:
    """
    Execute the selected action.
    
    Returns:
        Tuple of (results dict, updated positions dict)
    """
    total_results = {"success": 0, "failed": 0, "total": 0}
    
    # Define action parameters
    action_config = {
        1: {"desc": "close ALL positions", "side": None, "profit": False, "loss": False, "fraction": 1.0},
        2: {"desc": "close ALL LONG positions", "side": "LONG", "profit": False, "loss": False, "fraction": 1.0},
        3: {"desc": "close ALL SHORT positions", "side": "SHORT", "profit": False, "loss": False, "fraction": 1.0},
        4: {"desc": "close ALL positions in PROFIT", "side": None, "profit": True, "loss": False, "fraction": 1.0},
        5: {"desc": "close ALL positions in LOSS", "side": None, "profit": False, "loss": True, "fraction": 1.0},
        6: {"desc": "close HALF of LONG positions", "side": "LONG", "profit": False, "loss": False, "fraction": 0.5},
        7: {"desc": "close HALF of SHORT positions", "side": "SHORT", "profit": False, "loss": False, "fraction": 0.5},
    }
    
    if action not in action_config:
        print("❌ Invalid action")
        return total_results, all_positions
    
    config = action_config[action]
    
    # Filter and count affected positions
    filtered_positions = {}
    total_affected = 0
    
    for account in accounts:
        positions = all_positions.get(account.account_name, [])
        filtered = account.filter_positions(
            positions, 
            side=config["side"],
            profit_only=config["profit"],
            loss_only=config["loss"]
        )
        filtered_positions[account.account_name] = filtered
        total_affected += len(filtered)
    
    if total_affected == 0:
        print(f"\n✅ No positions match the criteria. Nothing to close.")
        return total_results, all_positions
    
    # Show filtered positions
    print(f"\n📊 Positions that will be affected:")
    for account in accounts:
        positions = filtered_positions[account.account_name]
        if positions:
            title = f"Positions to {config['desc']}"
            account.display_positions(positions, title)
    
    # Get confirmation
    if not get_confirmation(config["desc"], total_affected):
        print("\n❌ Confirmation failed. Aborting operation.")
        return total_results, all_positions
    
    # Execute closes
    print("\n" + "=" * 80)
    print("🔥 EXECUTING POSITION CLOSURES")
    print("=" * 80)
    
    for account in accounts:
        positions = filtered_positions[account.account_name]
        if positions:
            results = account.close_positions(positions, close_fraction=config["fraction"])
            total_results["success"] += results["success"]
            total_results["failed"] += results["failed"]
            total_results["total"] += results["total"]
    
    # Show summary
    print("\n" + "=" * 60)
    print("📊 ACTION SUMMARY")
    print("=" * 60)
    print(f"Total Positions Processed: {total_results['total']}")
    print(f"✅ Successfully Closed: {total_results['success']}")
    print(f"❌ Failed: {total_results['failed']}")
    
    if total_results['failed'] == 0 and total_results['success'] > 0:
        print("\n🎉 All positions processed successfully!")
    elif total_results['failed'] > 0:
        print(f"\n⚠️  {total_results['failed']} position(s) failed. Check errors above.")
    
    # Refresh positions after action
    print("\n🔄 Refreshing positions from Binance...")
    updated_positions = {}
    for account in accounts:
        positions = account.get_open_positions()
        updated_positions[account.account_name] = positions
    
    return total_results, updated_positions


def refresh_positions(accounts: List[PositionCloser]) -> Dict[str, List[Dict[str, Any]]]:
    """Refresh all positions from Binance"""
    print("\n🔄 Querying fresh positions from Binance...")
    all_positions = {}
    
    for account in accounts:
        positions = account.get_open_positions()
        all_positions[account.account_name] = positions
        account.display_positions(positions)
    
    total = sum(len(p) for p in all_positions.values())
    print(f"\n📊 Total positions across all accounts: {total}")
    
    return all_positions


def main():
    """Main execution flow"""
    
    print("=" * 80)
    print("🛠️  POSITION MANAGER - WMA AI Trading Bot")
    print("=" * 80)
    
    # Initialize closers for both accounts
    accounts = []
    
    # Account 1: Wajid
    api_key_1 = os.getenv('BINANCE_API_KEY')
    api_secret_1 = os.getenv('BINANCE_API_SECRET')
    
    if api_key_1 and api_secret_1:
        accounts.append(PositionCloser(api_key_1, api_secret_1, "Wajid"))
    else:
        print("⚠️  Wajid account credentials not found in .env")
    
    # Account 2: Asjad
    api_key_2 = os.getenv('BINANCE_API_KEY_BROTHER')
    api_secret_2 = os.getenv('BINANCE_API_SECRET_BROTHER')
    
    if api_key_2 and api_secret_2:
        accounts.append(PositionCloser(api_key_2, api_secret_2, "Asjad"))
    else:
        print("⚠️  Asjad account credentials not found in .env")
    
    if not accounts:
        print("\n❌ No valid accounts configured. Exiting.")
        return
    
    # Detect position mode for each account
    print("\n🔍 Detecting position modes...")
    for account in accounts:
        account.detect_position_mode()
    
    # Initial position fetch
    all_positions = refresh_positions(accounts)
    
    # Interactive menu loop
    while True:
        print_menu()
        
        try:
            choice = input("\nEnter your choice (0-8): ").strip()
            
            if choice == '0':
                print("\n👋 Exiting Position Manager. Goodbye!")
                break
            elif choice == '8':
                all_positions = refresh_positions(accounts)
            elif choice in ['1', '2', '3', '4', '5', '6', '7']:
                _, all_positions = execute_action(accounts, all_positions, int(choice))
            else:
                print("❌ Invalid choice. Please enter a number between 0-8.")
        
        except KeyboardInterrupt:
            print("\n\n❌ Operation cancelled by user (Ctrl+C)")
            continue
        except Exception as e:
            print(f"\n❌ Error: {e}")
            continue


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Operation cancelled by user (Ctrl+C)")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
