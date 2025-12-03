"""
Alert Engine Worker
Monitors markets and triggers alerts based on user-defined conditions
"""
import time
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AlertEngine:
    """Monitors markets and triggers alerts"""
    
    def __init__(self):
        self.db = SupabaseClient()
        self.check_interval = 30  # Check every 30 seconds
        self.last_prices: Dict[str, float] = {}
        self.volume_baseline: Dict[str, float] = {}
        
    def _get_market_price(self, market: Dict) -> Optional[float]:
        """Extract current price from market data"""
        # Try current_price field
        price = market.get('current_price')
        if price is not None:
            return float(price)
        
        # Try raw_data.outcomePrices
        raw_data = market.get('raw_data', {})
        outcome_prices = raw_data.get('outcomePrices', [])
        
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = json.loads(outcome_prices)
            except:
                outcome_prices = []
        
        if outcome_prices and len(outcome_prices) > 0:
            return float(outcome_prices[0])
        
        return None
    
    def check_price_alerts(self):
        """Check price-based alerts (price_above, price_below)"""
        try:
            # Get all active alerts
            alerts = self.db.get_alerts(status='active')
            price_alerts = [a for a in alerts if a.get('type') in ['price_above', 'price_below']]
            
            if not price_alerts:
                return
            
            # Get unique market IDs
            market_ids = set()
            for alert in price_alerts:
                market = alert.get('markets')
                if market:
                    market_ids.add(market.get('condition_id'))
            
            # Get current market data
            markets = self.db.get_markets(limit=500)
            market_map = {m.get('condition_id'): m for m in markets}
            
            triggered_count = 0
            
            for alert in price_alerts:
                try:
                    market = alert.get('markets')
                    if not market:
                        continue
                    
                    condition_id = market.get('condition_id')
                    current_market = market_map.get(condition_id)
                    
                    if not current_market:
                        continue
                    
                    current_price = self._get_market_price(current_market)
                    if current_price is None:
                        continue
                    
                    threshold = float(alert.get('threshold', 0))
                    alert_type = alert.get('type')
                    
                    should_trigger = False
                    
                    if alert_type == 'price_above' and current_price >= threshold:
                        should_trigger = True
                    elif alert_type == 'price_below' and current_price <= threshold:
                        should_trigger = True
                    
                    if should_trigger:
                        # Trigger the alert
                        self.db.trigger_alert(alert.get('id'))
                        triggered_count += 1
                        
                        # Create a signal for the triggered alert
                        self.db.insert_signal({
                            'market_id': condition_id,
                            'type': 'Alert Triggered',
                            'title': f"Price {alert_type.replace('_', ' ').title()}",
                            'description': f"Price crossed {threshold:.2f} (current: {current_price:.2f})",
                            'severity': 'high',
                            'data': {
                                'alert_type': alert_type,
                                'threshold': threshold,
                                'current_price': current_price
                            }
                        })
                        
                        logger.info(f"🔔 Alert triggered: {market.get('question', '')[:50]}... - {alert_type} {threshold}")
                
                except Exception as e:
                    logger.error(f"Error checking alert {alert.get('id')}: {e}")
                    continue
            
            if triggered_count > 0:
                logger.info(f"Triggered {triggered_count} price alerts")
                
        except Exception as e:
            logger.error(f"Error checking price alerts: {e}")
    
    def check_spread_alerts(self):
        """Check spread-based alerts"""
        try:
            alerts = self.db.get_alerts(status='active')
            spread_alerts = [a for a in alerts if a.get('type') == 'spread_above']
            
            if not spread_alerts:
                return
            
            # Get market stats for spread data
            for alert in spread_alerts:
                try:
                    market = alert.get('markets')
                    if not market:
                        continue
                    
                    condition_id = market.get('condition_id')
                    threshold = float(alert.get('threshold', 0))
                    
                    # Get latest order book
                    # Calculate spread from stored order books
                    # For now, we'll use a simplified approach
                    
                except Exception as e:
                    logger.error(f"Error checking spread alert: {e}")
                    continue
                
        except Exception as e:
            logger.error(f"Error checking spread alerts: {e}")
    
    def check_volume_spike_alerts(self):
        """Check for unusual volume activity"""
        try:
            alerts = self.db.get_alerts(status='active')
            volume_alerts = [a for a in alerts if a.get('type') == 'volume_spike']
            
            if not volume_alerts:
                return
            
            markets = self.db.get_markets(limit=200)
            
            for market in markets:
                condition_id = market.get('condition_id')
                if not condition_id:
                    continue
                
                current_volume = float(market.get('volume_24h', 0) or 0)
                
                # Check if volume has spiked compared to baseline
                if condition_id in self.volume_baseline:
                    baseline = self.volume_baseline[condition_id]
                    if baseline > 0:
                        volume_increase = ((current_volume - baseline) / baseline) * 100
                        
                        # Check against active volume alerts for this market
                        for alert in volume_alerts:
                            alert_market = alert.get('markets')
                            if alert_market and alert_market.get('condition_id') == condition_id:
                                threshold = float(alert.get('threshold', 50))  # Default 50% increase
                                
                                if volume_increase >= threshold:
                                    self.db.trigger_alert(alert.get('id'))
                                    
                                    self.db.insert_signal({
                                        'market_id': condition_id,
                                        'type': 'Volume Spike',
                                        'title': 'Unusual Volume Detected',
                                        'description': f"Volume up {volume_increase:.0f}% from baseline",
                                        'severity': 'medium',
                                        'data': {
                                            'current_volume': current_volume,
                                            'baseline_volume': baseline,
                                            'increase_percent': volume_increase
                                        }
                                    })
                                    
                                    logger.info(f"📊 Volume spike: {market.get('question', '')[:50]}... +{volume_increase:.0f}%")
                
                # Update baseline (rolling average)
                if condition_id not in self.volume_baseline:
                    self.volume_baseline[condition_id] = current_volume
                else:
                    # Smooth update
                    self.volume_baseline[condition_id] = (
                        self.volume_baseline[condition_id] * 0.9 + current_volume * 0.1
                    )
            
        except Exception as e:
            logger.error(f"Error checking volume spike alerts: {e}")
    
    def check_whale_trade_alerts(self):
        """Check for whale trade alerts on watched markets"""
        try:
            alerts = self.db.get_alerts(status='active')
            whale_alerts = [a for a in alerts if a.get('type') == 'whale_trade']
            
            if not whale_alerts:
                return
            
            # Get recent whale trades
            whale_trades = self.db.get_whale_trades(limit=10)
            
            for trade in whale_trades:
                trade_market = trade.get('markets')
                if not trade_market:
                    continue
                
                trade_market_id = trade_market.get('condition_id')
                
                for alert in whale_alerts:
                    alert_market = alert.get('markets')
                    if alert_market and alert_market.get('condition_id') == trade_market_id:
                        # Check if trade is recent (within last minute)
                        trade_time = trade.get('timestamp')
                        if trade_time:
                            try:
                                if isinstance(trade_time, str):
                                    trade_dt = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
                                else:
                                    trade_dt = trade_time
                                
                                age_seconds = (datetime.utcnow() - trade_dt.replace(tzinfo=None)).total_seconds()
                                
                                if age_seconds < 60:  # Trade in last minute
                                    self.db.trigger_alert(alert.get('id'))
                                    logger.info(f"🐋 Whale alert triggered for {trade_market.get('question', '')[:50]}...")
                            except Exception as e:
                                logger.error(f"Error parsing trade time: {e}")
                
        except Exception as e:
            logger.error(f"Error checking whale trade alerts: {e}")
    
    def cleanup_expired_alerts(self):
        """Mark expired alerts as expired"""
        try:
            alerts = self.db.get_alerts(status='active')
            
            now = datetime.utcnow()
            expired_count = 0
            
            for alert in alerts:
                expires_at = alert.get('expires_at')
                if expires_at:
                    try:
                        if isinstance(expires_at, str):
                            expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                        else:
                            expires_dt = expires_at
                        
                        if expires_dt.replace(tzinfo=None) < now:
                            # Mark as expired
                            # Note: Would need to add an update method for status
                            expired_count += 1
                    except:
                        pass
            
            if expired_count > 0:
                logger.info(f"Found {expired_count} expired alerts")
            
        except Exception as e:
            logger.error(f"Error cleaning up expired alerts: {e}")
    
    def run(self):
        """Main worker loop"""
        logger.info("Alert Engine started")
        
        while True:
            try:
                # Check all alert types
                self.check_price_alerts()
                self.check_spread_alerts()
                self.check_volume_spike_alerts()
                self.check_whale_trade_alerts()
                
                # Cleanup
                self.cleanup_expired_alerts()
                
            except Exception as e:
                logger.error(f"Fatal error in alert engine: {e}", exc_info=True)
            
            logger.info(f"Sleeping for {self.check_interval} seconds...")
            time.sleep(self.check_interval)


if __name__ == "__main__":
    engine = AlertEngine()
    engine.run()

