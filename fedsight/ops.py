"""Operational guardrails for a public demo: rate limiting, a daily spend cap, and an audit log."""
from __future__ import annotations

import hashlib
import json
import logging
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, date, datetime
from pathlib import Path


class RateLimiter:
    def __init__(self, per_hour: int, per_day_total: int):
        self.per_hour, self.per_day_total = per_hour, per_day_total
        self.hits: dict[str, deque] = defaultdict(deque)
        self.day, self.day_count = date.today(), 0
        self.lock = threading.Lock()

    def check(self, key: str) -> str | None:
        """Returns None if allowed, otherwise a message explaining the limit."""
        now = time.time()
        with self.lock:
            if date.today() != self.day:
                self.day, self.day_count = date.today(), 0
            if self.day_count >= self.per_day_total:
                return "The demo has hit its daily question limit. It resets at midnight UTC."
            q = self.hits[key]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= self.per_hour:
                return f"Rate limit: {self.per_hour} questions per hour. Try again in a bit."
            q.append(now)
            self.day_count += 1
            return None


class AuditLog:
    """One JSON line per request. On Cloud Run stdout goes to Cloud Logging; locally it's also written to a file."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.lock = threading.Lock()
        self.logger = logging.getLogger("fedsight.audit")
        if not self.logger.handlers:
            h = logging.StreamHandler(sys.stdout)
            h.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(h)
            self.logger.setLevel(logging.INFO)
            self.logger.propagate = False

    @staticmethod
    def hash_client(ip: str) -> str:
        return hashlib.sha256(("fedsight:" + ip).encode()).hexdigest()[:16]

    def write(self, record: dict) -> None:
        record = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), **record}
        line = json.dumps(record, default=str)
        self.logger.info(line)
        if self.path:
            with self.lock, open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
