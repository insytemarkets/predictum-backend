-- =============================================
-- Wolf Pack Intelligence Migration
-- Adds: price change tracking, money flow, order book snapshots, momentum
-- =============================================

-- Enable UUID extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================
-- ADD PRICE CHANGE COLUMNS TO MARKETS
-- =============================================

-- Add price tracking columns to markets table
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'current_price') THEN
        ALTER TABLE public.markets ADD COLUMN current_price NUMERIC;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'price_change_1h') THEN
        ALTER TABLE public.markets ADD COLUMN price_change_1h NUMERIC;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'price_change_24h') THEN
        ALTER TABLE public.markets ADD COLUMN price_change_24h NUMERIC;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'price_change_7d') THEN
        ALTER TABLE public.markets ADD COLUMN price_change_7d NUMERIC;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'price_change_percent') THEN
        ALTER TABLE public.markets ADD COLUMN price_change_percent NUMERIC;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'momentum') THEN
        ALTER TABLE public.markets ADD COLUMN momentum NUMERIC;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'volatility_24h') THEN
        ALTER TABLE public.markets ADD COLUMN volatility_24h NUMERIC;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'volume_change_24h') THEN
        ALTER TABLE public.markets ADD COLUMN volume_change_24h NUMERIC;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'best_bid') THEN
        ALTER TABLE public.markets ADD COLUMN best_bid NUMERIC;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'best_ask') THEN
        ALTER TABLE public.markets ADD COLUMN best_ask NUMERIC;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'spread_percentage') THEN
        ALTER TABLE public.markets ADD COLUMN spread_percentage NUMERIC;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'buy_pressure') THEN
        ALTER TABLE public.markets ADD COLUMN buy_pressure NUMERIC DEFAULT 50;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'markets' AND column_name = 'tokens') THEN
        ALTER TABLE public.markets ADD COLUMN tokens TEXT[];
    END IF;
END $$;

-- Create indexes for price change queries
CREATE INDEX IF NOT EXISTS idx_markets_price_change ON public.markets(price_change_percent DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_markets_momentum ON public.markets(momentum DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_markets_volatility ON public.markets(volatility_24h DESC NULLS LAST);

-- =============================================
-- MONEY FLOW TABLE
-- Track where money is moving in real-time
-- =============================================

CREATE TABLE IF NOT EXISTS public.money_flow (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    market_id UUID REFERENCES public.markets(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    net_flow NUMERIC DEFAULT 0,  -- buy_volume - sell_volume
    buy_volume NUMERIC DEFAULT 0,
    sell_volume NUMERIC DEFAULT 0,
    flow_velocity NUMERIC DEFAULT 0,  -- rate of change
    period TEXT DEFAULT '1h'  -- '1m', '5m', '1h', '24h'
);

-- Indexes for money flow
CREATE INDEX IF NOT EXISTS idx_money_flow_market ON public.money_flow(market_id);
CREATE INDEX IF NOT EXISTS idx_money_flow_timestamp ON public.money_flow(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_money_flow_period ON public.money_flow(period);
CREATE INDEX IF NOT EXISTS idx_money_flow_net ON public.money_flow(net_flow DESC);

-- RLS for money_flow
ALTER TABLE public.money_flow ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Public read access for money_flow" ON public.money_flow;
CREATE POLICY "Public read access for money_flow" ON public.money_flow FOR SELECT USING (true);

-- =============================================
-- ORDER BOOK SNAPSHOTS TABLE
-- Store depth analysis for intelligence
-- =============================================

CREATE TABLE IF NOT EXISTS public.orderbook_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    market_id UUID REFERENCES public.markets(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    bid_depth_10 NUMERIC DEFAULT 0,  -- liquidity within 10% of best bid
    ask_depth_10 NUMERIC DEFAULT 0,  -- liquidity within 10% of best ask
    spread NUMERIC DEFAULT 0,
    imbalance NUMERIC DEFAULT 0,  -- (bid_depth - ask_depth) / total
    best_bid NUMERIC DEFAULT 0,
    best_ask NUMERIC DEFAULT 0
);

-- Indexes for orderbook snapshots
CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_market ON public.orderbook_snapshots(market_id);
CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_timestamp ON public.orderbook_snapshots(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_imbalance ON public.orderbook_snapshots(imbalance DESC);

-- RLS for orderbook_snapshots
ALTER TABLE public.orderbook_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Public read access for orderbook_snapshots" ON public.orderbook_snapshots;
CREATE POLICY "Public read access for orderbook_snapshots" ON public.orderbook_snapshots FOR SELECT USING (true);

-- =============================================
-- SMART MONEY TABLE
-- Track whale wallets and their performance
-- =============================================

CREATE TABLE IF NOT EXISTS public.smart_money (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    wallet_address TEXT UNIQUE NOT NULL,
    total_trades INT DEFAULT 0,
    total_volume NUMERIC DEFAULT 0,
    profitable_trades INT DEFAULT 0,
    win_rate NUMERIC DEFAULT 0,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_smart_money BOOLEAN DEFAULT false,
    notes TEXT
);

-- Indexes for smart_money
CREATE INDEX IF NOT EXISTS idx_smart_money_wallet ON public.smart_money(wallet_address);
CREATE INDEX IF NOT EXISTS idx_smart_money_volume ON public.smart_money(total_volume DESC);
CREATE INDEX IF NOT EXISTS idx_smart_money_win_rate ON public.smart_money(win_rate DESC);

-- RLS for smart_money
ALTER TABLE public.smart_money ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Public read access for smart_money" ON public.smart_money;
CREATE POLICY "Public read access for smart_money" ON public.smart_money FOR SELECT USING (true);

-- =============================================
-- MOMENTUM SIGNALS TABLE
-- Store detected momentum events
-- =============================================

CREATE TABLE IF NOT EXISTS public.momentum_signals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    market_id UUID REFERENCES public.markets(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    signal_type TEXT NOT NULL,  -- 'breakout', 'breakdown', 'momentum_surge', 'mean_reversion'
    strength NUMERIC DEFAULT 0,  -- 0-100
    price_at_signal NUMERIC,
    volume_at_signal NUMERIC,
    description TEXT,
    status TEXT DEFAULT 'active'  -- 'active', 'resolved', 'expired'
);

-- Indexes for momentum_signals
CREATE INDEX IF NOT EXISTS idx_momentum_signals_market ON public.momentum_signals(market_id);
CREATE INDEX IF NOT EXISTS idx_momentum_signals_timestamp ON public.momentum_signals(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_momentum_signals_type ON public.momentum_signals(signal_type);
CREATE INDEX IF NOT EXISTS idx_momentum_signals_status ON public.momentum_signals(status);

-- RLS for momentum_signals
ALTER TABLE public.momentum_signals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Public read access for momentum_signals" ON public.momentum_signals;
CREATE POLICY "Public read access for momentum_signals" ON public.momentum_signals FOR SELECT USING (true);

-- =============================================
-- AGGREGATE FUNCTIONS FOR INTELLIGENCE
-- =============================================

-- Function to get sector flow (aggregate by category)
CREATE OR REPLACE FUNCTION get_sector_flow(hours_back INT DEFAULT 24)
RETURNS TABLE(category TEXT, net_flow NUMERIC, buy_volume NUMERIC, sell_volume NUMERIC, market_count BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COALESCE(m.raw_data->>'category', 'Other') as category,
        SUM(mf.net_flow) as net_flow,
        SUM(mf.buy_volume) as buy_volume,
        SUM(mf.sell_volume) as sell_volume,
        COUNT(DISTINCT m.id) as market_count
    FROM public.money_flow mf
    JOIN public.markets m ON mf.market_id = m.id
    WHERE mf.timestamp > NOW() - (hours_back || ' hours')::INTERVAL
    GROUP BY COALESCE(m.raw_data->>'category', 'Other')
    ORDER BY net_flow DESC;
END;
$$ LANGUAGE plpgsql;

-- Function to get top movers
CREATE OR REPLACE FUNCTION get_top_movers(hours_back INT DEFAULT 24, limit_count INT DEFAULT 10)
RETURNS TABLE(
    market_id UUID, 
    question TEXT, 
    price_change NUMERIC, 
    volume_24h NUMERIC,
    momentum NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        m.id as market_id,
        m.question,
        m.price_change_percent as price_change,
        m.volume_24h,
        m.momentum
    FROM public.markets m
    WHERE m.price_change_percent IS NOT NULL
    ORDER BY ABS(m.price_change_percent) DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

-- Function to get order book imbalance leaders
CREATE OR REPLACE FUNCTION get_imbalance_leaders(limit_count INT DEFAULT 10)
RETURNS TABLE(
    market_id UUID,
    question TEXT,
    imbalance NUMERIC,
    bid_depth NUMERIC,
    ask_depth NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT ON (os.market_id)
        m.id as market_id,
        m.question,
        os.imbalance,
        os.bid_depth_10 as bid_depth,
        os.ask_depth_10 as ask_depth
    FROM public.orderbook_snapshots os
    JOIN public.markets m ON os.market_id = m.id
    ORDER BY os.market_id, os.timestamp DESC, ABS(os.imbalance) DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

-- =============================================
-- GRANT PERMISSIONS
-- =============================================

GRANT USAGE ON SCHEMA public TO anon, authenticated;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO anon, authenticated;
GRANT INSERT ON public.money_flow TO anon, authenticated;
GRANT INSERT ON public.orderbook_snapshots TO anon, authenticated;
GRANT INSERT ON public.momentum_signals TO anon, authenticated;

