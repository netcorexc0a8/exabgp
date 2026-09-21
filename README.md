# ExaBGP + Python route fetcher lab

This lab fetches IPv4 CIDR lists from HTTP(S), validates them, assigns
BGP standard communities per source, merges duplicate prefixes, and
announces/withdraws them through ExaBGP.

## Architecture

raw URLs -> Python fetcher -> ExaBGP -> your BGP router

No router configuration is included.

## Defaults

- ExaBGP address: `192.168.80.10`
- ExaBGP AS: `65001`
- BGP peer: `192.168.80.1`
- BGP peer AS: `65000`
- IPv4 unicast
- refresh: 300 seconds
- aggregate limit: 10,000 prefixes

Edit `config/exabgp.conf` for the BGP peer and `config/sources.json`
for the sources/communities.

## Source types

Each source has a `type`:

### URL

```json
{
  "name": "github-list",
  "type": "url",
  "url": "https://raw.githubusercontent.com/ORG/REPO/main/routes.txt",
  "communities": ["65001:100", "no-export"]
}
```

### Local file

The compose file mounts `./lists` read-only as `/etc/exabgp/lists`.

```json
{
  "name": "local-list",
  "type": "file",
  "path": "/etc/exabgp/lists/local.txt",
  "communities": ["65001:200"]
}
```

The local file uses the same format as URL lists: one IPv4 CIDR per line,
blank lines and `#` comments are allowed.

### ASN

ASN sources use the RIPEstat `announced-prefixes` Data API. RIPE NCC documents
this endpoint as returning announced prefixes for a given ASN and supports
`min_peers_seeing` to exclude low-visibility announcements.

```json
{
  "name": "google",
  "type": "asn",
  "asn": 15169,
  "min_peers_seeing": 10,
  "max_prefixes": 5000,
  "communities": ["65001:300", "no-export"]
}
```

The RIPEstat response is normalized through the same CIDR validation and
prefix-length limits as URL/local sources.

The ASN source means **prefixes observed as announced by that ASN**, not
RIR-registered address space owned by the ASN. It is routing observation data
and can change over time.

You can configure several ASNs as separate sources, each with its own
community set.

Example:

```json
"sources": [
  {
    "name": "asn-15169",
    "type": "asn",
    "asn": 15169,
    "communities": ["65001:300", "no-export"]
  },
  {
    "name": "asn-13335",
    "type": "asn",
    "asn": 13335,
    "communities": ["65001:301"]
  }
]
```

For ASN sources, `min_peers_seeing` defaults to the global
`asn_min_peers_seeing` setting (10 in the example).

## Community model

Each source has a `communities` array:

```json
{
  "name": "malware",
  "url": "https://raw.githubusercontent.com/example/project/main/list.txt",
  "max_prefixes": 5000,
  "communities": [
    "65001:100",
    "no-export"
  ]
}
```

Supported standard communities in this lab:

- `ASN:value`, e.g. `65001:100`
- `internet`
- `no-export`
- `no-advertise`
- `no-export-subconfed`

If the same prefix occurs in multiple sources, communities are UNIONed.

Example:

source A:
`10.0.0.0/24 -> 65001:100`

source B:
`10.0.0.0/24 -> 65001:200 no-export`

The resulting announcement contains:

`65001:100 65001:200 no-export`

If a prefix's community set changes, the fetcher withdraws the old path
and re-announces it with the new attributes.

## Safety behavior

The fetcher intentionally fails closed:

- invalid CIDRs are ignored;
- IPv6 is ignored by default;
- prefix-length limits are enforced;
- per-source limits are enforced;
- aggregate prefix limit is enforced;
- an HTTP error does not withdraw a previously successful source;
- an empty source is treated as failed and does not withdraw its old state;
- if all sources fail, there is no state change.

This is conservative behavior. If you want "source disappeared => withdraw all
its routes", implement that as an explicit policy rather than treating every
HTTP error as an empty list.

## Important

`network_mode: host` is intentional. ExaBGP must be able to establish TCP/179
to your BGP router without Docker port/NAT complications.

Do not expose TCP/179 to untrusted networks. Use host firewalling and only allow
the intended BGP peer(s).

## Docker image

A ready-to-run Docker image is built automatically on every push to `main`
and on every tag. The image is published to the GitHub Container Registry
(GHCR).

### Prerequisites

Before pulling the image, create the required directories and configuration
files. The container mounts these paths at runtime:

```bash
mkdir -p config fetcher lists state
```

Create or edit the configuration files:

```bash
# Edit to match your BGP setup
# config/exabgp.conf - BGP peer, local AS, timers
# config/sources.json - sources, communities, settings
# fetcher/fetcher.py - the Python route fetcher
```

If you want to use local prefix lists, place them in `lists/`:

```bash
# Example: one IPv4 CIDR per line, blank lines and # comments allowed
echo "203.0.113.0/24" > lists/local.txt
```

The `state/` directory persists ExaBGP runtime state between restarts.

The image pre-creates the `run/` directory and named FIFO pipes
(`exabgp.in`, `exabgp.out`) required by ExaBGP's CLI mode. No action needed.

### Pull the latest image

```bash
docker pull ghcr.io/netcorexc0a8/exabgp:latest
```

### Run with docker compose

```bash
docker compose pull
docker compose up -d
docker compose logs -f
```

Override the image in `docker-compose.yml`:

```yaml
services:
  exabgp:
    image: ghcr.io/netcorexc0a8/exabgp:latest
    container_name: exabgp
    restart: unless-stopped
    network_mode: host
    environment:
      EXABGP_LOG_ALL: "true"
      PYTHONUNBUFFERED: "1"
    volumes:
      - ./config/exabgp.conf:/etc/exabgp/exabgp.conf:ro
      - ./config/sources.json:/etc/exabgp/sources.json:ro
      - ./fetcher/fetcher.py:/opt/fetcher/fetcher.py:ro
      - ./lists:/etc/exabgp/lists:ro
      - ./state:/var/lib/exabgp
    command: ["exabgp", "/etc/exabgp/exabgp.conf"]
```

Or pass the image at the command line without editing the file:

```bash
docker compose up -d --build
```

To use a specific tag, replace `latest` with the desired tag (for example
`v1.0.0` or `sha-a1b2c3d`).

### Run with docker run

```bash
docker run -d \
  --name exabgp \
  --network host \
  -v "$(pwd)/config/exabgp.conf:/etc/exabgp/exabgp.conf:ro" \
  -v "$(pwd)/config/sources.json:/etc/exabgp/sources.json:ro" \
  -v "$(pwd)/fetcher/fetcher.py:/opt/fetcher/fetcher.py:ro" \
  -v "$(pwd)/lists:/etc/exabgp/lists:ro" \
  -v "$(pwd)/state:/var/lib/exabgp" \
  ghcr.io/netcorexc0a8/exabgp:latest
```

### Build workflow

The build is defined in `.github/workflows/build-image.yml`. It triggers on:

- every push to `main`
- every tag matching `v*`
- manual trigger via the Actions UI

The workflow builds the image with Docker Buildx, pushes it to GHCR, and
tags it as:

- `latest` — on pushes to `main`
- `sha-<short-sha>` — on every push
- the tag name — on tag pushes (e.g. `v1.0.0`)

The workflow uses the default `GITHUB_TOKEN` secret, so no extra
configuration is required. If you want to use the image from a private
repository, make sure the `packages: write` permission is granted (it is
set in the workflow file).

## Version pin

The Dockerfile pins ExaBGP to `5.0.3` for reproducibility. Change
`EXABGP_VERSION` after testing a newer release.