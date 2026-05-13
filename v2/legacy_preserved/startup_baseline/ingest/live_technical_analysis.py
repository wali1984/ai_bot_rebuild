#!/usr/bin/env python3
"""
Live Technical Analysis Service
Continuously calculates and updates TA indicators in real-time like other ingestors
Provides fresh TA data for the trainer and trading systems
"""

import os
import sys

# Fix PYTHONPATH for imports when run directly
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import time
import logging
from datetime import datetime
from ingest.technical_analysis import TechnicalAnalysisEngine

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class LiveTechnicalAnalysisService:
    """
    Continuous TA calculation service that runs like other ingestors
    Updates TA indicators every 60 seconds to provide real-time data
    """
    
    def __init__(self, update_interval: int = 60):
        """
        Initialize the live TA service
        
        Args:
            update_interval: Seconds between TA recalculations (default: 60s)
        """
        self.update_interval = update_interval
        self.ta_engine = None
        self.running = False
        self.cycle_count = 0
        self.last_success_time = None
        
    def initialize(self):
        """Initialize the TA engine"""
        try:
            logger.info("🔧 Initializing Technical Analysis Engine...")
            self.ta_engine = TechnicalAnalysisEngine()
            logger.info("✅ TA Engine initialized successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize TA Engine: {e}")
            return False
    
    def calculate_and_store(self):
        """Calculate TA indicators for all symbols and timeframes"""
        try:
            start_time = time.time()
            logger.info(f"📊 Starting TA calculation cycle #{self.cycle_count + 1}...")
            
            # Hot-reload symbols so newly added listings begin receiving TA without restart.
            try:
                from utils.symbol_manager import get_symbols_cached
                dyn = get_symbols_cached() or []
            except Exception:
                dyn = []
            try:
                from config import SYMBOLS as CFG_SYMBOLS
                cfg_syms = list(CFG_SYMBOLS or [])
            except Exception:
                cfg_syms = []
            symbols_now = [s for s in (dyn or cfg_syms or []) if isinstance(s, str) and s.strip()]
            if symbols_now and self.ta_engine is not None:
                if list(getattr(self.ta_engine, "symbols", []) or []) != symbols_now:
                    logger.info(f"🔁 Hot-reloaded TA symbols: {len(symbols_now)} (was {len(getattr(self.ta_engine, 'symbols', []) or [])})")
                    self.ta_engine.symbols = symbols_now

            # Process all symbols and timeframes
            total_indicators = 0
            for symbol in self.ta_engine.symbols:
                logger.info(f"  Processing {symbol}...")
                
                # Process each timeframe
                for timeframe in self.ta_engine.timeframes:
                    indicators = self.ta_engine.process_symbol_timeframe(symbol, timeframe)
                    if indicators:
                        total_indicators += len(indicators)
                
                # Calculate cross-timeframe indicators
                cross_tf = self.ta_engine.calculate_cross_timeframe_indicators(symbol)
                if cross_tf:
                    self.ta_engine.store_indicators_to_redis(symbol, 'cross_tf', cross_tf)
                    total_indicators += len(cross_tf)
            
            duration = time.time() - start_time
            self.cycle_count += 1
            self.last_success_time = datetime.now()
            
            logger.info(f"✅ TA cycle #{self.cycle_count} complete: {total_indicators} indicators in {duration:.2f}s")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error in TA calculation cycle: {e}", exc_info=True)
            return False
    
    def run(self):
        """Main service loop - runs continuously like other ingestors"""
        logger.info("=" * 80)
        logger.info("🚀 LIVE TECHNICAL ANALYSIS SERVICE")
        logger.info("=" * 80)
        logger.info(f"Update Interval: {self.update_interval}s")
        logger.info(f"Purpose: Provide real-time TA indicators for trainer and trading")
        logger.info("=" * 80)
        
        # Initialize TA engine
        if not self.initialize():
            logger.error("❌ Failed to initialize TA service, exiting")
            sys.exit(1)
        
        self.running = True
        logger.info("✅ TA Service started - running continuously")
        
        # Main loop
        while self.running:
            try:
                # Calculate and store TA indicators
                success = self.calculate_and_store()
                
                if success:
                    logger.info(f"⏱️  Next update in {self.update_interval}s...")
                else:
                    logger.warning(f"⚠️  Cycle failed, retrying in {self.update_interval}s...")
                
                # Sleep until next cycle
                time.sleep(self.update_interval)
                
            except KeyboardInterrupt:
                logger.info("🛑 Keyboard interrupt received, shutting down...")
                self.running = False
                break
            except Exception as e:
                logger.error(f"❌ Unexpected error in service loop: {e}", exc_info=True)
                logger.info(f"🔄 Restarting in {self.update_interval}s...")
                time.sleep(self.update_interval)
        
        logger.info("👋 Live TA Service stopped")

def main():
    """Main entry point"""
    # Create and run the service
    service = LiveTechnicalAnalysisService(update_interval=60)
    service.run()

if __name__ == "__main__":
    main()
