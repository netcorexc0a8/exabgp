#!/usr/bin/env python3

import ipaddress
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Set, FrozenSet


CONFIG_FILE = "/etc/exabgp/sources.json"


def log(message: str) -> None:
    print(f"[fetcher] {message}", file=sys.stderr, flush=True)


def load_config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_community(value: str) -> str:
    """
    Accept:
      - standard well-known communities: no-export, no-advertise,
        no-export-subconfed, internet
      - standard numeric community: ASN:value, e.g. 65001:100

    This intentionally does not accept arbitrary extended/large
    communities. Add explicit support only if needed.
    """
    value = value.strip()

    well_known = {
        "internet",
        "no-export",
        "no-advertise",
        "no-export-subconfed",
    }
    if value in well_known:
        return value

    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid standard community: {value!r}")

    asn, number = parts
    if not (asn.isdigit() and number.isdigit()):
        raise ValueError(f"invalid standard community: {value!r}")

    asn_i = int(asn)
    number_i = int(number)

    if not (0 <= asn_i <= 65535):
        raise ValueError(f"ASN out of range in community: {value!r}")
    if not (0 <= number_i <= 65535):
        raise ValueError(f"value out of range in community: {value!r}")

    return f"{asn_i}:{number_i}"


def load_sources(config: dict) -> list[dict]:
    sources = config.get("sources", [])
    if not sources:
        raise ValueError("no sources configured")

    for source in sources:
        if not source.get("name"):
            raise ValueError("source without name")
        source_type = source.get("type", "url").lower()

        if source_type == "url" and not source.get("url"):
            raise ValueError(f"source {source.get('name')!r} has no url")
        if source_type == "file" and not source.get("path"):
            raise ValueError(f"source {source.get('name')!r} has no path")
        if source_type == "asn":
            asn = source.get("asn")
            if not isinstance(asn, int) or asn <= 0:
                raise ValueError(
                    f"source {source.get('name')!r} has invalid asn"
                )
        if source_type not in {"url", "file", "asn"}:
            raise ValueError(
                f"source {source.get('name')!r} has unsupported type "
                f"{source_type!r}"
            )

        communities = source.get("communities", [])
        source["communities"] = [
            validate_community(c) for c in communities
        ]

    return sources


def http_get(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "exabgp-github-fetcher/1.1",
            "Accept": "application/json,text/plain,*/*;q=0.8",
        },
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(
                f"HTTP status {response.status} for {url}"
            )
        return response.read()


def download(url: str, timeout: int) -> str:
    return http_get(url, timeout).decode(
        "utf-8",
        errors="replace",
    )


def load_local_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def fetch_asn(asn: int, timeout: int, min_peers_seeing: int = 10) -> Set[str]:
    """
    Get prefixes currently announced by an ASN using RIPEstat's
    announced-prefixes Data API.

    RIPEstat documents this endpoint as returning all announced
    prefixes for an ASN. min_peers_seeing can be used to exclude
    low-visibility/localized announcements.
    """
    if not isinstance(asn, int) or asn <= 0:
        raise ValueError(f"invalid ASN: {asn!r}")

    query = urllib.parse.urlencode({
        "resource": f"AS{asn}",
        "min_peers_seeing": int(min_peers_seeing),
    })

    url = (
        "https://stat.ripe.net/data/"
        f"announced-prefixes/data.json?{query}"
    )

    log(f"download ASN AS{asn} via RIPEstat")

    raw = http_get(url, timeout)
    payload = json.loads(raw.decode("utf-8"))

    try:
        records = payload["data"]["prefixes"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            f"unexpected RIPEstat response for AS{asn}"
        ) from exc

    result = set()

    for item in records:
        prefix = item.get("prefix") if isinstance(item, dict) else None
        if prefix:
            result.add(prefix)

    return result

def parse_prefixes(
    text: str,
    settings: dict,
) -> Set[str]:
    result: Set[str] = set()

    min_len = int(settings.get("min_prefix_length", 0))
    max_len = int(settings.get("max_prefix_length", 32))
    ipv4_only = bool(settings.get("ipv4_only", True))

    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if "#" in line:
            line = line.split("#", 1)[0].strip()

        try:
            network = ipaddress.ip_network(line, strict=False)
        except ValueError:
            log(
                f"invalid prefix ignored: {line!r} "
                f"(line {line_number})"
            )
            continue

        if ipv4_only and network.version != 4:
            log(f"IPv6 ignored: {network}")
            continue

        if not (min_len <= network.prefixlen <= max_len):
            log(
                f"prefix-length rejected: {network} "
                f"(line {line_number})"
            )
            continue

        result.add(str(network))

    return result


def fetch_source(
    source: dict,
    settings: dict,
) -> Set[str] | None:
    name = source["name"]
    source_type = source.get("type", "url").lower()
    timeout = int(settings.get("download_timeout_seconds", 30))

    log(f"fetch source={name} type={source_type}")

    try:
        if source_type == "url":
            url = source["url"]
            log(f"download {name}: {url}")
            text = download(url, timeout)
            prefixes = parse_prefixes(text, settings)

        elif source_type == "file":
            path = source["path"]
            log(f"read local file {name}: {path}")
            text = load_local_file(path)
            prefixes = parse_prefixes(text, settings)

        elif source_type == "asn":
            asn = int(source["asn"])
            min_peers = int(
                source.get(
                    "min_peers_seeing",
                    settings.get("asn_min_peers_seeing", 10),
                )
            )
            raw_prefixes = fetch_asn(
                asn,
                timeout=timeout,
                min_peers_seeing=min_peers,
            )
            # Apply exactly the same prefix validation to ASN results.
            prefixes = parse_prefixes(
                "\n".join(sorted(raw_prefixes)),
                settings,
            )

        else:
            raise ValueError(
                f"unsupported source type: {source_type!r}"
            )

    except Exception as exc:
        log(
            f"ERROR source={name}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None

    limit = int(
        source.get(
            "max_prefixes",
            settings["max_total_prefixes"],
        )
    )

    if not prefixes:
        log(
            f"ERROR source={name}: zero valid prefixes; "
            "keeping previous state"
        )
        return None

    if len(prefixes) > limit:
        log(
            f"ERROR source={name}: {len(prefixes)} prefixes "
            f"exceeds limit {limit}; keeping previous state"
        )
        return None

    log(f"source={name}: {len(prefixes)} valid prefixes")
    return prefixes

def build_desired_routes(
    source_states: Dict[str, Set[str]],
    sources: list[dict],
) -> Dict[str, FrozenSet[str]]:
    """
    Merge source results.

    If the same prefix appears in several sources, its communities
    are UNIONed. Example:

      source A -> 10.0.0.0/24 -> 65001:100
      source B -> 10.0.0.0/24 -> 65001:200 no-export

    Result:

      10.0.0.0/24 -> {65001:100, 65001:200, no-export}
    """
    result: Dict[str, Set[str]] = {}

    for source in sources:
        name = source["name"]
        prefixes = source_states.get(name, set())

        for prefix in prefixes:
            result.setdefault(prefix, set()).update(
                source["communities"]
            )

    return {
        prefix: frozenset(communities)
        for prefix, communities in result.items()
    }


def emit_announce(prefix: str, communities: FrozenSet[str]) -> None:
    parts = [
        "announce",
        "route",
        prefix,
        "next-hop",
        "self",
    ]

    if communities:
        parts.extend(
            ["community", "["]
        )
        parts.extend(sorted(communities))
        parts.append("]")

    print(" ".join(parts), flush=True)


def emit_withdraw(prefix: str) -> None:
    print(
        f"withdraw route {prefix}",
        flush=True,
    )


def reconcile(
    current: Dict[str, FrozenSet[str]],
    desired: Dict[str, FrozenSet[str]],
) -> Dict[str, FrozenSet[str]]:
    """
    A route whose community set changes is withdrawn and re-announced.
    This is deliberate: the BGP path attributes need to be replaced.
    """
    old_keys = set(current)
    new_keys = set(desired)

    added = new_keys - old_keys
    removed = old_keys - new_keys
    changed = {
        prefix
        for prefix in old_keys & new_keys
        if current[prefix] != desired[prefix]
    }

    for prefix in sorted(removed | changed):
        log(f"WITHDRAW {prefix}")
        emit_withdraw(prefix)

    for prefix in sorted(added | changed):
        communities = desired[prefix]
        community_text = (
            ", ".join(sorted(communities))
            if communities
            else "-"
        )
        log(
            f"ANNOUNCE {prefix} "
            f"communities={community_text}"
        )
        emit_announce(prefix, communities)

    if added or removed or changed:
        log(
            f"reconcile: +{len(added)} "
            f"-{len(removed)} "
            f"~{len(changed)} "
            f"total={len(desired)}"
        )
    else:
        log(f"reconcile: no changes total={len(desired)}")

    return desired


def main() -> None:
    log("starting")

    current: Dict[str, FrozenSet[str]] = {}
    source_states: Dict[str, Set[str]] = {}

    first_success = False

    while True:
        try:
            config = load_config()
            settings = config["settings"]
            sources = load_sources(config)

            successful_sources = 0

            for source in sources:
                name = source["name"]
                prefixes = fetch_source(source, settings)

                if prefixes is not None:
                    source_states[name] = prefixes
                    successful_sources += 1

            if successful_sources == 0:
                raise RuntimeError(
                    "all sources failed; no state change"
                )

            desired = build_desired_routes(
                source_states,
                sources,
            )

            max_total = int(
                settings["max_total_prefixes"]
            )

            if len(desired) > max_total:
                raise RuntimeError(
                    f"aggregate has {len(desired)} prefixes, "
                    f"limit is {max_total}; no state change"
                )

            current = reconcile(current, desired)
            first_success = True

        except Exception as exc:
            log(
                f"ERROR refresh failed: "
                f"{type(exc).__name__}: {exc}"
            )

            if not first_success:
                log(
                    "No routes announced yet; "
                    "waiting for a successful refresh"
                )

        try:
            refresh = int(
                config["settings"].get(
                    "refresh_seconds",
                    300,
                )
            )
        except Exception:
            refresh = 300

        time.sleep(max(5, refresh))


if __name__ == "__main__":
    main()
