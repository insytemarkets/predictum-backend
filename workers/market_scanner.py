"""
Market Scanner Worker
Fetches markets from Polymarket GAMMA API and stores in Supabase
"""
import time
import logging
from typing import Optional, List, Dict
from services.polymarket_api import PolymarketAPI
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MarketScanner:
    def __init__(self):
        self.api = PolymarketAPI()
        self.db = SupabaseClient()
        self.scan_interval = 30  # seconds
    
    def scan_markets(self):
        """Fetch and store markets with token IDs and initial prices"""
        try:
            logger.info("Starting market scan...")
            markets = self.api.get_markets(limit=200, active=True, closed=False)
            
            if not markets:
                logger.warning("No markets returned from API")
                return
            
            logger.info(f"Fetched {len(markets)} markets")
            
            stored_count = 0
            all_token_ids = []
            
            for market in markets:
                try:
                    # Transform market data
                    processed = self._process_market(market)
                    if processed:
                        condition_id = processed.get('condition_id')
                        if condition_id:
                            # Extract tokens directly from market data first
                            tokens = self._extract_tokens_from_market(market)
                            
                            # If not found, try API call
                            if not tokens:
                                tokens = self.api.get_market_tokens(condition_id)
                            
                            if tokens:
                                processed['tokens'] = tokens
                                all_token_ids.extend(tokens)
                                
                                # Store tokens in raw_data for later use
                                if isinstance(processed.get('raw_data'), dict):
                                    processed['raw_data']['stored_tokens'] = tokens
                            
                            result = self.db.upsert_market(processed)
                            if result:
                                stored_count += 1
                                
                                # Fetch and store initial prices for tokens
                                if tokens:
                                    self._fetch_and_store_prices(condition_id, tokens)
                            
                except Exception as e:
                    logger.error(f"Error processing market {market.get('id', 'unknown')}: {e}", exc_info=True)
                    continue
            
            logger.info(f"Stored {stored_count} markets with {len(set(all_token_ids))} unique tokens")
            
        except Exception as e:
            logger.error(f"Error in market scan: {e}", exc_info=True)
    
    def _extract_tokens_from_market(self, market: dict) -> List[str]:
        """Extract token IDs directly from market data structure"""
        tokens = []
        
        if not isinstance(market, dict):
            return tokens
        
        # PRIORITY: Check for clobTokenIds (GAMMA API format)
        # This is the primary field for token IDs in the GAMMA API response
        if 'clobTokenIds' in market and isinstance(market['clobTokenIds'], list):
            for token_id in market['clobTokenIds']:
                if token_id:
                    tokens.append(str(token_id))
            if tokens:
                logger.debug(f"Found {len(tokens)} tokens in clobTokenIds")
                return list(set(tokens))
        
        # Also check raw_data for clobTokenIds
        raw_data = market.get('raw_data', {})
        if isinstance(raw_data, dict) and 'clobTokenIds' in raw_data:
            for token_id in raw_data['clobTokenIds']:
                if token_id:
                    tokens.append(str(token_id))
            if tokens:
                logger.debug(f"Found {len(tokens)} tokens in raw_data.clobTokenIds")
                return list(set(tokens))
        
        # Check for tokens array in various locations
        if 'tokens' in market and isinstance(market['tokens'], list):
            for token in market['tokens']:
                if isinstance(token, dict):
                    # Try various token ID fields
                    token_id = (
                        token.get('token_id') or 
                        token.get('tokenId') or
                        token.get('id') or 
                        token.get('address') or
                        token.get('asset_id') or
                        token.get('assetId')
                    )
                    if token_id:
                        tokens.append(str(token_id))
                elif isinstance(token, str):
                    tokens.append(token)
        
        # Check outcomes array
        if 'outcomes' in market and isinstance(market['outcomes'], list):
            for outcome in market['outcomes']:
                if isinstance(outcome, dict):
                    token_id = (
                        outcome.get('token_id') or 
                        outcome.get('tokenId') or
                        outcome.get('id') or 
                        outcome.get('address') or
                        outcome.get('asset_id')
                    )
                    if token_id:
                        tokens.append(str(token_id))
        
        # Check tokenIds array
        if 'tokenIds' in market and isinstance(market['tokenIds'], list):
            for token_id in market['tokenIds']:
                if token_id:
                    tokens.append(str(token_id))
        
        # Check event nested structure
        if 'event' in market and isinstance(market['event'], dict):
            event = market['event']
            if 'tokens' in event:
                for token in event['tokens']:
                    if isinstance(token, dict):
                        token_id = token.get('token_id') or token.get('id')
                        if token_id:
                            tokens.append(str(token_id))
                    elif isinstance(token, str):
                        tokens.append(token)
        
        return list(set(tokens))  # Remove duplicates
    
    def _fetch_and_store_prices(self, condition_id: str, tokens: List[str]):
        """Fetch current prices for tokens and store in prices table"""
        try:
            if not tokens:
                return
                
            # Fetch prices in batch
            prices = self.api.get_prices_batch(tokens)
            
            if prices:
                # Store prices with outcome_index (0=YES, 1=NO typically)
                for idx, token_id in enumerate(tokens):
                    if token_id in prices:
                        price = prices[token_id]
                        self.db.insert_price(condition_id, idx, price)
            
        except Exception as e:
            logger.error(f"Error fetching/storing prices for {condition_id}: {e}", exc_info=True)
    
    def _process_market(self, market: dict) -> Optional[dict]:
        """Process raw market data into our schema"""
        try:
            # Extract condition_id (try multiple possible fields)
            condition_id = (
                market.get('conditionId') or
                market.get('condition_id') or 
                market.get('id') or 
                market.get('event', {}).get('conditionId') or
                market.get('event', {}).get('condition_id')
            )
            
            if not condition_id:
                logger.warning(f"Market missing condition_id: {market.keys()}")
                return None
            
            # Extract question
            question = (
                market.get('question') or 
                market.get('title') or
                market.get('event', {}).get('question', '') or
                market.get('name', '')
            )
            
            if not question:
                question = f"Market {condition_id}"
            
            # Extract slug
            slug = (
                market.get('slug') or 
                market.get('event', {}).get('slug') or
                market.get('id') or
                condition_id
            )
            
            # Extract volume and liquidity (try multiple field names)
            volume_24h = float(
                market.get('volume24hr') or
                market.get('volume_24h') or
                market.get('volume24h') or
                market.get('volume') or
                market.get('volumeUSD') or
                0
            )
            
            liquidity = float(
                market.get('liquidity') or
                market.get('liquidityUSD') or
                market.get('totalLiquidity') or
                0
            )
            
            # Extract end date (try multiple formats)
            end_date = (
                market.get('endDate') or
                market.get('end_date') or
                market.get('end_date_iso') or
                market.get('endDateISO') or
                market.get('event', {}).get('endDate') or
                market.get('event', {}).get('end_date_iso')
            )
            
            # Extract additional useful data
            tokens = market.get('tokens') or market.get('tokenIds') or []
            outcomes = market.get('outcomes') or []
            
            # Store tokens in raw_data for later extraction
            market_data = {
                'condition_id': str(condition_id),
                'question': str(question),
                'slug': str(slug),
                'url': f"https://polymarket.com/event/{slug}",
                'end_date': end_date,
                'volume_24h': volume_24h,
                'liquidity': liquidity,
                'raw_data': market
            }
            
            # Tokens will be added in scan_markets() after fetching
            return market_data
        except Exception as e:
            logger.error(f"Error processing market: {e}", exc_info=True)
            return None
    
    def run(self):
        """Main worker loop"""
        logger.info("Market Scanner Worker started")
        while True:
            try:
                self.scan_markets()
            except Exception as e:
                logger.error(f"Fatal error in market scanner: {e}", exc_info=True)
            
            logger.info(f"Sleeping for {self.scan_interval} seconds...")
            time.sleep(self.scan_interval)

if __name__ == "__main__":
    scanner = MarketScanner()
    scanner.run()
