"""
Order Book Scanner Worker
Fetches order books from CLOB API and stores in Supabase
"""
import time
import logging
from services.polymarket_api import PolymarketAPI
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OrderBookScanner:
    def __init__(self):
        self.api = PolymarketAPI()
        self.db = SupabaseClient()
        self.scan_interval = 10  # seconds
    
    def scan_orderbooks(self):
        """Fetch order books for active markets"""
        try:
            logger.info("Starting order book scan...")
            
            # Get active markets from database
            markets = self.db.get_markets(limit=50)
            
            if not markets:
                logger.warning("No markets found in database")
                return
            
            logger.info(f"Scanning order books for {len(markets)} markets")
            
            scanned_count = 0
            
            for market in markets:
                try:
                    condition_id = market.get('condition_id')
                    if not condition_id:
                        continue
                    
                    # Get tokens for this market
                    tokens = self.api.get_market_tokens(condition_id)
                    if not tokens:
                        # Try to extract from raw_data
                        raw_data = market.get('raw_data', {})
                        tokens = self._extract_tokens(raw_data)
                    
                    if not tokens:
                        logger.debug(f"No tokens found for market {condition_id}")
                        continue
                    
                    # Fetch order book for first token (typically YES outcome)
                    orderbook = self.api.get_orderbook(tokens[0])
                    if orderbook:
                        bids = orderbook.get('bids', [])
                        asks = orderbook.get('asks', [])
                        
                        if bids or asks:
                            self.db.insert_orderbook(condition_id, bids, asks)
                            scanned_count += 1
                    
                    # Small delay to respect rate limits
                    time.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"Error scanning orderbook for market {market.get('condition_id')}: {e}")
                    continue
            
            logger.info(f"Scanned {scanned_count} order books")
            
        except Exception as e:
            logger.error(f"Error in order book scan: {e}", exc_info=True)
    
    def _extract_tokens(self, raw_data: dict) -> list:
        """Extract token IDs from raw market data"""
        tokens = []
        
        if not isinstance(raw_data, dict):
            return tokens
        
        # Try different possible structures for tokens
        if 'tokens' in raw_data and isinstance(raw_data['tokens'], list):
            for token in raw_data['tokens']:
                if isinstance(token, dict):
                    token_id = token.get('token_id') or token.get('id') or token.get('address')
                    if token_id:
                        tokens.append(str(token_id))
                elif isinstance(token, str):
                    tokens.append(token)
        
        # Also check 'outcomes' array if present
        if 'outcomes' in raw_data and isinstance(raw_data['outcomes'], list):
            for outcome in raw_data['outcomes']:
                if isinstance(outcome, dict):
                    token_id = outcome.get('token_id') or outcome.get('id')
                    if token_id:
                        tokens.append(str(token_id))
        
        # Check tokenIds array
        if 'tokenIds' in raw_data and isinstance(raw_data['tokenIds'], list):
            for token_id in raw_data['tokenIds']:
                if token_id:
                    tokens.append(str(token_id))
        
        return list(set(tokens))  # Return unique tokens
    
    def run(self):
        """Main worker loop"""
        logger.info("Order Book Scanner Worker started")
        while True:
            try:
                self.scan_orderbooks()
            except Exception as e:
                logger.error(f"Fatal error in order book scanner: {e}", exc_info=True)
            
            logger.info(f"Sleeping for {self.scan_interval} seconds...")
            time.sleep(self.scan_interval)

if __name__ == "__main__":
    scanner = OrderBookScanner()
    scanner.run()
