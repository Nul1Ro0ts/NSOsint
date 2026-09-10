# --- nsoint/modules/person.py ---
"""Real-name -> public web mentions + username candidates."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote_plus

import aiohttp

from ..core import Result, safe_fetch

try:
    from bs4 import BeautifulSoup
    try:
        import lxml  # noqa: F401
        _BS_PARSER = "lxml"
    except ImportError:
        _BS_PARSER = "html.parser"
except ImportError:
    BeautifulSoup = None  # type: ignore
    _BS_PARSER = "html.parser"

SEARCH_ENDPOINTS = [
    ("duckduckgo", "https://html.duckduckgo.com/html/?q={q}"),
    ("bing",       "https://www.bing.com/search?q={q}"),
]


async def _search(session: aiohttp.ClientSession, engine: str, url: str) -> list[dict[str, str]]:
    if BeautifulSoup is None:
        return []
    status, body = await safe_fetch(session, url)
    if status != 200:
        return []
    soup = BeautifulSoup(body, _BS_PARSER)
    out: list[dict[str, str]] = []
    if engine == "duckduckgo":
        for a in soup.select("a.result__a")[:15]:
            out.append({"title": a.get_text(strip=True), "url": a.get("href", "")})
    else:
        for li in soup.select("li.b_algo")[:15]:
            a = li.find("a")
            if a:
                out.append({"title": a.get_text(strip=True), "url": a.get("href", "")})
    return out


def _username_candidates(full_name: str) -> list[str]:
    parts = [p for p in re.split(r"[\s._-]+", full_name.strip().lower()) if p]
    if not parts:
        return []
    first, *rest = parts
    cands = {first, parts[-1]}
    if rest:
        cands.add(f"{first}{parts[-1]}")
        cands.add(f"{first}.{parts[-1]}")
        cands.add(f"{first}_{parts[-1]}")
        cands.add(f"{first[0]}{parts[-1]}")
    return sorted(c for c in cands if len(c) >= 3)


async def scan_name(session: aiohttp.ClientSession, full_name: str) -> Result:
    if BeautifulSoup is None:
        return Result("person.name", full_name, False, error="beautifulsoup_unavailable")

    quoted = quote_plus(f'"{full_name}"')
    tasks = [_search(session, engine, tmpl.format(q=quoted)) for engine, tmpl in SEARCH_ENDPOINTS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    hits: dict[str, list[dict[str, str]]] = {}
    degraded: list[dict[str, str]] = []
    for (engine, _), res in zip(SEARCH_ENDPOINTS, results):
        if isinstance(res, Exception):
            degraded.append({
                "source": engine,
                "detail": f"exception:{type(res).__name__}",
            })
            continue
        hits[engine] = res

    return Result(
        module="person.name",
        target=full_name,
        found=any(hits.values()),
        data={
            "web_mentions": hits,
            "username_candidates": _username_candidates(full_name),
        },
        degraded=degraded,
    )
