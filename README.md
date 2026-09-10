# NSOsint
An free modern Osint tool.
## Installation
git clone https://github.com/Nul1Ro0ts/NSOsint.git

cd NSOsint 

cd NSOsint # An folder inside the tool

python3 -m venv ns

source ns/bin/activate

pip install -r requirements.txt

## Usage
# NSOsint v1.2.7 — Start & Usage Reference
# Save as: NSOINT_USAGE.md  (or paste into any editor)

================================================================================
START IT
================================================================================

    nsoint --help

If `nsoint` is not on PATH:

    python -m nsoint --help

Smoke test:

    nsoint ip 8.8.8.8

Expected: one JSON object printed to stdout.

================================================================================
GLOBAL FLAGS
================================================================================
Placed BEFORE the subcommand.

    nsoint --help
    nsoint -h
    nsoint --version
    nsoint -v <command>
    nsoint --no-cache <command>
    nsoint --purge-cache <command>

================================================================================
1. USERNAME SWEEP
================================================================================

    nsoint username <handle>

    nsoint username torvalds
    nsoint username johndoe

================================================================================
2. EMAIL PRESENCE
================================================================================

    nsoint email <address>

    nsoint email jane@example.com
    nsoint email admin@github.com

================================================================================
3. IP INTELLIGENCE
================================================================================

    nsoint ip <address>

    nsoint ip 8.8.8.8
    nsoint ip 1.1.1.1
    nsoint ip 2606:4700:4700::1111

================================================================================
4. PHONE INTELLIGENCE
================================================================================

    nsoint phone "<number>" [--region <ISO2>]

    nsoint phone "+14155552671"
    nsoint phone "03001234567" --region PK
    nsoint phone "+442071838750" --region GB
    nsoint phone "+919876543210" --region IN

================================================================================
5. DISCORD PUBLIC SURFACE
================================================================================

    nsoint discord <handle>

    nsoint discord someuser
    nsoint discord @someuser

Note: Discord does not expose IPs. Public profile surface only.

================================================================================
6. REAL-NAME MENTIONS
================================================================================

    nsoint name "<full name>"

    nsoint name "John Doe"
    nsoint name "Ada Lovelace"

================================================================================
7. DOMAIN DNS + WHOIS
================================================================================

    nsoint domain <domain>

    nsoint domain example.com
    nsoint domain github.com

================================================================================
8. TRACK (redirect listener)
================================================================================

    nsoint track --host <public-host-or-ip> [OPTIONS]

Options:
    --host          required   Public hostname or IP to embed in the link
    --port          8080       Listen port
    --mint          on         Mint a TinyURL
    --no-mint       -          Skip TinyURL minting
    --duration      None       Seconds to listen (Ctrl+C exits early)
    --enrich        off        Geo-enrich each hit (burns ipapi.co quota)
    --no-enrich     on         Skip geo enrichment (default)
    --trust-proxy   off        Trust X-Forwarded-For (only behind your own proxy)

    nsoint track --host 203.0.113.10 --duration 60
    nsoint track --host mydomain.example --port 8080 --duration 300 --enrich
    nsoint track --host tracker.example.com --port 8080 --trust-proxy --duration 600
    nsoint track --host 203.0.113.10 --no-mint --duration 120
    nsoint track --host 203.0.113.10

================================================================================
9. DISPATCHER (all kinds)
================================================================================

    nsoint all <target> --kind <kind>

    nsoint all torvalds --kind username
    nsoint all jane@example.com --kind email
    nsoint all 8.8.8.8 --kind ip
    nsoint all "+14155552671" --kind phone
    nsoint all "John Doe" --kind name
    nsoint all example.com --kind domain

================================================================================
CACHE
================================================================================
Cached for 300 seconds at ~/.cache/nsoint/cache.db

    nsoint ip 8.8.8.8                # network fetch
    nsoint ip 8.8.8.8                # cache hit
    nsoint --no-cache ip 8.8.8.8     # skip cache this run
    nsoint --purge-cache ip 8.8.8.8  # wipe cache, then run

================================================================================
OUTPUT FORMAT
================================================================================
Every command prints one JSON object:

    {
      "module": "ip.info",
      "target": "8.8.8.8",
      "found": true,
      "data": { "...": "..." },
      "error": null,
      "degraded": []
    }

Pipe to jq:

    nsoint ip 8.8.8.8 | jq '.data.geo.country_name'
    nsoint username torvalds | jq '.data.matches'
    nsoint domain example.com | jq '.data.whois.registrar'

================================================================================
Credit: Nul1
================================================================================
