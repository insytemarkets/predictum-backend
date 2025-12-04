"""
Supabase client for data storage
"""
import os
import logging
from typing import Dict, List, Optional, Any
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class SupabaseClient:
    """Client for Supabase database operations"""
    
    def __init__(self):
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        
        if not url or not key:
            raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables")
        
        self.client: Client = create_client(url, key)
        logger.info("Supabase client initialized")
    
    def upsert_market(self, market_data: Dict) -> Optional[Dict]:
        """Insert or update a market"""
        try:
            # Extract key fields
            condition_id = market_data.get('condition_id') or market_data.get('id')
            if not condition_id:
                logger.warning("Market missing condition_id")
                return None
            
            # Ensure proper data types
            volume_24h = float(market_data.get('volume_24h', 0) or 0)
            liquidity = float(market_data.get('liquidity', 0) or 0)
            
            data = {
                'condition_id': str(condition_id),
                'question': str(market_data.get('question', '')),
                'slug': str(market_data.get('slug', condition_id)),
                'url': str(market_data.get('url', f"https://polymarket.com/event/{condition_id}")),
                'end_date': market_data.get('end_date'),
                'volume_24h': volume_24h,
                'liquidity': liquidity,
                'raw_data': market_data.get('raw_data', market_data)
            }
            
            # Add price fields if provided
            if 'current_price' in market_data:
                data['current_price'] = float(market_data['current_price'])
            if 'price_change_24h' in market_data and market_data['price_change_24h'] is not None:
                data['price_change_24h'] = float(market_data['price_change_24h'])
            if 'price_change_percent' in market_data and market_data['price_change_percent'] is not None:
                data['price_change_percent'] = float(market_data['price_change_percent'])
            if 'tokens' in market_data:
                data['tokens'] = market_data['tokens']
            
            result = self.client.table('markets').upsert(
                data,
                on_conflict='condition_id'
            ).execute()
            
            if result.data:
                return result.data[0] if isinstance(result.data, list) else result.data
            return None
        except Exception as e:
            logger.error(f"Error upserting market: {e}", exc_info=True)
            return None
    
    def insert_orderbook(self, market_id: str, bids: List[Dict], asks: List[Dict], metadata: Optional[Dict] = None) -> Optional[Dict]:
        """Insert order book data with optional metadata"""
        try:
            # First, get market UUID from condition_id
            market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
            if not market.data or len(market.data) == 0:
                logger.warning(f"Market not found: {market_id}")
                return None
            
            market_uuid = market.data[0]['id']
            
            data = {
                'market_id': market_uuid,
                'bids': bids,
                'asks': asks
            }
            
            # Add metadata if provided
            if metadata:
                if 'min_order_size' in metadata:
                    data['min_order_size'] = float(metadata['min_order_size']) if metadata['min_order_size'] else None
                if 'tick_size' in metadata:
                    data['tick_size'] = float(metadata['tick_size']) if metadata['tick_size'] else None
                if 'neg_risk' in metadata:
                    data['neg_risk'] = bool(metadata['neg_risk'])
            
            result = self.client.table('order_books').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error inserting orderbook: {e}", exc_info=True)
            return None
    
    def insert_price(self, market_id: str, outcome_index: int, price: float) -> Optional[Dict]:
        """Insert price data with timestamp"""
        try:
            market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
            if not market.data or len(market.data) == 0:
                logger.warning(f"Market not found for price insert: {market_id}")
                return None
            
            market_uuid = market.data[0]['id']
            
            data = {
                'market_id': market_uuid,
                'outcome_index': outcome_index,
                'price': float(price),
                'timestamp': 'now()'
            }
            
            result = self.client.table('prices').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error inserting price: {e}", exc_info=True)
            return None
    
    def get_price_history(self, market_id: str, hours: int = 24) -> List[Dict]:
        """Get price history for a market"""
        try:
            market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
            if not market.data or len(market.data) == 0:
                return []
            
            market_uuid = market.data[0]['id']
            
            # Calculate cutoff time
            from datetime import datetime, timedelta
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            
            result = self.client.table('prices')\
                .select('*')\
                .eq('market_id', market_uuid)\
                .gte('timestamp', cutoff.isoformat())\
                .order('timestamp', desc=False)\
                .execute()
            
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting price history: {e}")
            return []
    
    def get_latest_prices(self, market_ids: List[str]) -> Dict[str, Dict]:
        """Get latest prices for multiple markets"""
        try:
            if not market_ids:
                return {}
            
            # Get market UUIDs
            markets_result = self.client.table('markets')\
                .select('id, condition_id')\
                .in_('condition_id', market_ids)\
                .execute()
            
            if not markets_result.data:
                return {}
            
            market_uuid_map = {m['condition_id']: m['id'] for m in markets_result.data}
            market_uuids = list(market_uuid_map.values())
            
            # Get latest prices for each market
            prices_result = self.client.table('prices')\
                .select('market_id, outcome_index, price, timestamp')\
                .in_('market_id', market_uuids)\
                .order('timestamp', desc=True)\
                .execute()
            
            # Group by market_id and get latest for each outcome
            latest_prices = {}
            for price_data in prices_result.data or []:
                market_uuid = price_data['market_id']
                condition_id = None
                for cid, uuid in market_uuid_map.items():
                    if uuid == market_uuid:
                        condition_id = cid
                        break
                
                if condition_id:
                    if condition_id not in latest_prices:
                        latest_prices[condition_id] = {}
                    outcome_idx = price_data['outcome_index']
                    if outcome_idx not in latest_prices[condition_id]:
                        latest_prices[condition_id][outcome_idx] = price_data
            
            return latest_prices
        except Exception as e:
            logger.error(f"Error getting latest prices: {e}")
            return {}
    
    def upsert_opportunity(self, opportunity_data: Dict) -> Optional[Dict]:
        """Insert or update an opportunity"""
        try:
            market_id = opportunity_data.get('market_id')
            if not market_id:
                logger.warning("Opportunity missing market_id")
                return None
            
            # Get market UUID
            market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
            if not market.data or len(market.data) == 0:
                logger.warning(f"Market not found for opportunity: {market_id}")
                return None
            
            market_uuid = market.data[0]['id']
            
            # Ensure proper data types
            profit_potential = float(opportunity_data.get('profit_potential', 0) or 0)
            confidence_score = float(opportunity_data.get('confidence_score', 0) or 0)
            
            data = {
                'market_id': market_uuid,
                'type': str(opportunity_data.get('type', 'spread')),
                'profit_potential': profit_potential,
                'confidence_score': confidence_score,
                'details': opportunity_data.get('details', {}),
                'status': str(opportunity_data.get('status', 'active'))
            }
            
            # Use upsert with conflict on market_id + type (unique combination)
            result = self.client.table('opportunities').upsert(
                data,
                on_conflict='market_id,type'
            ).execute()
            
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error upserting opportunity: {e}", exc_info=True)
            return None
    
    def upsert_market_stats(self, market_id: str, stats: Dict) -> Optional[Dict]:
        """Insert or update market statistics"""
        try:
            market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
            if not market.data or len(market.data) == 0:
                return None
            
            market_uuid = market.data[0]['id']
            
            data = {
                'market_id': market_uuid,
                'spread_percentage': stats.get('spread_percentage', 0),
                'buy_pressure': stats.get('buy_pressure', 0),
                'sell_pressure': stats.get('sell_pressure', 0)
            }
            
            result = self.client.table('market_stats').upsert(
                data,
                on_conflict='market_id'
            ).execute()
            
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error upserting market stats: {e}")
            return None
    
    def get_markets(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get markets from database"""
        try:
            result = self.client.table('markets').select('*').order('volume_24h', desc=True).limit(limit).offset(offset).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting markets: {e}")
            return []
    
    def get_opportunities(self, limit: int = 100, status: str = 'active', market_id: str = None) -> List[Dict]:
        """Get opportunities from database"""
        try:
            query = self.client.table('opportunities').select('*, markets(*)').eq('status', status)
            if market_id:
                # Get market UUID first
                market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
                if market.data:
                    query = query.eq('market_id', market.data[0]['id'])
            result = query.order('profit_potential', desc=True).limit(limit).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting opportunities: {e}")
            return []
    
    # ============================================
    # TRADES - For whale detection and trade flow
    # ============================================
    
    def insert_trade(self, trade_data: Dict) -> Optional[Dict]:
        """Insert a trade record"""
        try:
            market_id = trade_data.get('market_id')
            if not market_id:
                return None
            
            # Get market UUID
            market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
            if not market.data or len(market.data) == 0:
                return None
            
            market_uuid = market.data[0]['id']
            
            data = {
                'market_id': market_uuid,
                'token_id': str(trade_data.get('token_id', '')),
                'price': float(trade_data.get('price', 0)),
                'size': float(trade_data.get('size', 0)),
                'side': str(trade_data.get('side', 'UNKNOWN')),
                'maker': str(trade_data.get('maker', '')),
                'taker': str(trade_data.get('taker', '')),
                'is_whale': bool(trade_data.get('is_whale', False))
            }
            
            # Handle timestamp
            timestamp = trade_data.get('timestamp')
            if timestamp:
                data['timestamp'] = timestamp
            
            result = self.client.table('trades').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error inserting trade: {e}")
            return None
    
    def get_trades(self, market_id: str = None, limit: int = 100, whale_only: bool = False) -> List[Dict]:
        """Get trades, optionally filtered by market or whale status"""
        try:
            query = self.client.table('trades').select('*, markets(*)')
            
            if market_id:
                market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
                if market.data:
                    query = query.eq('market_id', market.data[0]['id'])
            
            if whale_only:
                query = query.eq('is_whale', True)
            
            result = query.order('timestamp', desc=True).limit(limit).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting trades: {e}")
            return []
    
    def get_whale_trades(self, limit: int = 50) -> List[Dict]:
        """Get recent whale trades"""
        return self.get_trades(whale_only=True, limit=limit)
    
    def get_trade_flow(self, market_id: str, hours: int = 24) -> Dict:
        """Calculate buy/sell pressure for a market"""
        try:
            from datetime import datetime, timedelta
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            
            market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
            if not market.data:
                return {'buy_volume': 0, 'sell_volume': 0, 'net_flow': 0}
            
            market_uuid = market.data[0]['id']
            
            result = self.client.table('trades')\
                .select('side, size, price')\
                .eq('market_id', market_uuid)\
                .gte('timestamp', cutoff.isoformat())\
                .execute()
            
            buy_volume = 0
            sell_volume = 0
            
            for trade in result.data or []:
                value = float(trade.get('size', 0)) * float(trade.get('price', 0))
                if trade.get('side') == 'BUY':
                    buy_volume += value
                else:
                    sell_volume += value
            
            return {
                'buy_volume': buy_volume,
                'sell_volume': sell_volume,
                'net_flow': buy_volume - sell_volume,
                'buy_pressure': buy_volume / (buy_volume + sell_volume) * 100 if (buy_volume + sell_volume) > 0 else 50
            }
        except Exception as e:
            logger.error(f"Error calculating trade flow: {e}")
            return {'buy_volume': 0, 'sell_volume': 0, 'net_flow': 0, 'buy_pressure': 50}
    
    # ============================================
    # ALERTS - User-defined price/event alerts
    # ============================================
    
    def insert_alert(self, alert_data: Dict) -> Optional[Dict]:
        """Create a new alert"""
        try:
            market_id = alert_data.get('market_id')
            market_uuid = None
            
            if market_id:
                market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
                if market.data:
                    market_uuid = market.data[0]['id']
            
            data = {
                'market_id': market_uuid,
                'type': str(alert_data.get('type', 'price_above')),
                'threshold': float(alert_data.get('threshold', 0)),
                'status': 'active'
            }
            
            result = self.client.table('alerts').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error inserting alert: {e}")
            return None
    
    def get_alerts(self, status: str = 'active', limit: int = 100) -> List[Dict]:
        """Get alerts"""
        try:
            query = self.client.table('alerts').select('*, markets(*)')
            if status:
                query = query.eq('status', status)
            result = query.order('created_at', desc=True).limit(limit).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting alerts: {e}")
            return []
    
    def trigger_alert(self, alert_id: str) -> Optional[Dict]:
        """Mark an alert as triggered"""
        try:
            from datetime import datetime
            result = self.client.table('alerts').update({
                'status': 'triggered',
                'triggered_at': datetime.utcnow().isoformat()
            }).eq('id', alert_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error triggering alert: {e}")
            return None
    
    def delete_alert(self, alert_id: str) -> bool:
        """Delete an alert"""
        try:
            self.client.table('alerts').delete().eq('id', alert_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error deleting alert: {e}")
            return False
    
    # ============================================
    # WATCHLIST - Personal market tracking
    # ============================================
    
    def add_to_watchlist(self, market_id: str, notes: str = '') -> Optional[Dict]:
        """Add a market to watchlist"""
        try:
            market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
            if not market.data:
                return None
            
            market_uuid = market.data[0]['id']
            
            data = {
                'market_id': market_uuid,
                'notes': notes
            }
            
            result = self.client.table('watchlists').upsert(
                data,
                on_conflict='market_id'
            ).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error adding to watchlist: {e}")
            return None
    
    def remove_from_watchlist(self, market_id: str) -> bool:
        """Remove a market from watchlist"""
        try:
            market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
            if not market.data:
                return False
            
            self.client.table('watchlists').delete().eq('market_id', market.data[0]['id']).execute()
            return True
        except Exception as e:
            logger.error(f"Error removing from watchlist: {e}")
            return False
    
    def get_watchlist(self, limit: int = 100) -> List[Dict]:
        """Get all watchlist items with market data"""
        try:
            result = self.client.table('watchlists')\
                .select('*, markets(*)')\
                .order('created_at', desc=True)\
                .limit(limit)\
                .execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting watchlist: {e}")
            return []
    
    def update_watchlist_notes(self, market_id: str, notes: str) -> Optional[Dict]:
        """Update notes for a watchlist item"""
        try:
            market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
            if not market.data:
                return None
            
            result = self.client.table('watchlists').update({
                'notes': notes
            }).eq('market_id', market.data[0]['id']).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error updating watchlist notes: {e}")
            return None
    
    # ============================================
    # CORRELATIONS - Cross-market analysis
    # ============================================
    
    def upsert_correlation(self, market_a_id: str, market_b_id: str, correlation_score: float) -> Optional[Dict]:
        """Insert or update a correlation between two markets"""
        try:
            # Get market UUIDs
            market_a = self.client.table('markets').select('id').eq('condition_id', market_a_id).execute()
            market_b = self.client.table('markets').select('id').eq('condition_id', market_b_id).execute()
            
            if not market_a.data or not market_b.data:
                return None
            
            data = {
                'market_a_id': market_a.data[0]['id'],
                'market_b_id': market_b.data[0]['id'],
                'correlation_score': float(correlation_score)
            }
            
            result = self.client.table('correlations').upsert(
                data,
                on_conflict='market_a_id,market_b_id'
            ).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error upserting correlation: {e}")
            return None
    
    def get_correlations(self, market_id: str = None, min_score: float = 0.5, limit: int = 50) -> List[Dict]:
        """Get market correlations"""
        try:
            # Get correlations with market data
            query = self.client.table('correlations')\
                .select('*, market_a:markets!correlations_market_a_id_fkey(*), market_b:markets!correlations_market_b_id_fkey(*)')
            
            if market_id:
                market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
                if market.data:
                    market_uuid = market.data[0]['id']
                    # Get correlations where this market is either A or B
                    query = query.or_(f'market_a_id.eq.{market_uuid},market_b_id.eq.{market_uuid}')
            
            result = query\
                .gte('correlation_score', min_score)\
                .order('correlation_score', desc=True)\
                .limit(limit)\
                .execute()
            
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting correlations: {e}")
            return []
    
    # ============================================
    # SIGNALS - For live signal feed
    # ============================================
    
    def insert_signal(self, signal_data: Dict) -> Optional[Dict]:
        """Insert a new signal"""
        try:
            market_id = signal_data.get('market_id')
            market_uuid = None
            
            if market_id:
                market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
                if market.data:
                    market_uuid = market.data[0]['id']
            
            data = {
                'market_id': market_uuid,
                'type': str(signal_data.get('type', 'alert')),
                'title': str(signal_data.get('title', '')),
                'description': str(signal_data.get('description', '')),
                'severity': str(signal_data.get('severity', 'medium')),
                'data': signal_data.get('data', {})
            }
            
            result = self.client.table('signals').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error inserting signal: {e}")
            return None
    
    def get_signals(self, limit: int = 50) -> List[Dict]:
        """Get recent signals"""
        try:
            result = self.client.table('signals')\
                .select('*, markets(*)')\
                .order('created_at', desc=True)\
                .limit(limit)\
                .execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting signals: {e}")
            return []
    
    # ============================================
    # SIGNAL PERFORMANCE - Track accuracy
    # ============================================
    
    def record_signal_performance(self, opportunity_id: str, detected_price: float, 
                                   resolved_price: float, was_profitable: bool) -> Optional[Dict]:
        """Record the performance of a signal/opportunity"""
        try:
            actual_profit = ((resolved_price - detected_price) / detected_price) * 100 if detected_price > 0 else 0
            
            data = {
                'opportunity_id': opportunity_id,
                'detected_price': detected_price,
                'resolved_price': resolved_price,
                'actual_profit': actual_profit,
                'was_profitable': was_profitable
            }
            
            result = self.client.table('signal_performance').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error recording signal performance: {e}")
            return None
    
    def get_performance_stats(self) -> Dict:
        """Get aggregate performance statistics"""
        try:
            result = self.client.table('signal_performance').select('*').execute()
            
            if not result.data:
                return {'total': 0, 'profitable': 0, 'accuracy': 0, 'avg_profit': 0}
            
            total = len(result.data)
            profitable = sum(1 for r in result.data if r.get('was_profitable'))
            avg_profit = sum(r.get('actual_profit', 0) for r in result.data) / total if total > 0 else 0
            
            return {
                'total': total,
                'profitable': profitable,
                'accuracy': (profitable / total) * 100 if total > 0 else 0,
                'avg_profit': avg_profit
            }
        except Exception as e:
            logger.error(f"Error getting performance stats: {e}")
            return {'total': 0, 'profitable': 0, 'accuracy': 0, 'avg_profit': 0}
    
    # ============================================
    # PRICE CHANGE TRACKING
    # ============================================
    
    def update_market_prices(self, condition_id: str, price_data: Dict) -> Optional[Dict]:
        """Update market with current price and price change data"""
        try:
            update_data = {}
            
            if 'current_price' in price_data and price_data['current_price'] is not None:
                update_data['current_price'] = float(price_data['current_price'])
            
            if 'price_change_24h' in price_data and price_data['price_change_24h'] is not None:
                update_data['price_change_24h'] = float(price_data['price_change_24h'])
            
            if 'price_change_percent' in price_data and price_data['price_change_percent'] is not None:
                update_data['price_change_percent'] = float(price_data['price_change_percent'])
            
            if 'price_change_1h' in price_data and price_data['price_change_1h'] is not None:
                update_data['price_change_1h'] = float(price_data['price_change_1h'])
            
            if 'price_change_7d' in price_data and price_data['price_change_7d'] is not None:
                update_data['price_change_7d'] = float(price_data['price_change_7d'])
            
            if 'momentum' in price_data and price_data['momentum'] is not None:
                update_data['momentum'] = float(price_data['momentum'])
            
            if 'volatility_24h' in price_data and price_data['volatility_24h'] is not None:
                update_data['volatility_24h'] = float(price_data['volatility_24h'])
            
            if not update_data:
                return None
            
            result = self.client.table('markets').update(update_data).eq('condition_id', condition_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error updating market prices: {e}")
            return None
    
    # ============================================
    # MONEY FLOW TRACKING
    # ============================================
    
    def insert_money_flow(self, flow_data: Dict) -> Optional[Dict]:
        """Insert money flow snapshot"""
        try:
            market_id = flow_data.get('market_id')
            market_uuid = None
            
            if market_id:
                market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
                if market.data:
                    market_uuid = market.data[0]['id']
            
            data = {
                'market_id': market_uuid,
                'net_flow': float(flow_data.get('net_flow', 0)),
                'buy_volume': float(flow_data.get('buy_volume', 0)),
                'sell_volume': float(flow_data.get('sell_volume', 0)),
                'flow_velocity': float(flow_data.get('flow_velocity', 0)),
                'period': str(flow_data.get('period', '1h'))
            }
            
            result = self.client.table('money_flow').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error inserting money flow: {e}")
            return None
    
    def get_money_flow(self, market_id: str = None, period: str = '24h', limit: int = 100) -> List[Dict]:
        """Get money flow data"""
        try:
            query = self.client.table('money_flow').select('*, markets(*)')
            
            if market_id:
                market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
                if market.data:
                    query = query.eq('market_id', market.data[0]['id'])
            
            if period:
                query = query.eq('period', period)
            
            result = query.order('timestamp', desc=True).limit(limit).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting money flow: {e}")
            return []
    
    # ============================================
    # ORDER BOOK INTELLIGENCE
    # ============================================
    
    def insert_orderbook_snapshot(self, snapshot_data: Dict) -> Optional[Dict]:
        """Insert order book snapshot with depth analysis"""
        try:
            market_id = snapshot_data.get('market_id')
            market_uuid = None
            
            if market_id:
                market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
                if market.data:
                    market_uuid = market.data[0]['id']
            
            data = {
                'market_id': market_uuid,
                'bid_depth_10': float(snapshot_data.get('bid_depth_10', 0)),
                'ask_depth_10': float(snapshot_data.get('ask_depth_10', 0)),
                'spread': float(snapshot_data.get('spread', 0)),
                'imbalance': float(snapshot_data.get('imbalance', 0)),
                'best_bid': float(snapshot_data.get('best_bid', 0)),
                'best_ask': float(snapshot_data.get('best_ask', 0))
            }
            
            result = self.client.table('orderbook_snapshots').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error inserting orderbook snapshot: {e}")
            return None
    
    def get_orderbook_snapshots(self, market_id: str, limit: int = 100) -> List[Dict]:
        """Get order book snapshots for analysis"""
        try:
            market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
            if not market.data:
                return []
            
            result = self.client.table('orderbook_snapshots')\
                .select('*')\
                .eq('market_id', market.data[0]['id'])\
                .order('timestamp', desc=True)\
                .limit(limit)\
                .execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting orderbook snapshots: {e}")
            return []
