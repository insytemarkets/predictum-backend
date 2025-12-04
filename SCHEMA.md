# Supabase Schema

The database schema is located at: `database/schema.sql`

## Quick Setup

1. Go to your Supabase project dashboard
2. Navigate to **SQL Editor**
3. Copy and paste the contents of `database/schema.sql`
4. Click **Run** to execute

## Schema Overview

### Tables

1. **markets** - Stores Polymarket market data
   - `condition_id` (unique) - Polymarket condition ID
   - `question` - Market question
   - `volume_24h` - 24-hour volume
   - `liquidity` - Current liquidity
   - `raw_data` (JSONB) - Full API response

2. **order_books** - Stores order book snapshots
   - `market_id` - References markets table
   - `bids` (JSONB) - Bid orders
   - `asks` (JSONB) - Ask orders

3. **prices** - Stores price history
   - `market_id` - References markets table
   - `outcome_index` - Outcome index (0=YES, 1=NO)
   - `price` - Price at timestamp

4. **opportunities** - Detected trading opportunities
   - `market_id` - References markets table
   - `type` - Opportunity type (spread, arbitrage, negative_risk)
   - `profit_potential` - Estimated profit %
   - `confidence_score` - Confidence level (0-100)

5. **market_stats** - Aggregated market statistics
   - `market_id` - References markets table
   - `spread_percentage` - Current spread %
   - `buy_pressure` - Buy pressure metric
   - `sell_pressure` - Sell pressure metric

## Row Level Security (RLS)

All tables have RLS enabled with public read access. This allows the frontend to read data without authentication.

## Enabling Realtime

To enable real-time updates in the frontend:

1. Go to **Database** → **Replication** in Supabase dashboard
2. Enable replication for:
   - `markets`
   - `opportunities`
   - `order_books`
   - `prices`

This allows the frontend to subscribe to changes and update in real-time.

