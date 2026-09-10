# README.md

## NSOsint v1.2.7

Open-source OSINT toolkit. Async core. Per-host rate limiting. Persistent
on-disk cache. SSL verification ON by default.

## Install

    pip install -e .
    # optional fast-path extras:
    pip install -e ".[fast]"

## Commands

    nsoint username <handle>
    nsoint email <address>
    nsoint ip <address>
    nsoint phone "<number>" --region US
    nsoint discord <handle>
    nsoint name "<full name>"
    nsoint domain <domain>
    nsoint track --host <public> --port 8080 --duration 300
    nsoint all <target> --kind <username|email|ip|phone|name|domain>

Read-only commands are cached for 300 seconds in a SQLite database at
`~/.cache/nsoint/cache.db`. The cache survives process restarts. The
directory is `0o700`, the file is forced to `0o600` on every open (fresh
install or upgrade), and the SQLite rollback journal runs in memory
(`PRAGMA journal_mode=MEMORY`) so there is no `-journal` sidecar. If the
directory is not writable, the cache falls back to `:memory:` and logs a
warning — `import nsoint` never raises on a hostile filesystem.

Two global flags:

    --no-cache      Skip cache reads AND writes for this run. Does not clear.
    --purge-cache   Delete every cached entry, then proceed normally.

## Feature Matrix (honest)

| Feature                       | Status | Notes |
|-------------------------------|--------|-------|
| Username sweep                | OK     | 19 platform checks (18 platforms; bluesky checked with two handle forms) |
| Email presence                | OK     | Gravatar + derived username. No HIBP (paid). No auth-gated APIs. |
| IP intel                      | OK     | ipapi.co -> ipwho.is fallback + rDNS + WHOIS |
| TinyURL tracker               | OK     | Live hit log. Geo-enrichment is opt-in (`--enrich`), off by default. |
| Phone intel                   | OK     | Full libphonenumber metadata |
| Basic OSINT bundle            | PARTIAL| No reverse image search, no metadata extractor, no subdomain brute-forcer. |
| IP from Discord username      | NO     | Discord does not expose IPs. `discord` command resolves public surface only. |
| Real-name mentions            | PARTIAL| DDG + Bing scrape. Rate-limited under sustained use; degraded list will show it. |

## About the tracker

The `track` command runs a local HTTP server that redirects visitors to
a target URL (Google by default) and logs the request headers — IP, user
agent, referer — to stdout. This is the same primitive every URL analytics
tool uses. Deploy it only against systems you are authorized to test, and
only against people who have consented to being redirected through it.

### IP source and X-Forwarded-For

By default the tracker records `self.client_address[0]` — the real TCP
peer IP. A target cannot spoof this.

When the listener runs behind a reverse proxy (nginx, Cloudflare Tunnel,
ngrok, Caddy), the TCP peer is the proxy and the real client is only
visible in `X-Forwarded-For`. Pass `--trust-proxy` to trust that header.

Only enable `--trust-proxy` when every request reaches the listener through
a proxy you control. If the port is directly reachable, a target can send
`X-Forwarded-For: 1.2.3.4` and forge the logged IP.

### Shutdown semantics

On SIGINT the tracker stops accepting new connections first, then drains
`hit_log`, then waits for the enrichment worker, then prints the final
log. `shutdown()` blocks until the accept loop exits and `server_close()`
closes the listening socket, but neither joins handler threads —
`ThreadingHTTPServer` runs them as daemons. A request already inside
`do_GET` at the moment of shutdown can still append after the drain
starts, in which case it is missing from the enriched output. The
residual window is narrow — bounded by OS thread scheduling latency, not
by anything the tracker does. See the `run_tracker` docstring for the
full sequence.

## What Changed in v1.2.7

- **`run_tracker` docstring: "sub-microsecond" replaced with a precise
  description.** The previous text overstated the tightness of the
  residual window. The drain loop's final `len()` check and a handler
  thread's `hit_log.append` are separated by OS thread scheduling
  latency, not by anything sub-microsecond. The docstring now says
  "narrow — bounded by OS thread scheduling latency" and explains why
  the window cannot be closed without thread tracking that
  `ThreadingHTTPServer` does not expose. No code change.

## What Changed in v1.2.6

(prior release — see git log)

## Security Posture

- SSL verification enabled by default.
- Per-host semaphore with LRU eviction, host-specific limits where known.
- Exponential backoff with jitter, semaphore released during sleep.
- UA rotation per session.
- SQLite TTL cache at `~/.cache/nsoint/cache.db`, dir `0o700`, file `0o600`
  enforced on every open, journal in memory. Falls back to `:memory:` if
  the disk is not writable.
- No proxy support. Planned for v1.3.

## What's Not Here Yet

- Proxy / Tor routing.
- Structured JSON logging.
- CI workflow.
- Reverse image search, metadata extractor, subdomain brute-forcer.
- Per-run `Cache` instance (module global `CACHE` is mutated by `--no-cache`;
  v1.3 will thread a local cache through the call graph).

## License

MIT.
