-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- Markets table
create table public.markets (
    id uuid primary key default uuid_generate_v4(),
    condition_id text unique not null,
    question text not null,
    slug text not null,
    url text,
    end_date timestamp with time zone,
    volume_24h numeric,
    liquidity numeric,
    current_price numeric,
    price_change_24h numeric,
    price_change_percent numeric,
    tokens jsonb,
    created_at timestamp with time zone default now(),
    updated_at timestamp with time zone default now(),
    raw_data jsonb
);

-- Order Books table
create table public.order_books (
    id uuid primary key default uuid_generate_v4(),
    market_id uuid references public.markets(id),
    bids jsonb not null,
    asks jsonb not null,
    timestamp timestamp with time zone default now()
);

-- Prices table
create table public.prices (
    id uuid primary key default uuid_generate_v4(),
    market_id uuid references public.markets(id),
    outcome_index integer not null,
    price numeric not null,
    timestamp timestamp with time zone default now()
);

-- Opportunities table
create table public.opportunities (
    id uuid primary key default uuid_generate_v4(),
    market_id uuid references public.markets(id),
    type text not null, -- 'spread', 'arbitrage', 'negative_risk'
    profit_potential numeric,
    confidence_score numeric,
    details jsonb,
    status text default 'active',
    detected_at timestamp with time zone default now(),
    expires_at timestamp with time zone,
    created_at timestamp with time zone default now(),
    resolved_at timestamp with time zone,
    unique(market_id, type) -- Allow one opportunity per type per market
);

-- Market Stats table
create table public.market_stats (
    id uuid primary key default uuid_generate_v4(),
    market_id uuid references public.markets(id),
    spread_percentage numeric,
    buy_pressure numeric,
    sell_pressure numeric,
    calculated_at timestamp with time zone default now()
);

-- Enable RLS
alter table public.markets enable row level security;
alter table public.order_books enable row level security;
alter table public.prices enable row level security;
alter table public.opportunities enable row level security;
alter table public.market_stats enable row level security;

-- Create policies (public read access for now)
create policy "Public read access for markets" on public.markets for select using (true);
create policy "Public read access for order_books" on public.order_books for select using (true);
create policy "Public read access for prices" on public.prices for select using (true);
create policy "Public read access for opportunities" on public.opportunities for select using (true);
create policy "Public read access for market_stats" on public.market_stats for select using (true);

