# README.md

# NSOsint

Open-source OSINT toolkit. Async core. Per-host rate limiting. Persistent
on-disk cache. SSL verification ON by default.

**Repository:** https://github.com/Nul1Ro0ts/NSOsint

---

## Feature Matrix

| Feature                       | Status | Notes |
|-------------------------------|--------|-------|
| Username sweep                | OK     | 18 platforms; Bluesky checked with two handle forms |
| Email presence                | OK     | Gravatar + derived username. No HIBP (paid). No auth-gated APIs. |
| IP intel                      | OK     | ipapi.co → ipwho.is fallback, reverse DNS, WHOIS |
| TinyURL tracker               | OK     | Live hit log; geo-enrichment is opt-in (`--enrich`) |
| Phone intel                   | OK     | Full libphonenumber metadata |
| Basic OSINT bundle            | PARTIAL| No reverse image search, no metadata extractor, no subdomain brute-forcer |
| IP from Discord username      | NO     | Discord does not expose IPs. `discord` command resolves public surface only. |
| Real-name mentions            | PARTIAL| DDG + Bing scrape. Rate-limited under sustained use. |

---

## Installation

### From source

```bash
git clone https://github.com/Nul1Ro0ts/NSOsint.git
cd NSOsint
pip install -e .
Optional extras:

bash
pip install -e ".[fast]"   # aiodns + lxml
pip install -e ".[dev]"    # pytest + ruff
Requirements only
bash
pip install -r requirements.txt
python -m nsoint --help
Verify
bash
nsoint --version
# nsoint, version 1.2.7

nsoint --help

nsoint ip 8.8.8.8
If nsoint is not on PATH:

bash
python -m nsoint ip 8.8.8.8
Quick Start
bash
nsoint username torvalds
nsoint email jane@example.com
nsoint ip 8.8.8.8
nsoint phone "+14155552671" --region US
nsoint discord someuser
nsoint name "John Doe"
nsoint domain example.com
nsoint track --host 203.0.113.10 --duration 60
nsoint all 8.8.8.8 --kind ip
Commands
Global flags
Placed before the subcommand.

bash
nsoint --help
nsoint -h
nsoint --version
nsoint -v <command>              # debug logging
nsoint --no-cache <command>      # skip cache reads + writes for this run
nsoint --purge-cache <command>   # delete every cached entry, then run
username
bash
nsoint username <handle>
Sweeps GitHub, GitLab, Bluesky (two handle forms), Instagram, Reddit,
LinkedIn, Pinterest, TikTok, YouTube, Twitch, Medium, Dev.to, Keybase,
HackerNews, Steam, Spotify, Telegram, Facebook.

bash
nsoint username torvalds
nsoint username johndoe
email
bash
nsoint email <address>
Gravatar lookup (MD5 hash), plus a derived-username sweep on the local
part.

bash
nsoint email jane@example.com
nsoint email admin@github.com
ip
bash
nsoint ip <address>
Geo + ASN (ipapi.co, fallback ipwho.is), reverse DNS (PTR), WHOIS.

bash
nsoint ip 8.8.8.8
nsoint ip 1.1.1.1
nsoint ip 2606:4700:4700::1111
nsoint ip 2001:4860:4860::8888
phone
bash
nsoint phone "<number>" [--region <ISO2>]
Returns E.164, international format, country code, region, carrier,
location, timezones, line type, validity.

bash
nsoint phone "+14155552671"
nsoint phone "03001234567" --region PK
nsoint phone "+442071838750" --region GB
nsoint phone "+919876543210" --region IN
--region must be a 2-letter ISO code. Required for numbers without a
country prefix.

discord
bash
nsoint discord <handle>
Resolves the handle against public directories (Disboard, top.gg,
discord.id).

Discord does not expose IPs via any API. This command returns
public-profile surface only.

bash
nsoint discord someuser
nsoint discord @someuser
name
bash
nsoint name "<full name>"
Scrapes DuckDuckGo HTML + Bing for quoted-name hits, and generates
username candidates (firstlast, first.last, first_last, f+last).

bash
nsoint name "John Doe"
nsoint name "Ada Lovelace"
Rate-limit note: DDG and Bing will CAPTCHA-block sustained use. Failures
show up in the degraded list of the JSON output, not as silent misses.

domain
bash
nsoint domain <domain>
Queries A, AAAA, MX, TXT, NS, CNAME, SOA with one shared resolver, plus
WHOIS.

bash
nsoint domain example.com
nsoint domain github.com
nsoint domain cloudflare.com
track
bash
nsoint track --host <public> [OPTIONS]
Runs a local HTTP server, optionally mints a TinyURL pointing at it, and
logs every hit (IP, user agent, referer, path) to stdout as JSON lines.
On exit it prints the full hit log.

Options:

Flag	Default	Description
--host	required	Public hostname or IP to embed in the link
--port	8080	Listen port
--mint / --no-mint	--mint	Mint a TinyURL via tinyurl.com
--duration	None	Seconds to listen (Ctrl+C exits early)
--enrich / --no-enrich	--no-enrich	Geo-enrich each hit (burns ipapi.co quota)
--trust-proxy	off	Trust X-Forwarded-For. Enable only behind a reverse proxy you control
bash
nsoint track --host 203.0.113.10 --duration 60
nsoint track --host mydomain.example --port 8080 --duration 300 --enrich
nsoint track --host tracker.example.com --port 8080 --trust-proxy --duration 600
nsoint track --host 203.0.113.10 --no-mint --duration 120
nsoint track --host 203.0.113.10
all
bash
nsoint all <target> --kind <kind>
Single entry point with a --kind selector. Same output shape as the
individual commands.

bash
nsoint all torvalds --kind username
nsoint all jane@example.com --kind email
nsoint all 8.8.8.8 --kind ip
nsoint all "+14155552671" --kind phone
nsoint all "John Doe" --kind name
nsoint all example.com --kind domain
Output Format
Every command prints one JSON object:

json
{
  "module": "ip.info",
  "target": "8.8.8.8",
  "found": true,
  "data": { "...": "..." },
  "error": null,
  "degraded": []
}
Field	Meaning
module	Which handler ran
target	What you asked about
found	Whether anything useful came back
data	The payload (shape depends on the module)
error	Set only when the request could not be attempted
degraded	List of {"source": str, "detail": str} for partial failures
Pipe to jq:

bash
nsoint ip 8.8.8.8 | jq '.data.geo.country_name'
nsoint username torvalds | jq '.data.matches'
nsoint domain example.com | jq '.data.whois.registrar'
nsoint email jane@example.com | jq '.degraded'
Cache
Read-only commands cache for 300 seconds in a SQLite database at
~/.cache/nsoint/cache.db.

bash
nsoint ip 8.8.8.8                # network fetch
nsoint ip 8.8.8.8                # cache hit
nsoint --no-cache ip 8.8.8.8     # skip cache this run
nsoint --purge-cache ip 8.8.8.8  # wipe cache, then run
Permissions and durability:

Directory ~/.cache/nsoint/ → mode 0o700

Database file cache.db → mode 0o600, forced on every open

SQLite rollback journal runs in memory (PRAGMA journal_mode=MEMORY),
so there is no cache.db-journal sidecar and no uncommitted payload
on disk

Read-only filesystem: if the cache directory is not writable
(read-only $HOME, Lambda, Cloud Run, hardened containers), the cache
falls back to an in-process :memory: database and logs a warning.
import nsoint never raises on a hostile filesystem.

phone and track are not cached.

About the Tracker
The track command runs a local HTTP server that redirects visitors to
a target URL (Google by default) and logs request headers — IP, user
agent, referer — to stdout. This is the same primitive every URL
analytics tool uses.

Deploy it only against systems you are authorized to test, and only
against people who have consented to being redirected through it.

IP source and X-Forwarded-For
By default the tracker records self.client_address[0] — the real TCP
peer IP. A target cannot spoof this.

When the listener runs behind a reverse proxy (nginx, Cloudflare Tunnel,
ngrok, Caddy), the TCP peer is the proxy and the real client is only
visible in X-Forwarded-For. Pass --trust-proxy to trust that header.

Only enable --trust-proxy when every request reaches the listener
through a proxy you control. A directly-exposed listener with the flag
will log attacker-chosen IPs.

Shutdown semantics
On SIGINT the tracker stops accepting new connections first, then drains
hit_log, then waits for the enrichment worker, then prints the final
log.

srv.shutdown() blocks until the accept loop exits and
server_close() closes the listening socket, but neither joins handler
threads — ThreadingHTTPServer runs them as daemons. A request already
inside do_GET at the moment of shutdown can still append after the
drain starts, in which case it is missing from the enriched output. The
residual window is narrow — bounded by OS thread scheduling latency.

Repository Structure
text
NSOsint/
├── .gitignore
├── LICENSE
├── README.md
├── pyproject.toml
├── requirements.txt
├── nsoint/
│   ├── __init__.py          # Light package root — no CLI import
│   ├── __main__.py          # python -m nsoint entry point
│   ├── _version.py          # Single-line version string
│   ├── cli.py               # Click command group
│   ├── core.py              # Session, Result, safe_fetch, Cache
│   └── modules/
│       ├── __init__.py
│       ├── discord.py       # Public surface for a Discord handle
│       ├── dns_whois.py     # DNS + WHOIS
│       ├── ipinfo.py        # IP geo + rDNS + WHOIS
│       ├── person.py        # Real-name web mentions
│       ├── phone.py         # libphonenumber metadata
│       ├── social.py        # Username + email sweep
│       └── tracker.py       # Short-link redirect listener
└── tests/
    ├── __init__.py
    ├── test_core.py         # Result, Cache, safe_fetch
    ├── test_social.py       # _is_hit, scan_username
    └── test_tracker.py      # HitLog, _TrackerServer, enrichment worker
Development
bash
git clone https://github.com/Nul1Ro0ts/NSOsint.git
cd NSOsint
python -m venv ns
source ns/bin/activate          # Windows: ns\Scripts\activate
pip install -e ".[dev]"

pytest -q
ruff check nsoint/
ruff format nsoint/
Architecture notes
safe_fetch is the only network primitive. It never raises, returns
(status, body) where status == 0 means transport failure, and
releases the per-host semaphore before sleeping on backoff.

Result is the only response shape. degraded is a closed schema:
list[dict[str, str]], unknown keys dropped with a warning.

Cache holds one SQLite connection for the object's lifetime.
:memory: works because the connection is not recreated per call.

_host_sems is an OrderedDict keyed by (host, id(loop)) with LRU
eviction. Each entry holds a weakref to the loop that bound the
semaphore.

No module raises out of its public function. Every failure mode lands
in degraded or error.

Security Posture
SSL verification enabled by default.

Per-host semaphore with LRU eviction, host-specific limits where known.

Exponential backoff with jitter, semaphore released during sleep.

UA rotation per session.

SQLite TTL cache at ~/.cache/nsoint/cache.db, directory 0o700,
file 0o600 enforced on every open, journal in memory.

Cache falls back to :memory: if the disk is not writable.

No proxy support. Planned for v1.3.

Known Limitations
Discord does not expose IPs. No tool can retrieve them. The
discord command returns public profile surface only.

HIBP is paid. No email-breach lookup in this tool. Gravatar and
derived-username sweeps only.

DDG and Bing CAPTCHA sustained name scraping. Failures land in
degraded, not as silent misses.

Nitter is dead. The Twitter handle check was removed. Bluesky was
added to compensate.

Uniform rate limits for unknown hosts (PER_HOST_LIMIT = 4).
Known-host overrides exist in HOST_LIMITS. Tune per target as
needed.

No SOCKS proxy. make_session(verify_ssl=False) exists but is not
exposed as a CLI flag.

What's Not Here Yet
Proxy / Tor routing.

Structured JSON logging.

CI workflow.

Reverse image search.

Metadata extractor (EXIF, PDF, Office).

Subdomain brute-forcer.

Per-run Cache instance (module global CACHE is mutated by
--no-cache; v1.3 will thread a local cache through the call graph).

License
MIT.

Author
Nul1Ro0ts — https://github.com/Nul1Ro0ts
