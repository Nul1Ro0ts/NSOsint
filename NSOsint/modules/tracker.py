# --- nsoint/modules/tracker.py ---
"""Short-link tracker: mints a URL, logs hit IP + optional geo to stdout."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

import aiohttp

from ..core import Result, make_session, safe_fetch

log = logging.getLogger("nsoint.tracker")


class HitLog:
    """Per-run hit collection. Bound to the server instance, not module scope."""

    def __init__(self) -> None:
        self.hits: list[dict[str, Any]] = []

    def append(self, hit: dict[str, Any]) -> None:
        self.hits.append(hit)

    def __len__(self) -> int:
        return len(self.hits)


class _TrackerServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with a HitLog and proxy trust flag."""

    def __init__(self, server_address, RequestHandlerClass, *, trust_proxy: bool = False):  # noqa: N803
        super().__init__(server_address, RequestHandlerClass)
        self.hit_log = HitLog()
        self.trust_proxy = trust_proxy


class _Handler(BaseHTTPRequestHandler):
    server_version = "nsoint/1.2"

    def do_GET(self) -> None:  # noqa: N802
        if self.server.trust_proxy:  # type: ignore[attr-defined]
            ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
        else:
            ip = self.client_address[0]
        hit = {
            "ts": time.time(),
            "ip": ip,
            "ua": self.headers.get("User-Agent", ""),
            "referer": self.headers.get("Referer", ""),
            "path": self.path,
        }
        self.server.hit_log.append(hit)  # type: ignore[attr-defined]
        self.send_response(302)
        self.send_header("Location", "https://www.google.com")
        self.end_headers()

    def log_message(self, *_: Any) -> None:
        return


def _serve(host: str, port: int, *, trust_proxy: bool = False) -> _TrackerServer:
    srv = _TrackerServer((host, port), _Handler, trust_proxy=trust_proxy)
    srv.daemon_threads = True
    Thread(target=srv.serve_forever, daemon=True).start()
    return srv


async def _mint_short(url: str) -> str | None:
    async with make_session() as s:
        status, body = await safe_fetch(
            s, "https://tinyurl.com/api-create.php", params={"url": url}
        )
        text = body.strip()
        if status == 200 and text.startswith("http") and len(text) < 512:
            return text
    return None


async def _fetch_geo(session: aiohttp.ClientSession, ip: str) -> dict[str, Any] | None:
    from .ipinfo import scan_ip
    r = await scan_ip(session, ip)
    geo = r.data.get("geo")
    return geo if isinstance(geo, dict) else None


async def _enrichment_worker(
    session: aiohttp.ClientSession,
    queue: asyncio.Queue,
    stop: asyncio.Event,
) -> None:
    """
    Drains the queue and geo-enriches each hit in place.

    Exit policy: sentinel (None) on the queue ends the loop. The `stop`
    event is checked only when the queue is idle — so pending work is
    never abandoned on shutdown.
    """
    while True:
        try:
            hit = await asyncio.wait_for(queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            if stop.is_set():
                return
            continue
        if hit is None:
            return
        ip = hit.get("ip")
        if not ip:
            continue
        try:
            hit["geo"] = await _fetch_geo(session, ip)
        except Exception as exc:  # noqa: BLE001
            hit["geo"] = None
            hit["geo_error"] = type(exc).__name__


async def run_tracker(
    *,
    public_host: str,
    port: int = 8080,
    mint: bool = True,
    duration: int | None = None,
    enrich: bool = False,
    trust_proxy: bool = False,
) -> Result:
    """
    Starts a redirect server. Optionally mints a TinyURL. Blocks for
    `duration` seconds or until SIGINT. Prints hits live. On exit, prints
    the full hit log and returns a Result.

    Shutdown order: (1) stop accepting connections, (2) drain remaining
    hits, (3) enqueue the sentinel, (4) wait for the enrichment worker,
    (5) tear down the session.

    What shutdown() and server_close() guarantee:

      * `srv.shutdown()` blocks until the serve_forever loop exits, so no
        new connections are accepted after it returns.
      * `srv.server_close()` closes the listening socket.
      * Neither call joins handler threads. Because `daemon_threads=True`,
        a request thread that was already inside do_GET when shutdown()
        was called can still be running when server_close() returns and
        may append to hit_log after that point.

    The drain below catches every hit present in hit_log at the instant
    it starts. A hit that arrives *after* the drain's final `len()` check
    is missed. The residual window is narrow — bounded by OS thread
    scheduling latency between the drain loop's last check and the
    handler thread finishing its append, not by anything the tracker
    does. Closing that window fully would require tracking and joining
    handler threads, which ThreadingHTTPServer does not expose.
    """
    srv = _serve("0.0.0.0", port, trust_proxy=trust_proxy)
    hit_log = srv.hit_log

    base = f"http://{public_host}:{port}/"
    short = await _mint_short(base) if mint else None

    print(f"[tracker] listening on {base}", flush=True)
    if short:
        print(f"[tracker] short link: {short}", flush=True)
    else:
        print("[tracker] mint failed — use the raw listener URL", flush=True)
    if not trust_proxy:
        print("[tracker] X-Forwarded-For ignored — pass --trust-proxy if behind a proxy",
              flush=True)

    deadline = time.monotonic() + duration if duration else None
    stop = asyncio.Event()

    def _sigint(*_: Any) -> None:
        stop.set()

    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, _sigint)
    except (NotImplementedError, RuntimeError):
        pass

    enrichment_queue: asyncio.Queue = asyncio.Queue()
    worker_task: asyncio.Task | None = None
    enrich_session: aiohttp.ClientSession | None = None

    if enrich:
        enrich_session = make_session()
        worker_task = asyncio.create_task(
            _enrichment_worker(enrich_session, enrichment_queue, stop)
        )

    seen = 0
    try:
        while not stop.is_set():
            await asyncio.sleep(0.5)
            while seen < len(hit_log):
                hit = hit_log.hits[seen]
                if enrich and hit.get("ip"):
                    await enrichment_queue.put(hit)
                print(json.dumps(hit, default=str), flush=True)
                seen += 1
            if deadline and time.monotonic() > deadline:
                break
    except KeyboardInterrupt:
        pass
    finally:
        # 1. Stop accepting new connections first. Once shutdown() returns
        #    and server_close() completes, no new requests can enter do_GET.
        #    In-flight daemon threads may still append (see docstring).
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:  # noqa: BLE001
            pass

        # 2. Drain every hit present in hit_log now. In practice this
        #    catches everything, including a request that landed during
        #    shutdown() itself.
        while seen < len(hit_log):
            hit = hit_log.hits[seen]
            if enrich and hit.get("ip"):
                await enrichment_queue.put(hit)
            print(json.dumps(hit, default=str), flush=True)
            seen += 1

        # 3. Sentinel tells the worker to exit once the queue is empty.
        #    FIFO ordering guarantees every hit enqueued above is processed.
        if enrich:
            await enrichment_queue.put(None)
            if worker_task is not None:
                try:
                    await asyncio.wait_for(worker_task, timeout=5.0)
                except asyncio.TimeoutError:
                    worker_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await worker_task

        # 4. Signal the outer stop flag (no-op at this point, but clean).
        stop.set()

        # 5. Close the enrichment session.
        if enrich_session is not None:
            await enrich_session.close()

        # 6. Print the final log.
        print(f"[tracker] final hit log ({len(hit_log)} hits):", flush=True)
        print(json.dumps(hit_log.hits, indent=2, default=str), flush=True)

    return Result(
        module="tracker.shortlink",
        target=short or base,
        found=True,
        data={"hits": hit_log.hits, "short": short, "listener": base},
    )
