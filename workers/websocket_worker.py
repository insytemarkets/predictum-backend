"""
WebSocket Worker for Real-Time Polymarket Data - Wolf Pack Edition
Connects to Polymarket WebSocket for live order book, price, and trade updates
Includes order book intelligence: depth analysis, imbalance detection, spread dynamics
Per docs: https://docs.polymarket.com/developers/CLOB/websocket/market-channel
"""
import asyncio
import json
import logging
import time
import os
import sys
from typing import Dict, List, Set, Optional
from datetime import datetime

# Add parent directory for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import websockets
except ImportError:
    print("Installing websockets...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets"])
    import websockets

from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Polymarket WebSocket endpoints
WS_MARKET_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
WS_USER_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"

# Intelligence thresholds
WHALE_THRESHOLD = 10000  # $10,000+ trades are whales
IMBALANCE_ALERT_THRESHOLD = 0.6  # 60% imbalance triggers alert
SPREAD_ALERT_THRESHOLD = 0.05  # 5% spread change triggers alert
PRICE_CHANGE_ALERT = 0.02  # 2% price change triggers alert


class WebSocketWorker:
    """
    Wolf Pack Real-Time Intelligence
    - Live order book updates with depth analysis
    - Real-time price tracking with significant move detection
    - Whale trade detection and tracking
    - Order book imbalance and spread dynamics
    """
    
    def __init__(self):
        self.db = SupabaseClient()
        self.subscribed_tokens: Set[str] = set()
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        self.running = True
        self.last_prices: Dict[str, float] = {}
        self.last_spreads: Dict[str, float] = {}
        self.connection = None
        self.token_to_market: Dict[str, str] = {}  # Cache token -> market mapping
        
    async def get_top_market_tokens(self, limit: int = 100) -> List[str]:
        """Get token IDs for top markets by volume"""
        try:
            markets = self.db.get_markets(limit=limit)
            tokens = []
            
            for market in markets:
                condition_id = market.get('condition_id')
                raw_data = market.get('raw_data', {})
                
                # Try clobTokenIds first
                clob_tokens = raw_data.get('clobTokenIds', [])
                if isinstance(clob_tokens, str):
                    try:
                        clob_tokens = json.loads(clob_tokens)
                    except:
                        clob_tokens = []
                
                if clob_tokens:
                    for token in clob_tokens:
                        tokens.append(token)
                        if condition_id:
                            self.token_to_market[token] = condition_id
                    continue
                
                # Try stored_tokens
                stored_tokens = raw_data.get('stored_tokens', [])
                if stored_tokens:
                    for token in stored_tokens:
                        tokens.append(token)
                        if condition_id:
                            self.token_to_market[token] = condition_id
                    continue
                
                # Try tokens field
                market_tokens = market.get('tokens', [])
                if isinstance(market_tokens, str):
                    try:
                        market_tokens = json.loads(market_tokens)
                    except:
                        market_tokens = []
                
                if market_tokens:
                    for token in market_tokens:
                        tokens.append(token)
                        if condition_id:
                            self.token_to_market[token] = condition_id
            
            # Remove duplicates and empty strings
            unique_tokens = list(set([t for t in tokens if t and isinstance(t, str)]))
            logger.info(f"Found {len(unique_tokens)} unique tokens from {len(markets)} markets")
            return unique_tokens[:200]  # Limit to 200 tokens
            
        except Exception as e:
            logger.error(f"Error getting market tokens: {e}")
            return []
    
    def _get_market_id_for_token(self, token_id: str) -> Optional[str]:
        """Get market condition_id for a token (uses cache)"""
        # Check cache first
        if token_id in self.token_to_market:
            return self.token_to_market[token_id]
        
        try:
            markets = self.db.get_markets(limit=500)
            for market in markets:
                condition_id = market.get('condition_id')
                raw_data = market.get('raw_data', {})
                
                clob_tokens = raw_data.get('clobTokenIds', [])
                if isinstance(clob_tokens, str):
                    try:
                        clob_tokens = json.loads(clob_tokens)
                    except:
                        clob_tokens = []
                
                if token_id in clob_tokens:
                    self.token_to_market[token_id] = condition_id
                    return condition_id
                
                stored_tokens = raw_data.get('stored_tokens', [])
                if token_id in stored_tokens:
                    self.token_to_market[token_id] = condition_id
                    return condition_id
            
            return None
        except Exception as e:
            logger.error(f"Error finding market for token {token_id}: {e}")
            return None
    
    async def handle_price_change(self, data: Dict):
        """Handle price change event with significant move detection"""
        try:
            token_id = data.get('asset_id') or data.get('token_id')
            price = data.get('price')
            
            if not token_id or price is None:
                return
            
            price = float(price)
            
            # Check for significant price change
            if token_id in self.last_prices:
                old_price = self.last_prices[token_id]
                if old_price > 0:
                    change_pct = ((price - old_price) / old_price) * 100
                    
                    if abs(change_pct) > PRICE_CHANGE_ALERT * 100:
                        direction = "📈" if change_pct > 0 else "📉"
                        logger.info(f"{direction} Price Move: {token_id[:16]}... {old_price:.4f} -> {price:.4f} ({change_pct:+.2f}%)")
                        
                        # Find market and create signal
                        market_id = self._get_market_id_for_token(token_id)
                        if market_id:
                            self.db.insert_signal({
                                'market_id': market_id,
                                'type': 'price_move',
                                'title': f"Price {'Surge' if change_pct > 0 else 'Drop'} Detected",
                                'description': f"Real-time price moved {change_pct:+.2f}%",
                                'severity': 'high' if abs(change_pct) > 5 else 'medium',
                                'data': {
                                    'old_price': old_price,
                                    'new_price': price,
                                    'change_percent': change_pct
                                }
                            })
            
            self.last_prices[token_id] = price
            
            # Find market and update price
            market_id = self._get_market_id_for_token(token_id)
            if market_id:
                self.db.insert_price(market_id, 0, price)
                
        except Exception as e:
            logger.error(f"Error handling price change: {e}")
    
    async def handle_trade(self, data: Dict):
        """Handle trade event - detect whales and track flow"""
        try:
            token_id = data.get('asset_id') or data.get('token_id')
            price = float(data.get('price', 0))
            size = float(data.get('size', 0))
            side = data.get('side', 'UNKNOWN')
            maker = data.get('maker', '')
            taker = data.get('taker', '')
            timestamp = data.get('timestamp') or datetime.utcnow().isoformat()
            
            # Calculate trade value
            trade_value = price * size
            is_whale = trade_value >= WHALE_THRESHOLD
            
            if is_whale:
                direction = "🟢" if side == 'BUY' else "🔴"
                logger.info(f"🐋 WHALE TRADE: {direction} {side} ${trade_value:,.2f} on {token_id[:16]}...")
            
            # Find market
            market_id = self._get_market_id_for_token(token_id)
            if not market_id:
                return
            
            # Insert trade
            self.db.insert_trade({
                'market_id': market_id,
                'token_id': token_id,
                'price': price,
                'size': size,
                'side': side,
                'maker': maker,
                'taker': taker,
                'timestamp': timestamp,
                'is_whale': is_whale
            })
            
            # Create whale signal
            if is_whale:
                self.db.insert_signal({
                    'market_id': market_id,
                    'type': 'whale_trade',
                    'title': f"Whale {side} Detected",
                    'description': f"${trade_value:,.0f} {side.lower()} executed",
                    'severity': 'high',
                    'data': {
                        'price': price,
                        'size': size,
                        'value': trade_value,
                        'side': side,
                        'maker': maker[:20] if maker else '',
                        'taker': taker[:20] if taker else ''
                    }
                })
            
        except Exception as e:
            logger.error(f"Error handling trade: {e}")
    
    async def handle_book_update(self, data: Dict):
        """Handle order book update with depth/imbalance analysis"""
        try:
            token_id = data.get('asset_id') or data.get('token_id')
            bids = data.get('bids', [])
            asks = data.get('asks', [])
            
            if not token_id:
                return
            
            # Find market
            market_id = self._get_market_id_for_token(token_id)
            if not market_id:
                return
            
            # Parse bids/asks
            parsed_bids = []
            for bid in bids[:20]:  # Top 20 levels
                if isinstance(bid, dict):
                    parsed_bids.append({
                        'price': float(bid.get('price', 0)),
                        'size': float(bid.get('size', 0))
                    })
                elif isinstance(bid, list) and len(bid) >= 2:
                    parsed_bids.append({
                        'price': float(bid[0]),
                        'size': float(bid[1])
                    })
            
            parsed_asks = []
            for ask in asks[:20]:
                if isinstance(ask, dict):
                    parsed_asks.append({
                        'price': float(ask.get('price', 0)),
                        'size': float(ask.get('size', 0))
                    })
                elif isinstance(ask, list) and len(ask) >= 2:
                    parsed_asks.append({
                        'price': float(ask[0]),
                        'size': float(ask[1])
                    })
            
            # Update order book in database
            if not parsed_bids and not parsed_asks:
                return
            
            self.db.insert_orderbook(market_id, parsed_bids, parsed_asks)
            
            # Calculate order book intelligence
            best_bid = parsed_bids[0]['price'] if parsed_bids else 0
            best_ask = parsed_asks[0]['price'] if parsed_asks else 0
            spread = best_ask - best_bid if best_ask and best_bid else 0
            
            # Calculate depth within 10% of midpoint
            midpoint = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
            bid_depth_10 = sum(b['size'] * b['price'] for b in parsed_bids 
                               if b['price'] >= midpoint * 0.9) if midpoint else 0
            ask_depth_10 = sum(a['size'] * a['price'] for a in parsed_asks 
                               if a['price'] <= midpoint * 1.1) if midpoint else 0
            
            # Calculate imbalance
            total_depth = bid_depth_10 + ask_depth_10
            imbalance = (bid_depth_10 - ask_depth_10) / total_depth if total_depth > 0 else 0
            
            # Store snapshot for intelligence
            self.db.insert_orderbook_snapshot({
                'market_id': market_id,
                'bid_depth_10': bid_depth_10,
                'ask_depth_10': ask_depth_10,
                'spread': spread,
                'imbalance': imbalance,
                'best_bid': best_bid,
                'best_ask': best_ask
            })
            
            # Alert on significant imbalance
            if abs(imbalance) > IMBALANCE_ALERT_THRESHOLD:
                direction = "BULLISH" if imbalance > 0 else "BEARISH"
                logger.info(f"📊 Order Book Imbalance: {direction} {imbalance:.2f} on {token_id[:16]}...")
                
                self.db.insert_signal({
                    'market_id': market_id,
                    'type': 'orderbook_imbalance',
                    'title': f"Strong {direction} Order Book",
                    'description': f"Order book shows {abs(imbalance)*100:.0f}% {direction.lower()} imbalance",
                    'severity': 'medium',
                    'data': {
                        'imbalance': imbalance,
                        'bid_depth': bid_depth_10,
                        'ask_depth': ask_depth_10,
                        'spread': spread
                    }
                })
            
            # Check for spread changes
            if token_id in self.last_spreads and spread > 0:
                old_spread = self.last_spreads[token_id]
                if old_spread > 0:
                    spread_change = (spread - old_spread) / old_spread
                    if abs(spread_change) > SPREAD_ALERT_THRESHOLD:
                        logger.info(f"Spread change: {token_id[:16]}... {spread_change:+.1%}")
            
            self.last_spreads[token_id] = spread
                
        except Exception as e:
            logger.error(f"Error handling book update: {e}")
    
    async def handle_message(self, message: str):
        """Route incoming WebSocket messages"""
        try:
            data = json.loads(message)
            event_type = data.get('event_type') or data.get('type') or data.get('channel')
            
            if event_type in ['price_change', 'price']:
                await self.handle_price_change(data)
            elif event_type in ['trade', 'last_trade_price']:
                await self.handle_trade(data)
            elif event_type in ['book', 'book_update', 'orderbook']:
                await self.handle_book_update(data)
            else:
                # Log unknown event types for debugging
                if event_type and event_type not in ['heartbeat', 'ping', 'pong', 'subscribed']:
                    logger.debug(f"Unknown event type: {event_type}")
                    
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON message: {message[:100]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def subscribe_to_markets(self, websocket, token_ids: List[str]):
        """Subscribe to market channels for given tokens"""
        for token_id in token_ids:
            if token_id in self.subscribed_tokens:
                continue
            
            try:
                # Subscribe message format per Polymarket docs
                subscribe_msg = {
                    "type": "subscribe",
                    "channel": "market",
                    "assets_ids": [token_id]
                }
                await websocket.send(json.dumps(subscribe_msg))
                self.subscribed_tokens.add(token_id)
                
            except Exception as e:
                logger.error(f"Error subscribing to {token_id}: {e}")
        
        logger.info(f"Subscribed to {len(self.subscribed_tokens)} market channels")
    
    async def connect_and_listen(self):
        """Main WebSocket connection loop"""
        reconnect_delay = self.reconnect_delay
        
        while self.running:
            try:
                logger.info(f"Connecting to Polymarket WebSocket: {WS_MARKET_URL}")
                
                async with websockets.connect(
                    WS_MARKET_URL,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5
                ) as websocket:
                    self.connection = websocket
                    reconnect_delay = self.reconnect_delay  # Reset on successful connect
                    
                    logger.info("WebSocket connected!")
                    
                    # Get tokens to subscribe to
                    tokens = await self.get_top_market_tokens(limit=100)
                    if tokens:
                        await self.subscribe_to_markets(websocket, tokens)
                    else:
                        logger.warning("No tokens found to subscribe to")
                    
                    # Listen for messages
                    async for message in websocket:
                        await self.handle_message(message)
                        
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}")
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
            
            if self.running:
                logger.info(f"Reconnecting in {reconnect_delay} seconds...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, self.max_reconnect_delay)
                self.subscribed_tokens.clear()
    
    async def refresh_subscriptions(self):
        """Periodically refresh market subscriptions"""
        while self.running:
            await asyncio.sleep(300)  # Every 5 minutes
            
            if self.connection:
                try:
                    tokens = await self.get_top_market_tokens(limit=100)
                    new_tokens = [t for t in tokens if t not in self.subscribed_tokens]
                    
                    if new_tokens:
                        logger.info(f"Adding {len(new_tokens)} new token subscriptions")
                        await self.subscribe_to_markets(self.connection, new_tokens)
                        
                except Exception as e:
                    logger.error(f"Error refreshing subscriptions: {e}")
    
    async def run(self):
        """Run the WebSocket worker"""
        logger.info("Starting WebSocket Worker (Wolf Pack Edition)")
        
        # Run both connection and refresh tasks
        await asyncio.gather(
            self.connect_and_listen(),
            self.refresh_subscriptions()
        )
    
    def stop(self):
        """Stop the worker"""
        self.running = False
        logger.info("Stopping WebSocket Worker")


def main():
    """Entry point"""
    worker = WebSocketWorker()
    
    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        worker.stop()
        logger.info("WebSocket Worker stopped by user")


if __name__ == "__main__":
    main()
