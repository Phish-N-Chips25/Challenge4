"""Shared in-memory event log for the web dashboard.

Agents push human-readable lines here (in addition to printing them); the
dashboard reads the buffer to render a live timeline. Kept tiny and dependency
free to avoid import cycles.
"""

import time
from collections import deque

LOG: deque = deque(maxlen=300)


def push(source: str, text: str) -> None:
    LOG.append({"t": time.time(), "source": source, "text": text})


def snapshot(limit: int = 80) -> list[dict]:
    """Return the most recent entries (oldest first)."""
    items = list(LOG)
    return items[-limit:]
