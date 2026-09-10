# --- nsoint/modules/discord.py ---
"""
Discord handle -> public profile surface.

Discord does NOT expose user IPs via any API. This module resolves public
handles to their public surface only.
"""

from __future__ import annotations

from typing import Any

import aiohttp

from ..core import Result, safe_fetch


async def scan_discord(session: aiohttp.ClientSession, handle: str) -> Result:
    clean = handle.lstrip("@").lower()
    data: dict[str, Any] = {"handle": clean}
    degraded: list[dict[str, str]] = []

    for name, url, marker in (
        ("disboard",  f"https://disboard.org/search?keyword={clean}", clean),
        ("topgg",     f"https://top.gg/user/{clean}",                 clean),
        ("discordid", f"https://discord.id/?prefill={clean}",         "discord"),
    ):
        status, body = await safe_fetch(session, url)
        hit = status == 200 and marker in body.lower()
        data[name] = {"status": status, "hit": hit, "url": url}
        if status not in (200, 404, 0):
            degraded.append({"source": name, "detail": str(status)})

    data["_meta"] = {"note": "Discord does not expose IPs. Public surface only."}

    return Result(
        module="discord.handle",
        target=clean,
        found=any(
            v.get("hit") for v in data.values()
            if isinstance(v, dict) and "hit" in v
        ),
        data=data,
        degraded=degraded,
    )
