"""
Momentum Engine - Wolf Pack Edition
Detects market momentum, price velocity, volume surges, and breakout opportunities
"""
import time
import json
import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Momentum detection thresholds
BREAKOUT_THRESHOLD = 0.05  # 5% price move triggers breakout
VOLUME_SURGE_MULTIPLIER = 2.0  # 2x average volume is a surge
MOMENTUM_ACCELERATION_THRESHOLD = 0.5  # 50% momentum increase
MEAN_REVERSION_THRESHOLD = 0.10  # 10% overextension
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30


class MomentumEngine:
    """
    Wolf Pack Momentum Intelligence
    - Price Velocity: Rate of price change (not just direction)
    - Volume Momentum: Is volume accelerating?
    - Breakout Detection: Price breaking through with volume confirmation
    - Mean Reversion: Overextended prices likely to snap back
    - Momentum Score: Combined metric for opportunity scoring
    """
    
    def __init__(self):
        self.db = SupabaseClient()
        self.scan_interval = 120  # 2 minutes
        self.price_history: Dict[str, List[Tuple[datetime, float]]] = {}
        self.volume_history: Dict[str, List[float]] = {}
        self.momentum_history: Dict[str, List[float]] = {}
        
    def _get_price_series(self, condition_id: str, hours: int = 24) -> List[Dict]:
        """Get price series for a market"""
        try:
            return self.db.get_price_history(condition_id, hours=hours)
        except Exception as e:
            logger.error(f"Error getting price series: {e}")
            return []
    
    def calculate_price_velocity(self, prices: List[float], periods: int = 5) -> float:
        """
        Calculate price velocity (rate of change)
        Positive = accelerating upward, Negative = accelerating downward
        """
        if len(prices) < periods + 1:
            return 0.0
        
        # Calculate sequential returns
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                ret = (prices[i] - prices[i-1]) / prices[i-1]
                returns.append(ret)
        
        if len(returns) < periods:
            return 0.0
        
        # Recent returns vs earlier returns
        recent = returns[-periods:]
        earlier = returns[:-periods] if len(returns) > periods else returns
        
        recent_avg = sum(recent) / len(recent) if recent else 0
        earlier_avg = sum(earlier) / len(earlier) if earlier else 0
        
        # Velocity = rate of change of returns (acceleration)
        velocity = (recent_avg - earlier_avg) * 100
        
        return velocity
    
    def calculate_volume_momentum(self, condition_id: str) -> Dict:
        """Calculate volume momentum and detect surges"""
        try:
            # Get market data for volume
            markets = self.db.get_markets(limit=1)
            market = None
            for m in markets:
                if m.get('condition_id') == condition_id:
                    market = m
                    break
            
            if not market:
                # Try to get by querying all markets
                all_markets = self.db.get_markets(limit=500)
                for m in all_markets:
                    if m.get('condition_id') == condition_id:
                        market = m
                        break
            
            if not market:
                return {'momentum': 0, 'is_surge': False, 'surge_multiplier': 1.0}
            
            current_volume = market.get('volume_24h', 0)
            
            # Track volume history
            if condition_id not in self.volume_history:
                self.volume_history[condition_id] = []
            
            self.volume_history[condition_id].append(current_volume)
            
            # Keep last 24 data points
            if len(self.volume_history[condition_id]) > 24:
                self.volume_history[condition_id] = self.volume_history[condition_id][-24:]
            
            history = self.volume_history[condition_id]
            
            if len(history) < 2:
                return {'momentum': 0, 'is_surge': False, 'surge_multiplier': 1.0}
            
            # Calculate average excluding current
            avg_volume = statistics.mean(history[:-1]) if len(history) > 1 else history[0]
            
            # Volume momentum
            momentum = 0
            if avg_volume > 0:
                momentum = ((current_volume - avg_volume) / avg_volume) * 100
            
            # Detect surge
            surge_multiplier = current_volume / avg_volume if avg_volume > 0 else 1.0
            is_surge = surge_multiplier >= VOLUME_SURGE_MULTIPLIER
            
            return {
                'momentum': momentum,
                'is_surge': is_surge,
                'surge_multiplier': surge_multiplier,
                'current_volume': current_volume,
                'avg_volume': avg_volume
            }
            
        except Exception as e:
            logger.error(f"Error calculating volume momentum: {e}")
            return {'momentum': 0, 'is_surge': False, 'surge_multiplier': 1.0}
    
    def calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return 50.0  # Neutral
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        # Use EMA for smoothing
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def detect_breakout(self, condition_id: str, prices: List[float], 
                        volume_data: Dict) -> Optional[Dict]:
        """
        Detect price breakouts with volume confirmation
        A breakout is: significant price move + above-average volume
        """
        if len(prices) < 5:
            return None
        
        current_price = prices[-1]
        
        # Calculate recent range
        recent_high = max(prices[-20:]) if len(prices) >= 20 else max(prices)
        recent_low = min(prices[-20:]) if len(prices) >= 20 else min(prices)
        range_size = recent_high - recent_low
        
        if range_size <= 0:
            return None
        
        # Check for breakout above resistance
        if current_price > recent_high * (1 - 0.01):  # Within 1% of high
            price_move = (current_price - recent_low) / recent_low if recent_low > 0 else 0
            
            # Need volume confirmation
            if price_move > BREAKOUT_THRESHOLD and volume_data.get('is_surge', False):
                return {
                    'type': 'bullish_breakout',
                    'price_move': price_move * 100,
                    'volume_multiplier': volume_data.get('surge_multiplier', 1),
                    'current_price': current_price,
                    'resistance': recent_high,
                    'support': recent_low
                }
        
        # Check for breakdown below support
        if current_price < recent_low * (1 + 0.01):  # Within 1% of low
            price_move = (recent_high - current_price) / recent_high if recent_high > 0 else 0
            
            if price_move > BREAKOUT_THRESHOLD and volume_data.get('is_surge', False):
                return {
                    'type': 'bearish_breakdown',
                    'price_move': price_move * 100,
                    'volume_multiplier': volume_data.get('surge_multiplier', 1),
                    'current_price': current_price,
                    'resistance': recent_high,
                    'support': recent_low
                }
        
        return None
    
    def detect_mean_reversion(self, prices: List[float], rsi: float) -> Optional[Dict]:
        """Detect mean reversion opportunities"""
        if len(prices) < 10:
            return None
        
        current_price = prices[-1]
        
        # Calculate moving average
        ma_period = min(20, len(prices))
        ma = sum(prices[-ma_period:]) / ma_period
        
        # Calculate deviation from MA
        deviation = (current_price - ma) / ma if ma > 0 else 0
        
        # Overbought + extended above MA = mean reversion short opportunity
        if rsi > RSI_OVERBOUGHT and deviation > MEAN_REVERSION_THRESHOLD:
            return {
                'type': 'overbought_extended',
                'direction': 'short',
                'rsi': rsi,
                'deviation_percent': deviation * 100,
                'current_price': current_price,
                'moving_average': ma,
                'expected_target': ma
            }
        
        # Oversold + extended below MA = mean reversion long opportunity
        if rsi < RSI_OVERSOLD and deviation < -MEAN_REVERSION_THRESHOLD:
            return {
                'type': 'oversold_extended',
                'direction': 'long',
                'rsi': rsi,
                'deviation_percent': deviation * 100,
                'current_price': current_price,
                'moving_average': ma,
                'expected_target': ma
            }
        
        return None
    
    def calculate_momentum_score(self, velocity: float, volume_momentum: float, 
                                  rsi: float, imbalance: float = 0) -> float:
        """
        Calculate composite momentum score (-100 to +100)
        Combines multiple factors into single actionable metric
        """
        # Normalize factors
        velocity_score = max(-50, min(50, velocity))  # Cap at ±50
        volume_score = max(-20, min(20, volume_momentum / 5))  # Scale and cap
        
        # RSI contribution (0-100 -> -20 to +20)
        rsi_score = (rsi - 50) * 0.4
        
        # Imbalance contribution (-1 to 1 -> -10 to +10)
        imbalance_score = imbalance * 10
        
        # Combine
        total = velocity_score + volume_score + rsi_score + imbalance_score
        
        return max(-100, min(100, total))
    
    def analyze_market(self, market: Dict) -> Dict:
        """Comprehensive momentum analysis for a single market"""
        condition_id = market.get('condition_id')
        if not condition_id:
            return {}
        
        try:
            # Get price history
            price_data = self._get_price_series(condition_id, hours=48)
            
            if not price_data:
                return {}
            
            prices = [float(p['price']) for p in price_data if p.get('price')]
            
            if len(prices) < 5:
                return {}
            
            # Calculate metrics
            velocity = self.calculate_price_velocity(prices)
            volume_data = self.calculate_volume_momentum(condition_id)
            rsi = self.calculate_rsi(prices)
            
            # Get order book imbalance if available
            imbalance = market.get('raw_data', {}).get('imbalance', 0)
            
            # Calculate momentum score
            momentum_score = self.calculate_momentum_score(
                velocity, 
                volume_data.get('momentum', 0),
                rsi,
                imbalance
            )
            
            # Detect signals
            breakout = self.detect_breakout(condition_id, prices, volume_data)
            mean_reversion = self.detect_mean_reversion(prices, rsi)
            
            return {
                'condition_id': condition_id,
                'velocity': velocity,
                'volume_momentum': volume_data.get('momentum', 0),
                'volume_surge': volume_data.get('is_surge', False),
                'rsi': rsi,
                'momentum_score': momentum_score,
                'breakout': breakout,
                'mean_reversion': mean_reversion
            }
            
        except Exception as e:
            logger.error(f"Error analyzing market {condition_id}: {e}")
            return {}
    
    def process_momentum(self):
        """Main momentum processing loop"""
        try:
            logger.info("Starting momentum analysis...")
            
            markets = self.db.get_markets(limit=100)
            if not markets:
                logger.warning("No markets found for momentum analysis")
                return
            
            high_momentum_count = 0
            breakout_count = 0
            reversion_count = 0
            
            for market in markets:
                analysis = self.analyze_market(market)
                
                if not analysis:
                    continue
                
                condition_id = analysis.get('condition_id')
                momentum_score = analysis.get('momentum_score', 0)
                velocity = analysis.get('velocity', 0)
                rsi = analysis.get('rsi', 50)
                
                # Update market with momentum data
                self.db.update_market_prices(condition_id, {
                    'momentum': momentum_score,
                    'volatility_24h': abs(velocity)  # Use velocity as volatility proxy
                })
                
                # Log high momentum markets
                if abs(momentum_score) > 50:
                    direction = "📈" if momentum_score > 0 else "📉"
                    logger.info(f"{direction} High Momentum: {market.get('question', '')[:40]}... Score: {momentum_score:.0f}")
                    high_momentum_count += 1
                
                # Handle breakout signals
                breakout = analysis.get('breakout')
                if breakout:
                    is_bullish = breakout['type'] == 'bullish_breakout'
                    logger.info(f"🚀 BREAKOUT: {'Bullish' if is_bullish else 'Bearish'} on {market.get('question', '')[:40]}...")
                    
                    self.db.insert_signal({
                        'market_id': condition_id,
                        'type': breakout['type'],
                        'title': f"{'Bullish Breakout' if is_bullish else 'Bearish Breakdown'} Detected",
                        'description': f"Price moved {breakout['price_move']:.1f}% with {breakout['volume_multiplier']:.1f}x volume",
                        'severity': 'high',
                        'data': breakout
                    })
                    breakout_count += 1
                
                # Handle mean reversion signals
                mean_reversion = analysis.get('mean_reversion')
                if mean_reversion:
                    direction = mean_reversion['direction']
                    logger.info(f"↩️ Mean Reversion: {direction.upper()} on {market.get('question', '')[:40]}...")
                    
                    self.db.insert_signal({
                        'market_id': condition_id,
                        'type': mean_reversion['type'],
                        'title': f"Mean Reversion Opportunity ({direction.title()})",
                        'description': f"RSI: {mean_reversion['rsi']:.0f}, {abs(mean_reversion['deviation_percent']):.1f}% extended",
                        'severity': 'medium',
                        'data': mean_reversion
                    })
                    reversion_count += 1
                
                # Alert on extreme RSI
                if rsi > RSI_OVERBOUGHT or rsi < RSI_OVERSOLD:
                    condition = "OVERBOUGHT" if rsi > RSI_OVERBOUGHT else "OVERSOLD"
                    logger.debug(f"⚠️ RSI {condition}: {rsi:.0f} on {market.get('question', '')[:30]}...")
            
            logger.info(f"Momentum Analysis Complete: {high_momentum_count} high momentum, {breakout_count} breakouts, {reversion_count} reversions")
            
        except Exception as e:
            logger.error(f"Error in momentum processing: {e}", exc_info=True)
    
    def run(self):
        """Main worker loop"""
        logger.info("Momentum Engine started (Wolf Pack Edition)")
        
        while True:
            try:
                self.process_momentum()
            except Exception as e:
                logger.error(f"Fatal error in momentum engine: {e}", exc_info=True)
            
            logger.info(f"Sleeping for {self.scan_interval} seconds...")
            time.sleep(self.scan_interval)


if __name__ == "__main__":
    engine = MomentumEngine()
    engine.run()

