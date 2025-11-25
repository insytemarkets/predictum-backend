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
        params = {
            'limit': limit,
            'active': str(active).lower(),
            'closed': str(closed).lower()
        }
        data = self._get_gamma('/events', params)
        if data and isinstance(data, list):
            return data
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
        return self._get_clob(f'/book', params={'token': token_id})
    
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
        # This might need to be constructed from market data
        # For now, we'll extract from market data structure
        market = self.get_market_by_slug(condition_id)
        if not market:
            return None
        
        tokens = []
        if 'tokens' in market:
            tokens = [token.get('token_id') for token in market['tokens'] if token.get('token_id')]
        return tokens if tokens else None
