"""Redis-backed cache + rate limiter with in-memory fallback.

Used for: translation cache (re-speak < 3s target), engine health snapshots,
per-user rate limits and quota counters.
"""

import json
import time
from typing import Any

from app.config import settings

try:
    import redis as redis_lib

    _pool = redis_lib.ConnectionPool.from_url(settings.redis_url, decode_responses=True)
    _client = redis_lib.Redis(connection_pool=_pool)
    _client.ping()
except Exception:  # pragma: no cover - Redis optional in dev
    _client = None


class MemoryCache:
    def __init__(self):
        self._data: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires and expires < time.monotonic():
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._data[key] = (
            (time.monotonic() + ttl) if ttl else None,
            value,
        )

    def incr(self, key: str, ttl: int) -> int:
        val = int(self.get(key) or 0) + 1
        self.set(key, str(val), ttl)
        return val

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


_memory = MemoryCache()


def cache() -> MemoryCache:
    """Return the Redis-backed cache, or the in-memory one as fallback."""
    return _RedisCache() if _client is not None else _memory


class _RedisCache:
    def get(self, key: str) -> str | None:
        try:
            return _client.get(key)
        except Exception:
            return _memory.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        try:
            _client.set(key, value, ex=ttl)
        except Exception:
            _memory.set(key, value, ttl)

    def incr(self, key: str, ttl: int) -> int:
        try:
            with _client.pipeline() as pipe:
                pipe.incr(key)
                pipe.expire(key, ttl, nx=True)
                return int(pipe.execute()[0])
        except Exception:
            return _memory.incr(key, ttl)

    def delete(self, key: str) -> None:
        try:
            _client.delete(key)
        except Exception:
            _memory.delete(key)

    # json helpers
    def get_json(self, key: str) -> Any:
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        self.set(key, json.dumps(value, ensure_ascii=False), ttl)


def translation_cache_key(text: str, lang: str) -> str:
    return f"tr:{lang}:{hash(text)}"


# ---- quotas ----

def quota_key(user_id: str) -> str:
    day = time.strftime("%Y%m%d")
    return f"quota:{user_id}:{day}"


def check_quota(user_id: str, plan: str, chars: int) -> bool:
    """True if the user still has headroom for `chars` of TTS today."""
    limit = settings.quota_by_plan.get(plan, settings.quota_free_chars)
    used = int(cache().get(quota_key(user_id)) or 0)
    return used + chars <= limit


def add_usage(user_id: str, chars: int) -> int:
    return cache().incr(quota_key(user_id), ttl=86400)


# ---- rate limits (requests per window) ----

def allow_rate(user_id: str, bucket: str, limit: int, window_seconds: int) -> bool:
    key = f"rate:{user_id}:{bucket}"
    count = cache().incr(key, ttl=window_seconds)
    return count <= limit
