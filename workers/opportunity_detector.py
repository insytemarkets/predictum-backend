"""
Opportunity Detector Worker
Analyzes market data to detect arbitrage, spreads, and negative risk opportunities
"""
import time
import logging
from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OpportunityDetector:
    def __init__(self):
        self.db = SupabaseClient()
        self.scan_interval = 60  # seconds
    
    def detect_opportunities(self):
        """Analyze markets and detect opportunities"""
        try:
            logger.info("Starting opportunity detection...")
            
            # Get recent order books and prices
            # This is a simplified version - real implementation would be more sophisticated
            markets = self.db.get_markets(limit=100)
            
            opportunities_found = 0
            for market in markets:
                try:
                    # Check for spread opportunities
                    spread_opp = self._detect_spread(market)
                    if spread_opp:
                        self.db.upsert_opportunity(spread_opp)
                        opportunities_found += 1
                    
                    # Check for negative risk (sum of probabilities > 100%)
                    neg_risk_opp = self._detect_negative_risk(market)
                    if neg_risk_opp:
                        self.db.upsert_opportunity(neg_risk_opp)
                        opportunities_found += 1
                        
                except Exception as e:
                    logger.error(f"Error detecting opportunities for market {market.get('condition_id')}: {e}")
                    continue
            
            logger.info(f"Detected {opportunities_found} opportunities")
            
        except Exception as e:
            logger.error(f"Error in opportunity detection: {e}", exc_info=True)
    
    def _detect_spread(self, market: dict) -> dict:
        """Detect spread opportunities"""
        # Simplified - would need actual order book data
        # For now, return None as placeholder
        return None
    
    def _detect_negative_risk(self, market: dict) -> dict:
        """Detect negative risk opportunities"""
        # Simplified - would need price data for all outcomes
        # For now, return None as placeholder
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
