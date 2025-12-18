"""
Price History Worker
Tracks price changes over time for charts and ticker display
"""
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from services.polymarket_api import PolymarketAPI
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PriceHistoryWorker:
    def __init__(self):
        self.api = PolymarketAPI()
        self.db = SupabaseClient()
        self.scan_interval = 300  # 5 minutes
    
    def _parse_clob_token_ids(self, clob_ids) -> list:
        """Parse clobTokenIds which can be a list or a JSON string"""
        import json
        if isinstance(clob_ids, list):
            return [str(t) for t in clob_ids if t]
        elif isinstance(clob_ids, str):
            try:
                parsed = json.loads(clob_ids)
                if isinstance(parsed, list):
                    return [str(t) for t in parsed if t]
            except (json.JSONDecodeError, ValueError):
                pass
        return []
    
    def update_prices(self):
        """Fetch current prices and calculate price changes"""
        try:
            logger.info("Starting price history update...")
            
            # Get active markets
            markets = self.db.get_markets(limit=100)
            
            if not markets:
                logger.warning("No markets found for price update")
                return
            
            updated_count = 0
            
            # Collect all tokens for batch fetching
            market_tokens_map = {}  # {condition_id: [tokens]}
            all_tokens = []
            
            for market in markets:
                condition_id = market.get('condition_id')
                if not condition_id:
                    continue
                
                # Get tokens
                tokens = market.get('tokens') or []
                if not tokens:
                    # Try to extract from raw_data
                    raw_data = market.get('raw_data', {})
                    if isinstance(raw_data, dict):
                        # Check for clobTokenIds first (GAMMA API format) - can be list or JSON string
                        tokens = self._parse_clob_token_ids(raw_data.get('clobTokenIds'))
                        if not tokens and 'tokens' in raw_data:
                            tokens = raw_data['tokens']
                    
                    if not tokens:
                        tokens = self.api.get_market_tokens(condition_id)
                
                if tokens:
                    market_tokens_map[condition_id] = tokens
                    all_tokens.extend(tokens)
            
            if not all_tokens:
                logger.warning("No tokens found for price update")
                return
            
            # Batch fetch current prices
            logger.info(f"Fetching prices for {len(all_tokens)} tokens...")
            current_prices = self.api.get_prices_batch(all_tokens)
            
            # Get price history for comparison
            price_history = {}
            for condition_id in market_tokens_map.keys():
                history = self.db.get_price_history(condition_id, hours=24)
                if history:
                    price_history[condition_id] = history
            
            # Update prices and calculate changes
            for condition_id, tokens in market_tokens_map.items():
                try:
                    # Get current prices for this market's tokens
                    token_prices = {}
                    for token in tokens:
                        if token in current_prices:
                            price_data = current_prices[token]
                            # Handle dict format {buy: x, sell: y, mid: z}
                            if isinstance(price_data, dict):
                                # Use mid price, or average of buy/sell
                                if 'mid' in price_data:
                                    token_prices[token] = float(price_data['mid'])
                                elif 'buy' in price_data and 'sell' in price_data:
                                    token_prices[token] = (float(price_data['buy']) + float(price_data['sell'])) / 2
                                elif 'buy' in price_data:
                                    token_prices[token] = float(price_data['buy'])
                                else:
                                    token_prices[token] = 0.5
                            else:
                                token_prices[token] = float(price_data) if price_data else 0.5
                    
                    if not token_prices:
                        continue
                    
                    # Store current prices
                    for idx, token in enumerate(tokens):
                        if token in token_prices:
                            price_val = token_prices[token]
                            if isinstance(price_val, (int, float)):
                                self.db.insert_price(condition_id, idx, price_val)
                    
                    # Calculate price changes
                    current_price = token_prices.get(tokens[0], 0.5) if tokens else 0.5  # Use YES token
                    
                    # Get price from 24h ago
                    price_24h_ago = None
                    if condition_id in price_history:
                        history = price_history[condition_id]
                        # Find price closest to 24h ago
                        cutoff = datetime.utcnow() - timedelta(hours=24)
                        for price_point in sorted(history, key=lambda x: x.get('timestamp', ''), reverse=True):
                            try:
                                price_time_str = price_point.get('timestamp', '')
                                if not price_time_str:
                                    continue
                                # Handle different timestamp formats
                                if 'T' in price_time_str:
                                    price_time = datetime.fromisoformat(price_time_str.replace('Z', '+00:00'))
                                else:
                                    continue
                                if price_time <= cutoff:
                                    price_24h_ago = float(price_point.get('price', 0))
                                    break
                            except Exception as e:
                                logger.debug(f"Error parsing timestamp: {e}")
                                continue
                    
                    # Calculate change
                    price_change_24h = 0
                    
                    if price_24h_ago and current_price and price_24h_ago > 0:
                        price_change_24h = (current_price - price_24h_ago) / price_24h_ago
                    
                    # Update market with current_price directly using upsert_market
                    self.db.upsert_market({
                        'condition_id': condition_id,
                        'current_price': current_price,
                        'price_change_24h': price_change_24h
                    })
                    
                    updated_count += 1
                    
                except Exception as e:
                    logger.error(f"Error updating prices for {condition_id}: {e}")
                    continue
            
            logger.info(f"Updated prices for {updated_count} markets")
            
        except Exception as e:
            logger.error(f"Error in price history update: {e}", exc_info=True)
    
    def run(self):
        """Main worker loop"""
        logger.info("Price History Worker started")
        while True:
            try:
                self.update_prices()
            except Exception as e:
                logger.error(f"Fatal error in price history worker: {e}", exc_info=True)
            
            logger.info(f"Sleeping for {self.scan_interval} seconds...")
            time.sleep(self.scan_interval)

if __name__ == "__main__":
    worker = PriceHistoryWorker()
    worker.run()

