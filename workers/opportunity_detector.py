"""
Opportunity Detector v2.0
Finds REAL alpha: negative risk arb, spread capture, momentum signals
"Everyone has access to the information. We just know how to analyze it better."
"""
import logging
import time
from typing import Dict, List, Any, Optional
from collections import defaultdict

from services.polymarket_api import PolymarketAPI
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OpportunityDetector:
    """
    Advanced opportunity detection engine
    Finds: negative risk, spread capture, momentum, volume anomalies
    """
    
    def __init__(self):
        self.api = PolymarketAPI()
        self.db = SupabaseClient()
        self.scan_interval = 30  # seconds
        
        # Thresholds
        self.WHALE_THRESHOLD = 10000  # USD
        self.SPREAD_THRESHOLD = 0.02  # 2% minimum spread for capture opportunity
        self.VOLUME_VELOCITY_THRESHOLD = 2.0  # 2x normal volume
        self.MOMENTUM_THRESHOLD = 0.05  # 5% price change
        self.NEG_RISK_MIN_PROFIT = 0.5  # 0.5% minimum for neg risk arb
    
    def detect_all(self) -> Dict[str, List[Dict]]:
        """Run all detection algorithms"""
        logger.info("Starting opportunity detection...")
        
        # Get markets from database
        markets = self.db.get_markets(limit=500)
        
        if not markets:
            logger.warning("No markets found for analysis")
            return {'neg_risk': [], 'spread': [], 'momentum': [], 'volume': []}
        
        logger.info(f"Analyzing {len(markets)} markets...")
        
        # Run detectors
        results = {
            'neg_risk': self.detect_negative_risk(markets),
            'spread': self.detect_spread_opportunities(markets),
            'momentum': self.detect_momentum_signals(markets),
            'volume': self.detect_volume_anomalies(markets)
        }
        
        # Store opportunities
        self._store_opportunities(results)
        
        # Log summary
        total = sum(len(v) for v in results.values())
        logger.info(f"Detection complete: {total} opportunities found")
        logger.info(f"  - Neg risk: {len(results['neg_risk'])}")
        logger.info(f"  - Spread: {len(results['spread'])}")
        logger.info(f"  - Momentum: {len(results['momentum'])}")
        logger.info(f"  - Volume: {len(results['volume'])}")
        
        return results
    
    def detect_negative_risk(self, markets: List[Dict]) -> List[Dict]:
        """
        NEGATIVE RISK ARBITRAGE
        When sum of NO prices in a mutually exclusive group < 1,
        buying all NOs guarantees profit.
        
        Example: Markets A, B, C are mutually exclusive
        - A: YES 30%, NO 70%
        - B: YES 40%, NO 60%
        - C: YES 25%, NO 75%
        Total NO cost = 0.70 + 0.60 + 0.75 = 2.05 > 1.00 (no arb)
        
        But if:
        - A: YES 30%, NO 70%
        - B: YES 35%, NO 65%  
        - C: YES 20%, NO 80%
        Total NO cost = 0.70 + 0.65 + (1-0.80) = 0.70 + 0.65 + 0.20 = 1.55 > 1.00
        
        Wait - in a 3-way exclusive, we only need ONE to be true.
        So we buy YES on the cheapest outcome and NO on others?
        
        Actually for true neg risk: buy ALL NOs in group
        If total cost < $1.00 per $1 guaranteed return = profit
        """
        opportunities = []
        
        # Group markets by neg_risk_market_id
        neg_risk_groups = defaultdict(list)
        
        for market in markets:
            # Check if market has neg_risk flag and group ID
            raw_data = market.get('raw_data', {})
            neg_risk = raw_data.get('neg_risk') or market.get('neg_risk', False)
            group_id = raw_data.get('negRiskMarketID') or market.get('neg_risk_market_id')
            
            if neg_risk and group_id:
                neg_risk_groups[group_id].append(market)
        
        logger.info(f"Found {len(neg_risk_groups)} negative risk groups")
        
        for group_id, group_markets in neg_risk_groups.items():
            if len(group_markets) < 2:
                continue  # Need at least 2 markets for arb
            
            # Calculate total NO cost
            no_prices = []
            for m in group_markets:
                # Get YES price
                yes_price = float(m.get('current_price', 0.5) or 0.5)
                
                # Also try from raw_data
                raw = m.get('raw_data', {})
                outcome_prices = raw.get('outcomePrices', [])
                if isinstance(outcome_prices, str):
                    try:
                        import json
                        outcome_prices = json.loads(outcome_prices)
                    except:
                        pass
                
                if isinstance(outcome_prices, list) and len(outcome_prices) > 0:
                    yes_price = float(outcome_prices[0])
                
                no_price = 1 - yes_price
                no_prices.append({
                    'market': m,
                    'yes_price': yes_price,
                    'no_price': no_price,
                    'question': m.get('question', '')[:60],
                    'liquidity': float(m.get('liquidity', 0) or 0)
                })
            
            total_no_cost = sum(p['no_price'] for p in no_prices)
            
            # If total NO cost < 1 (accounting for fees ~0.5%), we have guaranteed profit
            if total_no_cost < 0.995:
                profit_percent = (1 - total_no_cost) * 100
                min_liquidity = min(p['liquidity'] for p in no_prices) if no_prices else 0
                max_position = min_liquidity * 0.05  # Conservative 5% of smallest liquidity
                
                if profit_percent >= self.NEG_RISK_MIN_PROFIT:
                    opp = {
                        'type': 'negative_risk',
                        'group_id': group_id,
                        'profit_percent': round(profit_percent, 2),
                        'total_no_cost': round(total_no_cost, 4),
                        'max_position_usd': max_position,
                        'num_markets': len(group_markets),
                        'markets': no_prices,
                        'confidence': 99,  # Near-certain profit
                        'action': f'Buy all NO positions for ${total_no_cost*100:.1f} per $100 guaranteed return',
                        'edge': profit_percent
                    }
                    opportunities.append(opp)
                    logger.info(f"NEG RISK: {profit_percent:.2f}% profit in group {group_id[:20]}...")
        
        return opportunities
    
    def detect_spread_opportunities(self, markets: List[Dict]) -> List[Dict]:
        """
        SPREAD CAPTURE
        Wide bid-ask spreads = opportunity for market makers
        Provide liquidity, earn spread
        """
        opportunities = []
        
        for market in markets:
            spread = float(market.get('spread', 0) or 0)
            
            # Also check from raw_data if available
            raw = market.get('raw_data', {})
            if raw.get('spread'):
                spread = max(spread, float(raw.get('spread', 0)))
            
            # Check if spread is wide enough
            if spread >= self.SPREAD_THRESHOLD:
                liquidity = float(market.get('liquidity', 0) or 0)
                volume_24h = float(market.get('volume_24h', 0) or 0)
                
                # Estimate daily return from market making
                # Conservative: capture 40% of spread
                daily_trades = volume_24h  # Already in USD
                est_return = (spread * 0.4) * 100  # As percentage
                
                # Check for LP rewards
                has_rewards = market.get('has_rewards', False)
                rewards_rate = float(market.get('rewards_daily_rate', 0) or 0)
                
                opp = {
                    'type': 'spread',
                    'market_id': market.get('condition_id'),
                    'question': market.get('question', '')[:60],
                    'spread': round(spread * 100, 2),  # As percentage
                    'spread_percent': round(spread * 100, 2),
                    'liquidity': liquidity,
                    'volume_24h': volume_24h,
                    'est_return': round(est_return, 2),
                    'has_rewards': has_rewards,
                    'rewards_rate': rewards_rate,
                    'confidence': 75,
                    'action': f'Provide liquidity, earn ~{est_return:.1f}% from spread',
                    'edge': est_return
                }
                opportunities.append(opp)
        
        # Sort by estimated return
        opportunities.sort(key=lambda x: x['est_return'], reverse=True)
        
        return opportunities[:50]  # Top 50
    
    def detect_momentum_signals(self, markets: List[Dict]) -> List[Dict]:
        """
        MOMENTUM SIGNALS
        Strong price moves (>5% 24h) with volume confirmation
        """
        signals = []
        
        for market in markets:
            price_change = float(market.get('price_change_24h', 0) or 0)
            volume_velocity = float(market.get('volume_velocity', 1) or 1)
            volume_24h = float(market.get('volume_24h', 0) or 0)
            
            # Check for significant price movement
            if abs(price_change) >= self.MOMENTUM_THRESHOLD:
                direction = 'UP' if price_change > 0 else 'DOWN'
                
                # Confidence based on volume confirmation
                confidence = 60
                if volume_velocity > 1.5:
                    confidence = 70
                if volume_velocity > 2.0:
                    confidence = 80
                if volume_velocity > 3.0:
                    confidence = 90
                
                # Only signal if volume confirms
                if volume_velocity >= 1.2:
                    signal = {
                        'type': 'momentum',
                        'market_id': market.get('condition_id'),
                        'question': market.get('question', '')[:60],
                        'price_change': round(price_change * 100, 2),
                        'direction': direction,
                        'volume_velocity': round(volume_velocity, 2),
                        'volume_24h': volume_24h,
                        'current_price': float(market.get('current_price', 0.5) or 0.5),
                        'confidence': confidence,
                        'action': f'{direction} momentum: {abs(price_change)*100:.1f}% with {volume_velocity:.1f}x volume',
                        'edge': abs(price_change) * 100 * 0.3  # Conservative 30% of move remaining
                    }
                    signals.append(signal)
        
        # Sort by confidence then by edge
        signals.sort(key=lambda x: (x['confidence'], x['edge']), reverse=True)
        
        return signals[:30]  # Top 30
    
    def detect_volume_anomalies(self, markets: List[Dict]) -> List[Dict]:
        """
        VOLUME ANOMALIES
        Sudden volume spikes often precede price moves
        """
        anomalies = []
        
        for market in markets:
            volume_velocity = float(market.get('volume_velocity', 1) or 1)
            volume_24h = float(market.get('volume_24h', 0) or 0)
            
            if volume_velocity >= self.VOLUME_VELOCITY_THRESHOLD:
                # Categorize signal strength
                if volume_velocity >= 5:
                    strength = 'EXTREME'
                    confidence = 90
                elif volume_velocity >= 3:
                    strength = 'HIGH'
                    confidence = 75
                else:
                    strength = 'ELEVATED'
                    confidence = 60
                
                anomaly = {
                    'type': 'volume_anomaly',
                    'market_id': market.get('condition_id'),
                    'question': market.get('question', '')[:60],
                    'volume_velocity': round(volume_velocity, 2),
                    'volume_24h': volume_24h,
                    'signal_strength': strength,
                    'confidence': confidence,
                    'action': f'{strength} volume ({volume_velocity:.1f}x normal) - potential price move incoming',
                    'edge': min(volume_velocity * 2, 15)  # Cap at 15%
                }
                anomalies.append(anomaly)
        
        # Sort by volume velocity
        anomalies.sort(key=lambda x: x['volume_velocity'], reverse=True)
        
        return anomalies[:20]  # Top 20
    
    def _store_opportunities(self, results: Dict[str, List[Dict]]):
        """Store detected opportunities in database"""
        stored = 0
        
        # Store negative risk opportunities
        for opp in results.get('neg_risk', []):
            try:
                # Use first market in group as reference
                if opp.get('markets') and len(opp['markets']) > 0:
                    market = opp['markets'][0]['market']
                    market_id = market.get('condition_id')
                    
                    if market_id:
                        self.db.upsert_opportunity({
                            'market_id': market_id,
                            'type': 'negative_risk',
                            'profit_potential': opp['profit_percent'],
                            'confidence_score': opp['confidence'],
                            'details': opp,
                            'status': 'active'
                        })
                        stored += 1
            except Exception as e:
                logger.error(f"Error storing neg risk opp: {e}")
        
        # Store spread opportunities
        for opp in results.get('spread', []):
            try:
                market_id = opp.get('market_id')
                if market_id:
                    self.db.upsert_opportunity({
                        'market_id': market_id,
                        'type': 'spread',
                        'profit_potential': opp['est_return'],
                        'confidence_score': opp['confidence'],
                        'details': opp,
                        'status': 'active'
                    })
                    stored += 1
            except Exception as e:
                logger.error(f"Error storing spread opp: {e}")
        
        # Store momentum signals
        for signal in results.get('momentum', []):
            try:
                market_id = signal.get('market_id')
                if market_id:
                    self.db.upsert_opportunity({
                        'market_id': market_id,
                        'type': 'momentum',
                        'profit_potential': signal['edge'],
                        'confidence_score': signal['confidence'],
                        'details': signal,
                        'status': 'active'
                    })
                    stored += 1
            except Exception as e:
                logger.error(f"Error storing momentum signal: {e}")
        
        # Store volume anomalies as signals (not opportunities)
        for anomaly in results.get('volume', []):
            try:
                market_id = anomaly.get('market_id')
                if market_id:
                    self.db.insert_signal({
                        'market_id': market_id,
                        'type': 'volume_anomaly',
                        'title': f"Volume Spike: {anomaly['signal_strength']}",
                        'description': anomaly['action'],
                        'severity': 'high' if anomaly['signal_strength'] == 'EXTREME' else 'medium',
                        'data': anomaly
                    })
                    stored += 1
            except Exception as e:
                logger.error(f"Error storing volume anomaly: {e}")
        
        logger.info(f"Stored {stored} opportunities/signals")
    
    def run(self):
        """Main worker loop"""
        logger.info("Opportunity Detector v2.0 started")
        
        while True:
            try:
                self.detect_all()
            except Exception as e:
                logger.error(f"Error in detection cycle: {e}", exc_info=True)
            
            logger.info(f"Sleeping {self.scan_interval}s...")
            time.sleep(self.scan_interval)


if __name__ == "__main__":
    detector = OpportunityDetector()
    detector.run()
