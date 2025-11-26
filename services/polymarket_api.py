"""
Polymarket API Client
Supports both GAMMA API and CLOB API with rate limiting
"""
import requests
import logging
import sys
import os
from typing import Dict, List, Optional, Any

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

class PolymarketAPI:
    """Client for Polymarket APIs with rate limiting"""
    
    def __init__(self):
        self.gamma_base = "https://gamma-api.polymarket.com"
        self.clob_base = "https://clob.polymarket.com"
        self.data_api_base = "https://data-api.polymarket.com"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Predictum/1.0',
            'Accept': 'application/json'
        })
    
    def _get_gamma(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make a GET request to GAMMA API with rate limiting"""
        rate_limiter.wait_gamma()
        url = f"{self.gamma_base}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"GAMMA API error ({endpoint}): {e}")
            return None
    
    def _get_clob(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make a GET request to CLOB API with rate limiting"""
        rate_limiter.wait_clob()
        url = f"{self.clob_base}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"CLOB API error ({endpoint}): {e}")
            return None
    
    def get_markets(self, limit: int = 100, active: bool = True, closed: bool = False) -> List[Dict]:
        """
        Fetch markets from Polymarket API
        Tries multiple endpoints: /events, /markets, data-api
        """
        # Try GAMMA API /events endpoint first
        data = self._get_gamma('/events')
        
        if data:
            if isinstance(data, list):
                # Filter active markets if needed
                if active:
                    filtered = [m for m in data if m.get('active', True) and not m.get('closed', False)]
                    return filtered[:limit]
                return data[:limit]
            # Sometimes API returns dict with 'data' key
            if isinstance(data, dict):
                if 'data' in data:
                    markets = data['data'] if isinstance(data['data'], list) else []
                elif 'events' in data:
                    markets = data['events'] if isinstance(data['events'], list) else []
                elif 'results' in data:
                    markets = data['results'] if isinstance(data['results'], list) else []
                else:
                    markets = []
                
                if active and markets:
                    filtered = [m for m in markets if m.get('active', True) and not m.get('closed', False)]
                    return filtered[:limit]
                return markets[:limit]
        
        # Fallback: Try /markets endpoint
        logger.info("Trying /markets endpoint as fallback...")
        data = self._get_gamma('/markets')
        if data:
            if isinstance(data, list):
                return data[:limit]
            if isinstance(data, dict) and 'data' in data:
                return data['data'][:limit] if isinstance(data['data'], list) else []
        
        # Fallback: Try data-api endpoint
        logger.info("Trying data-api endpoint as fallback...")
        try:
            rate_limiter.wait_gamma()  # Use same rate limiter
            response = self.session.get(f"{self.data_api_base}/markets", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data[:limit]
                if isinstance(data, dict) and 'data' in data:
                    return data['data'][:limit] if isinstance(data['data'], list) else []
        except Exception as e:
            logger.error(f"Data-API error: {e}")
        
        logger.warning("All market endpoints returned no data")
        return []
    
    def get_market_by_slug(self, slug: str) -> Optional[Dict]:
        """Get a specific market by slug"""
        return self._get_gamma(f'/events/{slug}')
    
    def get_market_prices(self, condition_id: str) -> Optional[Dict]:
        """Get current prices for a market condition from GAMMA API"""
        return self._get_gamma(f'/prices/{condition_id}')
    
    def get_price(self, token_id: str, side: str = 'BUY') -> Optional[float]:
        """
        Get current price for a token from CLOB API
        Per docs: https://docs.polymarket.com/api-reference/pricing/get-market-price
        """
        params = {'token_id': token_id, 'side': side}
        data = self._get_clob('/price', params=params)
        
        if data and isinstance(data, dict):
            price = data.get('price') or data.get('value')
            if price:
                return float(price) if isinstance(price, (int, float)) else float(str(price))
        return None
    
    def get_prices_batch(self, token_ids: List[str]) -> Dict[str, float]:
        """
        Get prices for multiple tokens using POST /prices endpoint
        Per docs: https://docs.polymarket.com/api-reference/pricing/get-multiple-market-prices-by-request
        """
        if not token_ids:
            return {}
        
        payload = [{'token_id': token_id} for token_id in token_ids[:500]]  # Max 500
        
        data = self._post_clob('/prices', json_data=payload)
        
        prices = {}
        if isinstance(data, list):
            for item in data:
                token_id = item.get('token_id') or item.get('tokenId')
                price = item.get('price') or item.get('value')
                if token_id and price:
                    prices[token_id] = float(price) if isinstance(price, (int, float)) else float(str(price))
        
        return prices
    
    def get_midpoint_price(self, token_id: str) -> Optional[float]:
        """
        Get midpoint price for a token from CLOB API
        Per docs: https://docs.polymarket.com/api-reference/pricing/get-midpoint-price
        """
        params = {'token_id': token_id}
        data = self._get_clob('/midpoint', params=params)
        
        if data and isinstance(data, dict):
            midpoint = data.get('midpoint') or data.get('price') or data.get('value')
            if midpoint:
                return float(midpoint) if isinstance(midpoint, (int, float)) else float(str(midpoint))
        return None
    
    def get_bid_ask_spreads(self, token_ids: List[str]) -> Dict[str, Dict]:
        """
        Get bid-ask spreads for multiple tokens
        Per docs: https://docs.polymarket.com/api-reference/spreads/get-bid-ask-spreads
        """
        if not token_ids:
            return {}
        
        # Build query string with token_ids
        token_params = '&'.join([f'token_ids={token_id}' for token_id in token_ids[:100]])  # Reasonable limit
        endpoint = f'/spreads?{token_params}'
        
        rate_limiter.wait_clob()
        url = f"{self.clob_base}{endpoint}"
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            spreads = {}
            if isinstance(data, dict):
                # Response might be {token_id: {bid: X, ask: Y, spread: Z}}
                for token_id, spread_data in data.items():
                    if isinstance(spread_data, dict):
                        spreads[token_id] = {
                            'bid': float(spread_data.get('bid', 0)),
                            'ask': float(spread_data.get('ask', 0)),
                            'spread': float(spread_data.get('spread', 0)),
                            'spread_percent': float(spread_data.get('spread_percent', 0))
                        }
            elif isinstance(data, list):
                # Response might be list of {token_id, bid, ask, spread}
                for item in data:
                    token_id = item.get('token_id') or item.get('tokenId')
                    if token_id:
                        spreads[token_id] = {
                            'bid': float(item.get('bid', 0)),
                            'ask': float(item.get('ask', 0)),
                            'spread': float(item.get('spread', 0)),
                            'spread_percent': float(item.get('spread_percent', 0))
                        }
            
            return spreads
        except requests.exceptions.RequestException as e:
            logger.error(f"CLOB API spreads error (/spreads): {e}")
            return {}
    
    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """
        Get order book for a token from CLOB API
        Returns bids and asks with parsed prices/sizes
        Per docs: https://docs.polymarket.com/api-reference/orderbook/get-order-book-summary
        """
        # Correct endpoint format: /book?token_id=<TOKEN_ID>
        params = {'token_id': token_id}
        data = self._get_clob('/book', params=params)
        
        if data and isinstance(data, dict):
            # Parse string prices/sizes to floats for easier use
            if 'bids' in data and isinstance(data['bids'], list):
                data['bids'] = [
                    {
                        'price': float(bid.get('price', 0)) if isinstance(bid, dict) else float(bid[0]) if isinstance(bid, list) else 0,
                        'size': float(bid.get('size', 0)) if isinstance(bid, dict) else float(bid[1]) if isinstance(bid, list) else 0
                    }
                    for bid in data['bids']
                ]
            
            if 'asks' in data and isinstance(data['asks'], list):
                data['asks'] = [
                    {
                        'price': float(ask.get('price', 0)) if isinstance(ask, dict) else float(ask[0]) if isinstance(ask, list) else 0,
                        'size': float(ask.get('size', 0)) if isinstance(ask, dict) else float(ask[1]) if isinstance(ask, list) else 0
                    }
                    for ask in data['asks']
                ]
            
            return data
        
        return None
    
    def get_orderbooks_batch(self, token_ids: List[str]) -> List[Dict]:
        """
        Get multiple order books using POST /books endpoint
        Per docs: https://docs.polymarket.com/api-reference/orderbook/get-multiple-order-books-summaries-by-request
        """
        if not token_ids:
            return []
        
        # Prepare request body
        payload = [{'token_id': token_id} for token_id in token_ids[:500]]  # Max 500 per docs
        
        data = self._post_clob('/books', json_data=payload)
        
        if isinstance(data, list):
            # Parse prices/sizes for each order book
            for orderbook in data:
                if 'bids' in orderbook and isinstance(orderbook['bids'], list):
                    orderbook['bids'] = [
                        {
                            'price': float(bid.get('price', 0)) if isinstance(bid, dict) else 0,
                            'size': float(bid.get('size', 0)) if isinstance(bid, dict) else 0
                        }
                        for bid in orderbook['bids']
                    ]
                if 'asks' in orderbook and isinstance(orderbook['asks'], list):
                    orderbook['asks'] = [
                        {
                            'price': float(ask.get('price', 0)) if isinstance(ask, dict) else 0,
                            'size': float(ask.get('size', 0)) if isinstance(ask, dict) else 0
                        }
                        for ask in orderbook['asks']
                    ]
            return data
        
        return []
    
    def get_trades(self, token_id: str, limit: int = 100) -> List[Dict]:
        """Get recent trades for a token"""
        data = self._get_clob(f'/trades', params={'token': token_id, 'limit': limit})
        if data and isinstance(data, list):
            return data
        return []
    
    def get_market_tokens(self, condition_id: str) -> Optional[List[str]]:
        """
        Get token IDs for a market condition
        Returns list of token addresses for YES/NO outcomes
        Enhanced to check multiple possible locations
        """
        # Try to get market details
        market = self.get_market_by_slug(condition_id)
        if not market:
            # Try with condition_id directly
            market = self._get_gamma(f'/events/{condition_id}')
        
        if not market:
            return None
        
        tokens = []
        
        def extract_token_id(obj):
            """Helper to extract token ID from various formats"""
            if isinstance(obj, str):
                return obj
            if isinstance(obj, dict):
                return (
                    obj.get('token_id') or 
                    obj.get('tokenId') or
                    obj.get('id') or 
                    obj.get('address') or
                    obj.get('asset_id') or
                    obj.get('assetId')
                )
            return None
        
        if isinstance(market, dict):
            # Check for tokens array (most common)
            if 'tokens' in market:
                for token in market['tokens']:
                    token_id = extract_token_id(token)
                    if token_id:
                        tokens.append(str(token_id))
            
            # Check for outcomes array
            if 'outcomes' in market:
                for outcome in market['outcomes']:
                    token_id = extract_token_id(outcome)
                    if token_id:
                        tokens.append(str(token_id))
            
            # Check for asset_id (single token markets)
            if 'asset_id' in market or 'assetId' in market:
                asset_id = market.get('asset_id') or market.get('assetId')
                if asset_id:
                    tokens.append(str(asset_id))
            
            # Check raw_data if present
            if 'raw_data' in market and isinstance(market['raw_data'], dict):
                raw = market['raw_data']
                if 'tokens' in raw:
                    for token in raw['tokens']:
                        token_id = extract_token_id(token)
                        if token_id:
                            tokens.append(str(token_id))
                if 'outcomes' in raw:
                    for outcome in raw['outcomes']:
                        token_id = extract_token_id(outcome)
                        if token_id:
                            tokens.append(str(token_id))
            
            # Check event nested structure
            if 'event' in market and isinstance(market['event'], dict):
                event = market['event']
                if 'tokens' in event:
                    for token in event['tokens']:
                        token_id = extract_token_id(token)
                        if token_id:
                            tokens.append(str(token_id))
        
        # Remove duplicates and return
        unique_tokens = list(set(tokens))
        return unique_tokens if unique_tokens else None
    
    def get_market_details(self, condition_id: str) -> Optional[Dict]:
        """Get full market details including tokens and prices"""
        market = self.get_market_by_slug(condition_id)
        if not market:
            market = self._get_gamma(f'/events/{condition_id}')
        
        if market:
            # Get prices
            prices = self.get_market_prices(condition_id)
            if prices:
                market['prices'] = prices
            
            # Get tokens
            tokens = self.get_market_tokens(condition_id)
            if tokens:
                market['token_ids'] = tokens
        
        return market
