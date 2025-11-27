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
    
    def _parse_clob_token_ids(self, clob_ids) -> List[str]:
        """Parse clobTokenIds which can be a list or a JSON string"""
        import json
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
    
    def detect_opportunities(self):
        """Analyze markets and detect opportunities"""
        try:
            logger.info("Starting opportunity detection...")
            
            # Get active markets
            markets = self.db.get_markets(limit=100)
            
            if not markets:
                logger.warning("No markets found for opportunity detection")
                return
            
            logger.info(f"Analyzing {len(markets)} markets for opportunities...")
            opportunities_found = 0
            
            # PHASE 1: Price-based opportunity detection (uses stored prices, no orderbook needed)
            for market in markets:
                try:
                    condition_id = market.get('condition_id')
                    if not condition_id:
                        continue
                    
                    # Detect opportunities from stored market data
                    price_opp = self._detect_price_based_opportunity(market)
                    if price_opp:
                        result = self.db.upsert_opportunity(price_opp)
                        if result:
                            opportunities_found += 1
                            logger.debug(f"Found {price_opp['type']} opportunity for {condition_id}")
                    
                except Exception as e:
                    logger.error(f"Error in price-based detection for {market.get('condition_id')}: {e}")
                    continue
            
            # PHASE 2: Order book based detection (if tokens available)
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
                    if isinstance(raw_data, dict):
                        tokens = self._parse_clob_token_ids(raw_data.get('clobTokenIds'))
                        if not tokens and 'stored_tokens' in raw_data:
                            tokens = raw_data['stored_tokens']
                
                if tokens and len(tokens) >= 2:
                    market_tokens_map[condition_id] = tokens[:2]
                    all_tokens.extend(tokens[:2])
            
            if all_tokens:
                logger.info(f"Fetching order books for {len(all_tokens)} tokens...")
                orderbooks_list = self.api.get_orderbooks_batch(all_tokens)
                
                # Map orderbooks back to markets
                token_to_orderbook = {}
                for idx, orderbook in enumerate(orderbooks_list):
                    if idx < len(all_tokens) and orderbook:
                        token_id = all_tokens[idx]
                        token_to_orderbook[token_id] = orderbook
                
                # Process each market with orderbook data
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
                        
                        if len(orderbooks) < 1:  # Lower threshold - even 1 orderbook can reveal spread
                            continue
                        
                        # Detect spread opportunities
                        spread_opp = self._detect_spread(market, orderbooks)
                        if spread_opp:
                            result = self.db.upsert_opportunity(spread_opp)
                            if result:
                                opportunities_found += 1
                        
                        # Detect arbitrage opportunities
                        if len(orderbooks) >= 2:
                            arb_opp = self._detect_arbitrage(market, orderbooks)
                            if arb_opp:
                                result = self.db.upsert_opportunity(arb_opp)
                                if result:
                                    opportunities_found += 1
                            
                            # Detect negative risk
                            neg_risk_opp = self._detect_negative_risk(market, orderbooks)
                            if neg_risk_opp:
                                result = self.db.upsert_opportunity(neg_risk_opp)
                                if result:
                                    opportunities_found += 1
                        
                    except Exception as e:
                        logger.error(f"Error in orderbook detection for {market.get('condition_id')}: {e}")
                        continue
            else:
                logger.warning("No tokens found for orderbook-based detection")
            
            logger.info(f"Total opportunities detected: {opportunities_found}")
            
        except Exception as e:
            logger.error(f"Error in opportunity detection: {e}", exc_info=True)
    
    def _detect_price_based_opportunity(self, market: dict) -> Optional[dict]:
        """Detect opportunities from stored market prices (no orderbook needed)"""
        import json
        try:
            raw_data = market.get('raw_data', {})
            if not isinstance(raw_data, dict):
                return None
            
            # Parse outcomePrices (can be JSON string or list)
            outcome_prices = raw_data.get('outcomePrices', [])
            if isinstance(outcome_prices, str):
                try:
                    outcome_prices = json.loads(outcome_prices)
                except:
                    return None
            
            if not outcome_prices or len(outcome_prices) < 2:
                return None
            
            # Convert prices to floats
            prices = []
            for p in outcome_prices:
                try:
                    prices.append(float(p))
                except:
                    continue
            
            if len(prices) < 2:
                return None
            
            # Check for arbitrage: sum should be ~1.0
            total = sum(prices)
            deviation = abs(total - 1.0)
            
            volume = float(market.get('volume_24h') or 0)
            liquidity = float(market.get('liquidity') or 0)
            
            # Arbitrage opportunity if deviation > 1%
            if deviation > 0.01:
                profit_potential = deviation * 100
                confidence = min(90, 50 + (liquidity / 50000) * 10 + (deviation * 200))
                
                return {
                    'market_id': market.get('condition_id'),
                    'type': 'Arbitrage',
                    'profit_potential': round(profit_potential, 2),
                    'confidence_score': round(confidence, 1),
                    'details': {
                        'prices': prices,
                        'total_probability': round(total, 4),
                        'deviation': round(deviation, 4),
                        'volume_24h': volume,
                        'liquidity': liquidity,
                        'source': 'price_based'
                    },
                    'status': 'active'
                }
            
            # Check for spread opportunity (price close to 0.5 with high volume = volatile)
            if len(prices) >= 2:
                mid_price = prices[0]  # YES price typically
                
                # High volume with uncertain price (close to 50%) suggests opportunity
                if volume > 100000 and 0.35 <= mid_price <= 0.65:
                    # Calculate potential based on uncertainty
                    uncertainty = 0.5 - abs(mid_price - 0.5)
                    profit_potential = uncertainty * 10 + (volume / 1000000)
                    confidence = min(85, 40 + (volume / 500000) * 15 + (liquidity / 100000) * 10)
                    
                    if profit_potential > 0.5:
                        return {
                            'market_id': market.get('condition_id'),
                            'type': 'Spread',
                            'profit_potential': round(profit_potential, 2),
                            'confidence_score': round(confidence, 1),
                            'details': {
                                'current_price': round(mid_price, 4),
                                'uncertainty': round(uncertainty, 4),
                                'volume_24h': volume,
                                'liquidity': liquidity,
                                'source': 'price_based'
                            },
                            'status': 'active'
                        }
            
            # Negative risk: if any price is very low but volume is high
            min_price = min(prices)
            if min_price < 0.05 and volume > 50000:
                # Low probability events with high volume can be mispriced
                profit_potential = (0.05 - min_price) * 100 + 0.5
                confidence = min(80, 35 + (volume / 200000) * 15)
                
                return {
                    'market_id': market.get('condition_id'),
                    'type': 'Neg. Risk',
                    'profit_potential': round(profit_potential, 2),
                    'confidence_score': round(confidence, 1),
                    'details': {
                        'min_price': round(min_price, 4),
                        'prices': prices,
                        'volume_24h': volume,
                        'liquidity': liquidity,
                        'source': 'price_based'
                    },
                    'status': 'active'
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in price-based detection: {e}")
            return None
    
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
            
            # Flag as opportunity if spread is significant (> 0.5%)
            if spread_percentage > 0.5:
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
            
            if deviation > 0.01:  # 1% deviation threshold
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
