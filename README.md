# Predictum Backend

Backend workers for fetching and processing Polymarket data.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your Supabase credentials
```

3. Run workers:
```bash
# Run individual worker
python main.py data-worker
python main.py analysis-worker

# Or run all workers (for local dev)
python main.py all
```

## Workers (Consolidated to 2 workers)

### Data Worker
Uses `MarketScanner` and `OrderBookScanner` classes:
- **Markets**: Fetches markets from Polymarket GAMMA API (every 30s)
- **Order Books**: Fetches order books from CLOB API (every 10s)
- **Command**: `python main.py data-worker`

### Analysis Worker
Uses `OpportunityDetector` and `StatsAggregator` classes:
- **Opportunities**: Analyzes data for arbitrage opportunities (every 60s)
- **Stats**: Calculates market statistics (every 5min)
- **Command**: `python main.py analysis-worker`

## Individual Workers

You can also run individual workers directly:
```bash
python workers/market_scanner.py
python workers/orderbook_scanner.py
python workers/opportunity_detector.py
python workers/stats_aggregator.py
```

## Deployment

Deploy to Render as 2 background workers:

1. **Data Worker** (high frequency):
   ```bash
   python main.py data-worker
   ```

2. **Analysis Worker** (lower frequency):
   ```bash
   python main.py analysis-worker
   ```

## Project Structure

```
backend/
├── main.py                 # Entry point for workers
├── workers/
│   ├── data_worker.py      # Consolidated data worker
│   ├── analysis_worker.py  # Consolidated analysis worker
│   ├── market_scanner.py   # Market scanner class
│   ├── orderbook_scanner.py # Order book scanner class
│   ├── opportunity_detector.py # Opportunity detector class
│   └── stats_aggregator.py  # Stats aggregator class
├── services/
│   ├── polymarket_api.py  # Polymarket API client
│   └── supabase_client.py  # Supabase database client
└── utils/
    └── rate_limiter.py     # Rate limiting utilities
```
