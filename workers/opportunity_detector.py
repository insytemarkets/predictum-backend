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
            
            for market in markets:
                try:
                    condition_id = market.get('condition_id')
                    if not condition_id:
                        continue
                    
                    # Get market details including tokens and prices
                    market_details = self.api.get_market_details(condition_id)
                    if not market_details:
                        continue
                    
                    # Get tokens for this market
                    tokens = self.api.get_market_tokens(condition_id)
                    if not tokens or len(tokens) < 2:
                        # Try extracting from raw_data
                        raw_data = market.get('raw_data', {})
                        tokens = self._extract_tokens_from_market(raw_data)
                    
                    if not tokens or len(tokens) < 2:
                        continue
                    
                    # Fetch order books for both tokens (YES and NO)
                    orderbooks = {}
                    for token in tokens[:2]:  # Usually YES and NO tokens
                        orderbook = self.api.get_orderbook(token)
                        if orderbook:
                            orderbooks[token] = orderbook
                    
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
                    
                    # Small delay to respect rate limits
                    time.sleep(0.5)
                    
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
            if len(orderbooks) < 2:
                return None
            
            # Get best bid and ask from order books
            best_bids = []
            best_asks = []
            
            for token_id, orderbook in orderbooks.items():
                bids = orderbook.get('bids', [])
                asks = orderbook.get('asks', [])
                
                if bids:
                    # Bids are usually sorted highest first
                    best_bid = float(bids[0].get('price', 0) if isinstance(bids[0], dict) else bids[0])
                    best_bids.append(best_bid)
                
                if asks:
                    # Asks are usually sorted lowest first
                    best_ask = float(asks[0].get('price', 0) if isinstance(asks[0], dict) else asks[0])
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
                # Calculate profit potential (simplified)
                profit_potential = spread_percentage * 0.5  # Conservative estimate
                
                # Calculate confidence based on liquidity
                volume = market.get('volume_24h', 0) or 0
                liquidity = market.get('liquidity', 0) or 0
                confidence = min(95, 50 + (liquidity / 100000) * 5)  # Scale confidence with liquidity
                
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
                        'liquidity': liquidity
                    },
                    'status': 'active'
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error detecting spread: {e}")
            return None
    
    def _detect_arbitrage(self, market: dict, orderbooks: dict) -> Optional[dict]:
        """Detect arbitrage opportunities across tokens"""
        try:
            if len(orderbooks) < 2:
                return None
            
            # For binary markets, arbitrage exists if YES + NO prices don't sum to ~1.0
            prices = []
            for token_id, orderbook in orderbooks.items():
                bids = orderbook.get('bids', [])
                asks = orderbook.get('asks', [])
                
                if bids and asks:
                    mid_price = (float(bids[0].get('price', 0) if isinstance(bids[0], dict) else bids[0]) + 
                                float(asks[0].get('price', 0) if isinstance(asks[0], dict) else asks[0])) / 2
                    prices.append(mid_price)
            
            if len(prices) < 2:
                return None
            
            # Sum of probabilities should be ~1.0 for binary markets
            total_probability = sum(prices)
            
            # Arbitrage exists if sum is significantly different from 1.0
            deviation = abs(total_probability - 1.0)
            
            if deviation > 0.02:  # 2% deviation threshold
                # Calculate profit potential
                profit_potential = deviation * 100  # Convert to percentage
                
                # Higher confidence if deviation is larger
                confidence = min(95, 60 + (deviation * 1000))
                
                return {
                    'market_id': market.get('condition_id'),
                    'type': 'Arbitrage',
                    'profit_potential': round(profit_potential, 2),
                    'confidence_score': round(confidence, 1),
                    'details': {
                        'total_probability': round(total_probability, 4),
                        'deviation': round(deviation, 4),
                        'prices': [round(p, 4) for p in prices],
                        'volume_24h': market.get('volume_24h', 0) or 0
                    },
                    'status': 'active'
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error detecting arbitrage: {e}")
            return None
    
    def _detect_negative_risk(self, market: dict, orderbooks: dict) -> Optional[dict]:
        """Detect negative risk opportunities (sum of probabilities > 100%)"""
        try:
            if len(orderbooks) < 2:
                return None
            
            # Sum all outcome probabilities
            total_probability = 0
            prices = []
            
            for token_id, orderbook in orderbooks.items():
                bids = orderbook.get('bids', [])
                asks = orderbook.get('asks', [])
                
                if bids and asks:
                    mid_price = (float(bids[0].get('price', 0) if isinstance(bids[0], dict) else bids[0]) + 
                                float(asks[0].get('price', 0) if isinstance(asks[0], dict) else asks[0])) / 2
                    prices.append(mid_price)
                    total_probability += mid_price
            
            if total_probability > 1.0:
                # Negative risk opportunity - can buy all outcomes for less than $1
                excess = total_probability - 1.0
                profit_potential = excess * 100  # Convert to percentage
                
                # Higher confidence for larger excess
                confidence = min(95, 70 + (excess * 500))
                
                return {
                    'market_id': market.get('condition_id'),
                    'type': 'negative_risk',
                    'profit_potential': round(profit_potential, 2),
                    'confidence_score': round(confidence, 1),
                    'details': {
                        'total_probability': round(total_probability, 4),
                        'excess': round(excess, 4),
                        'prices': [round(p, 4) for p in prices],
                        'volume_24h': market.get('volume_24h', 0) or 0
                    },
                    'status': 'active'
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error detecting negative risk: {e}")
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
