"""
Market Scanner v2.0
Fetches ALL the rich market data from Polymarket and stores it
"""
import logging
import time
from typing import Dict, List, Any

from services.polymarket_api import PolymarketAPI
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MarketScanner:
    """
    Scans Polymarket for markets and stores rich data
    """
    
    def __init__(self):
        self.api = PolymarketAPI()
        self.db = SupabaseClient()
        self.scan_interval = 60  # seconds
    
    def scan_markets(self) -> int:
        """
        Scan all active markets and store rich data
        Returns number of markets processed
        """
        logger.info("Starting market scan with rich data extraction...")
        
        try:
            # Fetch markets with ALL the data
            markets = self.api.get_markets(limit=500)
            
            if not markets:
                logger.warning("No markets returned from API")
                return 0
            
            logger.info(f"Fetched {len(markets)} markets with rich data")
            
            # Process and store each market
            stored_count = 0
            neg_risk_count = 0
            high_volume_count = 0
            
            for market in markets:
                try:
                    # Transform to DB schema
                    db_market = self._transform_market(market)
                    
                    if db_market:
                        self.db.upsert_market(db_market)
                        stored_count += 1
                        
                        # Track interesting markets
                        if market.get('neg_risk'):
                            neg_risk_count += 1
                        if market.get('volume_24h', 0) > 100000:
                            high_volume_count += 1
                
                except Exception as e:
                    logger.error(f"Error storing market {market.get('condition_id')}: {e}")
            
            logger.info(f"Stored {stored_count} markets")
            logger.info(f"  - {neg_risk_count} with negative risk (arb potential)")
            logger.info(f"  - {high_volume_count} with >$100K 24h volume")
            
            # Log top movers
            self._log_top_movers(markets)
            
            return stored_count
            
        except Exception as e:
            logger.error(f"Error in market scan: {e}", exc_info=True)
            return 0
    
    def _transform_market(self, market: Dict) -> Dict:
        """Transform API market data to DB schema"""
        condition_id = market.get('condition_id')
        if not condition_id:
            return None
        
        # Extract token IDs as JSON string for storage
        clob_tokens = market.get('clob_token_ids', [])
        tokens_json = clob_tokens if isinstance(clob_tokens, list) else []
        
        return {
            'condition_id': condition_id,
            'question': market.get('question', ''),
            'slug': market.get('slug', ''),
            'description': market.get('description', ''),
            
            # Volume metrics
            'volume_24h': market.get('volume_24h', 0),
            'volume_7d': market.get('volume_7d', 0),
            'volume_30d': market.get('volume_30d', 0),
            'volume_velocity': market.get('volume_velocity', 1.0),
            'liquidity': market.get('liquidity', 0),
            
            # Price data
            'current_price': market.get('current_price', 0.5),
            'price_change_24h': market.get('price_change_24h', 0),
            'price_change_7d': market.get('price_change_7d', 0),
            'price_change_30d': market.get('price_change_30d', 0),
            'last_trade_price': market.get('last_trade_price'),
            
            # Orderbook data
            'best_bid': market.get('best_bid'),
            'best_ask': market.get('best_ask'),
            'spread': market.get('spread', 0),
            
            # Alpha signals
            'neg_risk': market.get('neg_risk', False),
            'neg_risk_market_id': market.get('neg_risk_market_id'),
            'competitive_score': market.get('competitive_score', 0),
            'accepting_orders': market.get('accepting_orders', True),
            
            # Rewards
            'has_rewards': market.get('has_rewards', False),
            'rewards_daily_rate': market.get('rewards_daily_rate', 0),
            'rewards_min_size': market.get('rewards_min_size'),
            'rewards_max_spread': market.get('rewards_max_spread'),
            
            # Metadata
            'category': market.get('category', ''),
            'image_url': market.get('image_url', ''),
            'end_date': market.get('end_date'),
            'active': market.get('active', True),
            'closed': market.get('closed', False),
            
            # Token data
            'tokens': tokens_json,
            'outcomes': market.get('outcomes', []),
            'outcome_prices': market.get('outcome_prices', []),
            
            # Raw data for debugging
            'raw_data': market.get('raw_data', {})
        }
    
    def _log_top_movers(self, markets: List[Dict]):
        """Log the top movers for monitoring"""
        # Top by 24h price change
        by_change = sorted(
            [m for m in markets if m.get('price_change_24h')],
            key=lambda x: abs(x.get('price_change_24h', 0)),
            reverse=True
        )[:5]
        
        if by_change:
            logger.info("Top 24h movers:")
            for m in by_change:
                change = m.get('price_change_24h', 0) * 100
                logger.info(f"  {change:+.1f}% | {m.get('question', '')[:50]}")
        
        # Top by volume velocity
        by_velocity = sorted(
            [m for m in markets if m.get('volume_velocity', 1) > 2],
            key=lambda x: x.get('volume_velocity', 1),
            reverse=True
        )[:5]
        
        if by_velocity:
            logger.info("High volume velocity (>2x normal):")
            for m in by_velocity:
                vel = m.get('volume_velocity', 1)
                logger.info(f"  {vel:.1f}x | {m.get('question', '')[:50]}")
    
    def run(self):
        """Main worker loop"""
        logger.info("Market Scanner v2.0 started")
        
        while True:
            try:
                count = self.scan_markets()
                logger.info(f"Scan complete: {count} markets processed")
            except Exception as e:
                logger.error(f"Fatal error in scan: {e}", exc_info=True)
            
            logger.info(f"Sleeping {self.scan_interval}s...")
            time.sleep(self.scan_interval)


if __name__ == "__main__":
    scanner = MarketScanner()
    scanner.run()
