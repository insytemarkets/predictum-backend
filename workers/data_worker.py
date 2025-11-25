"""
Unified Data Worker
Consolidates MarketScanner and OrderBookScanner into one worker
Runs high-frequency data collection tasks
"""
import time
import logging
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workers.market_scanner import MarketScanner
from workers.orderbook_scanner import OrderBookScanner

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DataWorker:
    """Unified worker for market and order book data collection"""
    
    def __init__(self):
        self.market_scanner = MarketScanner()
        self.orderbook_scanner = OrderBookScanner()
        self.running = True
        
        # Intervals
        self.market_interval = self.market_scanner.scan_interval  # 30 seconds
        self.orderbook_interval = self.orderbook_scanner.scan_interval  # 10 seconds
        
        # Last run times
        self.last_market_scan = 0
        self.last_orderbook_scan = 0
    
    def run(self):
        """Main worker loop - runs both scanners with different intervals"""
        logger.info("Data Worker started (Markets + Order Books)")
        
        # Run initial scans
        self.market_scanner.scan_markets()
        self.last_market_scan = time.time()
        
        self.orderbook_scanner.scan_orderbooks()
        self.last_orderbook_scan = time.time()
        
        while self.running:
            try:
                current_time = time.time()
                
                # Check if it's time to scan markets
                if current_time - self.last_market_scan >= self.market_interval:
                    self.market_scanner.scan_markets()
                    self.last_market_scan = time.time()
                
                # Check if it's time to scan order books
                if current_time - self.last_orderbook_scan >= self.orderbook_interval:
                    self.orderbook_scanner.scan_orderbooks()
                    self.last_orderbook_scan = time.time()
                
                # Sleep for 1 second to avoid busy waiting
                time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("Shutting down data worker...")
                self.running = False
                break
            except Exception as e:
                logger.error(f"Fatal error in data worker: {e}", exc_info=True)
                time.sleep(5)  # Wait before retrying

if __name__ == "__main__":
    worker = DataWorker()
    worker.run()
