# --- tests/test_tracker.py ---
import asyncio

import pytest

from nsoint.modules.tracker import HitLog, _Handler, _TrackerServer, _enrichment_worker


def test_hitlog_is_instance_scoped():
    a = HitLog()
    b = HitLog()
    a.append({"ip": "1.1.1.1"})
    assert len(a) == 1
    assert len(b) == 0


def test_server_initializes_hitlog():
    srv = _TrackerServer(("127.0.0.1", 0), _Handler)
    try:
        assert isinstance(srv.hit_log, HitLog)
        assert len(srv.hit_log) == 0
        assert srv.trust_proxy is False
    finally:
        srv.server_close()


def test_server_accepts_trust_proxy_flag():
    srv = _TrackerServer(("127.0.0.1", 0), _Handler, trust_proxy=True)
    try:
        assert srv.trust_proxy is True
    finally:
        srv.server_close()


@pytest.mark.asyncio
async def test_enrichment_worker_drains_before_sentinel(monkeypatch):
    processed: list[dict] = []

    async def fake_fetch_geo(session, ip):
        processed.append({"ip": ip})
        return {"country": "test", "ip": ip}

    monkeypatch.setattr("nsoint.modules.tracker._fetch_geo", fake_fetch_geo)

    queue: asyncio.Queue = asyncio.Queue()
    stop = asyncio.Event()

    hits = [{"ip": f"10.0.0.{i}"} for i in range(1, 4)]
    for h in hits:
        await queue.put(h)

    stop.set()
    await queue.put(None)

    await asyncio.wait_for(_enrichment_worker(None, queue, stop), timeout=5.0)

    assert len(processed) == 3
    for h in hits:
        assert h.get("geo", {}).get("country") == "test"
