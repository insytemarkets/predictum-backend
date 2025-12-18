# PREDICTUM 2.0 - MASTER PLAN
## "Everyone has access to the information. We just know how to analyze it better."

---

## 🔴 THE PROBLEM WITH CURRENT IMPLEMENTATION

### 1. **Data is STALE and INCOMPLETE**
- We're not extracting the RICH data that Polymarket's GAMMA API provides
- Missing: `volume24hr`, `volume1wk`, `volume1mo`, `oneDayPriceChange`, `oneWeekPriceChange`, `oneMonthPriceChange`, `lastTradePrice`, `spread`, `competitive`, `negRisk`, `bestBid`, `bestAsk`
- Not utilizing the CLOB API for real orderbook depth
- No real-time WebSocket connection for live updates

### 2. **No REAL Intelligence**
- Opportunity detection is basic price comparison
- No whale/smart money tracking
- No volume anomaly detection
- No cross-market correlation analysis
- No negative risk detection (the REAL alpha)

### 3. **UI is Just Tables**
- Data presentation is generic, boring
- No actionable intelligence visualization
- No real-time feel
- Doesn't feel like a Bloomberg Terminal for prediction markets

---

## 🟢 POLYMARKET API - THE GOLD MINE

### GAMMA API (`https://gamma-api.polymarket.com`)
```
GET /events?closed=false&limit=200
```
Returns EVERYTHING we need per market:
- **Basic**: `id`, `question`, `conditionId`, `slug`, `description`, `outcomes`, `outcomePrices`
- **Volume Metrics**:
  - `volume` (total all-time)
  - `volume24hr` ← **24H VOLUME - CRITICAL**
  - `volume1wk` ← 7 day volume
  - `volume1mo` ← 30 day volume
  - `volume1yr` ← yearly volume
- **Price Intelligence**:
  - `outcomePrices` ← Current YES/NO prices
  - `oneDayPriceChange` ← **24H PRICE CHANGE**
  - `oneWeekPriceChange` ← 7d change
  - `oneMonthPriceChange` ← 30d change
  - `lastTradePrice` ← Most recent trade price
  - `bestBid` / `bestAsk` ← Best orderbook prices
  - `spread` ← Current bid-ask spread
- **Market Health**:
  - `liquidity` ← Total liquidity
  - `competitive` ← Competition score (0-1)
  - `negRisk` ← **NEGATIVE RISK FLAG** (huge for arb)
  - `negRiskMarketID` ← Related negative risk market
  - `acceptingOrders` ← Is market live for trading
- **Rewards**:
  - `clobRewards` ← LP rewards info
  - `rewardsMinSize`, `rewardsMaxSpread`

### CLOB API (`https://clob.polymarket.com`)
```
GET /book?token_id=<TOKEN>          # Full orderbook (bids/asks)
GET /price?token_id=<TOKEN>         # Current best price
GET /midpoint?token_id=<TOKEN>      # Midpoint price
GET /spread?token_id=<TOKEN>        # Bid-ask spread
GET /prices-history?market=<TOKEN>  # Historical prices
POST /books                          # Batch orderbooks
POST /prices                         # Batch prices
```

### WebSocket (`wss://clob.polymarket.com/ws`)
**Market Channel** provides:
- `book` - Orderbook updates
- `price_change` - Price tick updates
- `tick_size_change` - Tick size changes  
- `last_trade_price` - Real-time trade prices

---

## 🔥 THE PLAN - PHASE BY PHASE

### PHASE 1: DATA LAYER OVERHAUL (Backend)

#### 1.1 Enhanced Market Scanner
```python
# Extract ALL the rich data from GAMMA API:
market_data = {
    'condition_id': market.get('conditionId'),
    'question': market.get('question'),
    
    # VOLUME METRICS (the juice)
    'volume_total': market.get('volumeNum') or market.get('volume'),
    'volume_24h': market.get('volume24hr'),
    'volume_7d': market.get('volume1wk'),
    'volume_30d': market.get('volume1mo'),
    
    # PRICE INTELLIGENCE
    'current_price': outcomePrices[0],  # YES price
    'price_change_24h': market.get('oneDayPriceChange'),
    'price_change_7d': market.get('oneWeekPriceChange'),
    'price_change_30d': market.get('oneMonthPriceChange'),
    'last_trade_price': market.get('lastTradePrice'),
    
    # ORDERBOOK DATA
    'best_bid': market.get('bestBid'),
    'best_ask': market.get('bestAsk'),
    'spread': market.get('spread'),
    'liquidity': market.get('liquidityNum'),
    
    # ALPHA SIGNALS
    'neg_risk': market.get('negRisk'),  # HUGE for arbitrage
    'neg_risk_market_id': market.get('negRiskMarketID'),
    'competitive': market.get('competitive'),
    'accepting_orders': market.get('acceptingOrders'),
    
    # REWARDS
    'has_rewards': len(market.get('clobRewards', [])) > 0,
    'rewards_daily_rate': market.get('clobRewards', [{}])[0].get('rewardsDailyRate', 0),
}
```

#### 1.2 WebSocket Worker (NEW)
```python
class WebSocketWorker:
    """Real-time data from Polymarket CLOB WebSocket"""
    
    def connect(self):
        ws = websocket.connect('wss://clob.polymarket.com/ws')
        
        # Subscribe to market channels for top 100 markets
        for market in top_markets:
            ws.send({
                'type': 'subscribe',
                'channel': 'market',
                'token_id': market.token_id
            })
    
    def on_message(self, msg):
        if msg.type == 'last_trade_price':
            # Real-time trade detection
            self.detect_whale_trade(msg)
            self.update_price(msg)
        
        if msg.type == 'book':
            # Orderbook update
            self.analyze_book_imbalance(msg)
```

#### 1.3 Advanced Opportunity Detector
```python
class OpportunityDetector:
    """Find REAL alpha"""
    
    def detect_negative_risk(self, markets):
        """
        NEGATIVE RISK = When sum of all NO positions < 100%
        Example: Market A YES=60%, Market B YES=55%
        If A and B are mutually exclusive: 
        Buy both NOs = 40% + 45% = 85% cost for 100% guaranteed return
        PROFIT = 15% risk-free
        """
        neg_risk_groups = group_by(markets, 'neg_risk_market_id')
        
        for group_id, group_markets in neg_risk_groups.items():
            total_no_cost = sum(1 - m.yes_price for m in group_markets)
            if total_no_cost < 0.99:  # 99% threshold for fees
                profit = (1 - total_no_cost) * 100
                yield Opportunity(
                    type='NEGATIVE_RISK',
                    profit=profit,
                    markets=group_markets,
                    action=f'Buy all NO positions, guaranteed {profit:.1f}% profit'
                )
    
    def detect_spread_opportunities(self, markets):
        """
        Wide spreads = opportunity for market makers
        """
        for market in markets:
            if market.spread > 0.02:  # 2% spread
                edge = market.spread * 0.4  # Conservative 40% capture
                yield Opportunity(
                    type='SPREAD',
                    profit=edge * 100,
                    market=market,
                    action=f'Provide liquidity, earn {edge*100:.1f}% from spread'
                )
    
    def detect_volume_anomalies(self, markets):
        """
        Sudden volume spikes often precede price moves
        """
        for market in markets:
            vol_ratio = market.volume_24h / (market.volume_7d / 7) if market.volume_7d > 0 else 1
            if vol_ratio > 3:  # 3x normal volume
                yield Signal(
                    type='VOLUME_SPIKE',
                    market=market,
                    message=f'Volume {vol_ratio:.1f}x normal - potential price move incoming'
                )
    
    def detect_price_momentum(self, markets):
        """
        Strong price momentum = follow the trend
        """
        for market in markets:
            if abs(market.price_change_24h) > 0.05:  # 5% move
                direction = 'UP' if market.price_change_24h > 0 else 'DOWN'
                yield Signal(
                    type='MOMENTUM',
                    market=market,
                    direction=direction,
                    message=f'{direction} {abs(market.price_change_24h)*100:.1f}% in 24h - momentum trade'
                )
```

---

### PHASE 2: DATABASE SCHEMA ENHANCEMENT

```sql
-- Enhanced markets table
ALTER TABLE markets ADD COLUMN IF NOT EXISTS volume_24h NUMERIC;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS volume_7d NUMERIC;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS volume_30d NUMERIC;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS price_change_24h NUMERIC;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS price_change_7d NUMERIC;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS price_change_30d NUMERIC;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS last_trade_price NUMERIC;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS best_bid NUMERIC;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS best_ask NUMERIC;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS spread NUMERIC;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS neg_risk BOOLEAN DEFAULT FALSE;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS neg_risk_group_id TEXT;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS competitive_score NUMERIC;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS has_rewards BOOLEAN DEFAULT FALSE;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS rewards_rate NUMERIC;

-- Real-time trades for whale detection
CREATE TABLE IF NOT EXISTS live_trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    market_id UUID REFERENCES markets(id),
    token_id TEXT NOT NULL,
    price NUMERIC NOT NULL,
    size NUMERIC NOT NULL,
    side TEXT NOT NULL,  -- 'BUY' or 'SELL'
    value_usd NUMERIC,
    is_whale BOOLEAN DEFAULT FALSE,
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Volume anomalies for intelligence
CREATE TABLE IF NOT EXISTS volume_anomalies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    market_id UUID REFERENCES markets(id),
    volume_ratio NUMERIC NOT NULL,  -- vs 7d average
    volume_24h NUMERIC NOT NULL,
    detected_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

### PHASE 3: FRONTEND TRANSFORMATION

#### 3.1 MARKETS PAGE - Make it a Trading Terminal

**Current**: Boring table with basic data
**New Vision**: Real trading terminal with:

```
┌─────────────────────────────────────────────────────────────────────┐
│ PREDICTUM MARKETS                         Live: 847 Markets Active  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│ │ 24H VOL  │ │ TOP MOVE │ │VOLATILITY│ │NEG RISK  │ │ WHALE    │   │
│ │ $847.2M  │ │ +34.5%   │ │ 12.4%    │ │ 23 LIVE  │ │ 156      │   │
│ │ ▲ +12%   │ │ BTC $125K│ │ ▼ -2.1%  │ │ OPPS     │ │ TRADES   │   │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│                                                                     │
│ ═══════════════════════════════════════════════════════════════════ │
│                                                                     │
│ [HOT 🔥] [POLITICS] [CRYPTO] [SPORTS] [ECONOMICS] [TECH] [ALL]     │
│                                                                     │
│ ┌───────────────────────────────────────────────────────────────┐   │
│ │                                                               │   │
│ │  🔥 Will Bitcoin reach $125,000 by Dec 31?                   │   │
│ │     ══════════════════════════════════════                   │   │
│ │     YES: 67¢  NO: 33¢  |  $3.04M Vol  |  ▲ +8.5% 24h        │   │
│ │     [████████████░░░░░░░] 67% YES                            │   │
│ │                                                               │   │
│ │     📊 Spread: 0.5%  💧 Liq: $845K  🐋 3 whale trades today  │   │
│ │     📈 7d: +12%  30d: +25%  |  NEG_RISK: 4.2% edge available │   │
│ │                                                               │   │
│ └───────────────────────────────────────────────────────────────┘   │
│                                                                     │
│ ┌───────────────────────────────────────────────────────────────┐   │
│ │  ⚡ Trump wins 2024 Election                                  │   │
│ │     ...                                                       │   │
│ └───────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Data Points per Market Card:**
- Current YES/NO price with probability bar
- 24H price change (with sparkline mini-chart)
- 24H / 7D / 30D volume comparison
- Spread percentage (color coded: green <1%, yellow 1-3%, red >3%)
- Liquidity depth
- Whale trade indicator (if any $10K+ trades in 24h)
- NEG_RISK badge if part of negative risk group
- Mini price chart (7 day)

#### 3.2 SCANNER PAGE - Alpha Detection Engine

```
┌─────────────────────────────────────────────────────────────────────┐
│ 🎯 PREDICTUM SCANNER               Active Signals: 47 | Edge: 4.2% │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ [ARBITRAGE 🔄] [SPREAD 📊] [NEG RISK ⚡] [MOMENTUM 🚀] [WHALE 🐋]  │
│                                                                     │
│ ═══════════════════════════════════════════════════════════════════ │
│ LIVE OPPORTUNITIES (Real-time scanning 847 markets)                 │
│ ═══════════════════════════════════════════════════════════════════ │
│                                                                     │
│ 🔴 HIGH PRIORITY - NEG RISK                                        │
│ ┌───────────────────────────────────────────────────────────────┐   │
│ │ ⚡ Fed Rate Cuts 2025 Group                                   │   │
│ │    GUARANTEED 3.7% PROFIT                                     │   │
│ │    Buy: 0 cuts (NO) @ 45¢ + 1 cut (NO) @ 52¢ = 97¢ for $1    │   │
│ │    ────────────────────────────────────────────                │   │
│ │    Confidence: 99% | Risk: NONE | Est. Return: $3,700/100K    │   │
│ │    [EXECUTE] [DETAILS] [SHARE]                                │   │
│ └───────────────────────────────────────────────────────────────┘   │
│                                                                     │
│ 🟡 SPREAD CAPTURE                                                   │
│ ┌───────────────────────────────────────────────────────────────┐   │
│ │ 📊 Bitcoin $90K by Dec 31                                     │   │
│ │    SPREAD: 4.2% (Bid: 0.61, Ask: 0.65)                       │   │
│ │    Est. LP Return: 2.1% by providing liquidity                │   │
│ │    Volume: $125K/day | Rewards: +5 USDC/day MM rewards       │   │
│ │    [PROVIDE LIQUIDITY] [DETAILS]                              │   │
│ └───────────────────────────────────────────────────────────────┘   │
│                                                                     │
│ 🟢 MOMENTUM SIGNAL                                                  │
│ ┌───────────────────────────────────────────────────────────────┐   │
│ │ 🚀 Trump Cabinet Pick X confirmed                             │   │
│ │    24H Change: +28.5% | Volume Spike: 5.2x normal            │   │
│ │    Whale Activity: 3 buys totaling $145K in last 2 hours     │   │
│ │    Signal: STRONG BUY MOMENTUM                                │   │
│ │    [FOLLOW TRADE] [SET ALERT]                                 │   │
│ └───────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

#### 3.3 INTELLIGENCE PAGE - Whale Tracking & Smart Money

```
┌─────────────────────────────────────────────────────────────────────┐
│ 🧠 PREDICTUM INTELLIGENCE          Smart Money Tracker v2.0        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ ┌─────────────────────┐  ┌─────────────────────────────────────┐   │
│ │ 🐋 WHALE RADAR      │  │ 📊 MARKET SENTIMENT                  │   │
│ │                     │  │                                     │   │
│ │  Last Hour: 12      │  │  ████████████░░░░░ 68% BULLISH      │   │
│ │  24H Total: 156     │  │  Based on 847 markets               │   │
│ │  Net Flow: +$2.4M   │  │  Avg confidence: 72%                │   │
│ │                     │  │                                     │   │
│ └─────────────────────┘  └─────────────────────────────────────┘   │
│                                                                     │
│ ═══════════════════════════════════════════════════════════════════ │
│ LIVE WHALE TRADES (>$10,000)                                        │
│ ═══════════════════════════════════════════════════════════════════ │
│                                                                     │
│ ⏱ 2 min ago   🐋 $45,000 BUY YES @ 0.67                            │
│              Bitcoin $125K by Dec 31                                │
│              Wallet: 0x7a3...f2b (Known MM)                         │
│                                                                     │
│ ⏱ 8 min ago   🐋 $28,500 BUY NO @ 0.34                             │
│              Trump wins Popular Vote                                │
│              Wallet: 0x4b2...8cd (New whale)                        │
│                                                                     │
│ ⏱ 15 min ago  🐋 $125,000 BUY YES @ 0.52                           │
│              Fed cuts rates in Dec                                  │
│              Wallet: 0x9e1...3ab (Institutional)                    │
│                                                                     │
│ ═══════════════════════════════════════════════════════════════════ │
│ CROSS-MARKET CORRELATIONS                                           │
│ ═══════════════════════════════════════════════════════════════════ │
│                                                                     │
│ 📈 Bitcoin $125K ←→ Bitcoin $100K : 0.94 correlation               │
│    When $100K moves, $125K follows within 15 min avg               │
│                                                                     │
│ 📈 Trump Election ←→ Republican Senate : 0.87 correlation          │
│    Arbitrage opportunity when divergence > 5%                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

### PHASE 4: KEY ALGORITHMS

#### 4.1 Whale Detection Algorithm
```python
def detect_whale_trade(trade):
    """
    Whale = trade > $10,000 USD value
    Track wallet patterns for known whales
    """
    value_usd = trade.size * trade.price
    
    if value_usd >= 10000:
        # Check if known wallet
        wallet_info = get_wallet_info(trade.maker_address)
        
        return {
            'is_whale': True,
            'value_usd': value_usd,
            'wallet_type': wallet_info.type,  # 'MM', 'Institutional', 'New', 'Known'
            'historical_accuracy': wallet_info.accuracy,  # Past win rate
            'signal_strength': calculate_signal_strength(trade, wallet_info)
        }
```

#### 4.2 Negative Risk Calculator
```python
def calculate_negative_risk_opportunity(markets_in_group):
    """
    For mutually exclusive markets, if sum(NO prices) < 1, 
    there's guaranteed profit by buying all NOs
    """
    no_prices = []
    for market in markets_in_group:
        yes_price = float(market.outcome_prices[0])
        no_price = 1 - yes_price
        no_prices.append({
            'market': market,
            'no_price': no_price,
            'liquidity': market.liquidity
        })
    
    total_no_cost = sum(p['no_price'] for p in no_prices)
    
    if total_no_cost < 0.99:  # Account for fees
        profit_percent = (1 - total_no_cost) * 100
        min_liquidity = min(p['liquidity'] for p in no_prices)
        max_position = min_liquidity * 0.1  # 10% of smallest liquidity
        
        return {
            'type': 'NEGATIVE_RISK',
            'profit_percent': profit_percent,
            'max_position_usd': max_position,
            'markets': no_prices,
            'confidence': 99,  # Near-certain profit
            'action': f'Buy all NO positions for {total_no_cost*100:.1f}¢, receive $1 guaranteed'
        }
```

#### 4.3 Volume Velocity Tracker
```python
def calculate_volume_velocity(market):
    """
    Compare current volume rate to historical average
    High velocity = something is happening
    """
    vol_24h = market.volume_24h
    vol_7d_daily_avg = market.volume_7d / 7
    
    if vol_7d_daily_avg > 0:
        velocity = vol_24h / vol_7d_daily_avg
        
        if velocity > 3:
            return {
                'velocity': velocity,
                'signal': 'EXTREME',
                'action': 'Major news event likely - monitor closely'
            }
        elif velocity > 2:
            return {
                'velocity': velocity,
                'signal': 'HIGH',
                'action': 'Above average activity - potential opportunity'
            }
    
    return {'velocity': 1, 'signal': 'NORMAL', 'action': None}
```

---

## 🎯 IMPLEMENTATION PRIORITY

### Week 1: Data Foundation
1. ✅ Enhance `polymarket_api.py` to extract ALL GAMMA data fields
2. ✅ Update database schema with new columns
3. ✅ Update market scanner to store rich data
4. ✅ Deploy backend changes

### Week 2: Intelligence Layer  
1. Implement WebSocket worker for real-time trades
2. Build whale detection algorithm
3. Create negative risk scanner
4. Build volume velocity tracker

### Week 3: Frontend Transformation
1. Redesign Markets page with rich data cards
2. Build Scanner page with live opportunities
3. Create Intelligence page with whale radar
4. Add real-time updates via Supabase subscriptions

### Week 4: Polish & Launch
1. Performance optimization
2. Mobile responsiveness
3. Documentation
4. Launch 🚀

---

## 📊 SUCCESS METRICS

- **Data Freshness**: < 10 second delay from Polymarket
- **Opportunities Detected**: 10+ actionable signals per day
- **Whale Tracking**: 95%+ of $10K+ trades captured
- **User Engagement**: 5+ minute avg session
- **Alpha Generated**: Track user P&L on followed signals

---

## THE BOTTOM LINE

Current Predictum = Generic data display
Predictum 2.0 = **The Bloomberg Terminal for Prediction Markets**

We have access to INSANELY rich data from Polymarket. We're just not using it.
Time to change that. 🔥

*"Everyone has access to the information. We just know how to analyze it better."*





