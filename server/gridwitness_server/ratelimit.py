"""Per-node token-bucket rate limiter (in-memory).

Sized in *rows per minute* — a node pushing every 30 s with a few phases is well under the default
cap; abuse trips 429. In-memory is fine for a single-process home server; if the server is ever
scaled out this moves to a shared store.
"""
from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, rows_per_min: int):
        self.capacity = float(rows_per_min)
        self.refill_per_sec = rows_per_min / 60.0
        self._buckets: dict[str, tuple[float, float]] = {}  # node_id -> (tokens, last_ts)
        self._lock = threading.Lock()

    def allow(self, node_id: str, rows: int) -> bool:
        """Consume ``rows`` tokens for ``node_id``; return False if the bucket can't cover them."""
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(node_id, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill_per_sec)
            if tokens < rows:
                self._buckets[node_id] = (tokens, now)
                return False
            self._buckets[node_id] = (tokens - rows, now)
            return True
