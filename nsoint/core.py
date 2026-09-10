"""Shared primitives: HTTP session, result schema, rate limiting, cache."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import sqlite3
import ssl
import time
import weakref
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp

log = logging.getLogger("nsoint")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 16_0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/19.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:138.0) Gecko/20100101 Firefox/138.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0",
]

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=6)

PER_HOST_LIMIT = 4
HOST_LIMITS: dict[str, int] = {
    "github.com": 8,
    "www.reddit.com": 1,
    "reddit.com": 1,
    "top.gg": 2,
    "html.duckduckgo.com": 1,
    "www.bing.com": 1,
}
_MAX_HOSTS = 512

_host_sems: "OrderedDict[tuple[str, int], tuple[asyncio.Semaphore, weakref.ReferenceType]]" = OrderedDict()


def _host_sem(host: str) -> asyncio.Semaphore:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.Semaphore(HOST_LIMITS.get(host, PER_HOST_LIMIT))

    key = (host, id(loop))
    entry = _host_sems.get(key)
    if entry is not None:
        sem, ref = entry
        if ref() is loop:
            _host_sems.move_to_end(key)
            return sem
        del _host_sems[key]

    if len(_host_sems) >= _MAX_HOSTS:
        _host_sems.popitem(last=False)

    sem = asyncio.Semaphore(HOST_LIMITS.get(host, PER_HOST_LIMIT))
    _host_sems[key] = (sem, weakref.ref(loop))
    return sem


def _now() -> float:
    return time.time()


@dataclass
class Result:
    module: str
    target: str
    found: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    degraded: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        normalized: list[dict[str, str]] = []
        for entry in self.degraded:
            if isinstance(entry, dict):
                source = str(entry.get("source", "unknown"))
                detail = str(entry.get("detail", ""))
                extra = set(entry.keys()) - {"source", "detail"}
                if extra:
                    log.warning(
                        "dropping extra keys from degraded entry: %s",
                        sorted(extra),
                    )
                normalized.append({"source": source, "detail": detail})
            elif isinstance(entry, str):
                normalized.append({"source": "unknown", "detail": entry})
            else:
                normalized.append({"source": "unknown", "detail": str(entry)})
        self.degraded = normalized

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=_json_default)


def _json_default(o: Any) -> Any:
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    if isinstance(o, bytes):
        return o.decode("utf-8", errors="replace")
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "nsoint"
_DEFAULT_CACHE_PATH = _DEFAULT_CACHE_DIR / "cache.db"

_CACHE_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS cache ("
    "  key TEXT PRIMARY KEY,"
    "  ts REAL NOT NULL,"
    "  payload TEXT NOT NULL"
    ")"
)


class Cache:
    def __init__(self, path=None, *, enabled: bool = True) -> None:
        if path is None:
            path = _DEFAULT_CACHE_PATH
        self.path = str(path)
        self.enabled = enabled
        self._conn = None

        if not enabled:
            return

        requested_path = self.path
        try:
            if requested_path != ":memory:":
                parent = Path(requested_path).parent
                parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                try:
                    parent.chmod(0o700)
                except OSError:
                    pass

                fd = os.open(requested_path, os.O_CREAT | os.O_WRONLY, 0o600)
                os.close(fd)
                try:
                    os.chmod(requested_path, 0o600)
                except OSError:
                    pass

            self._conn = sqlite3.connect(requested_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=MEMORY")
            self._conn.execute(_CACHE_SCHEMA)
            self._conn.commit()

        except (sqlite3.Error, OSError) as exc:
            log.warning(
                "disk cache unavailable at %s (%s) — falling back to in-memory",
                requested_path,
                exc,
            )
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None
            self.path = ":memory:"
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._conn.execute(_CACHE_SCHEMA)
            self._conn.commit()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def get(self, key: str, ttl: int):
        if not self.enabled or self._conn is None:
            return None
        try:
            row = self._conn.execute(
                "SELECT ts, payload FROM cache WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.Error as exc:
            log.warning("cache read failed: %s", exc)
            return None
        if not row:
            return None
        ts, payload = row
        if _now() - ts > ttl:
            return None
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            return None
        try:
            return Result(**data)
        except (TypeError, ValueError):
            return None

    def put(self, key: str, result: Result) -> None:
        if not self.enabled or self._conn is None:
            return
        try:
            payload = result.to_json()
        except (TypeError, ValueError) as exc:
            log.warning("cache serialization failed: %s", exc)
            return
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, ts, payload) VALUES (?, ?, ?)",
                (key, _now(), payload),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            log.warning("cache write failed: %s", exc)

    def clear(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute("DELETE FROM cache")
            self._conn.commit()
        except sqlite3.Error:
            pass

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None


CACHE = Cache()


def make_session(*, verify_ssl: bool = True) -> aiohttp.ClientSession:
    if verify_ssl:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        log.warning("SSL verification disabled.")

    connector = aiohttp.TCPConnector(ssl=ctx, limit=64, ttl_dns_cache=300)
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    return aiohttp.ClientSession(headers=headers, timeout=DEFAULT_TIMEOUT, connector=connector)


async def safe_fetch(session, url, method="GET", *, allow_redirects=True, retries=2, backoff=0.6, **kwargs):
    host = urlparse(url).netloc or "unknown"
    sem = _host_sem(host)
    last_status, last_body = 0, "unreachable"

    for attempt in range(retries + 1):
        async with sem:
            try:
                async with session.request(method, url, allow_redirects=allow_redirects, **kwargs) as resp:
                    body = await resp.text(errors="ignore")
                    status = resp.status
                    if 500 <= status < 600 and attempt < retries:
                        last_status, last_body = status, body
                    else:
                        return status, body
            except asyncio.TimeoutError:
                last_status, last_body = 0, "timeout"
            except aiohttp.ClientError as exc:
                last_status, last_body = 0, f"client_error:{type(exc).__name__}"
            except Exception as exc:
                last_status, last_body = 0, f"unexpected:{type(exc).__name__}"

        if attempt < retries:
            await asyncio.sleep(backoff * (2 ** attempt) + random.random() * 0.2)

    return last_status, last_body


def cache_key(module: str, target: str) -> str:
    digest = hashlib.sha1(target.encode("utf-8")).hexdigest()[:16]
    return f"{module}:{digest}"
