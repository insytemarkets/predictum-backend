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
    
    def insert_orderbook(self, market_id: str, bids: List[Dict], asks: List[Dict]) -> Optional[Dict]:
        """Insert order book data"""
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
            
            result = self.client.table('order_books').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error inserting orderbook: {e}")
            return None
    
    def insert_price(self, market_id: str, outcome_index: int, price: float) -> Optional[Dict]:
        """Insert price data"""
        try:
            market = self.client.table('markets').select('id').eq('condition_id', market_id).execute()
            if not market.data or len(market.data) == 0:
                return None
            
            market_uuid = market.data[0]['id']
            
            data = {
                'market_id': market_uuid,
                'outcome_index': outcome_index,
                'price': price
            }
            
            result = self.client.table('prices').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error inserting price: {e}")
            return None
    
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
