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
        Fetch markets from GAMMA API
        Returns list of market events
        """
        # Polymarket GAMMA API uses /events endpoint
        # Try different parameter formats
        params = {
            'limit': limit,
            'active': str(active).lower(),
            'closed': str(closed).lower(),
            'sort': 'volume',
            'order': 'desc'
        }
        
        data = self._get_gamma('/events', params)
        
        if data:
            if isinstance(data, list):
                return data
            # Sometimes API returns dict with 'data' key
            if isinstance(data, dict):
                if 'data' in data:
                    return data['data'] if isinstance(data['data'], list) else []
                if 'events' in data:
                    return data['events'] if isinstance(data['events'], list) else []
                if 'results' in data:
                    return data['results'] if isinstance(data['results'], list) else []
        
        # Fallback: try without params
        logger.warning("Failed to fetch with params, trying without...")
        data = self._get_gamma('/events')
        if data and isinstance(data, list):
            return data[:limit]
        
        return []
    
    def get_market_by_slug(self, slug: str) -> Optional[Dict]:
        """Get a specific market by slug"""
        return self._get_gamma(f'/events/{slug}')
    
    def get_market_prices(self, condition_id: str) -> Optional[Dict]:
        """Get current prices for a market condition"""
        return self._get_gamma(f'/prices/{condition_id}')
    
    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """
        Get order book for a token from CLOB API
        Returns bids and asks
        """
        # CLOB API uses /book endpoint
        # Try different parameter formats
        params = {'token': token_id}
        data = self._get_clob('/book', params=params)
        
        if data:
            if isinstance(data, dict):
                # Standard format: {'bids': [...], 'asks': [...]}
                if 'bids' in data and 'asks' in data:
                    return data
                # Alternative format: {'data': {'bids': [...], 'asks': [...]}}
                if 'data' in data and isinstance(data['data'], dict):
                    return data['data']
        
        # Try alternative endpoint format
        data = self._get_clob(f'/book/{token_id}')
        if data and isinstance(data, dict):
            return data
        
        return None
    
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
        """
        # Try to get market details
        market = self.get_market_by_slug(condition_id)
        if not market:
            # Try with condition_id directly
            market = self._get_gamma(f'/events/{condition_id}')
        
        if not market:
            return None
        
        tokens = []
        # Extract tokens from various possible structures
        if isinstance(market, dict):
            # Check for tokens array
            if 'tokens' in market:
                for token in market['tokens']:
                    if isinstance(token, dict):
                        token_id = token.get('token_id') or token.get('id') or token.get('address')
                        if token_id:
                            tokens.append(token_id)
                    elif isinstance(token, str):
                        tokens.append(token)
            
            # Check for outcomes array
            if 'outcomes' in market:
                for outcome in market['outcomes']:
                    if isinstance(outcome, dict):
                        token_id = outcome.get('token_id') or outcome.get('id') or outcome.get('address')
                        if token_id:
                            tokens.append(token_id)
            
            # Check raw_data if present
            if 'raw_data' in market and isinstance(market['raw_data'], dict):
                raw = market['raw_data']
                if 'tokens' in raw:
                    for token in raw['tokens']:
                        if isinstance(token, dict):
                            token_id = token.get('token_id') or token.get('id')
                            if token_id:
                                tokens.append(token_id)
        
        return tokens if tokens else None
    
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
