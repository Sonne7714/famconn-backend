from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request, status


class InMemoryRateLimiter:
    """Simple sliding-window limiter in memory (single instance).
    For multi-instance deployments, switch to a shared store (e.g., Redis)."""

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = {}

    def _prune(self, q: Deque[float], now: float, window_seconds: int) -> None:
        cutoff = now - window_seconds
        while q and q[0] <= cutoff:
            q.popleft()

    def hit(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
        now = time.time()
        q = self._hits.setdefault(key, deque())
        self._prune(q, now, window_seconds)
        if len(q) >= max_requests:
            retry_after = int(window_seconds - (now - q[0])) if q else window_seconds
            return False, max(1, retry_after)
        q.append(now)
        return True, 0


limiter = InMemoryRateLimiter()


def get_client_ip(request: Request) -> str:
    # If behind proxy (Render), x-forwarded-for contains the original IP.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit_or_429(request: Request, key: str, max_requests: int, window_seconds: int) -> None:
    ok, retry_after = limiter.hit(key, max_requests=max_requests, window_seconds=window_seconds)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
