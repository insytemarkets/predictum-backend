-- Signals table for live alerts
create table if not exists public.signals (
    id uuid primary key default uuid_generate_v4(),
    market_id uuid references public.markets(id),
    type text not null, -- 'price_spike', 'volume_surge', 'new_opportunity', 'price_drop', 'arbitrage_alert', 'high_confidence'
    title text not null,
    description text,
    severity text default 'medium', -- 'low', 'medium', 'high', 'critical'
    data jsonb,
    created_at timestamp with time zone default now(),
    expires_at timestamp with time zone default (now() + interval '24 hours'),
    read boolean default false
);

-- Enable RLS
alter table public.signals enable row level security;

-- Create policy for public read
create policy "Public read access for signals" on public.signals for select using (true);

-- Index for faster queries
create index if not exists idx_signals_created_at on public.signals(created_at desc);
create index if not exists idx_signals_type on public.signals(type);








