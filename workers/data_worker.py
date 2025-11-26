"""
Unified Data Worker
Consolidates MarketScanner, OrderBookScanner, and PriceHistoryWorker into one worker
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
from workers.price_history_worker import PriceHistoryWorker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DataWorker:
    """Unified worker for market, order book, and price history data collection"""
    
    def __init__(self):
        self.market_scanner = MarketScanner()
        self.orderbook_scanner = OrderBookScanner()
        self.price_history_worker = PriceHistoryWorker()
        self.running = True
        
        # Intervals
        self.market_interval = self.market_scanner.scan_interval  # 30 seconds
        self.orderbook_interval = self.orderbook_scanner.scan_interval  # 10 seconds
        self.price_interval = self.price_history_worker.scan_interval  # 300 seconds (5 minutes)
        
        # Last run times
        self.last_market_scan = 0
        self.last_orderbook_scan = 0
        self.last_price_update = 0
    
    def run(self):
        """Main worker loop - runs all scanners with different intervals"""
        logger.info("Data Worker started (Markets + Order Books + Price History)")
        
        # Run initial scans
        self.market_scanner.scan_markets()
        self.last_market_scan = time.time()
        
        self.orderbook_scanner.scan_orderbooks()
        self.last_orderbook_scan = time.time()
        
        self.price_history_worker.update_prices()
        self.last_price_update = time.time()
        
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
                
                # Check if it's time to update prices
                if current_time - self.last_price_update >= self.price_interval:
                    self.price_history_worker.update_prices()
                    self.last_price_update = time.time()
                
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
