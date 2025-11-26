"""
Stats Aggregator Worker
Calculates market statistics like spreads, buy/sell pressure, etc.
"""
import time
import logging
from typing import Dict, Optional
from services.polymarket_api import PolymarketAPI
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class StatsAggregator:
    def __init__(self):
        self.api = PolymarketAPI()
        self.db = SupabaseClient()
        self.scan_interval = 300  # 5 minutes
    
    def aggregate_stats(self):
        """Calculate and store market statistics"""
        try:
            logger.info("Starting stats aggregation...")
            
            markets = self.db.get_markets(limit=100)
            
            if not markets:
                logger.warning("No markets found for stats aggregation")
                return
            
            stats_count = 0
            
            for market in markets:
                try:
                    condition_id = market.get('condition_id')
                    if not condition_id:
                        continue
                    
                    # Get tokens
                    tokens = self.api.get_market_tokens(condition_id)
                    if not tokens:
                        continue
                    
                    # Get order book for first token
                    orderbook = self.api.get_orderbook(tokens[0])
                    if not orderbook:
                        continue
                    
                    # Calculate stats
                    stats = self._calculate_stats(market, orderbook)
                    if stats:
                        self.db.upsert_market_stats(condition_id, stats)
                        stats_count += 1
                    
                    # Small delay
                    time.sleep(0.3)
                    
                except Exception as e:
                    logger.error(f"Error aggregating stats for market {market.get('condition_id')}: {e}")
                    continue
            
            logger.info(f"Aggregated stats for {stats_count} markets")
            
        except Exception as e:
            logger.error(f"Error in stats aggregation: {e}", exc_info=True)
    
    def _calculate_stats(self, market: dict, orderbook: dict) -> Optional[dict]:
        """Calculate market statistics from order book"""
        try:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            if not bids or not asks:
                return None
            
            # Calculate spread
            best_bid = float(bids[0].get('price', 0) if isinstance(bids[0], dict) else bids[0])
            best_ask = float(asks[0].get('price', 0) if isinstance(asks[0], dict) else asks[0])
            
            if best_ask <= 0:
                return None
            
            spread_percentage = ((best_ask - best_bid) / best_ask) * 100
            
            # Calculate buy/sell pressure from order book depth
            total_bid_size = sum(float(bid.get('size', 0) if isinstance(bid, dict) else bid) for bid in bids[:10])
            total_ask_size = sum(float(ask.get('size', 0) if isinstance(ask, dict) else ask) for ask in asks[:10])
            
            total_size = total_bid_size + total_ask_size
            if total_size > 0:
                buy_pressure = total_bid_size / total_size
                sell_pressure = total_ask_size / total_size
            else:
                buy_pressure = 0.5
                sell_pressure = 0.5
            
            return {
                'spread_percentage': round(spread_percentage, 2),
                'buy_pressure': round(buy_pressure, 3),
                'sell_pressure': round(sell_pressure, 3)
            }
            
        except Exception as e:
            logger.error(f"Error calculating stats: {e}")
            return None
    
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
