"""
Token bucket rate limiter for Polymarket APIs
GAMMA: 125 requests per 10 seconds
CLOB: 80 requests per 10 seconds
"""
import time
import threading
from typing import Optional

class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        """
        Args:
            capacity: Maximum number of tokens
            refill_rate: Tokens per second
        """
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_refill = time.time()
        self.lock = threading.Lock()
    
    def acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens. Returns True if successful."""
        with self.lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def wait(self, tokens: int = 1) -> float:
        """Wait until tokens are available. Returns wait time."""
        with self.lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0
            
            # Calculate wait time
            needed = tokens - self.tokens
            wait_time = needed / self.refill_rate
            self.tokens = 0  # Use all available tokens
            return wait_time
    
    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now

class RateLimiter:
    """Rate limiter for Polymarket APIs"""
    
    def __init__(self):
        # GAMMA: 125 req / 10s = 12.5 req/s, capacity 125
        self.gamma = TokenBucket(capacity=125, refill_rate=12.5)
        
        # CLOB: 80 req / 10s = 8 req/s, capacity 80
        self.clob = TokenBucket(capacity=80, refill_rate=8.0)
    
    def wait_gamma(self, tokens: int = 1):
        """Wait for GAMMA API tokens"""
        wait_time = self.gamma.wait(tokens)
        if wait_time > 0:
            time.sleep(wait_time)
    
    def wait_clob(self, tokens: int = 1):
        """Wait for CLOB API tokens"""
        wait_time = self.clob.wait(tokens)
        if wait_time > 0:
            time.sleep(wait_time)

# Global rate limiter instance
rate_limiter = RateLimiter()

