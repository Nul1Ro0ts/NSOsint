# --- nsoint/modules/social.py ---
"""Username / email sweep across social platforms."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import aiohttp

from ..core import Result, safe_fetch

PLATFORMS: list[tuple[str, str]] = [
    ("github",        "https://github.com/{u}"),
    ("gitlab",        "https://gitlab.com/{u}"),
    ("bluesky",       "https://bsky.app/profile/{u}.bsky.social"),
    ("bluesky_custom","https://bsky.app/profile/{u}"),
    ("instagram",     "https://www.instagram.com/{u}/"),
    ("reddit",        "https://www.reddit.com/user/{u}/about.json"),
    ("linkedin",      "https://www.linkedin.com/in/{u}"),
    ("pinterest",     "https://www.pinterest.com/{u}/"),
    ("tiktok",        "https://www.tiktok.com/@{u}"),
    ("youtube",       "https://www.youtube.com/@{u}"),
    ("twitch",        "https://www.twitch.tv/{u}"),
    ("medium",        "https://medium.com/@{u}"),
    ("devto",         "https://dev.to/{u}"),
    ("keybase",       "https://keybase.io/{u}"),
    ("hackernews",    "https://news.ycombinator.com/user?id={u}"),
    ("steam",         "https://steamcommunity.com/id/{u}"),
    ("spotify",       "https://open.spotify.com/user/{u}"),
    ("telegram",      "https://t.me/{u}"),
    ("facebook",      "https://www.facebook.com/{u}"),
]

_BOT_MARKERS = (
    "captcha",
    "are you a robot",
    "are you human",
    "attention required",
    "just a moment",
    "checking your browser",
    "cloudflare",
    "ddos protection",
    "access denied",
    "request blocked",
)

_MISS_MARKERS = {
    "github":         ["not found"],
    "gitlab":         ["page not found"],
    "hackernews":     ["no such user"],
    "keybase":        ["not found"],
    "medium":         ["page not found"],
    "bluesky":        ["profile not found", "not found"],
    "bluesky_custom": ["profile not found", "not found"],
}


def _is_hit(name: str, status: int, body: str) -> bool:
    if status != 200:
        return False
    low = body.lower()
    for marker in _BOT_MARKERS:
        if marker in low:
            return False
    for marker in _MISS_MARKERS.get(name, []):
        if marker in low:
            return False
    return True


async def _check(
    session: aiohttp.ClientSession, name: str, url: str
) -> tuple[str, bool, str, int]:
    status, body = await safe_fetch(session, url)
    if name == "reddit" and status == 200:
        try:
            data = json.loads(body)
            if data.get("error") == 404 or data.get("message") == "Not Found":
                return name, False, url, status
        except (ValueError, TypeError):
            pass
    return name, _is_hit(name, status, body), url, status


async def scan_username(session: aiohttp.ClientSession, username: str) -> Result:
    tasks = [_check(session, name, tmpl.format(u=username)) for name, tmpl in PLATFORMS]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    found: dict[str, Any] = {}
    degraded: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, Exception):
            degraded.append({"source": "platform", "detail": f"exception:{type(item).__name__}"})
            continue
        name, hit, url, status = item
        if hit:
            found[name] = url
        elif status not in (200, 404, 0):
            degraded.append({"source": name, "detail": str(status)})

    return Result(
        module="social.username",
        target=username,
        found=bool(found),
        data={"matches": found, "checked": len(PLATFORMS)},
        degraded=degraded,
    )


async def scan_email(session: aiohttp.ClientSession, email: str) -> Result:
    h = hashlib.md5(email.strip().lower().encode()).hexdigest()
    gravatar_url = f"https://secure.gravatar.com/avatar/{h}.json"

    found: dict[str, Any] = {}
    degraded: list[dict[str, str]] = []
    status, body = await safe_fetch(session, gravatar_url)
    if status == 200:
        try:
            found["gravatar"] = json.loads(body)
        except (ValueError, TypeError):
            found["gravatar"] = {"raw_status": status}
    elif status == 0:
        degraded.append({"source": "gravatar", "detail": "transport_failure"})

    local = email.split("@", 1)[0]
    uname_result = await scan_username(session, local)
    if uname_result.found:
        found["username_derived"] = uname_result.data["matches"]
    for d in uname_result.degraded:
        degraded.append({
            "source": f"username_derived.{d.get('source', 'unknown')}",
            "detail": d.get("detail", ""),
        })

    return Result(
        module="social.email",
        target=email,
        found=bool(found),
        data={"matches": found, "local_part_used": local},
        degraded=degraded,
    )
