"""
Stats Aggregator Worker
Calculates market statistics like spreads, buy/sell pressure, etc.
"""
import time
import logging
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class StatsAggregator:
    def __init__(self):
        self.db = SupabaseClient()
        self.scan_interval = 300  # 5 minutes
    
    def aggregate_stats(self):
        """Calculate and store market statistics"""
        try:
            logger.info("Starting stats aggregation...")
            
            markets = self.db.get_markets(limit=100)
            
            stats_count = 0
            for market in markets:
                try:
                    condition_id = market.get('condition_id')
                    if not condition_id:
                        continue
                    
                    # Calculate stats (simplified)
                    stats = self._calculate_stats(market)
                    if stats:
                        self.db.upsert_market_stats(condition_id, stats)
                        stats_count += 1
                        
                except Exception as e:
                    logger.error(f"Error aggregating stats for market {market.get('condition_id')}: {e}")
                    continue
            
            logger.info(f"Aggregated stats for {stats_count} markets")
            
        except Exception as e:
            logger.error(f"Error in stats aggregation: {e}", exc_info=True)
    
    def _calculate_stats(self, market: dict) -> dict:
        """Calculate market statistics"""
        # Simplified - would need order book data
        # For now, return basic stats
        return {
            'spread_percentage': 0.5,  # Placeholder
            'buy_pressure': 0.6,  # Placeholder
            'sell_pressure': 0.4  # Placeholder
        }
    
    def run(self):
        """Main worker loop"""
        logger.info("Stats Aggregator Worker started")
        while True:
            try:
                self.aggregate_stats()
            except Exception as e:
                logger.error(f"Fatal error in stats aggregator: {e}", exc_info=True)
            
            logger.info(f"Sleeping for {self.scan_interval} seconds...")
            time.sleep(self.scan_interval)

if __name__ == "__main__":
    aggregator = StatsAggregator()
    aggregator.run()
