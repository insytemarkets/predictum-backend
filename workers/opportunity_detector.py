"""
Opportunity Detector Worker
Analyzes market data to detect arbitrage, spreads, and negative risk opportunities
"""
import time
import logging
from typing import Dict, List, Optional
from services.polymarket_api import PolymarketAPI
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OpportunityDetector:
    def __init__(self):
        self.api = PolymarketAPI()
        self.db = SupabaseClient()
        self.scan_interval = 60  # seconds
    
    def detect_opportunities(self):
        """Analyze markets and detect opportunities"""
        try:
            logger.info("Starting opportunity detection...")
            
            # Get active markets
            markets = self.db.get_markets(limit=100)
            
            if not markets:
                logger.warning("No markets found for opportunity detection")
                return
            
            opportunities_found = 0
            
            # Collect all tokens for batch fetching
            market_tokens_map = {}  # {condition_id: [tokens]}
            all_tokens = []
            
            for market in markets:
                condition_id = market.get('condition_id')
                if not condition_id:
                    continue
                
                # Get tokens for this market
                tokens = market.get('tokens') or []
                if not tokens:
                    # Try extracting from raw_data
                    raw_data = market.get('raw_data', {})
                    if 'stored_tokens' in raw_data:
                        tokens = raw_data['stored_tokens']
                    elif 'tokens' in raw_data:
                        tokens = raw_data['tokens']
                    else:
                        tokens = self.api.get_market_tokens(condition_id)
                
                if tokens and len(tokens) >= 2:
                    market_tokens_map[condition_id] = tokens[:2]  # YES and NO
                    all_tokens.extend(tokens[:2])
            
            if not all_tokens:
                logger.warning("No tokens found for opportunity detection")
                return
            
            # Batch fetch order books
            logger.info(f"Batch fetching {len(all_tokens)} order books for opportunity detection...")
            orderbooks_list = self.api.get_orderbooks_batch(all_tokens)
            
            # Map orderbooks back to markets
            token_to_orderbook = {}
            for idx, orderbook in enumerate(orderbooks_list):
                if idx < len(all_tokens):
                    token_id = all_tokens[idx]
                    token_to_orderbook[token_id] = orderbook
            
            # Process each market
            for market in markets:
                try:
                    condition_id = market.get('condition_id')
                    if not condition_id or condition_id not in market_tokens_map:
                        continue
                    
                    tokens = market_tokens_map[condition_id]
                    
                    # Get orderbooks for this market's tokens
                    orderbooks = {}
                    for token in tokens:
                        if token in token_to_orderbook:
                            orderbooks[token] = token_to_orderbook[token]
                    
                    if len(orderbooks) < 2:
                        continue
                    
                    # Detect spread opportunities
                    spread_opp = self._detect_spread(market, orderbooks)
                    if spread_opp:
                        self.db.upsert_opportunity(spread_opp)
                        opportunities_found += 1
                    
                    # Detect arbitrage opportunities
                    arb_opp = self._detect_arbitrage(market, orderbooks)
                    if arb_opp:
                        self.db.upsert_opportunity(arb_opp)
                        opportunities_found += 1
                    
                    # Detect negative risk (sum of probabilities > 100%)
                    neg_risk_opp = self._detect_negative_risk(market, orderbooks)
                    if neg_risk_opp:
                        self.db.upsert_opportunity(neg_risk_opp)
                        opportunities_found += 1
                    
                    # No delay needed - batch processing is efficient
                    
                except Exception as e:
                    logger.error(f"Error detecting opportunities for market {market.get('condition_id')}: {e}")
                    continue
            
            logger.info(f"Detected {opportunities_found} opportunities")
            
        except Exception as e:
            logger.error(f"Error in opportunity detection: {e}", exc_info=True)
    
    def _extract_tokens_from_market(self, market_data: dict) -> List[str]:
        """Extract token IDs from market data"""
        tokens = []
        
        if isinstance(market_data, dict):
            # Check tokens array
            if 'tokens' in market_data:
                for token in market_data['tokens']:
                    if isinstance(token, dict):
                        token_id = token.get('token_id') or token.get('id') or token.get('address')
                        if token_id:
                            tokens.append(str(token_id))
                    elif isinstance(token, str):
                        tokens.append(token)
            
            # Check outcomes
            if 'outcomes' in market_data:
                for outcome in market_data['outcomes']:
                    if isinstance(outcome, dict):
                        token_id = outcome.get('token_id') or outcome.get('id')
                        if token_id:
                            tokens.append(str(token_id))
        
        return list(set(tokens))  # Remove duplicates
    
    def _detect_spread(self, market: dict, orderbooks: dict) -> Optional[dict]:
        """Detect spread opportunities (wide bid-ask spreads)"""
        try:
            if not orderbooks or len(orderbooks) == 0:
                return None
            
            # Get best bid and ask from order books
            # Prices are already parsed as floats from API client
            best_bids = []
            best_asks = []
            
            for token_id, orderbook in orderbooks.items():
                bids = orderbook.get('bids', [])
                asks = orderbook.get('asks', [])
                
                if bids and len(bids) > 0:
                    # Bids are usually sorted highest first
                    best_bid = bids[0].get('price', 0) if isinstance(bids[0], dict) else float(bids[0]) if isinstance(bids[0], (int, float)) else 0
                    if best_bid > 0:
                        best_bids.append(best_bid)
                
                if asks and len(asks) > 0:
                    # Asks are usually sorted lowest first
                    best_ask = asks[0].get('price', 0) if isinstance(asks[0], dict) else float(asks[0]) if isinstance(asks[0], (int, float)) else 0
                    if best_ask > 0:
                        best_asks.append(best_ask)
            
            if not best_bids or not best_asks:
                return None
            
            # Calculate spread
            max_bid = max(best_bids)
            min_ask = min(best_asks)
            
            if min_ask <= 0 or max_bid <= 0:
                return None
            
            spread = min_ask - max_bid
            spread_percentage = (spread / min_ask) * 100 if min_ask > 0 else 0
            
            # Only flag as opportunity if spread is significant (> 1%)
            if spread_percentage > 1.0:
                # Calculate profit potential based on spread
                # More conservative for smaller spreads
                if spread_percentage > 5.0:
                    profit_potential = spread_percentage * 0.6
                elif spread_percentage > 2.0:
                    profit_potential = spread_percentage * 0.5
                else:
                    profit_potential = spread_percentage * 0.4
                
                # Calculate confidence based on liquidity and order book depth
                volume = market.get('volume_24h', 0) or 0
                liquidity = market.get('liquidity', 0) or 0
                
                # Base confidence on liquidity
                base_confidence = 50
                liquidity_bonus = min(30, (liquidity / 100000) * 5)
                
                # Bonus for larger spreads (more reliable)
                spread_bonus = min(15, spread_percentage * 2)
                
                confidence = min(95, base_confidence + liquidity_bonus + spread_bonus)
                
                return {
                    'market_id': market.get('condition_id'),
                    'type': 'Spread',
                    'profit_potential': round(profit_potential, 2),
                    'confidence_score': round(confidence, 1),
                    'details': {
                        'spread_percentage': round(spread_percentage, 2),
                        'best_bid': round(max_bid, 4),
                        'best_ask': round(min_ask, 4),
                        'volume_24h': volume,
                        'liquidity': liquidity,
                        'order_book_depth': len(best_bids) + len(best_asks)
                    },
                    'status': 'active'
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error detecting spread: {e}", exc_info=True)
            return None
    
    def _detect_arbitrage(self, market: dict, orderbooks: dict) -> Optional[dict]:
        """Detect arbitrage opportunities across tokens"""
        try:
            if not orderbooks or len(orderbooks) < 2:
                return None
            
            # For binary markets, arbitrage exists if YES + NO prices don't sum to ~1.0
            prices = []
            for token_id, orderbook in orderbooks.items():
                bids = orderbook.get('bids', [])
                asks = orderbook.get('asks', [])
                
                if bids and asks and len(bids) > 0 and len(asks) > 0:
                    # Prices are already floats from API client
                    bid_price = bids[0].get('price', 0) if isinstance(bids[0], dict) else float(bids[0]) if isinstance(bids[0], (int, float)) else 0
                    ask_price = asks[0].get('price', 0) if isinstance(asks[0], dict) else float(asks[0]) if isinstance(asks[0], (int, float)) else 0
                    
                    if bid_price > 0 and ask_price > 0:
                        mid_price = (bid_price + ask_price) / 2
                        prices.append(mid_price)
            
            if len(prices) < 2:
                return None
            
            # Sum of probabilities should be ~1.0 for binary markets
            total_probability = sum(prices)
            
            # Arbitrage exists if sum is significantly different from 1.0
            deviation = abs(total_probability - 1.0)
            
            if deviation > 0.02:  # 2% deviation threshold
                # Calculate profit potential
                # Can buy all outcomes for total_probability, sell for 1.0
                profit_potential = deviation * 100  # Convert to percentage
                
                # Higher confidence if deviation is larger and liquidity is good
                volume = market.get('volume_24h', 0) or 0
                liquidity = market.get('liquidity', 0) or 0
                
                base_confidence = 60
                deviation_bonus = min(20, deviation * 500)  # Up to 20% for large deviations
                liquidity_bonus = min(15, (liquidity / 200000) * 5)  # Up to 15% for high liquidity
                
                confidence = min(95, base_confidence + deviation_bonus + liquidity_bonus)
                
                return {
                    'market_id': market.get('condition_id'),
                    'type': 'Arbitrage',
                    'profit_potential': round(profit_potential, 2),
                    'confidence_score': round(confidence, 1),
                    'details': {
                        'total_probability': round(total_probability, 4),
                        'deviation': round(deviation, 4),
                        'prices': [round(p, 4) for p in prices],
                        'volume_24h': volume,
                        'liquidity': liquidity
                    },
                    'status': 'active'
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error detecting arbitrage: {e}", exc_info=True)
            return None
    
    def _detect_negative_risk(self, market: dict, orderbooks: dict) -> Optional[dict]:
        """Detect negative risk opportunities (sum of probabilities > 100%)"""
        try:
            if not orderbooks or len(orderbooks) < 2:
                return None
            
            # Sum all outcome probabilities
            total_probability = 0
            prices = []
            
            for token_id, orderbook in orderbooks.items():
                bids = orderbook.get('bids', [])
                asks = orderbook.get('asks', [])
                
                if bids and asks and len(bids) > 0 and len(asks) > 0:
                    # Prices are already floats from API client
                    bid_price = bids[0].get('price', 0) if isinstance(bids[0], dict) else float(bids[0]) if isinstance(bids[0], (int, float)) else 0
                    ask_price = asks[0].get('price', 0) if isinstance(asks[0], dict) else float(asks[0]) if isinstance(asks[0], (int, float)) else 0
                    
                    if bid_price > 0 and ask_price > 0:
                        mid_price = (bid_price + ask_price) / 2
                        prices.append(mid_price)
                        total_probability += mid_price
            
            if total_probability > 1.0:
                # Negative risk opportunity - can buy all outcomes for less than $1
                excess = total_probability - 1.0
                profit_potential = excess * 100  # Convert to percentage
                
                # Higher confidence for larger excess and good liquidity
                volume = market.get('volume_24h', 0) or 0
                liquidity = market.get('liquidity', 0) or 0
                
                base_confidence = 70
                excess_bonus = min(20, excess * 400)  # Up to 20% for large excess
                liquidity_bonus = min(5, (liquidity / 500000) * 2)  # Small bonus for liquidity
                
                confidence = min(95, base_confidence + excess_bonus + liquidity_bonus)
                
                return {
                    'market_id': market.get('condition_id'),
                    'type': 'negative_risk',
                    'profit_potential': round(profit_potential, 2),
                    'confidence_score': round(confidence, 1),
                    'details': {
                        'total_probability': round(total_probability, 4),
                        'excess': round(excess, 4),
                        'prices': [round(p, 4) for p in prices],
                        'volume_24h': volume,
                        'liquidity': liquidity
                    },
                    'status': 'active'
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error detecting negative risk: {e}", exc_info=True)
            return None
    
    def run(self):
        """Main worker loop"""
        logger.info("Opportunity Detector Worker started")
        while True:
            try:
                self.detect_opportunities()
            except Exception as e:
                logger.error(f"Fatal error in opportunity detector: {e}", exc_info=True)
            
            logger.info(f"Sleeping for {self.scan_interval} seconds...")
            time.sleep(self.scan_interval)

if __name__ == "__main__":
    detector = OpportunityDetector()
    detector.run()
