"""
Price History Worker - Wolf Pack Edition
Tracks price changes, calculates momentum, volatility, and price velocity
"""
import time
import json
import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from services.polymarket_api import PolymarketAPI
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PriceHistoryWorker:
    """
    Wolf Pack Price Intelligence
    - Tracks real-time price changes
    - Calculates momentum (price velocity)
    - Measures volatility
    - Identifies price breakouts
    """
    
    def __init__(self):
        self.api = PolymarketAPI()
        self.db = SupabaseClient()
        self.scan_interval = 60  # 1 minute for more frequent updates
        self.price_cache: Dict[str, List[Tuple[datetime, float]]] = {}  # In-memory price cache
        
    def _parse_clob_token_ids(self, clob_ids) -> list:
        """Parse clobTokenIds which can be a list or a JSON string"""
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
    
    def _get_price_at_time(self, condition_id: str, target_time: datetime, 
                           history: List[Dict]) -> Optional[float]:
        """Find the price closest to a target time from history"""
        if not history:
            return None
        
        best_price = None
        best_diff = float('inf')
        
        for price_point in history:
            try:
                ts = price_point.get('timestamp', '')
                if not ts:
                    continue
                
                # Parse timestamp
                if isinstance(ts, str):
                    if 'T' in ts:
                        price_time = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    else:
                        continue
                elif isinstance(ts, datetime):
                    price_time = ts
                else:
                    continue
                
                # Make timezone aware if not
                if price_time.tzinfo is None:
                    price_time = price_time.replace(tzinfo=timezone.utc)
                
                diff = abs((price_time - target_time).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_price = float(price_point.get('price', 0))
                    
            except Exception as e:
                logger.debug(f"Error parsing timestamp: {e}")
                continue
        
        return best_price
    
    def _calculate_volatility(self, prices: List[float]) -> float:
        """Calculate price volatility as standard deviation of returns"""
        if len(prices) < 2:
            return 0.0
        
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                ret = (prices[i] - prices[i-1]) / prices[i-1]
                returns.append(ret)
        
        if len(returns) < 2:
            return 0.0
        
        return statistics.stdev(returns) * 100  # As percentage
    
    def _calculate_momentum(self, current_price: float, prices_1h: List[float], 
                           prices_24h: List[float]) -> float:
        """
        Calculate momentum score (-100 to +100)
        Positive = bullish momentum, Negative = bearish momentum
        """
        if not prices_1h or not prices_24h:
            return 0.0
        
        # Short-term momentum (1h trend)
        short_term = 0.0
        if len(prices_1h) >= 2 and prices_1h[0] > 0:
            short_term = ((current_price - prices_1h[0]) / prices_1h[0]) * 100
        
        # Long-term momentum (24h trend)
        long_term = 0.0
        if len(prices_24h) >= 2 and prices_24h[0] > 0:
            long_term = ((current_price - prices_24h[0]) / prices_24h[0]) * 100
        
        # Acceleration (is short-term stronger than long-term?)
        acceleration = short_term - (long_term / 24)  # Normalize long-term to hourly
        
        # Combined momentum score
        momentum = (short_term * 0.4) + (long_term * 0.3) + (acceleration * 0.3)
        
        # Clamp to -100 to +100
        return max(-100, min(100, momentum))
    
    def update_prices(self):
        """Fetch current prices and calculate comprehensive price intelligence"""
        try:
            logger.info("Starting price intelligence update...")
            
            # Get active markets
            markets = self.db.get_markets(limit=200)
            
            if not markets:
                logger.warning("No markets found for price update")
                return
            
            updated_count = 0
            
            # Collect all tokens for batch fetching
            market_tokens_map: Dict[str, List[str]] = {}
            all_tokens: List[str] = []
            
            for market in markets:
                condition_id = market.get('condition_id')
                if not condition_id:
                    continue
                
                # Get tokens - try multiple sources
                tokens = []
                
                # Try stored tokens field first
                stored_tokens = market.get('tokens')
                if stored_tokens:
                    tokens = self._parse_clob_token_ids(stored_tokens)
                
                if not tokens:
                    # Try raw_data
                    raw_data = market.get('raw_data', {})
                    if isinstance(raw_data, dict):
                        tokens = self._parse_clob_token_ids(raw_data.get('clobTokenIds', []))
                        if not tokens:
                            tokens = self._parse_clob_token_ids(raw_data.get('stored_tokens', []))
                
                if tokens:
                    market_tokens_map[condition_id] = tokens
                    all_tokens.extend(tokens)
            
            if not all_tokens:
                logger.warning("No tokens found for price update")
                return
            
            # Batch fetch current prices from API
            logger.info(f"Fetching prices for {len(all_tokens)} tokens across {len(market_tokens_map)} markets...")
            current_prices = self.api.get_prices_batch(list(set(all_tokens)))
            
            # Process each market
            now = datetime.now(timezone.utc)
            time_1h_ago = now - timedelta(hours=1)
            time_24h_ago = now - timedelta(hours=24)
            time_7d_ago = now - timedelta(days=7)
            
            for condition_id, tokens in market_tokens_map.items():
                try:
                    # Get current price for YES token (first token)
                    current_price = None
                    for token in tokens:
                        if token in current_prices:
                            current_price = float(current_prices[token])
                            break
                    
                    if current_price is None:
                        continue
                    
                    # Store current price in database
                    self.db.insert_price(condition_id, 0, current_price)
                    
                    # Get price history for calculations
                    history = self.db.get_price_history(condition_id, hours=168)  # 7 days
                    
                    # Calculate price changes
                    price_1h_ago = self._get_price_at_time(condition_id, time_1h_ago, history)
                    price_24h_ago = self._get_price_at_time(condition_id, time_24h_ago, history)
                    price_7d_ago = self._get_price_at_time(condition_id, time_7d_ago, history)
                    
                    # Calculate percentage changes
                    change_1h = None
                    change_24h = None
                    change_7d = None
                    
                    if price_1h_ago and price_1h_ago > 0:
                        change_1h = ((current_price - price_1h_ago) / price_1h_ago) * 100
                    
                    if price_24h_ago and price_24h_ago > 0:
                        change_24h = ((current_price - price_24h_ago) / price_24h_ago) * 100
                    
                    if price_7d_ago and price_7d_ago > 0:
                        change_7d = ((current_price - price_7d_ago) / price_7d_ago) * 100
                    
                    # Extract prices for volatility calculation
                    recent_prices = [float(p['price']) for p in history if p.get('price')][-50:]
                    volatility = self._calculate_volatility(recent_prices) if recent_prices else 0
                    
                    # Calculate momentum
                    prices_1h = [float(p['price']) for p in history 
                                if p.get('price') and p.get('timestamp', '') > time_1h_ago.isoformat()]
                    prices_24h = [float(p['price']) for p in history 
                                 if p.get('price') and p.get('timestamp', '') > time_24h_ago.isoformat()]
                    
                    momentum = self._calculate_momentum(current_price, prices_1h, prices_24h)
                    
                    # Update market with all intelligence
                    update_data = {
                        'condition_id': condition_id,
                        'current_price': current_price,
                        'price_change_1h': change_1h,
                        'price_change_24h': change_24h,
                        'price_change_7d': change_7d,
                        'price_change_percent': change_24h,  # Default to 24h for general display
                        'momentum': momentum,
                        'volatility_24h': volatility
                    }
                    
                    self.db.update_market_prices(condition_id, update_data)
                    updated_count += 1
                    
                    # Log significant moves
                    if change_24h and abs(change_24h) > 5:
                        direction = "📈" if change_24h > 0 else "📉"
                        logger.info(f"{direction} Big Move: {condition_id[:20]}... {change_24h:+.2f}% (momentum: {momentum:.1f})")
                    
                except Exception as e:
                    logger.error(f"Error updating prices for {condition_id}: {e}")
                    continue
            
            logger.info(f"Updated price intelligence for {updated_count} markets")
            
        except Exception as e:
            logger.error(f"Error in price intelligence update: {e}", exc_info=True)
    
    def detect_breakouts(self):
        """Detect price breakouts and mean reversion opportunities"""
        try:
            markets = self.db.get_markets(limit=100)
            
            for market in markets:
                condition_id = market.get('condition_id')
                if not condition_id:
                    continue
                
                current_price = market.get('current_price')
                momentum = market.get('momentum', 0)
                volatility = market.get('volatility_24h', 0)
                change_24h = market.get('price_change_percent', 0)
                
                if not current_price:
                    continue
                
                # Breakout detection: High momentum + price move > 2x volatility
                if momentum and volatility and change_24h:
                    if abs(change_24h) > volatility * 2 and abs(momentum) > 30:
                        signal_type = 'breakout' if change_24h > 0 else 'breakdown'
                        logger.info(f"🚀 {signal_type.upper()}: {market.get('question', '')[:50]}...")
                        
                        # Insert signal
                        self.db.insert_signal({
                            'market_id': condition_id,
                            'type': signal_type,
                            'title': f"Price {signal_type.title()} Detected",
                            'description': f"Price moved {change_24h:+.1f}% with strong {momentum:.0f} momentum",
                            'severity': 'high',
                            'data': {
                                'price': current_price,
                                'change': change_24h,
                                'momentum': momentum,
                                'volatility': volatility
                            }
                        })
                    
                    # Mean reversion detection: Low momentum but large move
                    elif abs(change_24h) > volatility * 3 and abs(momentum) < 20:
                        logger.info(f"↩️ Mean Reversion Signal: {market.get('question', '')[:50]}...")
                        
                        self.db.insert_signal({
                            'market_id': condition_id,
                            'type': 'mean_reversion',
                            'title': "Mean Reversion Opportunity",
                            'description': f"Price extended {change_24h:+.1f}% but momentum fading ({momentum:.0f})",
                            'severity': 'medium',
                            'data': {
                                'price': current_price,
                                'change': change_24h,
                                'momentum': momentum,
                                'expected_direction': 'down' if change_24h > 0 else 'up'
                            }
                        })
                        
        except Exception as e:
            logger.error(f"Error detecting breakouts: {e}")
    
    def run(self):
        """Main worker loop"""
        logger.info("Price Intelligence Worker started (Wolf Pack Edition)")
        
        cycle = 0
        while True:
            try:
                # Update prices every cycle
                self.update_prices()
                
                # Detect breakouts every 5 cycles (5 minutes)
                cycle += 1
                if cycle % 5 == 0:
                    self.detect_breakouts()
                    
            except Exception as e:
                logger.error(f"Fatal error in price intelligence worker: {e}", exc_info=True)
            
            logger.info(f"Sleeping for {self.scan_interval} seconds...")
            time.sleep(self.scan_interval)


if __name__ == "__main__":
    worker = PriceHistoryWorker()
    worker.run()
