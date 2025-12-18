-- =============================================
-- Predictum Full Platform Database Migration
-- Adds: trades, alerts, watchlists, correlations, signal_performance
-- =============================================

-- Enable UUID extension (if not already enabled)
create extension if not exists "uuid-ossp";

-- =============================================
-- TRADES TABLE - For whale detection and trade flow analysis
-- =============================================
create table if not exists public.trades (
    id uuid primary key default uuid_generate_v4(),
    market_id uuid references public.markets(id) on delete cascade,
    token_id text,
    price numeric not null,
    size numeric not null,
    side text not null, -- 'BUY' or 'SELL'
    maker text,
    taker text,
    timestamp timestamp with time zone default now(),
    is_whale boolean default false,
    created_at timestamp with time zone default now()
);

-- Indexes for trades
create index if not exists idx_trades_market_id on public.trades(market_id);
create index if not exists idx_trades_timestamp on public.trades(timestamp desc);
create index if not exists idx_trades_is_whale on public.trades(is_whale) where is_whale = true;
create index if not exists idx_trades_side on public.trades(side);

-- RLS for trades
alter table public.trades enable row level security;
create policy "Public read access for trades" on public.trades for select using (true);

-- =============================================
-- ALERTS TABLE - User-defined price/event alerts
-- =============================================
create table if not exists public.alerts (
    id uuid primary key default uuid_generate_v4(),
    market_id uuid references public.markets(id) on delete cascade,
    type text not null, -- 'price_above', 'price_below', 'spread_above', 'volume_spike', 'whale_trade'
    threshold numeric,
    status text default 'active', -- 'active', 'triggered', 'expired', 'deleted'
    triggered_at timestamp with time zone,
    created_at timestamp with time zone default now(),
    expires_at timestamp with time zone default (now() + interval '30 days')
);

-- Indexes for alerts
create index if not exists idx_alerts_market_id on public.alerts(market_id);
create index if not exists idx_alerts_status on public.alerts(status);
create index if not exists idx_alerts_type on public.alerts(type);

-- RLS for alerts
alter table public.alerts enable row level security;
create policy "Public read access for alerts" on public.alerts for select using (true);
create policy "Public insert access for alerts" on public.alerts for insert with check (true);
create policy "Public update access for alerts" on public.alerts for update using (true);
create policy "Public delete access for alerts" on public.alerts for delete using (true);

-- =============================================
-- WATCHLISTS TABLE - Personal market tracking
-- =============================================
create table if not exists public.watchlists (
    id uuid primary key default uuid_generate_v4(),
    market_id uuid references public.markets(id) on delete cascade unique,
    notes text,
    created_at timestamp with time zone default now(),
    updated_at timestamp with time zone default now()
);

-- Indexes for watchlists
create index if not exists idx_watchlists_market_id on public.watchlists(market_id);
create index if not exists idx_watchlists_created_at on public.watchlists(created_at desc);

-- RLS for watchlists
alter table public.watchlists enable row level security;
create policy "Public read access for watchlists" on public.watchlists for select using (true);
create policy "Public insert access for watchlists" on public.watchlists for insert with check (true);
create policy "Public update access for watchlists" on public.watchlists for update using (true);
create policy "Public delete access for watchlists" on public.watchlists for delete using (true);

-- =============================================
-- CORRELATIONS TABLE - Cross-market analysis
-- =============================================
create table if not exists public.correlations (
    id uuid primary key default uuid_generate_v4(),
    market_a_id uuid references public.markets(id) on delete cascade,
    market_b_id uuid references public.markets(id) on delete cascade,
    correlation_score numeric not null, -- -1 to 1
    calculated_at timestamp with time zone default now(),
    unique(market_a_id, market_b_id)
);

-- Indexes for correlations
create index if not exists idx_correlations_market_a on public.correlations(market_a_id);
create index if not exists idx_correlations_market_b on public.correlations(market_b_id);
create index if not exists idx_correlations_score on public.correlations(correlation_score desc);

-- RLS for correlations
alter table public.correlations enable row level security;
create policy "Public read access for correlations" on public.correlations for select using (true);

-- =============================================
-- SIGNAL PERFORMANCE TABLE - Track accuracy of signals
-- =============================================
create table if not exists public.signal_performance (
    id uuid primary key default uuid_generate_v4(),
    opportunity_id uuid references public.opportunities(id) on delete cascade,
    detected_price numeric,
    resolved_price numeric,
    actual_profit numeric,
    was_profitable boolean,
    resolved_at timestamp with time zone default now(),
    created_at timestamp with time zone default now()
);

-- Indexes for signal_performance
create index if not exists idx_signal_performance_opportunity on public.signal_performance(opportunity_id);
create index if not exists idx_signal_performance_profitable on public.signal_performance(was_profitable);

-- RLS for signal_performance
alter table public.signal_performance enable row level security;
create policy "Public read access for signal_performance" on public.signal_performance for select using (true);

-- =============================================
-- UPDATE EXISTING TABLES
-- =============================================

-- Add min_order_size and tick_size to order_books if not exists
do $$ 
begin
    if not exists (select 1 from information_schema.columns 
                   where table_name = 'order_books' and column_name = 'min_order_size') then
        alter table public.order_books add column min_order_size numeric;
    end if;
    
    if not exists (select 1 from information_schema.columns 
                   where table_name = 'order_books' and column_name = 'tick_size') then
        alter table public.order_books add column tick_size numeric;
    end if;
    
    if not exists (select 1 from information_schema.columns 
                   where table_name = 'order_books' and column_name = 'neg_risk') then
        alter table public.order_books add column neg_risk boolean default false;
    end if;
end $$;

-- Add category to markets if not exists
do $$ 
begin
    if not exists (select 1 from information_schema.columns 
                   where table_name = 'markets' and column_name = 'category') then
        alter table public.markets add column category text;
    end if;
end $$;

-- =============================================
-- FUNCTIONS FOR ANALYTICS
-- =============================================

-- Function to get trade volume by side for a market
create or replace function get_trade_volume(market_uuid uuid, hours_back int default 24)
returns table(buy_volume numeric, sell_volume numeric, total_trades bigint) as $$
begin
    return query
    select 
        coalesce(sum(case when side = 'BUY' then size * price else 0 end), 0) as buy_volume,
        coalesce(sum(case when side = 'SELL' then size * price else 0 end), 0) as sell_volume,
        count(*) as total_trades
    from public.trades
    where market_id = market_uuid
    and timestamp > now() - (hours_back || ' hours')::interval;
end;
$$ language plpgsql;

-- Function to get whale trade count
create or replace function get_whale_count(hours_back int default 24)
returns bigint as $$
begin
    return (
        select count(*)
        from public.trades
        where is_whale = true
        and timestamp > now() - (hours_back || ' hours')::interval
    );
end;
$$ language plpgsql;

-- =============================================
-- GRANT PERMISSIONS
-- =============================================

-- Grant usage on schema
grant usage on schema public to anon, authenticated;

-- Grant select on all tables
grant select on all tables in schema public to anon, authenticated;

-- Grant insert/update/delete on user-modifiable tables
grant insert, update, delete on public.alerts to anon, authenticated;
grant insert, update, delete on public.watchlists to anon, authenticated;







