# --- nsoint/modules/ipinfo.py ---
"""IP intelligence: geo, ASN, reverse DNS, WHOIS."""

from __future__ import annotations

import asyncio
import ipaddress
import json
from typing import Any

import aiohttp
import dns.asyncresolver
import dns.reversename

from ..core import Result, safe_fetch

PRIMARY = "https://ipapi.co/{ip}/json/"
FALLBACK = "https://ipwho.is/{ip}"


async def _reverse_dns(ip: str) -> str | None:
    try:
        rev = dns.reversename.from_address(ip)
        ans = await dns.asyncresolver.resolve(rev, "PTR", lifetime=5)
        return str(ans[0]).rstrip(".")
    except Exception:
        return None


async def _whois(ip: str) -> dict[str, Any]:
    def _run() -> dict[str, Any]:
        try:
            import whois as _w
            w = _w.whois(ip)
            return {
                "ok": True,
                "org": getattr(w, "org", None),
                "netname": getattr(w, "netname", None),
                "country": getattr(w, "country", None),
                "cidr": getattr(w, "cidr", None),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": type(exc).__name__}

    return await asyncio.to_thread(_run)


async def scan_ip(session: aiohttp.ClientSession, ip: str) -> Result:
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return Result("ip.info", ip, False, error="invalid_ip")

    data: dict[str, Any] = {"ip": ip}
    degraded: list[dict[str, str]] = []

    status, body = await safe_fetch(session, PRIMARY.format(ip=ip))
    if status == 200:
        try:
            data["geo"] = json.loads(body)
        except (ValueError, TypeError):
            data["geo"] = {"raw_status": status}
            degraded.append({"source": "geo.primary", "detail": "parse_failure"})
    else:
        if status not in (404,):
            degraded.append({"source": "geo.primary", "detail": str(status)})
        status, body = await safe_fetch(session, FALLBACK.format(ip=ip))
        try:
            data["geo"] = json.loads(body) if status == 200 else {"status": status}
        except (ValueError, TypeError):
            data["geo"] = {"status": status}
        if status != 200:
            degraded.append({"source": "geo.fallback", "detail": str(status)})

    data["reverse_dns"] = await _reverse_dns(ip)

    whois_data = await _whois(ip)
    data["whois"] = whois_data
    if not whois_data.get("ok"):
        degraded.append({
            "source": "whois",
            "detail": str(whois_data.get("error", "unknown")),
        })

    return Result("ip.info", ip, True, data=data, degraded=degraded)
