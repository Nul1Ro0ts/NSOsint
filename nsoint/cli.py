"""NSOsint command-line interface."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import click
from rich.console import Console

from ._version import __version__
from .core import CACHE, Result, cache_key, make_session
from .modules.discord import scan_discord
from .modules.dns_whois import scan_domain
from .modules.ipinfo import scan_ip
from .modules.person import scan_name
from .modules.phone import scan_phone
from .modules.social import scan_email, scan_username
from .modules.tracker import run_tracker

console = Console()

DEFAULT_TTL = 300


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _emit(result: Result) -> None:
    console.print_json(result.to_json())


def _run_cached(
    module: str,
    target: str,
    factory: Callable[[], Awaitable[Result]],
    ttl: int = DEFAULT_TTL,
) -> None:
    key = cache_key(module, target)
    hit = CACHE.get(key, ttl)
    if hit is not None:
        console.print(f"[dim]cache hit: {module}::{target}[/dim]")
        _emit(hit)
        return
    result = asyncio.run(factory())
    CACHE.put(key, result)
    _emit(result)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.option("--no-cache", "no_cache", is_flag=True,
              help="Skip cache reads and writes for this run. Does not clear the cache.")
@click.option("--purge-cache", "purge_cache", is_flag=True,
              help="Delete every cached entry before the run, then proceed normally.")
@click.version_option(__version__, prog_name="nsoint")
def cli(verbose: bool, no_cache: bool, purge_cache: bool) -> None:
    """NSOsint - open-source OSINT toolkit."""
    _setup_logging(verbose)
    if purge_cache:
        CACHE.clear()
        console.print("[dim]cache purged[/dim]")
    if no_cache:
        CACHE.set_enabled(False)


@cli.command("username")
@click.argument("username")
def cmd_username(username: str) -> None:
    """Sweep social platforms for a username."""

    async def make() -> Result:
        async with make_session() as s:
            return await scan_username(s, username)

    _run_cached("social.username", username, make)


@cli.command("email")
@click.argument("email")
def cmd_email(email: str) -> None:
    """Check public presence for an email address (Gravatar + derived username)."""

    async def make() -> Result:
        async with make_session() as s:
            return await scan_email(s, email)

    _run_cached("social.email", email, make)


@cli.command("ip")
@click.argument("ip")
def cmd_ip(ip: str) -> None:
    """Geo, ASN, reverse DNS, and WHOIS for an IP."""

    async def make() -> Result:
        async with make_session() as s:
            return await scan_ip(s, ip)

    _run_cached("ip.info", ip, make)


@cli.command("phone")
@click.argument("number")
@click.option("--region", default=None, help="ISO region hint, e.g. US, GB, PK.")
def cmd_phone(number: str, region: str | None) -> None:
    """Carrier, region, and line type for a phone number."""
    if region and (len(region) != 2 or not region.isalpha()):
        raise click.BadParameter("region must be a 2-letter ISO code, e.g. US, GB.")
    result = scan_phone(number, region.upper() if region else None)
    _emit(result)


@cli.command("discord")
@click.argument("handle")
def cmd_discord(handle: str) -> None:
    """Public surface for a Discord handle. Discord does not expose IPs."""

    async def make() -> Result:
        async with make_session() as s:
            return await scan_discord(s, handle)

    _run_cached("discord.handle", handle.lstrip("@").lower(), make)


@cli.command("name")
@click.argument("full_name")
def cmd_name(full_name: str) -> None:
    """Web mentions and username candidates for a real name."""

    async def make() -> Result:
        async with make_session() as s:
            return await scan_name(s, full_name)

    _run_cached("person.name", full_name, make)


@cli.command("domain")
@click.argument("domain")
def cmd_domain(domain: str) -> None:
    """DNS records and WHOIS for a domain."""

    async def make() -> Result:
        return await scan_domain(domain)

    _run_cached("domain.info", domain, make)


@cli.command("track")
@click.option("--host", required=True, help="Public hostname or IP for the link.")
@click.option("--port", default=8080, show_default=True, type=int)
@click.option("--mint/--no-mint", default=True, help="Mint a TinyURL.")
@click.option("--duration", default=None, type=int, help="Seconds to listen.")
@click.option("--enrich/--no-enrich", default=False,
              help="Geo-enrich each hit (opt-in; burns ipapi.co quota).")
@click.option("--trust-proxy", is_flag=True, default=False,
              help="Trust X-Forwarded-For. Only enable when behind a reverse proxy "
                   "you control. Off by default — a directly-exposed listener records "
                   "the real peer IP.")
def cmd_track(host: str, port: int, mint: bool, duration: int | None,
              enrich: bool, trust_proxy: bool) -> None:
    """Spin up a redirect listener and log every hit."""
    try:
        asyncio.run(run_tracker(
            public_host=host,
            port=port,
            mint=mint,
            duration=duration,
            enrich=enrich,
            trust_proxy=trust_proxy,
        ))
    except OSError as exc:
        raise click.ClickException(f"cannot bind {host}:{port} — {exc}") from exc


async def _dispatch_all(session, kind: str, target: str) -> Result:
    if kind == "phone":
        return scan_phone(target, None)
    if kind == "domain":
        return await scan_domain(target)
    table = {
        "username": scan_username,
        "email":    scan_email,
        "ip":       scan_ip,
        "name":     scan_name,
    }
    return await table[kind](session, target)


@cli.command("all")
@click.argument("target")
@click.option("--kind", type=click.Choice(
    ["username", "email", "ip", "phone", "name", "domain"]), required=True)
def cmd_all(target: str, kind: str) -> None:
    """Run the module for a target kind and print structured JSON."""

    async def make() -> Result:
        async with make_session() as s:
            return await _dispatch_all(s, kind, target)

    _run_cached(f"all.{kind}", target, make)


if __name__ == "__main__":
    cli()
