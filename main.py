"""
Main entry point for Predictum backend workers
Consolidated into 2 workers to reduce costs:
- data-worker: Markets + Order Books (high frequency)
- analysis-worker: Opportunities + Stats (lower frequency)
"""
import sys
import os
import argparse
import logging

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from workers.data_worker import DataWorker
from workers.analysis_worker import AnalysisWorker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_data_worker():
    """Run unified data worker (markets + order books)"""
    worker = DataWorker()
    worker.run()

def run_analysis_worker():
    """Run unified analysis worker (opportunities + stats)"""
    worker = AnalysisWorker()
    worker.run()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Predictum Backend Workers')
    parser.add_argument(
        'worker',
        choices=['data-worker', 'analysis-worker', 'all'],
        help='Which worker to run'
    )
    
    args = parser.parse_args()
    
    if args.worker == 'data-worker':
        run_data_worker()
    elif args.worker == 'analysis-worker':
        run_analysis_worker()
    elif args.worker == 'all':
        # For local development, run both in separate threads
        import threading
        threads = [
            threading.Thread(target=run_data_worker, daemon=True),
            threading.Thread(target=run_analysis_worker, daemon=True),
        ]
        for t in threads:
            t.start()
        # Keep main thread alive
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down workers...")
