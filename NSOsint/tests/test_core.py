# --- tests/test_core.py ---
import asyncio
import json
import os
import sqlite3
from pathlib import Path

import aiohttp
import pytest

from nsoint import __version__
from nsoint.core import Cache, Result, cache_key, make_session, safe_fetch


def test_version_is_present():
    assert __version__ == "1.2.7"


def test_result_serializes_sets():
    r = Result("m", "t", True, data={"tags": {"a", "b"}})
    parsed = json.loads(r.to_json())
    assert parsed["data"]["tags"] == ["a", "b"]


def test_result_serializes_datetime():
    from datetime import datetime
    r = Result("m", "t", True, data={"ts": datetime(2026, 1, 1, 12, 0, 0)})
    parsed = json.loads(r.to_json())
    assert parsed["data"]["ts"].startswith("2026-01-01T12:00:00")


def test_result_rejects_unknown_type():
    class Weird:
        pass

    r = Result("m", "t", True, data={"x": Weird()})
    with pytest.raises(TypeError):
        r.to_json()


def test_result_degraded_defaults_empty():
    r = Result("m", "t", True)
    assert r.degraded == []


def test_result_degraded_normalizes_bare_string():
    r = Result("m", "t", True, degraded=["github:429"])
    assert r.degraded == [{"source": "unknown", "detail": "github:429"}]


def test_result_degraded_normalizes_dict():
    r = Result("m", "t", True, degraded=[{"source": "github", "detail": "429"}])
    assert r.degraded == [{"source": "github", "detail": "429"}]


def test_result_degraded_coerces_values():
    r = Result("m", "t", True, degraded=[{"source": 1, "detail": 2}])
    assert r.degraded == [{"source": "1", "detail": "2"}]


def test_result_degraded_drops_unknown_keys():
    r = Result("m", "t", True, degraded=[
        {"source": "s", "detail": "d", "extra": "x"},
    ])
    assert r.degraded == [{"source": "s", "detail": "d"}]


def test_result_degraded_fills_missing_keys():
    r = Result("m", "t", True, degraded=[{"source": "s"}])
    assert r.degraded == [{"source": "s", "detail": ""}]


# --- Cache: memory ---

def test_cache_memory_hit_and_miss():
    c = Cache(path=":memory:")
    try:
        assert c.get("k", ttl=60) is None
        c.put("k", Result("m", "t", True))
        got = c.get("k", ttl=60)
        assert got is not None
        assert got.module == "m"
        assert got.found is True
    finally:
        c.close()


def test_cache_memory_ttl_respected(monkeypatch):
    monkeypatch.setattr("nsoint.core._now", lambda: 1_000_000.0)
    c = Cache(path=":memory:")
    try:
        c.put("k", Result("m", "t", True))

        monkeypatch.setattr("nsoint.core._now", lambda: 1_000_030.0)
        hit = c.get("k", ttl=60)
        assert hit is not None
        assert hit.module == "m"

        monkeypatch.setattr("nsoint.core._now", lambda: 1_000_999.0)
        assert c.get("k", ttl=60) is None
    finally:
        c.close()


def test_cache_expiry(monkeypatch):
    monkeypatch.setattr("nsoint.core._now", lambda: 1_000_000.0)
    c = Cache(path=":memory:")
    try:
        c.put("k", Result("m", "t", True))
        monkeypatch.setattr("nsoint.core._now", lambda: 1_000_999.0)
        assert c.get("k", ttl=60) is None
    finally:
        c.close()


# --- Cache: disk ---

def test_cache_persists_across_instances(tmp_path):
    db = tmp_path / "cache.db"
    c1 = Cache(path=db)
    try:
        c1.put("k", Result("m", "persisted", True))
    finally:
        c1.close()
    c2 = Cache(path=db)
    try:
        got = c2.get("k", ttl=60)
        assert got is not None
        assert got.target == "persisted"
    finally:
        c2.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits not applicable")
def test_cache_directory_is_restricted(tmp_path):
    import stat

    db = tmp_path / "nested" / "cache.db"
    c = Cache(path=db)
    try:
        c.put("k", Result("m", "t", True))
        dir_mode = stat.S_IMODE(os.stat(db.parent).st_mode)
        file_mode = stat.S_IMODE(os.stat(db).st_mode)
        assert dir_mode == 0o700, f"expected 0o700, got {oct(dir_mode)}"
        assert file_mode == 0o600, f"expected 0o600, got {oct(file_mode)}"
    finally:
        c.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits not applicable")
def test_cache_tightens_existing_permissive_file(tmp_path):
    """
    Upgrade path: a pre-existing cache.db created with 0o644 by an earlier
    version must be tightened to 0o600 on next open.
    """
    import stat

    db = tmp_path / "cache.db"
    db.write_bytes(b"")
    os.chmod(db, 0o644)
    assert stat.S_IMODE(os.stat(db).st_mode) == 0o644

    c = Cache(path=db)
    try:
        file_mode = stat.S_IMODE(os.stat(db).st_mode)
        assert file_mode == 0o600, f"expected 0o600, got {oct(file_mode)}"
    finally:
        c.close()


def test_cache_falls_back_to_memory_when_disk_unavailable(tmp_path, monkeypatch):
    def boom(self, *args, **kwargs):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(Path, "mkdir", boom)

    db = tmp_path / "sub" / "cache.db"
    c = Cache(path=db)
    try:
        assert c.path == ":memory:"
        assert c._conn is not None
        c.put("k", Result("m", "t", True))
        assert c.get("k", ttl=60) is not None
    finally:
        c.close()


def test_cache_closes_failed_disk_connection(tmp_path, monkeypatch):
    """
    Regression: if the disk connection opens but schema execution fails,
    the connection must be closed before falling back to :memory:.
    """
    real_connect = sqlite3.connect
    wrappers: list = []

    class Wrap:
        def __init__(self, real):
            self._real = real
            self._is_disk = True
            self._schema_attempted = False
            self._closed = False
        def __getattr__(self, name):
            return getattr(self._real, name)
        def execute(self, sql, *args, **kwargs):
            if "CREATE TABLE" in sql and self._is_disk and not self._schema_attempted:
                self._schema_attempted = True
                raise sqlite3.OperationalError("simulated schema failure")
            return self._real.execute(sql, *args, **kwargs)
        def close(self):
            self._closed = True
            return self._real.close()

    def fake_connect(path, **kwargs):
        real = real_connect(path, **kwargs)
        if path == ":memory:":
            return real
        w = Wrap(real)
        wrappers.append(w)
        return w

    monkeypatch.setattr(sqlite3, "connect", fake_connect)

    db = tmp_path / "cache.db"
    c = Cache(path=db)
    try:
        assert c.path == ":memory:"
        assert wrappers, "Wrap was never created"
        assert all(w._closed for w in wrappers), "failed disk connection was not closed"
    finally:
        c.close()


def test_cache_put_swallows_serialization_errors(tmp_path):
    class Weird:
        pass

    db = tmp_path / "cache.db"
    c = Cache(path=db)
    try:
        bad = Result("m", "t", True, data={"x": Weird()})
        c.put("k", bad)
        assert c.get("k", ttl=60) is None
    finally:
        c.close()


def test_cache_disabled_short_circuits():
    c = Cache(path=":memory:", enabled=False)
    c.put("k", Result("m", "t", True))
    assert c.get("k", ttl=60) is None


def test_cache_set_enabled_toggles():
    c = Cache(path=":memory:")
    try:
        c.put("k", Result("m", "t", True))
        assert c.get("k", ttl=60) is not None
        c.set_enabled(False)
        assert c.get("k", ttl=60) is None
        c.set_enabled(True)
        assert c.get("k", ttl=60) is not None
    finally:
        c.close()


def test_cache_journal_mode_is_memory(tmp_path):
    """PRAGMA journal_mode=MEMORY means no cache.db-journal sidecar file."""
    db = tmp_path / "cache.db"
    c = Cache(path=db)
    try:
        mode = c._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "memory"
        c.put("k", Result("m", "t", True))
        sidecar = Path(str(db) + "-journal")
        assert not sidecar.exists()
    finally:
        c.close()


def test_cache_key_stable():
    assert cache_key("m", "abc") == cache_key("m", "abc")
    assert cache_key("m", "abc") != cache_key("m", "abd")


# --- HTTP ---

@pytest.mark.asyncio
async def test_safe_fetch_bad_host():
    async with make_session() as s:
        status, body = await safe_fetch(
            s, "http://192.0.2.1:1/",
            retries=0, backoff=0.01,
            timeout=aiohttp.ClientTimeout(total=1, connect=1),
        )
        assert status == 0


@pytest.mark.asyncio
async def test_safe_fetch_releases_semaphore_during_backoff(monkeypatch):
    from unittest.mock import patch
    from nsoint import core

    monkeypatch.setitem(core.HOST_LIMITS, "example.test", 1)

    class FakeResp:
        def __init__(self, status: int, body: str) -> None:
            self.status = status
            self._body = body

        async def text(self, errors: str = "ignore") -> str:
            return self._body

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeCtx:
        def __init__(self, status: int, body: str) -> None:
            self._resp = FakeResp(status, body)

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, *exc):
            return False

    def fake_request(self, method, url, **kwargs):
        return FakeCtx(500, "server error")

    async with make_session() as s:
        with patch("aiohttp.ClientSession.request", new=fake_request):
            await asyncio.wait_for(
                asyncio.gather(
                    safe_fetch(s, "http://example.test/a", retries=1, backoff=1.0),
                    safe_fetch(s, "http://example.test/b", retries=1, backoff=1.0),
                ),
                timeout=1.5,
            )
