"""
Trades Worker
Fetches recent trades from Polymarket, detects whale trades, calculates trade flow
Per docs: https://docs.polymarket.com/developers/CLOB/trades/trades
"""
import time
import json
import logging
import statistics
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.polymarket_api import PolymarketAPI
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Whale detection thresholds
WHALE_THRESHOLD_USD = 10000  # $10,000+ trades are whales
WHALE_THRESHOLD_STDDEV = 2.0  # Trades > 2 standard deviations from mean

class TradesWorker:
    """Fetches and analyzes trades from Polymarket"""
    
    def __init__(self):
        self.api = PolymarketAPI()
        self.db = SupabaseClient()
        self.scan_interval = 30  # seconds
        self.trade_history: Dict[str, List[float]] = {}  # token_id -> list of trade sizes
        self.last_trade_ids: Dict[str, str] = {}  # token_id -> last processed trade id
        
    def _parse_clob_token_ids(self, tokens) -> List[str]:
        """Parse clobTokenIds which might be a JSON string"""
        if isinstance(tokens, list):
            return [str(t) for t in tokens if t]
        elif isinstance(tokens, str):
            try:
                parsed = json.loads(tokens)
                if isinstance(parsed, list):
                    return [str(t) for t in parsed if t]
            except (json.JSONDecodeError, ValueError):
                pass
        return []
    
    def _get_market_tokens(self, limit: int = 50) -> Dict[str, str]:
        """Get token IDs mapped to their market condition_ids"""
        token_to_market = {}
        
        try:
            markets = self.db.get_markets(limit=limit)
            
            for market in markets:
                condition_id = market.get('condition_id')
                if not condition_id:
                    continue
                
                raw_data = market.get('raw_data', {})
                
                # Try clobTokenIds
                clob_tokens = self._parse_clob_token_ids(raw_data.get('clobTokenIds', []))
                for token in clob_tokens:
                    token_to_market[token] = condition_id
                
                # Try stored_tokens
                stored_tokens = raw_data.get('stored_tokens', [])
                for token in stored_tokens:
                    if token:
                        token_to_market[str(token)] = condition_id
                
                # Try tokens field
                market_tokens = self._parse_clob_token_ids(market.get('tokens', []))
                for token in market_tokens:
                    token_to_market[token] = condition_id
            
            logger.info(f"Found {len(token_to_market)} tokens from {len(markets)} markets")
            return token_to_market
            
        except Exception as e:
            logger.error(f"Error getting market tokens: {e}")
            return {}
    
    def _is_whale_trade(self, token_id: str, size: float, price: float) -> bool:
        """
        Determine if a trade is a whale trade based on:
        1. Absolute value threshold (>$10k)
        2. Statistical outlier (>2 std devs from mean for this token)
        """
        trade_value = size * price
        
        # Check absolute threshold
        if trade_value >= WHALE_THRESHOLD_USD:
            return True
        
        # Check statistical outlier
        if token_id in self.trade_history and len(self.trade_history[token_id]) >= 10:
            history = self.trade_history[token_id]
            mean = statistics.mean(history)
            stdev = statistics.stdev(history) if len(history) > 1 else 0
            
            if stdev > 0 and trade_value > mean + (WHALE_THRESHOLD_STDDEV * stdev):
                return True
        
        return False
    
    def _update_trade_history(self, token_id: str, trade_value: float):
        """Maintain rolling history of trade sizes for statistical analysis"""
        if token_id not in self.trade_history:
            self.trade_history[token_id] = []
        
        self.trade_history[token_id].append(trade_value)
        
        # Keep only last 100 trades
        if len(self.trade_history[token_id]) > 100:
            self.trade_history[token_id] = self.trade_history[token_id][-100:]
    
    def fetch_and_process_trades(self):
        """Fetch recent trades and process them"""
        try:
            logger.info("Starting trade fetch...")
            
            token_to_market = self._get_market_tokens(limit=50)
            if not token_to_market:
                logger.warning("No tokens found for trade fetching")
                return
            
            total_trades = 0
            whale_trades = 0
            
            for token_id, market_id in token_to_market.items():
                try:
                    # Fetch trades from API
                    trades = self.api.get_trades(token_id, limit=50)
                    
                    if not trades:
                        continue
                    
                    for trade in trades:
                        # Skip if we've already processed this trade
                        trade_id = trade.get('id') or trade.get('trade_id')
                        if trade_id and self.last_trade_ids.get(token_id) == trade_id:
                            break
                        
                        # Extract trade data
                        price = float(trade.get('price', 0))
                        size = float(trade.get('size', 0))
                        side = trade.get('side', 'UNKNOWN')
                        maker = trade.get('maker', '')
                        taker = trade.get('taker', '')
                        timestamp = trade.get('timestamp') or trade.get('match_time')
                        
                        if price <= 0 or size <= 0:
                            continue
                        
                        trade_value = price * size
                        
                        # Check for whale
                        is_whale = self._is_whale_trade(token_id, size, price)
                        
                        if is_whale:
                            whale_trades += 1
                            logger.info(f"🐋 WHALE: {side} ${trade_value:,.2f} on {token_id[:16]}...")
                            
                            # Create a signal for whale trades
                            self.db.insert_signal({
                                'market_id': market_id,
                                'type': 'Whale Trade',
                                'title': f"Whale {side} Detected",
                                'description': f"Large {side.lower()} of ${trade_value:,.0f} detected",
                                'severity': 'high',
                                'data': {
                                    'size': size,
                                    'price': price,
                                    'value': trade_value,
                                    'side': side
                                }
                            })
                        
                        # Store trade
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
                        
                        # Update history for statistical analysis
                        self._update_trade_history(token_id, trade_value)
                        total_trades += 1
                    
                    # Update last processed trade ID
                    if trades and trades[0].get('id'):
                        self.last_trade_ids[token_id] = trades[0].get('id')
                    
                except Exception as e:
                    logger.error(f"Error processing trades for {token_id}: {e}")
                    continue
            
            logger.info(f"Processed {total_trades} trades, {whale_trades} whale trades detected")
            
        except Exception as e:
            logger.error(f"Error in trade fetch: {e}", exc_info=True)
    
    def calculate_market_flow(self):
        """Calculate buy/sell pressure for all markets and update stats"""
        try:
            markets = self.db.get_markets(limit=100)
            
            for market in markets:
                condition_id = market.get('condition_id')
                if not condition_id:
                    continue
                
                flow = self.db.get_trade_flow(condition_id, hours=24)
                
                # Update market stats with buy/sell pressure
                self.db.upsert_market_stats(condition_id, {
                    'buy_pressure': flow.get('buy_pressure', 50),
                    'sell_pressure': 100 - flow.get('buy_pressure', 50)
                })
                
        except Exception as e:
            logger.error(f"Error calculating market flow: {e}")
    
    def detect_smart_money(self):
        """
        Identify smart money patterns:
        - Wallets that consistently profit
        - Coordinated buying/selling
        - Unusual timing patterns
        """
        try:
            # Get whale trades from last 24 hours
            whale_trades = self.db.get_whale_trades(limit=100)
            
            if not whale_trades:
                return
            
            # Group by maker/taker addresses
            address_trades: Dict[str, List] = {}
            
            for trade in whale_trades:
                maker = trade.get('maker', '')
                taker = trade.get('taker', '')
                
                if maker:
                    if maker not in address_trades:
                        address_trades[maker] = []
                    address_trades[maker].append(trade)
                
                if taker:
                    if taker not in address_trades:
                        address_trades[taker] = []
                    address_trades[taker].append(trade)
            
            # Find addresses with multiple whale trades (potential smart money)
            for address, trades in address_trades.items():
                if len(trades) >= 3:  # At least 3 whale trades
                    total_value = sum(
                        float(t.get('size', 0)) * float(t.get('price', 0)) 
                        for t in trades
                    )
                    logger.info(f"🧠 Smart Money Candidate: {address[:16]}... - {len(trades)} whale trades, ${total_value:,.0f} total")
                    
        except Exception as e:
            logger.error(f"Error detecting smart money: {e}")
    
    def run(self):
        """Main worker loop"""
        logger.info("Trades Worker started")
        
        while True:
            try:
                # Fetch and process trades
                self.fetch_and_process_trades()
                
                # Calculate market flow every cycle
                self.calculate_market_flow()
                
                # Detect smart money patterns (less frequently)
                self.detect_smart_money()
                
            except Exception as e:
                logger.error(f"Fatal error in trades worker: {e}", exc_info=True)
            
            logger.info(f"Sleeping for {self.scan_interval} seconds...")
            time.sleep(self.scan_interval)


if __name__ == "__main__":
    worker = TradesWorker()
    worker.run()



