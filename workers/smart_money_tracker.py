"""
Smart Money Tracker - Wolf Pack Edition
Tracks whale wallets, identifies smart money patterns, and builds sentiment indicators
"""
import time
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Smart money detection thresholds
WHALE_TRADE_MIN_USD = 10000  # $10k+ is whale
SMART_MONEY_MIN_TRADES = 5  # Need 5+ trades to analyze
SMART_MONEY_WIN_RATE_THRESHOLD = 0.60  # 60%+ win rate = smart money
COORDINATED_TRADING_THRESHOLD = 3  # 3+ whales same direction = coordinated


class SmartMoneyTracker:
    """
    Wolf Pack Smart Money Intelligence
    - Tracks whale wallet addresses
    - Calculates wallet win rates and profitability
    - Detects coordinated whale activity
    - Builds smart money sentiment indicator
    """
    
    def __init__(self):
        self.db = SupabaseClient()
        self.scan_interval = 300  # 5 minutes
        self.wallet_trades: Dict[str, List[Dict]] = {}  # wallet -> trades
        self.smart_money_wallets: Set[str] = set()
        
    def _get_recent_whale_trades(self, hours: int = 24) -> List[Dict]:
        """Get whale trades from the last N hours"""
        try:
            trades = self.db.get_whale_trades(limit=500)
            
            # Filter by time
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            recent_trades = []
            
            for trade in trades:
                ts = trade.get('timestamp')
                if ts:
                    if isinstance(ts, str):
                        try:
                            trade_time = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        except:
                            continue
                    else:
                        trade_time = ts
                    
                    if trade_time.tzinfo is None:
                        trade_time = trade_time.replace(tzinfo=timezone.utc)
                    
                    if trade_time >= cutoff:
                        recent_trades.append(trade)
            
            return recent_trades
            
        except Exception as e:
            logger.error(f"Error getting whale trades: {e}")
            return []
    
    def _group_trades_by_wallet(self, trades: List[Dict]) -> Dict[str, List[Dict]]:
        """Group trades by wallet address"""
        wallet_trades = defaultdict(list)
        
        for trade in trades:
            # Use maker or taker address
            maker = trade.get('maker', '')
            taker = trade.get('taker', '')
            
            if maker and len(maker) > 10:  # Valid address
                wallet_trades[maker].append({**trade, 'role': 'maker'})
            
            if taker and len(taker) > 10:
                wallet_trades[taker].append({**trade, 'role': 'taker'})
        
        return dict(wallet_trades)
    
    def analyze_wallet(self, wallet_address: str, trades: List[Dict]) -> Dict:
        """Analyze a wallet's trading behavior and performance"""
        if not trades or len(trades) < 2:
            return {}
        
        try:
            total_volume = 0
            buy_volume = 0
            sell_volume = 0
            trade_count = len(trades)
            markets_traded = set()
            
            # Calculate metrics
            for trade in trades:
                value = float(trade.get('size', 0)) * float(trade.get('price', 0))
                total_volume += value
                
                side = trade.get('side', '').upper()
                if side == 'BUY':
                    buy_volume += value
                elif side == 'SELL':
                    sell_volume += value
                
                market_id = trade.get('market_id')
                if market_id:
                    markets_traded.add(str(market_id))
            
            # Calculate buy/sell ratio
            buy_ratio = buy_volume / total_volume if total_volume > 0 else 0.5
            
            # Determine wallet sentiment
            if buy_ratio > 0.7:
                sentiment = 'bullish'
            elif buy_ratio < 0.3:
                sentiment = 'bearish'
            else:
                sentiment = 'neutral'
            
            # Estimate win rate (simplified - based on whether trades were 
            # made at favorable prices vs current)
            # In a real system, you'd track actual P&L
            profitable_trades = 0
            for trade in trades:
                # Get market data to compare current price
                market_data = trade.get('markets', {})
                current_price = market_data.get('current_price')
                trade_price = float(trade.get('price', 0))
                side = trade.get('side', '').upper()
                
                if current_price and trade_price:
                    if side == 'BUY' and current_price > trade_price:
                        profitable_trades += 1
                    elif side == 'SELL' and current_price < trade_price:
                        profitable_trades += 1
            
            win_rate = profitable_trades / trade_count if trade_count > 0 else 0.5
            
            # Determine if this is "smart money"
            is_smart_money = (
                trade_count >= SMART_MONEY_MIN_TRADES and
                total_volume >= WHALE_TRADE_MIN_USD * 3 and
                win_rate >= SMART_MONEY_WIN_RATE_THRESHOLD
            )
            
            return {
                'wallet_address': wallet_address,
                'total_trades': trade_count,
                'total_volume': total_volume,
                'buy_volume': buy_volume,
                'sell_volume': sell_volume,
                'buy_ratio': buy_ratio,
                'sentiment': sentiment,
                'win_rate': win_rate,
                'markets_traded': len(markets_traded),
                'is_smart_money': is_smart_money
            }
            
        except Exception as e:
            logger.error(f"Error analyzing wallet {wallet_address}: {e}")
            return {}
    
    def detect_coordinated_activity(self, wallet_trades: Dict[str, List[Dict]]) -> List[Dict]:
        """Detect coordinated trading activity among whales"""
        coordinated_signals = []
        
        try:
            # Group trades by market and time window
            market_activity = defaultdict(lambda: {'buys': [], 'sells': []})
            
            for wallet, trades in wallet_trades.items():
                for trade in trades:
                    market_id = trade.get('market_id')
                    if not market_id:
                        continue
                    
                    side = trade.get('side', '').upper()
                    if side == 'BUY':
                        market_activity[market_id]['buys'].append(wallet)
                    elif side == 'SELL':
                        market_activity[market_id]['sells'].append(wallet)
            
            # Check for coordinated activity
            for market_id, activity in market_activity.items():
                unique_buyers = set(activity['buys'])
                unique_sellers = set(activity['sells'])
                
                # Coordinated buying
                if len(unique_buyers) >= COORDINATED_TRADING_THRESHOLD:
                    coordinated_signals.append({
                        'market_id': market_id,
                        'type': 'coordinated_buying',
                        'whale_count': len(unique_buyers),
                        'wallets': list(unique_buyers)[:5]  # Limit for privacy
                    })
                
                # Coordinated selling
                if len(unique_sellers) >= COORDINATED_TRADING_THRESHOLD:
                    coordinated_signals.append({
                        'market_id': market_id,
                        'type': 'coordinated_selling',
                        'whale_count': len(unique_sellers),
                        'wallets': list(unique_sellers)[:5]
                    })
            
            return coordinated_signals
            
        except Exception as e:
            logger.error(f"Error detecting coordinated activity: {e}")
            return []
    
    def calculate_smart_money_sentiment(self, wallet_analyses: List[Dict]) -> Dict:
        """Calculate aggregate smart money sentiment"""
        try:
            if not wallet_analyses:
                return {'sentiment': 'neutral', 'score': 0, 'confidence': 0}
            
            # Filter to smart money wallets only
            smart_money = [w for w in wallet_analyses if w.get('is_smart_money')]
            
            if not smart_money:
                return {'sentiment': 'neutral', 'score': 0, 'confidence': 0}
            
            # Calculate weighted sentiment
            total_volume = sum(w.get('total_volume', 0) for w in smart_money)
            
            if total_volume == 0:
                return {'sentiment': 'neutral', 'score': 0, 'confidence': 0}
            
            weighted_buy_ratio = sum(
                w.get('buy_ratio', 0.5) * w.get('total_volume', 0) 
                for w in smart_money
            ) / total_volume
            
            # Convert to -100 to +100 scale
            sentiment_score = (weighted_buy_ratio - 0.5) * 200
            
            # Determine sentiment label
            if sentiment_score > 20:
                sentiment = 'bullish'
            elif sentiment_score < -20:
                sentiment = 'bearish'
            else:
                sentiment = 'neutral'
            
            # Confidence based on number of smart money wallets and volume
            confidence = min(100, len(smart_money) * 10 + (total_volume / 100000) * 20)
            
            return {
                'sentiment': sentiment,
                'score': sentiment_score,
                'confidence': confidence,
                'smart_money_wallets': len(smart_money),
                'total_volume': total_volume,
                'weighted_buy_ratio': weighted_buy_ratio
            }
            
        except Exception as e:
            logger.error(f"Error calculating smart money sentiment: {e}")
            return {'sentiment': 'neutral', 'score': 0, 'confidence': 0}
    
    def track_smart_money(self):
        """Main smart money tracking loop"""
        try:
            logger.info("Starting smart money analysis...")
            
            # Get recent whale trades
            trades = self._get_recent_whale_trades(hours=24)
            
            if not trades:
                logger.info("No whale trades found in last 24 hours")
                return
            
            logger.info(f"Analyzing {len(trades)} whale trades...")
            
            # Group by wallet
            wallet_trades = self._group_trades_by_wallet(trades)
            logger.info(f"Found {len(wallet_trades)} unique whale wallets")
            
            # Analyze each wallet
            wallet_analyses = []
            new_smart_money = 0
            
            for wallet, trades in wallet_trades.items():
                if len(trades) < 2:
                    continue
                
                analysis = self.analyze_wallet(wallet, trades)
                
                if analysis:
                    wallet_analyses.append(analysis)
                    
                    if analysis.get('is_smart_money'):
                        if wallet not in self.smart_money_wallets:
                            self.smart_money_wallets.add(wallet)
                            new_smart_money += 1
                            logger.info(f"🧠 New Smart Money: {wallet[:16]}... "
                                      f"(Win Rate: {analysis['win_rate']:.0%}, "
                                      f"Volume: ${analysis['total_volume']:,.0f})")
            
            # Calculate aggregate sentiment
            sentiment = self.calculate_smart_money_sentiment(wallet_analyses)
            
            logger.info(f"📊 Smart Money Sentiment: {sentiment['sentiment'].upper()} "
                       f"(Score: {sentiment['score']:.0f}, "
                       f"Confidence: {sentiment['confidence']:.0f}%)")
            
            # Create signal for significant sentiment
            if abs(sentiment['score']) > 30 and sentiment['confidence'] > 50:
                direction = 'Bullish' if sentiment['score'] > 0 else 'Bearish'
                self.db.insert_signal({
                    'market_id': None,  # Global signal
                    'type': 'smart_money_sentiment',
                    'title': f"Smart Money {direction}",
                    'description': f"{sentiment['smart_money_wallets']} smart money wallets showing {direction.lower()} sentiment",
                    'severity': 'high',
                    'data': sentiment
                })
            
            # Detect coordinated activity
            coordinated = self.detect_coordinated_activity(wallet_trades)
            
            for signal in coordinated:
                is_buying = signal['type'] == 'coordinated_buying'
                logger.info(f"🐋 Coordinated {'Buying' if is_buying else 'Selling'}: "
                           f"{signal['whale_count']} whales in market {signal['market_id'][:16]}...")
                
                self.db.insert_signal({
                    'market_id': signal['market_id'],
                    'type': signal['type'],
                    'title': f"Coordinated Whale {'Buying' if is_buying else 'Selling'}",
                    'description': f"{signal['whale_count']} whale wallets {'buying' if is_buying else 'selling'} together",
                    'severity': 'high',
                    'data': signal
                })
            
            # Log summary
            smart_money_count = len([w for w in wallet_analyses if w.get('is_smart_money')])
            logger.info(f"Smart Money Analysis Complete: "
                       f"{smart_money_count} smart money wallets identified, "
                       f"{new_smart_money} new, "
                       f"{len(coordinated)} coordinated activities")
            
        except Exception as e:
            logger.error(f"Error in smart money tracking: {e}", exc_info=True)
    
    def run(self):
        """Main worker loop"""
        logger.info("Smart Money Tracker started (Wolf Pack Edition)")
        
        while True:
            try:
                self.track_smart_money()
            except Exception as e:
                logger.error(f"Fatal error in smart money tracker: {e}", exc_info=True)
            
            logger.info(f"Sleeping for {self.scan_interval} seconds...")
            time.sleep(self.scan_interval)


if __name__ == "__main__":
    tracker = SmartMoneyTracker()
    tracker.run()

