"""Conservative per-process usage guard; not a substitute for edge rate limiting."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque


class RequestLimited(Exception):
    pass


class AIGuard:
    def __init__(self, requests_per_minute: int = 6, concurrency: int = 2) -> None:
        self.limit = requests_per_minute
        self.history: dict[str, deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(concurrency)

    async def check_rate(self, identity: str) -> None:
        now = time.monotonic()
        async with self.lock:
            # Bound number of retained client keys, even with arbitrary connections.
            if len(self.history) >= 5000 and identity not in self.history:
                self.history = defaultdict(deque, {
                    key: times for key, times in self.history.items()
                    if times and times[-1] > now - 60
                })
                if len(self.history) >= 5000:
                    raise RequestLimited("AI processing is busy; try again later")
            times = self.history[identity]
            while times and times[0] <= now - 60:
                times.popleft()
            if len(times) >= self.limit:
                raise RequestLimited("Too many AI requests; try again later")
            times.append(now)

    async def acquire(self) -> None:
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=0.2)
        except TimeoutError as exc:
            raise RequestLimited("AI processing is busy; try again later") from exc

    def release(self) -> None:
        self.semaphore.release()
