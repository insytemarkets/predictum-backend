"""
Unified Analysis Worker
Consolidates OpportunityDetector and StatsAggregator into one worker
Runs lower-frequency analysis tasks
"""
import time
import logging
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workers.opportunity_detector import OpportunityDetector
from workers.stats_aggregator import StatsAggregator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AnalysisWorker:
    """Unified worker for opportunity detection and stats aggregation"""
    
    def __init__(self):
        self.opportunity_detector = OpportunityDetector()
        self.stats_aggregator = StatsAggregator()
        self.running = True
        
        # Intervals
        self.opportunity_interval = self.opportunity_detector.scan_interval  # 60 seconds
        self.stats_interval = self.stats_aggregator.scan_interval  # 300 seconds (5 min)
        
        # Last run times
        self.last_opportunity_scan = 0
        self.last_stats_scan = 0
    
    def run(self):
        """Main worker loop - runs both analysis tasks with different intervals"""
        logger.info("Analysis Worker started (Opportunities + Stats)")
        
        # Run initial scans
        self.opportunity_detector.detect_opportunities()
        self.last_opportunity_scan = time.time()
        
        self.stats_aggregator.aggregate_stats()
        self.last_stats_scan = time.time()
        
        while self.running:
            try:
                current_time = time.time()
                
                # Check if it's time to detect opportunities
                if current_time - self.last_opportunity_scan >= self.opportunity_interval:
                    self.opportunity_detector.detect_opportunities()
                    self.last_opportunity_scan = time.time()
                
                # Check if it's time to aggregate stats
                if current_time - self.last_stats_scan >= self.stats_interval:
                    self.stats_aggregator.aggregate_stats()
                    self.last_stats_scan = time.time()
                
                # Sleep for 1 second to avoid busy waiting
                time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("Shutting down analysis worker...")
                self.running = False
                break
            except Exception as e:
                logger.error(f"Fatal error in analysis worker: {e}", exc_info=True)
                time.sleep(5)  # Wait before retrying

if __name__ == "__main__":
    worker = AnalysisWorker()
    worker.run()
