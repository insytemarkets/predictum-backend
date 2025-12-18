"""
Unified Analysis Worker
Consolidates OpportunityDetector, StatsAggregator, and SignalDetector into one worker
Runs analysis and generates real-time signals
"""
import time
import logging
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workers.opportunity_detector import OpportunityDetector
from workers.stats_aggregator import StatsAggregator
from workers.signal_detector import SignalDetector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AnalysisWorker:
    """Unified worker for opportunity detection, stats aggregation, and signal generation"""
    
    def __init__(self):
        self.opportunity_detector = OpportunityDetector()
        self.stats_aggregator = StatsAggregator()
        self.signal_detector = SignalDetector()
        self.running = True
        
        # Intervals
        self.opportunity_interval = self.opportunity_detector.scan_interval  # 60 seconds
        self.stats_interval = self.stats_aggregator.scan_interval  # 300 seconds (5 min)
        self.signal_interval = self.signal_detector.scan_interval  # 30 seconds
        
        # Last run times
        self.last_opportunity_scan = 0
        self.last_stats_scan = 0
        self.last_signal_scan = 0
    
    def run(self):
        """Main worker loop - runs all analysis tasks with different intervals"""
        logger.info("Analysis Worker started (Opportunities + Stats + Signals)")
        
        # Run initial scans
        self.opportunity_detector.detect_all()
        self.last_opportunity_scan = time.time()
        
        self.stats_aggregator.aggregate_stats()
        self.last_stats_scan = time.time()
        
        self.signal_detector.detect_signals()
        self.last_signal_scan = time.time()
        
        while self.running:
            try:
                current_time = time.time()
                
                # Check if it's time to detect signals (fastest - every 30s)
                if current_time - self.last_signal_scan >= self.signal_interval:
                    self.signal_detector.detect_signals()
                    self.last_signal_scan = time.time()
                
                # Check if it's time to detect opportunities (every 60s)
                if current_time - self.last_opportunity_scan >= self.opportunity_interval:
                    self.opportunity_detector.detect_all()
                    self.last_opportunity_scan = time.time()
                
                # Check if it's time to aggregate stats (every 5 min)
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
