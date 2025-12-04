"""
Order Book Scanner Worker - Wolf Pack Edition
Fetches order books from CLOB API, analyzes depth, imbalance, and spread dynamics
"""
import time
import json
import logging
import statistics
from typing import Dict, List, Optional, Tuple
from services.polymarket_api import PolymarketAPI
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Intelligence thresholds
IMBALANCE_ALERT_THRESHOLD = 0.5  # 50% imbalance triggers alert
SPREAD_WIDENING_ALERT = 0.1  # 10% spread widening triggers alert
WALL_SIZE_THRESHOLD = 2.0  # Order size > 2x average is a wall
DEPTH_ANALYSIS_LEVELS = 10  # Analyze top 10 price levels


class OrderBookScanner:
    """
    Wolf Pack Order Book Intelligence
    - Depth Analysis: Where is liquidity concentrated?
    - Imbalance Detection: Bullish/bearish pressure building
    - Spread Dynamics: Track spread changes for volatility signals
    - Support/Resistance: Identify order walls
    """
    
    def __init__(self):
        self.api = PolymarketAPI()
        self.db = SupabaseClient()
        self.scan_interval = 10  # seconds
        self.spread_history: Dict[str, List[float]] = {}  # Track spreads over time
        self.imbalance_history: Dict[str, List[float]] = {}  # Track imbalances
    
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
    
    def _extract_tokens(self, raw_data: dict) -> list:
        """Extract token IDs from raw market data"""
        tokens = []
        
        if not isinstance(raw_data, dict):
            return tokens
        
        # PRIORITY: Check for clobTokenIds (GAMMA API format)
        if 'clobTokenIds' in raw_data:
            tokens = self._parse_clob_token_ids(raw_data['clobTokenIds'])
            if tokens:
                return list(set(tokens))
        
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
        
        return list(set(tokens))
    
    def analyze_order_book(self, bids: List[Dict], asks: List[Dict]) -> Dict:
        """
        Analyze order book for intelligence insights:
        - Depth at various levels
        - Imbalance (buy vs sell pressure)
        - Spread and spread dynamics
        - Order walls (large orders)
        """
        analysis = {
            'best_bid': 0,
            'best_ask': 0,
            'spread': 0,
            'spread_percentage': 0,
            'bid_depth_total': 0,
            'ask_depth_total': 0,
            'bid_depth_10': 0,  # Depth within 10% of best bid
            'ask_depth_10': 0,  # Depth within 10% of best ask
            'imbalance': 0,
            'bid_walls': [],
            'ask_walls': [],
            'support_levels': [],
            'resistance_levels': []
        }
        
        try:
            # Parse bids and asks
            parsed_bids = []
            for bid in bids[:DEPTH_ANALYSIS_LEVELS]:
                if isinstance(bid, dict):
                    price = float(bid.get('price', 0))
                    size = float(bid.get('size', 0))
                elif isinstance(bid, list) and len(bid) >= 2:
                    price = float(bid[0])
                    size = float(bid[1])
                else:
                    continue
                
                if price > 0 and size > 0:
                    parsed_bids.append({'price': price, 'size': size, 'value': price * size})
            
            parsed_asks = []
            for ask in asks[:DEPTH_ANALYSIS_LEVELS]:
                if isinstance(ask, dict):
                    price = float(ask.get('price', 0))
                    size = float(ask.get('size', 0))
                elif isinstance(ask, list) and len(ask) >= 2:
                    price = float(ask[0])
                    size = float(ask[1])
                else:
                    continue
                
                if price > 0 and size > 0:
                    parsed_asks.append({'price': price, 'size': size, 'value': price * size})
            
            if not parsed_bids and not parsed_asks:
                return analysis
            
            # Best bid/ask and spread
            if parsed_bids:
                analysis['best_bid'] = max(b['price'] for b in parsed_bids)
            if parsed_asks:
                analysis['best_ask'] = min(a['price'] for a in parsed_asks)
            
            if analysis['best_bid'] and analysis['best_ask']:
                analysis['spread'] = analysis['best_ask'] - analysis['best_bid']
                midpoint = (analysis['best_bid'] + analysis['best_ask']) / 2
                analysis['spread_percentage'] = (analysis['spread'] / midpoint) * 100 if midpoint > 0 else 0
            
            # Total depth
            analysis['bid_depth_total'] = sum(b['value'] for b in parsed_bids)
            analysis['ask_depth_total'] = sum(a['value'] for a in parsed_asks)
            
            # Depth within 10% of best price
            if analysis['best_bid']:
                bid_10_threshold = analysis['best_bid'] * 0.9
                analysis['bid_depth_10'] = sum(
                    b['value'] for b in parsed_bids if b['price'] >= bid_10_threshold
                )
            
            if analysis['best_ask']:
                ask_10_threshold = analysis['best_ask'] * 1.1
                analysis['ask_depth_10'] = sum(
                    a['value'] for a in parsed_asks if a['price'] <= ask_10_threshold
                )
            
            # Imbalance calculation
            total_depth = analysis['bid_depth_10'] + analysis['ask_depth_10']
            if total_depth > 0:
                analysis['imbalance'] = (analysis['bid_depth_10'] - analysis['ask_depth_10']) / total_depth
            
            # Detect order walls (orders significantly larger than average)
            if parsed_bids:
                avg_bid_size = statistics.mean(b['size'] for b in parsed_bids)
                for bid in parsed_bids:
                    if bid['size'] > avg_bid_size * WALL_SIZE_THRESHOLD:
                        analysis['bid_walls'].append({
                            'price': bid['price'],
                            'size': bid['size'],
                            'value': bid['value']
                        })
                        analysis['support_levels'].append(bid['price'])
            
            if parsed_asks:
                avg_ask_size = statistics.mean(a['size'] for a in parsed_asks)
                for ask in parsed_asks:
                    if ask['size'] > avg_ask_size * WALL_SIZE_THRESHOLD:
                        analysis['ask_walls'].append({
                            'price': ask['price'],
                            'size': ask['size'],
                            'value': ask['value']
                        })
                        analysis['resistance_levels'].append(ask['price'])
            
        except Exception as e:
            logger.error(f"Error analyzing order book: {e}")
        
        return analysis
    
    def detect_spread_dynamics(self, condition_id: str, current_spread: float) -> Optional[Dict]:
        """Detect significant spread changes"""
        if condition_id not in self.spread_history:
            self.spread_history[condition_id] = []
        
        self.spread_history[condition_id].append(current_spread)
        
        # Keep last 60 data points (10 minutes at 10s interval)
        if len(self.spread_history[condition_id]) > 60:
            self.spread_history[condition_id] = self.spread_history[condition_id][-60:]
        
        # Need at least 10 data points
        if len(self.spread_history[condition_id]) < 10:
            return None
        
        history = self.spread_history[condition_id]
        avg_spread = statistics.mean(history[:-1])  # Exclude current
        
        if avg_spread > 0:
            spread_change = (current_spread - avg_spread) / avg_spread
            
            if abs(spread_change) > SPREAD_WIDENING_ALERT:
                return {
                    'type': 'spread_widening' if spread_change > 0 else 'spread_tightening',
                    'change_percent': spread_change * 100,
                    'current_spread': current_spread,
                    'avg_spread': avg_spread
                }
        
        return None
    
    def detect_imbalance_shift(self, condition_id: str, current_imbalance: float) -> Optional[Dict]:
        """Detect significant imbalance shifts"""
        if condition_id not in self.imbalance_history:
            self.imbalance_history[condition_id] = []
        
        self.imbalance_history[condition_id].append(current_imbalance)
        
        # Keep last 30 data points
        if len(self.imbalance_history[condition_id]) > 30:
            self.imbalance_history[condition_id] = self.imbalance_history[condition_id][-30:]
        
        # Need at least 5 data points
        if len(self.imbalance_history[condition_id]) < 5:
            return None
        
        history = self.imbalance_history[condition_id]
        avg_imbalance = statistics.mean(history[:-1])
        
        # Detect significant shift
        imbalance_shift = current_imbalance - avg_imbalance
        
        if abs(imbalance_shift) > 0.3:  # 30% shift
            return {
                'type': 'bullish_shift' if imbalance_shift > 0 else 'bearish_shift',
                'current_imbalance': current_imbalance,
                'avg_imbalance': avg_imbalance,
                'shift': imbalance_shift
            }
        
        return None
    
    def scan_orderbooks(self):
        """Fetch and analyze order books for active markets"""
        try:
            logger.info("Starting order book intelligence scan...")
            
            # Get active markets from database
            markets = self.db.get_markets(limit=50)
            
            if not markets:
                logger.warning("No markets found in database")
                return
            
            logger.info(f"Scanning order books for {len(markets)} markets")
            
            # Collect all tokens for batch fetching
            market_tokens_map = {}
            all_tokens = []
            
            for market in markets:
                condition_id = market.get('condition_id')
                if not condition_id:
                    continue
                
                # Get tokens for this market
                tokens = market.get('tokens') or []
                if not tokens:
                    raw_data = market.get('raw_data', {})
                    if isinstance(raw_data, dict):
                        tokens = self._extract_tokens(raw_data)
                        if not tokens and 'stored_tokens' in raw_data:
                            tokens = raw_data['stored_tokens']
                    if not tokens:
                        tokens = self.api.get_market_tokens(condition_id)
                
                if tokens:
                    market_tokens_map[condition_id] = tokens
                    all_tokens.extend(tokens[:1])  # Use first token (YES)
            
            if not all_tokens:
                logger.warning("No tokens found for any markets")
                return
            
            # Batch fetch order books
            logger.info(f"Batch fetching {len(all_tokens)} order books...")
            orderbooks = self.api.get_orderbooks_batch(all_tokens)
            
            scanned_count = 0
            intelligence_signals = 0
            
            token_to_market = {}
            for condition_id, tokens in market_tokens_map.items():
                if tokens:
                    token_to_market[tokens[0]] = condition_id
            
            # Process batch results
            for idx, orderbook in enumerate(orderbooks):
                try:
                    # Match orderbook to market
                    if idx < len(all_tokens):
                        token_id = all_tokens[idx]
                        condition_id = token_to_market.get(token_id)
                    
                    if not condition_id:
                        asset_id = orderbook.get('asset_id')
                        for tid, cid in token_to_market.items():
                            if str(tid) == str(asset_id):
                                condition_id = cid
                                break
                    
                    if not condition_id:
                        continue
                    
                    bids = orderbook.get('bids', [])
                    asks = orderbook.get('asks', [])
                    
                    if not bids and not asks:
                        continue
                    
                    # Store raw order book
                    metadata = {
                        'min_order_size': orderbook.get('min_order_size'),
                        'tick_size': orderbook.get('tick_size'),
                        'neg_risk': orderbook.get('neg_risk', False)
                    }
                    self.db.insert_orderbook(condition_id, bids, asks, metadata)
                    
                    # Analyze order book
                    analysis = self.analyze_order_book(bids, asks)
                    
                    # Store order book snapshot with analysis
                    self.db.insert_orderbook_snapshot({
                        'market_id': condition_id,
                        'bid_depth_10': analysis['bid_depth_10'],
                        'ask_depth_10': analysis['ask_depth_10'],
                        'spread': analysis['spread'],
                        'imbalance': analysis['imbalance'],
                        'best_bid': analysis['best_bid'],
                        'best_ask': analysis['best_ask']
                    })
                    
                    # Update market with spread and buy pressure
                    buy_pressure = ((analysis['imbalance'] + 1) / 2) * 100  # Convert -1 to 1 -> 0 to 100
                    self.db.update_market_prices(condition_id, {
                        'best_bid': analysis['best_bid'],
                        'best_ask': analysis['best_ask'],
                        'spread_percentage': analysis['spread_percentage']
                    })
                    self.db.upsert_market_stats(condition_id, {
                        'buy_pressure': buy_pressure,
                        'sell_pressure': 100 - buy_pressure,
                        'spread_percentage': analysis['spread_percentage']
                    })
                    
                    scanned_count += 1
                    
                    # Detect and alert on significant imbalance
                    if abs(analysis['imbalance']) > IMBALANCE_ALERT_THRESHOLD:
                        direction = "BULLISH" if analysis['imbalance'] > 0 else "BEARISH"
                        logger.info(f"📊 Imbalance Alert: {direction} {analysis['imbalance']:.2f} on {condition_id[:20]}...")
                        
                        self.db.insert_signal({
                            'market_id': condition_id,
                            'type': 'orderbook_imbalance',
                            'title': f"Strong {direction} Order Book",
                            'description': f"Order book shows {abs(analysis['imbalance'])*100:.0f}% {direction.lower()} imbalance",
                            'severity': 'high' if abs(analysis['imbalance']) > 0.7 else 'medium',
                            'data': {
                                'imbalance': analysis['imbalance'],
                                'bid_depth': analysis['bid_depth_10'],
                                'ask_depth': analysis['ask_depth_10'],
                                'spread': analysis['spread'],
                                'spread_pct': analysis['spread_percentage']
                            }
                        })
                        intelligence_signals += 1
                    
                    # Detect spread dynamics
                    spread_signal = self.detect_spread_dynamics(condition_id, analysis['spread'])
                    if spread_signal:
                        is_widening = spread_signal['type'] == 'spread_widening'
                        logger.info(f"📈 Spread {'Widening' if is_widening else 'Tightening'}: {spread_signal['change_percent']:.1f}% on {condition_id[:20]}...")
                        
                        self.db.insert_signal({
                            'market_id': condition_id,
                            'type': spread_signal['type'],
                            'title': f"Spread {'Widening' if is_widening else 'Tightening'}",
                            'description': f"Spread changed {spread_signal['change_percent']:+.1f}% from average",
                            'severity': 'medium',
                            'data': spread_signal
                        })
                        intelligence_signals += 1
                    
                    # Detect imbalance shift
                    imbalance_signal = self.detect_imbalance_shift(condition_id, analysis['imbalance'])
                    if imbalance_signal:
                        is_bullish = imbalance_signal['type'] == 'bullish_shift'
                        logger.info(f"🔄 Imbalance Shift: {'Bullish' if is_bullish else 'Bearish'} on {condition_id[:20]}...")
                        
                        self.db.insert_signal({
                            'market_id': condition_id,
                            'type': imbalance_signal['type'],
                            'title': f"{'Bullish' if is_bullish else 'Bearish'} Pressure Building",
                            'description': f"Order book shifted {imbalance_signal['shift']*100:+.0f}% towards {'buyers' if is_bullish else 'sellers'}",
                            'severity': 'high',
                            'data': imbalance_signal
                        })
                        intelligence_signals += 1
                    
                    # Alert on order walls
                    if analysis['bid_walls']:
                        for wall in analysis['bid_walls']:
                            logger.info(f"🧱 BID WALL: ${wall['value']:,.0f} at {wall['price']:.4f}")
                    
                    if analysis['ask_walls']:
                        for wall in analysis['ask_walls']:
                            logger.info(f"🧱 ASK WALL: ${wall['value']:,.0f} at {wall['price']:.4f}")
                    
                except Exception as e:
                    logger.error(f"Error processing orderbook: {e}")
                    continue
            
            logger.info(f"Scanned {scanned_count} order books, generated {intelligence_signals} signals")
            
        except Exception as e:
            logger.error(f"Error in order book scan: {e}", exc_info=True)
    
    def run(self):
        """Main worker loop"""
        logger.info("Order Book Intelligence Scanner started (Wolf Pack Edition)")
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
