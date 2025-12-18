"""
Rate Limiter for Polymarket APIs
Based on: https://docs.polymarket.com/quickstart/introduction/rate-limits

GAMMA API Limits:
- General: 750 requests / 10s (75/s)
- /events: 100 requests / 10s (10/s)
- /markets: 125 requests / 10s (12.5/s)

CLOB API Limits:
- General: 5000 requests / 10s (500/s)
- /book: 200 requests / 10s (20/s)
- /books (batch): 80 requests / 10s (8/s)
- /price: 200 requests / 10s (20/s)
- /prices (batch): 80 requests / 10s (8/s)
- /midpoint: 200 requests / 10s (20/s)
- Price History: 100 requests / 10s (10/s)
- /spread: 200 requests / 10s (20/s)

We'll be conservative and stay at 80% of these limits.
"""
import time
import threading
from collections import defaultdict
from typing import Dict
import logging

logger = logging.getLogger(__name__)


class TokenBucket:
    """Token bucket rate limiter"""
    
    def __init__(self, rate: float, capacity: float):
        """
        Args:
            rate: Tokens added per second
            capacity: Maximum tokens in bucket
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self.lock = threading.Lock()
    
    def acquire(self, tokens: int = 1) -> float:
        """
        Acquire tokens, blocking if necessary.
        Returns time waited.
        """
        with self.lock:
            now = time.monotonic()
            
            # Add tokens based on time elapsed
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0
            
            # Calculate wait time
            tokens_needed = tokens - self.tokens
            wait_time = tokens_needed / self.rate
            
            return wait_time
    
    def wait(self, tokens: int = 1):
        """Acquire tokens, sleeping if necessary"""
        wait_time = self.acquire(tokens)
        if wait_time > 0:
            time.sleep(wait_time)
            # Deduct tokens after waiting
            with self.lock:
                self.tokens = max(0, self.tokens - tokens)


class PolymarketRateLimiter:
    """
    Rate limiter specifically designed for Polymarket APIs
    """
    
    def __init__(self):
        # GAMMA API buckets (80% of limits for safety)
        self.gamma_general = TokenBucket(rate=60, capacity=600)  # 75/s * 0.8
        self.gamma_events = TokenBucket(rate=8, capacity=80)     # 10/s * 0.8
        self.gamma_markets = TokenBucket(rate=10, capacity=100)  # 12.5/s * 0.8
        
        # CLOB API buckets (80% of limits for safety)
        self.clob_general = TokenBucket(rate=400, capacity=4000)    # 500/s * 0.8
        self.clob_book = TokenBucket(rate=16, capacity=160)         # 20/s * 0.8
        self.clob_books_batch = TokenBucket(rate=6, capacity=64)    # 8/s * 0.8
        self.clob_price = TokenBucket(rate=16, capacity=160)        # 20/s * 0.8
        self.clob_prices_batch = TokenBucket(rate=6, capacity=64)   # 8/s * 0.8
        self.clob_spread = TokenBucket(rate=16, capacity=160)       # 20/s * 0.8
        self.clob_midpoint = TokenBucket(rate=16, capacity=160)     # 20/s * 0.8
        self.clob_history = TokenBucket(rate=8, capacity=80)        # 10/s * 0.8
        
        # Request counters for logging
        self.request_counts: Dict[str, int] = defaultdict(int)
        self.last_log_time = time.monotonic()
        self.log_interval = 60  # Log stats every 60 seconds
    
    def _log_stats(self):
        """Log request statistics periodically"""
        now = time.monotonic()
        if now - self.last_log_time >= self.log_interval:
            if any(self.request_counts.values()):
                stats = ", ".join(f"{k}: {v}" for k, v in sorted(self.request_counts.items()))
                logger.info(f"Rate limiter stats (last {self.log_interval}s): {stats}")
            self.request_counts.clear()
            self.last_log_time = now
    
    def wait_gamma(self, endpoint: str = "general"):
        """
        Wait for GAMMA API rate limit
        
        Args:
            endpoint: One of "general", "events", "markets"
        """
        self._log_stats()
        self.request_counts[f"gamma_{endpoint}"] += 1
        
        # Always check general limit
        self.gamma_general.wait()
        
        # Check endpoint-specific limit
        if endpoint == "events":
            self.gamma_events.wait()
        elif endpoint == "markets":
            self.gamma_markets.wait()
    
    def wait_clob(self, endpoint: str = "general"):
        """
        Wait for CLOB API rate limit
        
        Args:
            endpoint: One of "general", "book", "books", "price", "prices", 
                     "spread", "midpoint", "history"
        """
        self._log_stats()
        self.request_counts[f"clob_{endpoint}"] += 1
        
        # Always check general limit
        self.clob_general.wait()
        
        # Check endpoint-specific limit
        if endpoint == "book":
            self.clob_book.wait()
        elif endpoint == "books":
            self.clob_books_batch.wait()
        elif endpoint == "price":
            self.clob_price.wait()
        elif endpoint == "prices":
            self.clob_prices_batch.wait()
        elif endpoint == "spread":
            self.clob_spread.wait()
        elif endpoint == "midpoint":
            self.clob_midpoint.wait()
        elif endpoint == "history":
            self.clob_history.wait()
    
    def get_stats(self) -> Dict[str, float]:
        """Get current token levels for monitoring"""
        return {
            "gamma_general": self.gamma_general.tokens,
            "gamma_events": self.gamma_events.tokens,
            "gamma_markets": self.gamma_markets.tokens,
            "clob_general": self.clob_general.tokens,
            "clob_book": self.clob_book.tokens,
            "clob_price": self.clob_price.tokens,
        }


# Global rate limiter instance
rate_limiter = PolymarketRateLimiter()


# Convenience functions
def wait_gamma(endpoint: str = "general"):
    """Wait for GAMMA API rate limit"""
    rate_limiter.wait_gamma(endpoint)


def wait_clob(endpoint: str = "general"):
    """Wait for CLOB API rate limit"""
    rate_limiter.wait_clob(endpoint)
