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
        """Fetch order books for active markets using batch API when possible"""
        try:
            logger.info("Starting order book scan...")
            
            # Get active markets from database
            markets = self.db.get_markets(limit=50)
            
            if not markets:
                logger.warning("No markets found in database")
                return
            
            logger.info(f"Scanning order books for {len(markets)} markets")
            
            # Collect all tokens for batch fetching
            market_tokens_map = {}  # {condition_id: [tokens]}
            all_tokens = []
            
            for market in markets:
                condition_id = market.get('condition_id')
                if not condition_id:
                    continue
                
                # Get tokens for this market (prefer stored tokens)
                tokens = market.get('tokens') or []
                if not tokens:
                    # Try to extract from raw_data
                    raw_data = market.get('raw_data', {})
                    if isinstance(raw_data, dict):
                        if 'stored_tokens' in raw_data:
                            tokens = raw_data['stored_tokens']
                        elif 'tokens' in raw_data:
                            tokens = raw_data['tokens']
                        else:
                            tokens = self._extract_tokens(raw_data)
                    # Fallback to API call
                    if not tokens:
                        tokens = self.api.get_market_tokens(condition_id)
                
                if tokens:
                    market_tokens_map[condition_id] = tokens
                    all_tokens.extend(tokens[:1])  # Use first token (YES) for now
            
            if not all_tokens:
                logger.warning("No tokens found for any markets")
                return
            
            # Batch fetch order books
            logger.info(f"Batch fetching {len(all_tokens)} order books...")
            orderbooks = self.api.get_orderbooks_batch(all_tokens)
            
            scanned_count = 0
            token_to_market = {}
            for condition_id, tokens in market_tokens_map.items():
                if tokens:
                    token_to_market[tokens[0]] = condition_id
            
            # Process batch results - match by index since order should match
            for idx, orderbook in enumerate(orderbooks):
                try:
                    # Match orderbook to market by index (order should match)
                    if idx < len(all_tokens):
                        token_id = all_tokens[idx]
                        condition_id = token_to_market.get(token_id)
                        
                        # Fallback: try matching by asset_id or market field
                        if not condition_id:
                            asset_id = orderbook.get('asset_id')
                            market_id = orderbook.get('market')
                            for tid, cid in token_to_market.items():
                                if str(tid) == str(asset_id) or str(tid) == str(market_id):
                                    condition_id = cid
                                    break
                    
                    if not condition_id:
                        continue
                    
                    bids = orderbook.get('bids', [])
                    asks = orderbook.get('asks', [])
                    
                    if bids or asks:
                        metadata = {
                            'min_order_size': orderbook.get('min_order_size'),
                            'tick_size': orderbook.get('tick_size'),
                            'neg_risk': orderbook.get('neg_risk', False),
                            'timestamp': orderbook.get('timestamp')
                        }
                        self.db.insert_orderbook(condition_id, bids, asks, metadata)
                        scanned_count += 1
                        
                except Exception as e:
                    logger.error(f"Error processing batch orderbook: {e}")
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
