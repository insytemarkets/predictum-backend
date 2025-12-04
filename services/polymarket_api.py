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
import time
from typing import Dict, List, Optional, Any, Tuple

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
    Uses GAMMA for market data + CLOB for order books, prices, and history
    """
    
    def __init__(self):
        self.gamma_base = "https://gamma-api.polymarket.com"
        self.clob_base = "https://clob.polymarket.com"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Predictum/2.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    
    def _get_gamma(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        """Make a GET request to GAMMA API with endpoint-specific rate limiting"""
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
                time.sleep(2)
                return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"GAMMA API error ({endpoint}): {e}")
            return None
    
    def _get_clob(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        """Make a GET request to CLOB API with endpoint-specific rate limiting"""
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
                time.sleep(2)
                return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"CLOB API error ({endpoint}): {e}")
            return None
    
    def _post_clob(self, endpoint: str, json_data: Any) -> Optional[Any]:
        """Make a POST request to CLOB API with batch rate limiting"""
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
                time.sleep(2)
                return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"CLOB API POST error ({endpoint}): {e}")
            return None
    
    # =========================================================================
    # GAMMA API - Market Data
    # =========================================================================
    
    def get_markets(self, limit: int = 200) -> List[Dict]:
        """
        Fetch markets from GAMMA API with ALL the rich data
        """
        data = self._get_gamma('/events', params={'closed': 'false', 'limit': 500})
        
        if not data:
            logger.warning("GAMMA API /events returned no data")
            return []
        
        events = []
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = data.get('data') or data.get('events') or data.get('results') or []
        
        if not events:
            return []
        
        logger.info(f"GAMMA API returned {len(events)} events")
        events = [e for e in events if e.get('active', True) and not e.get('closed', False)]
        
        all_markets = []
        for event in events:
            event_markets = event.get('markets', [])
            if event_markets:
                for market in event_markets:
                    if isinstance(market, dict):
                        market_data = self._extract_market_data(market, event)
                        if market_data:
                            all_markets.append(market_data)
            else:
                if event.get('conditionId') or event.get('condition_id'):
                    market_data = self._extract_market_data(event, event)
                    if market_data:
                        all_markets.append(market_data)
        
        all_markets.sort(key=lambda x: safe_float(x.get('volume_24h')), reverse=True)
        return all_markets[:limit]
    
    def _extract_market_data(self, market: Dict, event: Dict) -> Optional[Dict]:
        """Extract ALL the rich data from a market object"""
        condition_id = market.get('conditionId') or market.get('condition_id')
        if not condition_id:
            return None
        
        clob_tokens = parse_json_field(market.get('clobTokenIds', []))
        outcomes = parse_json_field(market.get('outcomes', []))
        outcome_prices = parse_json_field(market.get('outcomePrices', []))
        clob_rewards = parse_json_field(market.get('clobRewards', []))
        
        current_price = 0.5
        if outcome_prices and len(outcome_prices) > 0:
            current_price = safe_float(outcome_prices[0], 0.5)
        
        has_rewards = len(clob_rewards) > 0 if isinstance(clob_rewards, list) else False
        rewards_daily_rate = 0
        if has_rewards and isinstance(clob_rewards, list) and len(clob_rewards) > 0:
            rewards_daily_rate = safe_float(clob_rewards[0].get('rewardsDailyRate', 0))
        
        volume_24h = safe_float(market.get('volume24hr') or market.get('volume24hrClob'))
        volume_7d = safe_float(market.get('volume1wk') or market.get('volume1wkClob'))
        volume_velocity = 1.0
        if volume_7d > 0:
            daily_avg = volume_7d / 7
            if daily_avg > 0:
                volume_velocity = volume_24h / daily_avg
        
        return {
            'condition_id': condition_id,
            'question': market.get('question') or event.get('title', ''),
            'slug': market.get('slug') or event.get('slug', ''),
            'description': market.get('description', ''),
            'volume_total': safe_float(market.get('volumeNum') or market.get('volume')),
            'volume_24h': volume_24h,
            'volume_7d': volume_7d,
            'volume_30d': safe_float(market.get('volume1mo') or market.get('volume1moClob')),
            'volume_velocity': round(volume_velocity, 2),
            'current_price': current_price,
            'price_change_24h': safe_float(market.get('oneDayPriceChange')),
            'price_change_7d': safe_float(market.get('oneWeekPriceChange')),
            'price_change_30d': safe_float(market.get('oneMonthPriceChange')),
            'last_trade_price': safe_float(market.get('lastTradePrice')),
            'best_bid': safe_float(market.get('bestBid')),
            'best_ask': safe_float(market.get('bestAsk')),
            'spread': safe_float(market.get('spread')),
            'liquidity': safe_float(market.get('liquidityNum') or market.get('liquidity')),
            'neg_risk': bool(market.get('negRisk', False)),
            'neg_risk_market_id': market.get('negRiskMarketID') or market.get('negRiskRequestID'),
            'competitive_score': safe_float(market.get('competitive')),
            'accepting_orders': bool(market.get('acceptingOrders', True)),
            'has_rewards': has_rewards,
            'rewards_daily_rate': rewards_daily_rate,
            'category': market.get('category') or event.get('category', ''),
            'image_url': market.get('image') or market.get('icon', ''),
            'end_date': market.get('endDate') or event.get('endDate'),
            'active': bool(market.get('active', True)),
            'closed': bool(market.get('closed', False)),
            'clob_token_ids': clob_tokens,
            'outcomes': outcomes,
            'outcome_prices': outcome_prices,
            'raw_data': market
        }
    
    # =========================================================================
    # CLOB API - Order Books (from /books endpoint)
    # https://docs.polymarket.com/api-reference/orderbook/get-multiple-order-books-summaries-by-request
    # =========================================================================
    
    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """Get single order book"""
        data = self._get_clob('/book', params={'token_id': token_id})
        if not data:
            return None
        return self._parse_orderbook(data, token_id)
    
    def get_orderbooks_batch(self, token_ids: List[str], max_batch: int = 50) -> Dict[str, Dict]:
        """
        Get order books for multiple tokens in batch
        POST /books - max ~100 per request recommended
        Returns: {token_id: orderbook_data}
        """
        if not token_ids:
            return {}
        
        results = {}
        
        # Process in batches
        for i in range(0, len(token_ids), max_batch):
            batch = token_ids[i:i + max_batch]
            payload = [{'token_id': tid} for tid in batch]
            
            data = self._post_clob('/books', payload)
            if not data or not isinstance(data, list):
                continue
            
            for book in data:
                token_id = book.get('asset_id') or book.get('token_id')
                if token_id:
                    results[token_id] = self._parse_orderbook(book, token_id)
        
        return results
    
    def _parse_orderbook(self, data: Dict, token_id: str = None) -> Dict:
        """Parse orderbook response into structured data"""
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
        spread_percent = (spread / best_bid * 100) if best_bid > 0 else 0
        
        # Calculate depth (total value on each side)
        bid_depth = sum(b['price'] * b['size'] for b in bids)
        ask_depth = sum(a['price'] * a['size'] for a in asks)
        total_depth = bid_depth + ask_depth
        
        # Order imbalance: positive = more buying pressure
        imbalance = (bid_depth - ask_depth) / total_depth if total_depth > 0 else 0
        buy_pressure = (bid_depth / total_depth * 100) if total_depth > 0 else 50
        
        return {
            'token_id': token_id or data.get('asset_id'),
            'bids': bids,
            'asks': asks,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'spread': spread,
            'spread_percent': round(spread_percent, 2),
            'bid_depth': round(bid_depth, 2),
            'ask_depth': round(ask_depth, 2),
            'total_depth': round(total_depth, 2),
            'imbalance': round(imbalance, 3),
            'buy_pressure': round(buy_pressure, 1),
            'tick_size': safe_float(data.get('tick_size', 0.01)),
            'min_order_size': safe_float(data.get('min_order_size', 5)),
            'neg_risk': bool(data.get('neg_risk', False)),
            'timestamp': data.get('timestamp')
        }
    
    # =========================================================================
    # CLOB API - Prices (from /prices and /price endpoints)
    # https://docs.polymarket.com/api-reference/pricing/get-multiple-market-prices
    # =========================================================================
    
    def get_price(self, token_id: str, side: str = 'BUY') -> Optional[float]:
        """Get single token price"""
        data = self._get_clob('/price', params={'token_id': token_id, 'side': side})
        if data and isinstance(data, dict):
            return safe_float(data.get('price'))
        return None
    
    def get_prices_batch(self, token_ids: List[str]) -> Dict[str, Dict]:
        """
        Get prices for multiple tokens
        POST /prices - max 500 per request
        Returns: {token_id: {BUY: price, SELL: price}}
        """
        if not token_ids:
            return {}
        
        # Build request payload
        payload = []
        for tid in token_ids[:500]:
            payload.append({'token_id': tid, 'side': 'BUY'})
            payload.append({'token_id': tid, 'side': 'SELL'})
        
        data = self._post_clob('/prices', payload)
        if not data or not isinstance(data, dict):
            return {}
        
        # Parse response: {token_id: {BUY: price, SELL: price}}
        results = {}
        for token_id, prices in data.items():
            if isinstance(prices, dict):
                results[token_id] = {
                    'buy': safe_float(prices.get('BUY')),
                    'sell': safe_float(prices.get('SELL')),
                    'spread': safe_float(prices.get('SELL')) - safe_float(prices.get('BUY')),
                    'mid': (safe_float(prices.get('BUY')) + safe_float(prices.get('SELL'))) / 2
                }
        
        return results
    
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
    
    # =========================================================================
    # CLOB API - Price History (from /prices-history endpoint)
    # https://docs.polymarket.com/api-reference/pricing/get-price-history-for-a-traded-token
    # =========================================================================
    
    def get_price_history(
        self, 
        token_id: str, 
        interval: str = '1d',
        fidelity: int = 60,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None
    ) -> List[Dict]:
        """
        Get price history for a token
        
        Args:
            token_id: CLOB token ID
            interval: '1m', '1h', '6h', '1d', '1w', 'max'
            fidelity: Resolution in minutes (60 = hourly points)
            start_ts: Unix timestamp start (optional)
            end_ts: Unix timestamp end (optional)
        
        Returns: List of {timestamp: int, price: float}
        """
        params = {'market': token_id, 'fidelity': fidelity}
        
        if start_ts and end_ts:
            params['startTs'] = start_ts
            params['endTs'] = end_ts
        else:
            params['interval'] = interval
        
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
    
    def get_price_history_batch(
        self, 
        token_ids: List[str], 
        interval: str = '1d',
        fidelity: int = 60
    ) -> Dict[str, List[Dict]]:
        """
        Get price history for multiple tokens
        Returns: {token_id: [{timestamp, price}, ...]}
        """
        results = {}
        for tid in token_ids:
            history = self.get_price_history(tid, interval=interval, fidelity=fidelity)
            if history:
                results[tid] = history
        return results
    
    def calculate_momentum(self, history: List[Dict]) -> Dict:
        """
        Calculate momentum metrics from price history
        
        Returns:
            change_1h: % change in last hour
            change_24h: % change in last 24h
            trend: 'UP', 'DOWN', 'FLAT'
            volatility: standard deviation of prices
        """
        if not history or len(history) < 2:
            return {'change_1h': 0, 'change_24h': 0, 'trend': 'FLAT', 'volatility': 0}
        
        prices = [h['price'] for h in history if h.get('price')]
        if not prices:
            return {'change_1h': 0, 'change_24h': 0, 'trend': 'FLAT', 'volatility': 0}
        
        current = prices[-1]
        
        # 24h change (first vs last)
        change_24h = (current - prices[0]) / prices[0] if prices[0] > 0 else 0
        
        # 1h change (roughly last 1/24th of data)
        hour_idx = max(0, len(prices) - len(prices) // 24)
        change_1h = (current - prices[hour_idx]) / prices[hour_idx] if prices[hour_idx] > 0 else 0
        
        # Trend direction
        if change_24h > 0.02:
            trend = 'UP'
        elif change_24h < -0.02:
            trend = 'DOWN'
        else:
            trend = 'FLAT'
        
        # Volatility (standard deviation)
        mean_price = sum(prices) / len(prices)
        variance = sum((p - mean_price) ** 2 for p in prices) / len(prices)
        volatility = variance ** 0.5
        
        return {
            'change_1h': round(change_1h, 4),
            'change_24h': round(change_24h, 4),
            'trend': trend,
            'volatility': round(volatility, 4),
            'current_price': current,
            'high': max(prices),
            'low': min(prices)
        }
    
    # =========================================================================
    # COMBINED DATA FETCHING
    # =========================================================================
    
    def get_market_intelligence(self, token_id: str) -> Dict:
        """
        Get full intelligence data for a single market
        Combines: orderbook + prices + history
        """
        # Get orderbook
        orderbook = self.get_orderbook(token_id)
        
        # Get price history and calculate momentum
        history = self.get_price_history(token_id, interval='1d', fidelity=60)
        momentum = self.calculate_momentum(history)
        
        return {
            'token_id': token_id,
            'orderbook': orderbook,
            'price_history': history,
            'momentum': momentum,
            'buy_pressure': orderbook.get('buy_pressure', 50) if orderbook else 50,
            'spread_percent': orderbook.get('spread_percent', 0) if orderbook else 0,
            'total_depth': orderbook.get('total_depth', 0) if orderbook else 0
        }
    
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
        
        return {k: v for k, v in groups.items() if len(v) >= 2}
    
    def get_market_tokens(self, condition_id: str) -> List[str]:
        """
        Get CLOB token IDs for a specific market
        Fallback method when tokens aren't cached
        """
        data = self._get_gamma(f'/markets/{condition_id}')
        if not data:
            return []
        
        clob_tokens = parse_json_field(data.get('clobTokenIds', []))
        if isinstance(clob_tokens, list):
            return [str(t) for t in clob_tokens if t]
        return []
