#!/usr/bin/env python3
"""
AI-Select Coins Manager

Configuration-based manager for Binance AI-select coins.
Reads rankings from config file and syncs with symbol manager.

No web scraping - rankings updated manually from:
https://www.binance.com/en/markets/ai-select

Usage:
    # Show current rankings
    python -m utils.ai_coins_manager show
    
    # Sync top 5 to symbol manager (dry-run)
    python -m utils.ai_coins_manager sync --dry-run
    
    # Sync top 5 to symbol manager (live)
    python -m utils.ai_coins_manager sync
    
    # Sync top 3 only
    python -m utils.ai_coins_manager sync --top 3
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.symbol_manager import (
    get_active_symbols,
    add_symbols,
    remove_symbols,
    check_capacity,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Config file path
CONFIG_FILE = project_root / "config" / "ai_select_rankings.json"


class AICoinsManager:
    """Manages AI-select coin rankings and symbol manager integration."""
    
    def __init__(self, config_path: Path = CONFIG_FILE):
        self.config_path = config_path
        self.rankings = []
        self.last_updated = None
        self.source = None
        
    def load_rankings(self) -> bool:
        """Load rankings from config file."""
        try:
            if not self.config_path.exists():
                logger.error(f"Config file not found: {self.config_path}")
                return False
                
            with open(self.config_path, 'r') as f:
                data = json.load(f)
                
            self.rankings = data.get('rankings', [])
            self.last_updated = data.get('last_updated')
            self.source = data.get('source')
            
            logger.info(f"Loaded {len(self.rankings)} AI-select rankings")
            logger.info(f"Last updated: {self.last_updated}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load rankings: {e}")
            return False
    
    def get_top_symbols(self, top_n: int = 5) -> List[str]:
        """Get top N symbols from rankings."""
        if not self.rankings:
            logger.warning("No rankings loaded")
            return []
            
        # Sort by rank (just in case)
        sorted_rankings = sorted(self.rankings, key=lambda x: x.get('rank', 999))
        
        # Get top N symbols
        top_symbols = [r['symbol'] for r in sorted_rankings[:top_n]]
        
        logger.info(f"Top {top_n} AI-select symbols: {', '.join(top_symbols)}")
        return top_symbols
    
    def show_rankings(self) -> None:
        """Display current rankings in formatted table."""
        if not self.rankings:
            print("No rankings loaded. Please check config file.")
            return
            
        print(f"\n{'='*80}")
        print(f"Binance AI-Select Coin Rankings")
        print(f"{'='*80}")
        print(f"Source: {self.source}")
        print(f"Last Updated: {self.last_updated}")
        print(f"{'='*80}\n")
        
        # Header
        print(f"{'Rank':<6} {'Symbol':<15} {'Sentiment':<20} {'Discussions':<15}")
        print(f"{'-'*6} {'-'*15} {'-'*20} {'-'*15}")
        
        # Rankings
        for r in sorted(self.rankings, key=lambda x: x.get('rank', 999)):
            rank = r.get('rank', '-')
            symbol = r.get('symbol', '-')
            sentiment = r.get('sentiment', '-')
            discussions = r.get('discussions', '-')
            print(f"{rank:<6} {symbol:<15} {sentiment:<20} {discussions:<15}")
        
        print(f"\n{'='*80}\n")
    
    def sync_to_symbol_manager(
        self,
        top_n: int = 5,
        dry_run: bool = False
    ) -> Dict[str, List[str]]:
        """
        Sync top N AI-select coins to symbol manager.
        
        Args:
            top_n: Number of top coins to sync
            dry_run: If True, only show what would be done
            
        Returns:
            Dict with 'added', 'skipped', 'removed' lists
        """
        result = {
            'added': [],
            'skipped': [],
            'removed': [],
            'errors': []
        }
        
        # Load rankings
        if not self.load_rankings():
            result['errors'].append("Failed to load rankings")
            return result
        
        # Get top symbols
        top_symbols = self.get_top_symbols(top_n)
        if not top_symbols:
            result['errors'].append("No top symbols found")
            return result
        
        # Get current active symbols
        try:
            active_symbols = get_active_symbols()
            logger.info(f"Currently active symbols: {len(active_symbols)}")
        except Exception as e:
            logger.error(f"Failed to get active symbols: {e}")
            result['errors'].append(f"Failed to get active symbols: {e}")
            return result
        
        # Check capacity before adding
        try:
            capacity_info = check_capacity()
            available_slots = capacity_info['available']
            logger.info(f"Available symbol slots: {available_slots}")
        except Exception as e:
            logger.warning(f"Could not check capacity: {e}")
            available_slots = 999  # Assume capacity available
        
        # Determine which symbols to add
        symbols_to_add = []
        for symbol in top_symbols:
            if symbol in active_symbols:
                result['skipped'].append(symbol)
                logger.info(f"✓ {symbol} already active (rank {top_symbols.index(symbol) + 1})")
            else:
                symbols_to_add.append(symbol)
        
        # Check if we have capacity for new symbols
        if len(symbols_to_add) > available_slots:
            logger.warning(
                f"Want to add {len(symbols_to_add)} symbols but only "
                f"{available_slots} slots available"
            )
            logger.warning(f"Will add first {available_slots} symbols only")
            symbols_to_add = symbols_to_add[:available_slots]
        
        # Add new symbols
        if symbols_to_add:
            if dry_run:
                logger.info(f"[DRY-RUN] Would add: {', '.join(symbols_to_add)}")
                result['added'] = symbols_to_add
            else:
                logger.info(f"Adding AI-select symbols: {', '.join(symbols_to_add)}")
                try:
                    success = add_symbols(symbols_to_add)
                    if success:
                        result['added'] = symbols_to_add
                        logger.info(f"✓ Successfully added {len(symbols_to_add)} symbols")
                    else:
                        error_msg = "Failed to add symbols (see symbol_manager logs)"
                        logger.error(error_msg)
                        result['errors'].append(error_msg)
                except Exception as e:
                    logger.error(f"Exception adding symbols: {e}")
                    result['errors'].append(str(e))
        else:
            logger.info("No new symbols to add - top AI-select coins already active")
        
        # Summary
        logger.info(f"\nSync Summary:")
        logger.info(f"  Added: {len(result['added'])} symbols")
        logger.info(f"  Already Active: {len(result['skipped'])} symbols")
        if result['errors']:
            logger.error(f"  Errors: {len(result['errors'])}")
            for err in result['errors']:
                logger.error(f"    - {err}")
        
        return result


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Manage AI-select coin rankings and symbol sync',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show current rankings from config
  python -m utils.ai_coins_manager show
  
  # Sync top 5 (dry-run)
  python -m utils.ai_coins_manager sync --dry-run
  
  # Sync top 5 (live)
  python -m utils.ai_coins_manager sync
  
  # Sync top 3 only
  python -m utils.ai_coins_manager sync --top 3
  
To update rankings:
  1. Visit https://www.binance.com/en/markets/ai-select
  2. Edit config/ai_select_rankings.json
  3. Update 'rankings' list and 'last_updated' timestamp
  4. Run sync command
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Show command
    show_parser = subparsers.add_parser('show', help='Display current rankings')
    
    # Sync command
    sync_parser = subparsers.add_parser('sync', help='Sync to symbol manager')
    sync_parser.add_argument(
        '--top',
        type=int,
        default=5,
        help='Number of top coins to sync (default: 5)'
    )
    sync_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    # Create manager
    manager = AICoinsManager()
    
    if args.command == 'show':
        # Load and display rankings
        if manager.load_rankings():
            manager.show_rankings()
        else:
            logger.error("Failed to load rankings")
            sys.exit(1)
            
    elif args.command == 'sync':
        # Sync to symbol manager
        result = manager.sync_to_symbol_manager(
            top_n=args.top,
            dry_run=args.dry_run
        )
        
        # Exit with error if sync failed
        if result['errors']:
            sys.exit(1)
            
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
