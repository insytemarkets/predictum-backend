"""
Correlation Worker
Calculates price correlations between markets to find leading indicators
"""
import time
import json
import logging
import math
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.polymarket_api import PolymarketAPI
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CorrelationWorker:
    """Calculates correlations between prediction markets"""
    
    def __init__(self):
        self.api = PolymarketAPI()
        self.db = SupabaseClient()
        self.scan_interval = 300  # 5 minutes
        self.min_data_points = 10  # Minimum price points needed for correlation
        self.correlation_threshold = 0.5  # Only store correlations above this
        
    def _parse_clob_token_ids(self, tokens) -> List[str]:
        """Parse clobTokenIds which might be a JSON string"""
        if isinstance(tokens, list):
            return [str(t) for t in tokens if t]
        elif isinstance(tokens, str):
            try:
                parsed = json.loads(tokens)
                if isinstance(parsed, list):
                    return [str(t) for t in parsed if t]
            except (json.JSONDecodeError, ValueError):
                pass
        return []
    
    def _get_market_tokens(self) -> Dict[str, Dict]:
        """Get market data with tokens"""
        markets_data = {}
        
        try:
            markets = self.db.get_markets(limit=100)
            
            for market in markets:
                condition_id = market.get('condition_id')
                if not condition_id:
                    continue
                
                raw_data = market.get('raw_data', {})
                tokens = self._parse_clob_token_ids(raw_data.get('clobTokenIds', []))
                
                if not tokens:
                    tokens = self._parse_clob_token_ids(raw_data.get('stored_tokens', []))
                
                if tokens:
                    markets_data[condition_id] = {
                        'tokens': tokens,
                        'question': market.get('question', ''),
                        'category': raw_data.get('category', 'Other'),
                        'volume': market.get('volume_24h', 0)
                    }
            
            return markets_data
            
        except Exception as e:
            logger.error(f"Error getting market tokens: {e}")
            return {}
    
    def _calculate_pearson_correlation(self, x: List[float], y: List[float]) -> float:
        """
        Calculate Pearson correlation coefficient between two price series
        Returns value between -1 and 1
        """
        n = len(x)
        if n != len(y) or n < self.min_data_points:
            return 0.0
        
        # Calculate means
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        
        # Calculate standard deviations and covariance
        sum_xy = 0
        sum_x2 = 0
        sum_y2 = 0
        
        for i in range(n):
            dx = x[i] - mean_x
            dy = y[i] - mean_y
            sum_xy += dx * dy
            sum_x2 += dx * dx
            sum_y2 += dy * dy
        
        # Avoid division by zero
        if sum_x2 == 0 or sum_y2 == 0:
            return 0.0
        
        correlation = sum_xy / math.sqrt(sum_x2 * sum_y2)
        return correlation
    
    def _align_price_series(self, prices_a: List[Dict], prices_b: List[Dict]) -> Tuple[List[float], List[float]]:
        """
        Align two price series by timestamp for comparison
        Returns aligned price values
        """
        # Create timestamp -> price maps
        map_a = {}
        map_b = {}
        
        for p in prices_a:
            ts = p.get('timestamp')
            price = p.get('price')
            if ts and price:
                # Normalize timestamp to hour for alignment
                if isinstance(ts, str):
                    try:
                        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        ts = dt.replace(minute=0, second=0, microsecond=0).isoformat()
                    except:
                        pass
                map_a[ts] = float(price)
        
        for p in prices_b:
            ts = p.get('timestamp')
            price = p.get('price')
            if ts and price:
                if isinstance(ts, str):
                    try:
                        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        ts = dt.replace(minute=0, second=0, microsecond=0).isoformat()
                    except:
                        pass
                map_b[ts] = float(price)
        
        # Find common timestamps
        common_ts = sorted(set(map_a.keys()) & set(map_b.keys()))
        
        if len(common_ts) < self.min_data_points:
            return [], []
        
        aligned_a = [map_a[ts] for ts in common_ts]
        aligned_b = [map_b[ts] for ts in common_ts]
        
        return aligned_a, aligned_b
    
    def calculate_correlations(self):
        """Calculate correlations between all market pairs"""
        try:
            logger.info("Starting correlation calculation...")
            
            markets_data = self._get_market_tokens()
            if len(markets_data) < 2:
                logger.warning("Not enough markets for correlation analysis")
                return
            
            market_ids = list(markets_data.keys())
            price_cache: Dict[str, List[Dict]] = {}
            
            # Fetch price history for all markets
            logger.info(f"Fetching price history for {len(market_ids)} markets...")
            
            for market_id in market_ids:
                tokens = markets_data[market_id].get('tokens', [])
                if tokens:
                    # Get price history for first token (YES outcome)
                    history = self.api.get_price_history(tokens[0], interval='1h', fidelity=100)
                    if history:
                        price_cache[market_id] = history
            
            logger.info(f"Got price history for {len(price_cache)} markets")
            
            if len(price_cache) < 2:
                logger.warning("Not enough price data for correlation analysis")
                return
            
            # Calculate pairwise correlations
            correlations_found = 0
            market_list = list(price_cache.keys())
            
            for i, market_a in enumerate(market_list):
                for market_b in market_list[i+1:]:
                    try:
                        # Align price series
                        prices_a, prices_b = self._align_price_series(
                            price_cache[market_a],
                            price_cache[market_b]
                        )
                        
                        if len(prices_a) < self.min_data_points:
                            continue
                        
                        # Calculate correlation
                        correlation = self._calculate_pearson_correlation(prices_a, prices_b)
                        
                        # Only store significant correlations
                        if abs(correlation) >= self.correlation_threshold:
                            self.db.upsert_correlation(market_a, market_b, correlation)
                            correlations_found += 1
                            
                            # Log strong correlations
                            if abs(correlation) >= 0.7:
                                q_a = markets_data[market_a].get('question', '')[:50]
                                q_b = markets_data[market_b].get('question', '')[:50]
                                direction = "positive" if correlation > 0 else "negative"
                                logger.info(f"Strong {direction} correlation ({correlation:.2f}): {q_a}... <-> {q_b}...")
                    
                    except Exception as e:
                        logger.error(f"Error calculating correlation for {market_a} <-> {market_b}: {e}")
                        continue
            
            logger.info(f"Calculated {correlations_found} significant correlations")
            
        except Exception as e:
            logger.error(f"Error in correlation calculation: {e}", exc_info=True)
    
    def find_leading_indicators(self):
        """
        Find markets that tend to move before others
        A leads B if changes in A predict changes in B with a time lag
        """
        try:
            logger.info("Searching for leading indicators...")
            
            markets_data = self._get_market_tokens()
            if len(markets_data) < 2:
                return
            
            # Get price histories
            price_histories = {}
            for market_id, data in markets_data.items():
                tokens = data.get('tokens', [])
                if tokens:
                    history = self.api.get_price_history(tokens[0], interval='1h', fidelity=48)
                    if history and len(history) >= 24:
                        # Calculate price changes (returns)
                        changes = []
                        for i in range(1, len(history)):
                            prev_price = history[i-1].get('price', 0)
                            curr_price = history[i].get('price', 0)
                            if prev_price > 0:
                                change = (curr_price - prev_price) / prev_price
                                changes.append(change)
                        
                        if len(changes) >= 12:
                            price_histories[market_id] = changes
            
            if len(price_histories) < 2:
                return
            
            # Check for leading relationships (with 1-hour lag)
            leading_pairs = []
            market_list = list(price_histories.keys())
            
            for i, market_a in enumerate(market_list):
                for market_b in market_list[i+1:]:
                    changes_a = price_histories[market_a]
                    changes_b = price_histories[market_b]
                    
                    # A leads B: correlate A[t] with B[t+1]
                    min_len = min(len(changes_a) - 1, len(changes_b) - 1)
                    if min_len < 10:
                        continue
                    
                    # A -> B (A leads B)
                    a_leads = self._calculate_pearson_correlation(
                        changes_a[:min_len],
                        changes_b[1:min_len+1]
                    )
                    
                    # B -> A (B leads A)
                    b_leads = self._calculate_pearson_correlation(
                        changes_b[:min_len],
                        changes_a[1:min_len+1]
                    )
                    
                    # Check for significant leading relationship
                    if abs(a_leads) > 0.5 and abs(a_leads) > abs(b_leads):
                        leading_pairs.append((market_a, market_b, a_leads))
                        q_a = markets_data[market_a].get('question', '')[:40]
                        q_b = markets_data[market_b].get('question', '')[:40]
                        logger.info(f"📈 Leading indicator: {q_a}... -> {q_b}... (r={a_leads:.2f})")
                    
                    elif abs(b_leads) > 0.5 and abs(b_leads) > abs(a_leads):
                        leading_pairs.append((market_b, market_a, b_leads))
                        q_a = markets_data[market_a].get('question', '')[:40]
                        q_b = markets_data[market_b].get('question', '')[:40]
                        logger.info(f"📈 Leading indicator: {q_b}... -> {q_a}... (r={b_leads:.2f})")
            
            logger.info(f"Found {len(leading_pairs)} leading indicator relationships")
            
        except Exception as e:
            logger.error(f"Error finding leading indicators: {e}", exc_info=True)
    
    def analyze_category_correlations(self):
        """Analyze correlations within categories (Politics, Crypto, etc.)"""
        try:
            markets_data = self._get_market_tokens()
            
            # Group markets by category
            categories = defaultdict(list)
            for market_id, data in markets_data.items():
                category = data.get('category', 'Other')
                categories[category].append(market_id)
            
            logger.info(f"Categories found: {dict((k, len(v)) for k, v in categories.items())}")
            
            # Analyze intra-category correlations
            for category, market_ids in categories.items():
                if len(market_ids) < 2:
                    continue
                
                # Get existing correlations for this category
                correlations = []
                for market_id in market_ids:
                    market_corrs = self.db.get_correlations(market_id=market_id, min_score=0.3)
                    for corr in market_corrs:
                        corr_score = corr.get('correlation_score', 0)
                        if abs(corr_score) >= 0.3:
                            correlations.append(abs(corr_score))
                
                if correlations:
                    avg_correlation = sum(correlations) / len(correlations)
                    logger.info(f"Category '{category}': {len(market_ids)} markets, avg correlation: {avg_correlation:.2f}")
            
        except Exception as e:
            logger.error(f"Error analyzing category correlations: {e}")
    
    def run(self):
        """Main worker loop"""
        logger.info("Correlation Worker started")
        
        while True:
            try:
                # Calculate market correlations
                self.calculate_correlations()
                
                # Find leading indicators
                self.find_leading_indicators()
                
                # Analyze by category
                self.analyze_category_correlations()
                
            except Exception as e:
                logger.error(f"Fatal error in correlation worker: {e}", exc_info=True)
            
            logger.info(f"Sleeping for {self.scan_interval} seconds...")
            time.sleep(self.scan_interval)


if __name__ == "__main__":
    worker = CorrelationWorker()
    worker.run()



