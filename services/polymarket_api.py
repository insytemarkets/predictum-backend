"""
Polymarket API Client v2.0
Extracts ALL the rich data from GAMMA and CLOB APIs
"Everyone has access to the information. We just know how to analyze it better."

Rate limits (from https://docs.polymarket.com/quickstart/introduction/rate-limits):
- GAMMA /events: 100 requests / 10s
- GAMMA /markets: 125 requests / 10s
- CLOB /book: 200 requests / 10s
- CLOB /books (batch): 80 requests / 10s
- CLOB /price: 200 requests / 10s
- CLOB /spread: 200 requests / 10s
- CLOB Price History: 100 requests / 10s
"""
import requests
import logging
import sys
import os
import json
from typing import Dict, List, Optional, Any

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)


def parse_json_field(field: Any) -> Any:
    """Parse field that might be a JSON string or already parsed"""
    if field is None:
        return None
    if isinstance(field, (list, dict)):
        return field
    if isinstance(field, str):
        try:
            return json.loads(field)
        except (json.JSONDecodeError, ValueError):
            pass
    return field


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float"""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


class PolymarketAPI:
    """
    Enhanced Polymarket API Client
    Extracts EVERYTHING useful from the APIs
    """
    
    def __init__(self):
        self.gamma_base = "https://gamma-api.polymarket.com"
        self.clob_base = "https://clob.polymarket.com"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Predictum/2.0',
            'Accept': 'application/json'
        })
    
    def _get_gamma(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        """Make a GET request to GAMMA API with endpoint-specific rate limiting"""
        # Determine endpoint type for rate limiting
        if '/events' in endpoint:
            rate_limiter.wait_gamma("events")
        elif '/markets' in endpoint:
            rate_limiter.wait_gamma("markets")
        else:
            rate_limiter.wait_gamma("general")
        
        url = f"{self.gamma_base}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=15)
            if response.status_code == 422:
                logger.debug(f"GAMMA API 422 for {endpoint} - invalid params")
                return None
            if response.status_code == 429:
                logger.warning(f"GAMMA API rate limited on {endpoint} - backing off")
                return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"GAMMA API error ({endpoint}): {e}")
            return None
    
    def _get_clob(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        """Make a GET request to CLOB API with endpoint-specific rate limiting"""
        # Determine endpoint type for rate limiting
        if endpoint == '/book':
            rate_limiter.wait_clob("book")
        elif endpoint == '/price':
            rate_limiter.wait_clob("price")
        elif endpoint == '/spread':
            rate_limiter.wait_clob("spread")
        elif endpoint == '/midpoint':
            rate_limiter.wait_clob("midpoint")
        elif '/prices-history' in endpoint:
            rate_limiter.wait_clob("history")
        else:
            rate_limiter.wait_clob("general")
        
        url = f"{self.clob_base}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=15)
            if response.status_code == 429:
                logger.warning(f"CLOB API rate limited on {endpoint} - backing off")
                return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"CLOB API error ({endpoint}): {e}")
            return None
    
    def _post_clob(self, endpoint: str, json_data: Any) -> Optional[Any]:
        """Make a POST request to CLOB API with batch rate limiting"""
        # Batch endpoints have lower limits
        if endpoint == '/books':
            rate_limiter.wait_clob("books")
        elif endpoint == '/prices':
            rate_limiter.wait_clob("prices")
        else:
            rate_limiter.wait_clob("general")
        
        url = f"{self.clob_base}{endpoint}"
        try:
            response = self.session.post(url, json=json_data, timeout=15)
            if response.status_code == 429:
                logger.warning(f"CLOB API rate limited on {endpoint} - backing off")
                return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"CLOB API POST error ({endpoint}): {e}")
            return None
    
    def get_markets(self, limit: int = 200) -> List[Dict]:
        """
        Fetch markets from GAMMA API with ALL the rich data
        This is where the magic happens
        """
        # Fetch active markets
        data = self._get_gamma('/events', params={'closed': 'false'})
        
        if not data:
            logger.warning("GAMMA API /events returned no data")
            return []
        
        # Handle response format
        events = []
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = data.get('data') or data.get('events') or data.get('results') or []
        
        if not events:
            logger.warning("No events in GAMMA response")
            return []
        
        logger.info(f"GAMMA API returned {len(events)} events")
        
        # Filter to only active, non-closed markets
        events = [e for e in events if e.get('active', True) and not e.get('closed', False)]
        logger.info(f"After filtering: {len(events)} active events")
        
        # Extract individual markets with ALL the data
        all_markets = []
        
        for event in events:
            event_markets = event.get('markets', [])
            
            # If event has nested markets, process each
            if event_markets:
                for market in event_markets:
                    if isinstance(market, dict):
                        market_data = self._extract_market_data(market, event)
                        if market_data:
                            all_markets.append(market_data)
            else:
                # Event itself is a market
                if event.get('conditionId') or event.get('condition_id'):
                    market_data = self._extract_market_data(event, event)
                    if market_data:
                        all_markets.append(market_data)
        
        logger.info(f"Extracted {len(all_markets)} markets with rich data")
        
        # Sort by 24h volume (most active first)
        all_markets.sort(
            key=lambda x: safe_float(x.get('volume_24h') or x.get('volume_total')), 
            reverse=True
        )
        
        return all_markets[:limit]
    
    def _extract_market_data(self, market: Dict, event: Dict) -> Optional[Dict]:
        """
        Extract ALL the rich data from a market object
        This is THE JUICE
        """
        condition_id = market.get('conditionId') or market.get('condition_id')
        if not condition_id:
            return None
        
        # Parse JSON fields
        clob_tokens = parse_json_field(market.get('clobTokenIds', []))
        outcomes = parse_json_field(market.get('outcomes', []))
        outcome_prices = parse_json_field(market.get('outcomePrices', []))
        clob_rewards = parse_json_field(market.get('clobRewards', []))
        
        # Calculate current price (YES price)
        current_price = 0.5
        if outcome_prices and len(outcome_prices) > 0:
            current_price = safe_float(outcome_prices[0], 0.5)
        
        # Extract rewards info
        has_rewards = len(clob_rewards) > 0 if isinstance(clob_rewards, list) else False
        rewards_daily_rate = 0
        if has_rewards and isinstance(clob_rewards, list) and len(clob_rewards) > 0:
            rewards_daily_rate = safe_float(clob_rewards[0].get('rewardsDailyRate', 0))
        
        # Calculate volume velocity (24h volume vs 7d daily average)
        volume_24h = safe_float(market.get('volume24hr') or market.get('volume24hrClob'))
        volume_7d = safe_float(market.get('volume1wk') or market.get('volume1wkClob'))
        volume_velocity = 1.0
        if volume_7d > 0:
            daily_avg = volume_7d / 7
            if daily_avg > 0:
                volume_velocity = volume_24h / daily_avg
        
        return {
            # Core identifiers
            'condition_id': condition_id,
            'question': market.get('question') or event.get('title', ''),
            'slug': market.get('slug') or event.get('slug', ''),
            'description': market.get('description', ''),
            
            # VOLUME METRICS - THE JUICE
            'volume_total': safe_float(market.get('volumeNum') or market.get('volume') or market.get('volumeClob')),
            'volume_24h': volume_24h,
            'volume_7d': volume_7d,
            'volume_30d': safe_float(market.get('volume1mo') or market.get('volume1moClob')),
            'volume_velocity': round(volume_velocity, 2),
            
            # PRICE INTELLIGENCE
            'current_price': current_price,
            'price_change_24h': safe_float(market.get('oneDayPriceChange')),
            'price_change_7d': safe_float(market.get('oneWeekPriceChange')),
            'price_change_30d': safe_float(market.get('oneMonthPriceChange')),
            'last_trade_price': safe_float(market.get('lastTradePrice')),
            
            # ORDERBOOK DATA
            'best_bid': safe_float(market.get('bestBid')),
            'best_ask': safe_float(market.get('bestAsk')),
            'spread': safe_float(market.get('spread')),
            'liquidity': safe_float(market.get('liquidityNum') or market.get('liquidity') or market.get('liquidityClob')),
            
            # ALPHA SIGNALS - THE REAL GOLD
            'neg_risk': bool(market.get('negRisk', False)),
            'neg_risk_market_id': market.get('negRiskMarketID') or market.get('negRiskRequestID'),
            'competitive_score': safe_float(market.get('competitive')),
            'accepting_orders': bool(market.get('acceptingOrders', True)),
            
            # REWARDS
            'has_rewards': has_rewards,
            'rewards_daily_rate': rewards_daily_rate,
            'rewards_min_size': safe_float(market.get('rewardsMinSize')),
            'rewards_max_spread': safe_float(market.get('rewardsMaxSpread')),
            
            # METADATA
            'category': market.get('category') or event.get('category', ''),
            'image_url': market.get('image') or market.get('icon', ''),
            'end_date': market.get('endDate') or event.get('endDate'),
            'active': bool(market.get('active', True)),
            'closed': bool(market.get('closed', False)),
            
            # TOKEN DATA
            'clob_token_ids': clob_tokens,
            'outcomes': outcomes,
            'outcome_prices': outcome_prices,
            
            # RAW DATA (for debugging/future use)
            'raw_data': market
        }
    
    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """
        Get full orderbook for a token
        Returns bids, asks, spread, depth
        """
        data = self._get_clob('/book', params={'token_id': token_id})
        
        if not data or not isinstance(data, dict):
            return None
        
        # Parse bids and asks
        bids = []
        asks = []
        
        for bid in data.get('bids', []):
            if isinstance(bid, dict):
                bids.append({
                    'price': safe_float(bid.get('price')),
                    'size': safe_float(bid.get('size'))
                })
        
        for ask in data.get('asks', []):
            if isinstance(ask, dict):
                asks.append({
                    'price': safe_float(ask.get('price')),
                    'size': safe_float(ask.get('size'))
                })
        
        # Sort
        bids.sort(key=lambda x: x['price'], reverse=True)
        asks.sort(key=lambda x: x['price'])
        
        # Calculate spread
        spread = 0
        best_bid = bids[0]['price'] if bids else 0
        best_ask = asks[0]['price'] if asks else 1
        if best_bid > 0:
            spread = best_ask - best_bid
        
        # Calculate depth
        bid_depth = sum(b['price'] * b['size'] for b in bids[:10])
        ask_depth = sum(a['price'] * a['size'] for a in asks[:10])
        
        return {
            'token_id': token_id,
            'bids': bids,
            'asks': asks,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'spread': spread,
            'spread_percent': (spread / best_bid * 100) if best_bid > 0 else 0,
            'bid_depth': bid_depth,
            'ask_depth': ask_depth,
            'imbalance': (bid_depth - ask_depth) / (bid_depth + ask_depth) if (bid_depth + ask_depth) > 0 else 0,
            'tick_size': safe_float(data.get('tick_size', 0.001)),
            'min_order_size': safe_float(data.get('min_order_size', 5)),
            'neg_risk': bool(data.get('neg_risk', False))
        }
    
    def get_orderbooks_batch(self, token_ids: List[str]) -> Dict[str, Dict]:
        """Get orderbooks for multiple tokens"""
        if not token_ids:
            return {}
        
        # Batch request
        payload = [{'token_id': tid} for tid in token_ids[:100]]
        data = self._post_clob('/books', json_data=payload)
        
        if not data or not isinstance(data, list):
            return {}
        
        result = {}
        for book in data:
            token_id = book.get('asset_id') or book.get('token_id')
            if token_id:
                result[token_id] = self._parse_orderbook(book)
        
        return result
    
    def _parse_orderbook(self, data: Dict) -> Dict:
        """Parse a single orderbook response"""
        bids = []
        asks = []
        
        for bid in data.get('bids', []):
            if isinstance(bid, dict):
                bids.append({
                    'price': safe_float(bid.get('price')),
                    'size': safe_float(bid.get('size'))
                })
        
        for ask in data.get('asks', []):
            if isinstance(ask, dict):
                asks.append({
                    'price': safe_float(ask.get('price')),
                    'size': safe_float(ask.get('size'))
                })
        
        bids.sort(key=lambda x: x['price'], reverse=True)
        asks.sort(key=lambda x: x['price'])
        
        best_bid = bids[0]['price'] if bids else 0
        best_ask = asks[0]['price'] if asks else 1
        spread = best_ask - best_bid if best_bid > 0 else 0
        
        return {
            'bids': bids,
            'asks': asks,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'spread': spread,
            'spread_percent': (spread / best_bid * 100) if best_bid > 0 else 0
        }
    
    def get_price(self, token_id: str, side: str = 'BUY') -> Optional[float]:
        """Get current price for a token"""
        data = self._get_clob('/price', params={'token_id': token_id, 'side': side})
        if data and isinstance(data, dict):
            return safe_float(data.get('price'))
        return None
    
    def get_midpoint_price(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token"""
        data = self._get_clob('/midpoint', params={'token_id': token_id})
        if data and isinstance(data, dict):
            return safe_float(data.get('mid') or data.get('midpoint') or data.get('price'))
        return None
    
    def get_spread(self, token_id: str) -> Optional[float]:
        """Get spread for a token"""
        data = self._get_clob('/spread', params={'token_id': token_id})
        if data and isinstance(data, dict):
            return safe_float(data.get('spread'))
        return None
    
    def get_price_history(self, token_id: str, start_ts: Optional[int] = None, 
                          end_ts: Optional[int] = None, fidelity: int = 60) -> List[Dict]:
        """
        Get price history for a token
        fidelity = number of minutes between data points
        """
        import time
        
        params = {'market': token_id, 'fidelity': fidelity}
        
        if start_ts:
            params['startTs'] = start_ts
        else:
            # Default to 7 days ago
            params['startTs'] = int(time.time()) - (7 * 24 * 60 * 60)
        
        if end_ts:
            params['endTs'] = end_ts
        
        data = self._get_clob('/prices-history', params=params)
        
        if not data:
            return []
        
        history = data.get('history', []) if isinstance(data, dict) else data
        
        result = []
        for item in history:
            if isinstance(item, dict):
                result.append({
                    'timestamp': item.get('t'),
                    'price': safe_float(item.get('p'))
                })
        
        return result
    
    def get_market_by_id(self, condition_id: str) -> Optional[Dict]:
        """Get a specific market by condition ID"""
        data = self._get_gamma(f'/markets/{condition_id}')
        if data:
            return self._extract_market_data(data, data)
        return None
    
    def get_market_by_slug(self, slug: str) -> Optional[Dict]:
        """Get a specific market by slug"""
        data = self._get_gamma(f'/events/{slug}')
        if data:
            return self._extract_market_data(data, data)
        return None
    
    def get_neg_risk_groups(self, markets: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Group markets by their negative risk market ID
        This is KEY for finding arbitrage opportunities
        """
        groups = {}
        
        for market in markets:
            if market.get('neg_risk') and market.get('neg_risk_market_id'):
                group_id = market['neg_risk_market_id']
                if group_id not in groups:
                    groups[group_id] = []
                groups[group_id].append(market)
        
        # Only return groups with 2+ markets (where arb is possible)
        return {k: v for k, v in groups.items() if len(v) >= 2}
