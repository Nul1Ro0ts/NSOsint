# --- nsoint/modules/dns_whois.py ---
"""Domain surface: DNS records + WHOIS. Single resolver, batched."""

from __future__ import annotations

import asyncio
from typing import Any

import dns.asyncresolver

from ..core import Result

RECORD_TYPES = ("A", "AAAA", "MX", "TXT", "NS", "CNAME", "SOA")

_RESOLVER: dns.asyncresolver.Resolver | None = None


def _resolver() -> dns.asyncresolver.Resolver:
    global _RESOLVER
    if _RESOLVER is None:
        _RESOLVER = dns.asyncresolver.Resolver()
        _RESOLVER.lifetime = 6
        _RESOLVER.timeout = 3
    return _RESOLVER


async def _records(domain: str, rtype: str) -> list[str]:
    try:
        ans = await _resolver().resolve(domain, rtype)
        return [r.to_text() for r in ans]
    except Exception:
        return []


async def _whois(domain: str) -> dict[str, Any]:
    def _run() -> dict[str, Any]:
        try:
            import whois as _w
            w = _w.whois(domain)
            return {
                "ok": True,
                "registrar": getattr(w, "registrar", None),
                "creation_date": getattr(w, "creation_date", None),
                "expiration_date": getattr(w, "expiration_date", None),
                "name_servers": getattr(w, "name_servers", None),
                "emails": getattr(w, "emails", None),
                "country": getattr(w, "country", None),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": type(exc).__name__}

    return await asyncio.to_thread(_run)


async def scan_domain(domain: str) -> Result:
    recs = await asyncio.gather(*(_records(domain, r) for r in RECORD_TYPES))
    data: dict[str, Any] = {rtype: recs[i] for i, rtype in enumerate(RECORD_TYPES)}

    whois_data = await _whois(domain)
    data["whois"] = whois_data
    degraded: list[dict[str, str]] = []
    if not whois_data.get("ok"):
        degraded.append({
            "source": "whois",
            "detail": str(whois_data.get("error", "unknown")),
        })

    return Result("domain.info", domain, True, data=data, degraded=degraded)
