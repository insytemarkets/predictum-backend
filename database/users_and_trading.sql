-- ============================================
-- PREDICTUM 2.0 - Users & Trading Schema
-- ============================================

-- User Profiles (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT,
    display_name TEXT,
    avatar_url TEXT,
    
    -- Trading Settings
    trading_enabled BOOLEAN DEFAULT FALSE,
    auto_trade_enabled BOOLEAN DEFAULT FALSE,
    risk_limit_usd NUMERIC DEFAULT 1000,
    max_position_usd NUMERIC DEFAULT 500,
    
    -- Polymarket Wallet (for trading)
    wallet_address TEXT,
    -- Note: Private key should be stored encrypted or use external secrets manager
    wallet_encrypted_key TEXT,
    
    -- Trading Preferences
    auto_arb_enabled BOOLEAN DEFAULT FALSE,  -- Auto-execute neg risk arbs
    auto_arb_min_profit NUMERIC DEFAULT 2.0, -- Min % profit for auto-arb
    auto_spread_enabled BOOLEAN DEFAULT FALSE, -- Market making
    copy_trading_enabled BOOLEAN DEFAULT FALSE,
    
    -- Notification Settings
    email_alerts BOOLEAN DEFAULT TRUE,
    push_alerts BOOLEAN DEFAULT FALSE,
    whale_alerts BOOLEAN DEFAULT TRUE,
    opportunity_alerts BOOLEAN DEFAULT TRUE,
    
    -- Stats
    total_pnl NUMERIC DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    win_rate NUMERIC DEFAULT 0,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- User Positions (active holdings)
CREATE TABLE IF NOT EXISTS public.positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    market_id UUID REFERENCES public.markets(id),
    
    token_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('YES', 'NO')),
    size NUMERIC NOT NULL,
    avg_entry_price NUMERIC NOT NULL,
    current_price NUMERIC,
    
    unrealized_pnl NUMERIC DEFAULT 0,
    realized_pnl NUMERIC DEFAULT 0,
    
    status TEXT DEFAULT 'open' CHECK (status IN ('open', 'closed', 'pending')),
    
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- User Trades (execution history)
CREATE TABLE IF NOT EXISTS public.user_trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    market_id UUID REFERENCES public.markets(id),
    position_id UUID REFERENCES public.positions(id),
    
    token_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    order_type TEXT DEFAULT 'MARKET' CHECK (order_type IN ('MARKET', 'LIMIT', 'GTC', 'FOK')),
    
    size NUMERIC NOT NULL,
    price NUMERIC NOT NULL,
    value_usd NUMERIC NOT NULL,
    
    -- Trade source
    source TEXT DEFAULT 'manual' CHECK (source IN ('manual', 'auto_arb', 'auto_spread', 'copy_trade', 'signal')),
    signal_id UUID, -- If triggered by a signal
    opportunity_id UUID REFERENCES public.opportunities(id),
    
    -- Execution
    order_id TEXT, -- Polymarket order ID
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'filled', 'partial', 'cancelled', 'failed')),
    fill_price NUMERIC,
    fees NUMERIC DEFAULT 0,
    
    executed_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- User Watchlists (now per-user)
CREATE TABLE IF NOT EXISTS public.user_watchlists (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    market_id UUID REFERENCES public.markets(id),
    notes TEXT,
    alert_on_price_change BOOLEAN DEFAULT FALSE,
    alert_threshold NUMERIC DEFAULT 0.05,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, market_id)
);

-- User Alerts (per-user)
CREATE TABLE IF NOT EXISTS public.user_alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    market_id UUID REFERENCES public.markets(id),
    
    type TEXT NOT NULL CHECK (type IN ('price_above', 'price_below', 'volume_spike', 'whale_trade', 'opportunity')),
    threshold NUMERIC,
    
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'triggered', 'disabled')),
    triggered_at TIMESTAMPTZ,
    notification_sent BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Whale Addresses to Track
CREATE TABLE IF NOT EXISTS public.tracked_wallets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    
    wallet_address TEXT NOT NULL,
    label TEXT, -- "Smart Money 1", "Institutional", etc.
    
    -- Stats (updated by workers)
    total_trades INTEGER DEFAULT 0,
    win_rate NUMERIC DEFAULT 0,
    avg_profit NUMERIC DEFAULT 0,
    
    copy_enabled BOOLEAN DEFAULT FALSE,
    copy_percentage NUMERIC DEFAULT 100, -- Copy 100% of their trades
    copy_max_size NUMERIC DEFAULT 100, -- Max $100 per copy trade
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, wallet_address)
);

-- Trading Bot Executions (logs auto-trades)
CREATE TABLE IF NOT EXISTS public.bot_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id),
    
    strategy TEXT NOT NULL CHECK (strategy IN ('neg_risk_arb', 'spread_capture', 'momentum', 'copy_whale')),
    opportunity_id UUID REFERENCES public.opportunities(id),
    
    -- Execution details
    markets JSONB, -- Array of market IDs involved
    orders JSONB, -- Array of order IDs placed
    total_size_usd NUMERIC,
    expected_profit NUMERIC,
    
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'executing', 'completed', 'partial', 'failed')),
    actual_profit NUMERIC,
    error_message TEXT,
    
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- ============================================
-- RLS Policies (Row Level Security)
-- ============================================

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_watchlists ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tracked_wallets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bot_executions ENABLE ROW LEVEL SECURITY;

-- Users can only see/edit their own data
CREATE POLICY "Users can view own profile" ON public.profiles
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can update own profile" ON public.profiles
    FOR UPDATE USING (auth.uid() = id);

CREATE POLICY "Users can view own positions" ON public.positions
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own positions" ON public.positions
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Users can view own trades" ON public.user_trades
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own trades" ON public.user_trades
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Users can view own watchlist" ON public.user_watchlists
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own watchlist" ON public.user_watchlists
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Users can view own alerts" ON public.user_alerts
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own alerts" ON public.user_alerts
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Users can view tracked wallets" ON public.tracked_wallets
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can manage tracked wallets" ON public.tracked_wallets
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Users can view bot executions" ON public.bot_executions
    FOR SELECT USING (auth.uid() = user_id);

-- Service role can insert bot executions
CREATE POLICY "Service can manage bot executions" ON public.bot_executions
    FOR ALL USING (true);

-- ============================================
-- Triggers
-- ============================================

-- Auto-create profile on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, display_name)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1))
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Update timestamps
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_profiles_updated_at
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER update_positions_updated_at
    BEFORE UPDATE ON public.positions
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- ============================================
-- Indexes for Performance
-- ============================================

CREATE INDEX IF NOT EXISTS idx_positions_user_id ON public.positions(user_id);
CREATE INDEX IF NOT EXISTS idx_positions_market_id ON public.positions(market_id);
CREATE INDEX IF NOT EXISTS idx_positions_status ON public.positions(status);

CREATE INDEX IF NOT EXISTS idx_user_trades_user_id ON public.user_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_user_trades_executed_at ON public.user_trades(executed_at);

CREATE INDEX IF NOT EXISTS idx_user_alerts_user_id ON public.user_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_user_alerts_status ON public.user_alerts(status);

CREATE INDEX IF NOT EXISTS idx_bot_executions_user_id ON public.bot_executions(user_id);
CREATE INDEX IF NOT EXISTS idx_bot_executions_status ON public.bot_executions(status);
