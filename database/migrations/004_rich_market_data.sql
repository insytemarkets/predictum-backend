-- Migration 004: Rich Market Data Enhancement
-- Adds all the juicy data fields from Polymarket GAMMA API

-- ============================================
-- ENHANCED MARKETS TABLE - THE GOOD STUFF
-- ============================================

-- Volume Metrics (24h, 7d, 30d breakdown)
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS volume_7d NUMERIC DEFAULT 0;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS volume_30d NUMERIC DEFAULT 0;

-- Price Intelligence
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS price_change_24h NUMERIC DEFAULT 0;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS price_change_7d NUMERIC DEFAULT 0;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS price_change_30d NUMERIC DEFAULT 0;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS last_trade_price NUMERIC;

-- Orderbook Data
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS best_bid NUMERIC;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS best_ask NUMERIC;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS spread NUMERIC DEFAULT 0;

-- Alpha Signals (THE JUICE)
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS neg_risk BOOLEAN DEFAULT FALSE;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS neg_risk_market_id TEXT;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS competitive_score NUMERIC DEFAULT 0;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS accepting_orders BOOLEAN DEFAULT TRUE;

-- Rewards
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS has_rewards BOOLEAN DEFAULT FALSE;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS rewards_daily_rate NUMERIC DEFAULT 0;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS rewards_min_size NUMERIC;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS rewards_max_spread NUMERIC;

-- Market Metadata
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS image_url TEXT;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS outcomes JSONB;
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS outcome_prices JSONB;

-- Volume Velocity (calculated field)
ALTER TABLE public.markets ADD COLUMN IF NOT EXISTS volume_velocity NUMERIC DEFAULT 1;

-- Indexes for fast queries on new fields
CREATE INDEX IF NOT EXISTS idx_markets_volume_24h ON public.markets(volume_24h DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_markets_price_change_24h ON public.markets(price_change_24h DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_markets_neg_risk ON public.markets(neg_risk) WHERE neg_risk = true;
CREATE INDEX IF NOT EXISTS idx_markets_neg_risk_market_id ON public.markets(neg_risk_market_id);
CREATE INDEX IF NOT EXISTS idx_markets_spread ON public.markets(spread ASC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_markets_volume_velocity ON public.markets(volume_velocity DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_markets_has_rewards ON public.markets(has_rewards) WHERE has_rewards = true;

-- ============================================
-- LIVE TRADES TABLE - WHALE DETECTION
-- ============================================

CREATE TABLE IF NOT EXISTS public.live_trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    market_id UUID REFERENCES public.markets(id) ON DELETE CASCADE,
    token_id TEXT NOT NULL,
    price NUMERIC NOT NULL,
    size NUMERIC NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    value_usd NUMERIC NOT NULL,
    is_whale BOOLEAN DEFAULT FALSE,
    maker_address TEXT,
    taker_address TEXT,
    trade_timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.live_trades ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read access for live_trades" ON public.live_trades FOR SELECT USING (true);

CREATE INDEX IF NOT EXISTS idx_live_trades_market_id ON public.live_trades(market_id);
CREATE INDEX IF NOT EXISTS idx_live_trades_timestamp ON public.live_trades(trade_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_live_trades_is_whale ON public.live_trades(is_whale) WHERE is_whale = true;
CREATE INDEX IF NOT EXISTS idx_live_trades_value ON public.live_trades(value_usd DESC);

-- ============================================
-- NEGATIVE RISK OPPORTUNITIES TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS public.neg_risk_opportunities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id TEXT NOT NULL,
    profit_percent NUMERIC NOT NULL,
    total_no_cost NUMERIC NOT NULL,
    max_position_usd NUMERIC,
    market_ids UUID[] NOT NULL,
    market_questions TEXT[] NOT NULL,
    no_prices NUMERIC[] NOT NULL,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'expired', 'executed')),
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.neg_risk_opportunities ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read access for neg_risk_opportunities" ON public.neg_risk_opportunities FOR SELECT USING (true);

CREATE INDEX IF NOT EXISTS idx_neg_risk_profit ON public.neg_risk_opportunities(profit_percent DESC);
CREATE INDEX IF NOT EXISTS idx_neg_risk_status ON public.neg_risk_opportunities(status);
CREATE INDEX IF NOT EXISTS idx_neg_risk_group ON public.neg_risk_opportunities(group_id);

-- ============================================
-- VOLUME ANOMALIES TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS public.volume_anomalies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    market_id UUID REFERENCES public.markets(id) ON DELETE CASCADE,
    volume_ratio NUMERIC NOT NULL,
    volume_24h NUMERIC NOT NULL,
    volume_7d_avg NUMERIC NOT NULL,
    signal_strength TEXT CHECK (signal_strength IN ('NORMAL', 'HIGH', 'EXTREME')),
    detected_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.volume_anomalies ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read access for volume_anomalies" ON public.volume_anomalies FOR SELECT USING (true);

CREATE INDEX IF NOT EXISTS idx_volume_anomalies_market ON public.volume_anomalies(market_id);
CREATE INDEX IF NOT EXISTS idx_volume_anomalies_ratio ON public.volume_anomalies(volume_ratio DESC);
CREATE INDEX IF NOT EXISTS idx_volume_anomalies_detected ON public.volume_anomalies(detected_at DESC);

-- ============================================
-- ENHANCED OPPORTUNITIES TABLE
-- ============================================

-- Add new columns to existing opportunities table
ALTER TABLE public.opportunities ADD COLUMN IF NOT EXISTS edge_percent NUMERIC;
ALTER TABLE public.opportunities ADD COLUMN IF NOT EXISTS action_description TEXT;
ALTER TABLE public.opportunities ADD COLUMN IF NOT EXISTS related_market_ids UUID[];
ALTER TABLE public.opportunities ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- ============================================
-- ENHANCED SIGNALS TABLE
-- ============================================

-- Add whale-specific fields
ALTER TABLE public.signals ADD COLUMN IF NOT EXISTS whale_value_usd NUMERIC;
ALTER TABLE public.signals ADD COLUMN IF NOT EXISTS whale_address TEXT;
ALTER TABLE public.signals ADD COLUMN IF NOT EXISTS volume_velocity NUMERIC;
ALTER TABLE public.signals ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

