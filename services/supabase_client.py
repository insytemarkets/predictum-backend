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
    
    def get_opportunities(self, limit: int = 100, status: str = 'active') -> List[Dict]:
        """Get opportunities from database"""
        try:
            result = self.client.table('opportunities').select('*, markets(*)').eq('status', status).order('profit_potential', desc=True).limit(limit).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting opportunities: {e}")
            return []
