"""
WebSocket Worker for Real-Time Polymarket Data
Connects to Polymarket WebSocket for live order book, price, and trade updates
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

# Whale detection threshold (in USDC)
WHALE_THRESHOLD = 10000  # $10,000+ trades are whales

class WebSocketWorker:
    """Real-time WebSocket connection to Polymarket"""
    
    def __init__(self):
        self.db = SupabaseClient()
        self.subscribed_tokens: Set[str] = set()
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        self.running = True
        self.last_prices: Dict[str, float] = {}
        self.connection = None
        
    async def get_top_market_tokens(self, limit: int = 100) -> List[str]:
        """Get token IDs for top markets by volume"""
        try:
            markets = self.db.get_markets(limit=limit)
            tokens = []
            
            for market in markets:
                # Extract tokens from raw_data
                raw_data = market.get('raw_data', {})
                
                # Try clobTokenIds first
                clob_tokens = raw_data.get('clobTokenIds', [])
                if isinstance(clob_tokens, str):
                    try:
                        clob_tokens = json.loads(clob_tokens)
                    except:
                        clob_tokens = []
                
                if clob_tokens:
                    tokens.extend(clob_tokens)
                    continue
                
                # Try stored_tokens
                stored_tokens = raw_data.get('stored_tokens', [])
                if stored_tokens:
                    tokens.extend(stored_tokens)
                    continue
                
                # Try tokens field
                market_tokens = market.get('tokens', [])
                if isinstance(market_tokens, str):
                    try:
                        market_tokens = json.loads(market_tokens)
                    except:
                        market_tokens = []
                
                if market_tokens:
                    tokens.extend(market_tokens)
            
            # Remove duplicates and empty strings
            unique_tokens = list(set([t for t in tokens if t and isinstance(t, str)]))
            logger.info(f"Found {len(unique_tokens)} unique tokens from {len(markets)} markets")
            return unique_tokens[:200]  # Limit to 200 tokens
            
        except Exception as e:
            logger.error(f"Error getting market tokens: {e}")
            return []
    
    def _get_market_id_for_token(self, token_id: str) -> Optional[str]:
        """Get market condition_id for a token"""
        try:
            markets = self.db.get_markets(limit=500)
            for market in markets:
                raw_data = market.get('raw_data', {})
                clob_tokens = raw_data.get('clobTokenIds', [])
                if isinstance(clob_tokens, str):
                    try:
                        clob_tokens = json.loads(clob_tokens)
                    except:
                        clob_tokens = []
                
                if token_id in clob_tokens:
                    return market.get('condition_id')
                
                stored_tokens = raw_data.get('stored_tokens', [])
                if token_id in stored_tokens:
                    return market.get('condition_id')
            
            return None
        except Exception as e:
            logger.error(f"Error finding market for token {token_id}: {e}")
            return None
    
    async def handle_price_change(self, data: Dict):
        """Handle price change event"""
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
                    if abs(change_pct) > 2.0:  # 2% change
                        logger.info(f"Significant price change: {token_id} {old_price:.4f} -> {price:.4f} ({change_pct:+.2f}%)")
            
            self.last_prices[token_id] = price
            
            # Find market and update price
            market_id = self._get_market_id_for_token(token_id)
            if market_id:
                # Insert price record
                self.db.insert_price(market_id, 0, price)
                
        except Exception as e:
            logger.error(f"Error handling price change: {e}")
    
    async def handle_trade(self, data: Dict):
        """Handle trade event - detect whales"""
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
                logger.info(f"🐋 WHALE TRADE: {side} ${trade_value:,.2f} on {token_id}")
            
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
            
        except Exception as e:
            logger.error(f"Error handling trade: {e}")
    
    async def handle_book_update(self, data: Dict):
        """Handle order book update"""
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
            if parsed_bids or parsed_asks:
                self.db.insert_orderbook(market_id, parsed_bids, parsed_asks)
                
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
        logger.info("Starting WebSocket Worker")
        
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

