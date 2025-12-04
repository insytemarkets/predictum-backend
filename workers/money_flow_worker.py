"""
Money Flow Worker - Wolf Pack Edition
Tracks where money is moving in real-time across markets and sectors
"""
import time
import json
import logging
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

# Flow detection thresholds
SIGNIFICANT_FLOW_USD = 50000  # $50k+ flow is significant
FLOW_SURGE_MULTIPLIER = 2.0  # 2x average flow is a surge
SECTOR_ROTATION_THRESHOLD = 0.3  # 30% shift indicates rotation


class MoneyFlowWorker:
    """
    Wolf Pack Money Flow Intelligence
    - Tracks buy/sell volume per market
    - Calculates flow velocity (acceleration of money movement)
    - Detects cross-market flow patterns
    - Identifies sector rotation
    """
    
    def __init__(self):
        self.db = SupabaseClient()
        self.scan_interval = 60  # 1 minute
        self.flow_history: Dict[str, List[Dict]] = {}  # Market flow history
        self.sector_flow_history: Dict[str, List[float]] = {}  # Sector net flow history
        
    def _get_category(self, market: Dict) -> str:
        """Extract category from market data"""
        raw_data = market.get('raw_data', {})
        
        # Try multiple category fields
        category = raw_data.get('category')
        if category:
            return category
        
        tags = raw_data.get('tags', [])
        if tags and isinstance(tags, list):
            return tags[0] if tags else 'Other'
        
        # Try to infer from question
        question = market.get('question', '').lower()
        if any(word in question for word in ['trump', 'biden', 'election', 'president', 'congress']):
            return 'Politics'
        elif any(word in question for word in ['bitcoin', 'ethereum', 'crypto', 'btc', 'eth']):
            return 'Crypto'
        elif any(word in question for word in ['fed', 'interest rate', 'inflation', 'gdp']):
            return 'Economics'
        elif any(word in question for word in ['super bowl', 'nfl', 'nba', 'world series']):
            return 'Sports'
        
        return 'Other'
    
    def calculate_market_flow(self, market_id: str, hours: int = 1) -> Dict:
        """Calculate money flow for a single market"""
        try:
            flow_data = self.db.get_trade_flow(market_id, hours=hours)
            
            buy_volume = flow_data.get('buy_volume', 0)
            sell_volume = flow_data.get('sell_volume', 0)
            net_flow = buy_volume - sell_volume
            buy_pressure = flow_data.get('buy_pressure', 50)
            
            # Calculate flow velocity (compare to previous period)
            prev_flow = self.flow_history.get(market_id, [])
            velocity = 0
            
            if prev_flow:
                prev_net = prev_flow[-1].get('net_flow', 0)
                if prev_net != 0:
                    velocity = ((net_flow - prev_net) / abs(prev_net)) * 100
            
            return {
                'market_id': market_id,
                'buy_volume': buy_volume,
                'sell_volume': sell_volume,
                'net_flow': net_flow,
                'buy_pressure': buy_pressure,
                'flow_velocity': velocity,
                'period': f'{hours}h'
            }
            
        except Exception as e:
            logger.error(f"Error calculating flow for {market_id}: {e}")
            return {}
    
    def calculate_sector_flow(self) -> Dict[str, Dict]:
        """Calculate aggregate flow by sector/category"""
        try:
            markets = self.db.get_markets(limit=200)
            
            sector_flows: Dict[str, Dict] = defaultdict(lambda: {
                'buy_volume': 0,
                'sell_volume': 0,
                'net_flow': 0,
                'market_count': 0
            })
            
            for market in markets:
                condition_id = market.get('condition_id')
                if not condition_id:
                    continue
                
                category = self._get_category(market)
                flow = self.calculate_market_flow(condition_id, hours=24)
                
                if flow:
                    sector_flows[category]['buy_volume'] += flow.get('buy_volume', 0)
                    sector_flows[category]['sell_volume'] += flow.get('sell_volume', 0)
                    sector_flows[category]['net_flow'] += flow.get('net_flow', 0)
                    sector_flows[category]['market_count'] += 1
            
            # Calculate buy pressure for each sector
            for sector in sector_flows:
                total = sector_flows[sector]['buy_volume'] + sector_flows[sector]['sell_volume']
                sector_flows[sector]['buy_pressure'] = (
                    (sector_flows[sector]['buy_volume'] / total * 100) if total > 0 else 50
                )
            
            return dict(sector_flows)
            
        except Exception as e:
            logger.error(f"Error calculating sector flow: {e}")
            return {}
    
    def detect_sector_rotation(self, sector_flows: Dict[str, Dict]) -> List[Dict]:
        """Detect money rotating between sectors"""
        rotations = []
        
        try:
            for sector, flow in sector_flows.items():
                net_flow = flow.get('net_flow', 0)
                
                # Track historical flow
                if sector not in self.sector_flow_history:
                    self.sector_flow_history[sector] = []
                
                self.sector_flow_history[sector].append(net_flow)
                
                # Keep only last 24 data points (1 per hour for 24h)
                if len(self.sector_flow_history[sector]) > 24:
                    self.sector_flow_history[sector] = self.sector_flow_history[sector][-24:]
                
                # Need at least 2 data points
                if len(self.sector_flow_history[sector]) < 2:
                    continue
                
                # Calculate trend
                history = self.sector_flow_history[sector]
                avg_flow = sum(history) / len(history)
                
                # Detect significant changes
                if avg_flow != 0:
                    change_ratio = (net_flow - avg_flow) / abs(avg_flow)
                    
                    if abs(change_ratio) > SECTOR_ROTATION_THRESHOLD:
                        rotations.append({
                            'sector': sector,
                            'direction': 'inflow' if change_ratio > 0 else 'outflow',
                            'magnitude': abs(change_ratio),
                            'net_flow': net_flow,
                            'avg_flow': avg_flow
                        })
            
            return rotations
            
        except Exception as e:
            logger.error(f"Error detecting sector rotation: {e}")
            return []
    
    def detect_cross_market_flow(self, markets: List[Dict]) -> List[Dict]:
        """Detect correlated money movement between markets"""
        cross_flows = []
        
        try:
            # Group markets by category
            category_markets = defaultdict(list)
            for market in markets:
                category = self._get_category(market)
                category_markets[category].append(market)
            
            # Look for correlated flows within categories
            for category, market_list in category_markets.items():
                if len(market_list) < 2:
                    continue
                
                # Calculate flows for all markets in category
                flows = []
                for market in market_list:
                    condition_id = market.get('condition_id')
                    if condition_id:
                        flow = self.calculate_market_flow(condition_id, hours=1)
                        if flow:
                            flow['question'] = market.get('question', '')[:50]
                            flows.append(flow)
                
                # Find markets with opposite flows (potential arbitrage)
                inflows = [f for f in flows if f.get('net_flow', 0) > 0]
                outflows = [f for f in flows if f.get('net_flow', 0) < 0]
                
                if inflows and outflows:
                    # Report strongest opposing flows
                    top_inflow = max(inflows, key=lambda x: x.get('net_flow', 0))
                    top_outflow = min(outflows, key=lambda x: x.get('net_flow', 0))
                    
                    cross_flows.append({
                        'category': category,
                        'inflow_market': top_inflow.get('question'),
                        'inflow_amount': top_inflow.get('net_flow', 0),
                        'outflow_market': top_outflow.get('question'),
                        'outflow_amount': top_outflow.get('net_flow', 0)
                    })
            
            return cross_flows
            
        except Exception as e:
            logger.error(f"Error detecting cross-market flow: {e}")
            return []
    
    def process_flows(self):
        """Main flow processing loop"""
        try:
            logger.info("Starting money flow analysis...")
            
            markets = self.db.get_markets(limit=200)
            if not markets:
                logger.warning("No markets found for flow analysis")
                return
            
            # Process individual market flows
            significant_flows = []
            
            for market in markets:
                condition_id = market.get('condition_id')
                if not condition_id:
                    continue
                
                # Calculate 1-hour flow
                flow = self.calculate_market_flow(condition_id, hours=1)
                if not flow:
                    continue
                
                # Store flow snapshot
                self.db.insert_money_flow(flow)
                
                # Track history
                if condition_id not in self.flow_history:
                    self.flow_history[condition_id] = []
                
                self.flow_history[condition_id].append(flow)
                
                # Keep only last 24 data points
                if len(self.flow_history[condition_id]) > 24:
                    self.flow_history[condition_id] = self.flow_history[condition_id][-24:]
                
                # Check for significant flow
                net_flow = flow.get('net_flow', 0)
                if abs(net_flow) > SIGNIFICANT_FLOW_USD:
                    direction = "📈 INFLOW" if net_flow > 0 else "📉 OUTFLOW"
                    logger.info(f"{direction}: ${abs(net_flow):,.0f} in {market.get('question', '')[:40]}...")
                    
                    significant_flows.append({
                        'market': market,
                        'flow': flow
                    })
                    
                    # Create signal for significant flow
                    self.db.insert_signal({
                        'market_id': condition_id,
                        'type': 'money_flow',
                        'title': f"Large {'Inflow' if net_flow > 0 else 'Outflow'} Detected",
                        'description': f"${abs(net_flow):,.0f} net {'buying' if net_flow > 0 else 'selling'} in the last hour",
                        'severity': 'high' if abs(net_flow) > SIGNIFICANT_FLOW_USD * 2 else 'medium',
                        'data': flow
                    })
            
            # Calculate and analyze sector flows
            sector_flows = self.calculate_sector_flow()
            
            # Log sector summary
            logger.info("=== Sector Flow Summary ===")
            for sector, flow in sorted(sector_flows.items(), key=lambda x: abs(x[1].get('net_flow', 0)), reverse=True):
                net = flow.get('net_flow', 0)
                pressure = flow.get('buy_pressure', 50)
                direction = "📈" if net > 0 else "📉" if net < 0 else "➡️"
                logger.info(f"  {direction} {sector}: ${net:+,.0f} (Buy Pressure: {pressure:.0f}%)")
            
            # Detect sector rotation
            rotations = self.detect_sector_rotation(sector_flows)
            for rotation in rotations:
                sector = rotation['sector']
                direction = rotation['direction']
                magnitude = rotation['magnitude']
                
                logger.info(f"🔄 Sector Rotation: {sector} seeing strong {direction} ({magnitude:.0%})")
                
                # Create signal for rotation
                self.db.insert_signal({
                    'market_id': None,
                    'type': 'sector_rotation',
                    'title': f"{sector} Sector {direction.title()}",
                    'description': f"Money {'flowing into' if direction == 'inflow' else 'leaving'} {sector} sector ({magnitude:.0%} above average)",
                    'severity': 'high' if magnitude > 0.5 else 'medium',
                    'data': rotation
                })
            
            # Detect cross-market flows
            cross_flows = self.detect_cross_market_flow(markets)
            for cf in cross_flows:
                logger.info(f"🔀 Cross-Market: {cf['category']} - IN: {cf['inflow_market'][:30]}... / OUT: {cf['outflow_market'][:30]}...")
            
            logger.info(f"Processed flows for {len(markets)} markets, {len(significant_flows)} significant")
            
        except Exception as e:
            logger.error(f"Error in flow processing: {e}", exc_info=True)
    
    def run(self):
        """Main worker loop"""
        logger.info("Money Flow Worker started (Wolf Pack Edition)")
        
        while True:
            try:
                self.process_flows()
            except Exception as e:
                logger.error(f"Fatal error in money flow worker: {e}", exc_info=True)
            
            logger.info(f"Sleeping for {self.scan_interval} seconds...")
            time.sleep(self.scan_interval)


if __name__ == "__main__":
    worker = MoneyFlowWorker()
    worker.run()

