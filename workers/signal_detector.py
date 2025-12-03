"""
Signal Detector Worker
Generates real-time alerts for significant market events
"""
import time
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SignalDetector:
    def __init__(self):
        self.db = SupabaseClient()
        self.scan_interval = 30  # Run every 30 seconds for real-time feel
        self.price_cache = {}  # Cache previous prices for comparison
        self.volume_cache = {}  # Cache previous volumes
    
    def detect_signals(self):
        """Main signal detection loop"""
        try:
            logger.info("Running signal detection...")
            
            # Get active markets
            markets = self.db.get_markets(limit=50)
            if not markets:
                logger.warning("No markets found for signal detection")
                return
            
            # Get active opportunities
            opportunities = self._get_opportunities()
            
            signals_generated = 0
            
            for market in markets:
                try:
                    condition_id = market.get('condition_id')
                    if not condition_id:
                        continue
                    
                    # Get current price
                    current_price = self._get_market_price(market)
                    current_volume = float(market.get('volume_24h') or 0)
                    liquidity = float(market.get('liquidity') or 0)
                    
                    # Check for price movements
                    price_signal = self._detect_price_movement(market, current_price)
                    if price_signal:
                        self._store_signal(price_signal)
                        signals_generated += 1
                    
                    # Check for volume surges
                    volume_signal = self._detect_volume_surge(market, current_volume)
                    if volume_signal:
                        self._store_signal(volume_signal)
                        signals_generated += 1
                    
                    # Check for high-confidence opportunities
                    opp_signal = self._detect_opportunity_signal(market, opportunities)
                    if opp_signal:
                        self._store_signal(opp_signal)
                        signals_generated += 1
                    
                    # Check for markets near resolution
                    resolution_signal = self._detect_near_resolution(market, current_price)
                    if resolution_signal:
                        self._store_signal(resolution_signal)
                        signals_generated += 1
                    
                    # Update caches
                    self.price_cache[condition_id] = current_price
                    self.volume_cache[condition_id] = current_volume
                    
                except Exception as e:
                    logger.error(f"Error processing market {market.get('condition_id')}: {e}")
                    continue
            
            if signals_generated > 0:
                logger.info(f"Generated {signals_generated} new signals")
            
            # Cleanup old signals
            self._cleanup_old_signals()
            
        except Exception as e:
            logger.error(f"Error in signal detection: {e}", exc_info=True)
    
    def _get_market_price(self, market: dict) -> float:
        """Extract current price from market data"""
        try:
            # Try current_price field
            if market.get('current_price') is not None:
                return float(market['current_price'])
            
            # Try raw_data.outcomePrices
            raw_data = market.get('raw_data', {})
            if raw_data and raw_data.get('outcomePrices'):
                prices = raw_data['outcomePrices']
                if isinstance(prices, str):
                    prices = json.loads(prices)
                if isinstance(prices, list) and len(prices) > 0:
                    return float(prices[0])
            
            return 0.5  # Default
        except:
            return 0.5
    
    def _get_opportunities(self) -> List[Dict]:
        """Get active opportunities from database"""
        try:
            result = self.db.client.table('opportunities')\
                .select('*, markets(*)')\
                .eq('status', 'active')\
                .execute()
            return result.data if result.data else []
        except:
            return []
    
    def _detect_price_movement(self, market: dict, current_price: float) -> Optional[dict]:
        """Detect significant price movements"""
        condition_id = market.get('condition_id')
        market_id = market.get('id')
        
        # Get previous price from cache
        prev_price = self.price_cache.get(condition_id)
        
        if prev_price is None or prev_price == 0:
            return None
        
        # Calculate change
        change = current_price - prev_price
        change_percent = (change / prev_price) * 100 if prev_price > 0 else 0
        
        # Significant movement threshold (> 3%)
        if abs(change_percent) >= 3:
            is_spike = change > 0
            severity = 'high' if abs(change_percent) >= 5 else 'medium'
            
            question = market.get('question', 'Unknown Market')[:80]
            
            return {
                'market_id': market_id,
                'type': 'price_spike' if is_spike else 'price_drop',
                'title': f"{'📈' if is_spike else '📉'} {'+' if is_spike else ''}{change_percent:.1f}% - {question}",
                'description': f"Price moved from {prev_price*100:.0f}¢ to {current_price*100:.0f}¢",
                'severity': severity,
                'data': {
                    'prev_price': round(prev_price, 4),
                    'current_price': round(current_price, 4),
                    'change_percent': round(change_percent, 2),
                    'volume_24h': market.get('volume_24h'),
                    'condition_id': condition_id
                }
            }
        
        return None
    
    def _detect_volume_surge(self, market: dict, current_volume: float) -> Optional[dict]:
        """Detect volume surges"""
        condition_id = market.get('condition_id')
        market_id = market.get('id')
        
        prev_volume = self.volume_cache.get(condition_id)
        
        if prev_volume is None or prev_volume == 0:
            return None
        
        # Volume increase threshold (> 20% in short time)
        volume_change = ((current_volume - prev_volume) / prev_volume) * 100 if prev_volume > 0 else 0
        
        if volume_change >= 20 and current_volume > 50000:  # Must have meaningful volume
            question = market.get('question', 'Unknown Market')[:80]
            
            return {
                'market_id': market_id,
                'type': 'volume_surge',
                'title': f"🔥 Volume +{volume_change:.0f}% - {question}",
                'description': f"Trading activity spiking - ${current_volume/1000:.0f}K volume",
                'severity': 'high' if volume_change >= 50 else 'medium',
                'data': {
                    'prev_volume': round(prev_volume, 2),
                    'current_volume': round(current_volume, 2),
                    'volume_change_percent': round(volume_change, 2),
                    'condition_id': condition_id
                }
            }
        
        return None
    
    def _detect_opportunity_signal(self, market: dict, opportunities: List[Dict]) -> Optional[dict]:
        """Generate signal for high-confidence opportunities"""
        market_id = market.get('id')
        
        # Find opportunities for this market
        market_opps = [o for o in opportunities if o.get('market_id') == market_id]
        
        if not market_opps:
            return None
        
        # Find highest confidence opportunity
        best_opp = max(market_opps, key=lambda x: float(x.get('confidence_score') or 0))
        confidence = float(best_opp.get('confidence_score') or 0)
        profit = float(best_opp.get('profit_potential') or 0)
        opp_type = best_opp.get('type', 'Opportunity')
        
        # Only signal for high confidence opportunities (> 70%)
        if confidence >= 70 and profit >= 1.0:
            question = market.get('question', 'Unknown Market')[:60]
            
            return {
                'market_id': market_id,
                'type': 'high_confidence',
                'title': f"⚡ {opp_type} +{profit:.1f}% - {question}",
                'description': f"{confidence:.0f}% confidence - Potential {opp_type.lower()} opportunity",
                'severity': 'critical' if confidence >= 85 else 'high',
                'data': {
                    'opportunity_type': opp_type,
                    'profit_potential': profit,
                    'confidence_score': confidence,
                    'details': best_opp.get('details', {}),
                    'condition_id': market.get('condition_id')
                }
            }
        
        return None
    
    def _detect_near_resolution(self, market: dict, current_price: float) -> Optional[dict]:
        """Detect markets near resolution (price very high or low)"""
        market_id = market.get('id')
        
        # If price is extreme (>95% or <5%), market is near resolution
        if current_price >= 0.95 or current_price <= 0.05:
            question = market.get('question', 'Unknown Market')[:70]
            direction = "YES" if current_price >= 0.95 else "NO"
            
            return {
                'market_id': market_id,
                'type': 'near_resolution',
                'title': f"🎯 {current_price*100:.0f}% → {direction} likely - {question}",
                'description': f"Market strongly favoring {direction} outcome",
                'severity': 'medium',
                'data': {
                    'current_price': round(current_price, 4),
                    'likely_outcome': direction,
                    'volume_24h': market.get('volume_24h'),
                    'condition_id': market.get('condition_id')
                }
            }
        
        return None
    
    def _store_signal(self, signal: dict):
        """Store signal in database"""
        try:
            # Check if similar signal exists recently (avoid duplicates)
            existing = self.db.client.table('signals')\
                .select('id')\
                .eq('market_id', signal['market_id'])\
                .eq('type', signal['type'])\
                .gte('created_at', (datetime.utcnow() - timedelta(minutes=15)).isoformat())\
                .execute()
            
            if existing.data and len(existing.data) > 0:
                logger.debug(f"Similar signal already exists, skipping")
                return
            
            # Insert new signal
            result = self.db.client.table('signals').insert({
                'market_id': signal['market_id'],
                'type': signal['type'],
                'title': signal['title'],
                'description': signal.get('description'),
                'severity': signal.get('severity', 'medium'),
                'data': signal.get('data', {}),
                'expires_at': (datetime.utcnow() + timedelta(hours=24)).isoformat()
            }).execute()
            
            logger.info(f"Stored signal: {signal['type']} - {signal['title'][:50]}")
            
        except Exception as e:
            logger.error(f"Error storing signal: {e}")
    
    def _cleanup_old_signals(self):
        """Remove expired signals"""
        try:
            # Delete signals older than 24 hours
            cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
            self.db.client.table('signals')\
                .delete()\
                .lt('created_at', cutoff)\
                .execute()
        except Exception as e:
            logger.error(f"Error cleaning up signals: {e}")
    
    def run(self):
        """Main run loop"""
        logger.info("Signal Detector started")
        
        while True:
            try:
                self.detect_signals()
                time.sleep(self.scan_interval)
            except KeyboardInterrupt:
                logger.info("Shutting down signal detector...")
                break
            except Exception as e:
                logger.error(f"Fatal error: {e}", exc_info=True)
                time.sleep(10)


if __name__ == "__main__":
    detector = SignalDetector()
    detector.run()


