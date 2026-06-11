"""SSRF-guard voor server-side fetches van door gebruikers/feeds aangeleverde URLs.

`assert_public_url` resolvet de hostname en weigert private/loopback/link-local/
reserved adressen (cloud-metadata 169.254.169.254, interne Docker-services,
localhost, etc.). `safe_get` volgt redirects handmatig en valideert élke hop —
anders kan een publieke URL alsnog 302'en naar een intern adres.

Gebruik dit alléén voor untrusted bron-URLs (inbox-fetch, article-extractie,
og:image-scrape, feed-polling). NIET voor operator-geconfigureerde interne
integraties (Obsidian/Vikunja/LiteLLM) — die wijzen bewust naar private hosts.
"""
from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urljoin, urlparse

import httpx


class UnsafeURLError(Exception):
    """Geheven wanneer een URL naar een niet-publiek adres (dreigt te) wijzen."""


_REDIRECT_CODES = {301, 302, 303, 307, 308}


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # onparsebaar adres → blokkeer
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def assert_public_url(url: str) -> None:
    """Raise UnsafeURLError als `url` geen http(s) is of naar een niet-publiek IP resolvet."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"scheme niet toegestaan: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("geen hostname in URL")

    loop = asyncio.get_event_loop()
    try:
        infos = await loop.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise UnsafeURLError(f"DNS-resolutie faalde voor {host}: {exc}")

    if not infos:
        raise UnsafeURLError(f"geen adressen voor {host}")
    for info in infos:
        ip_str = info[4][0]
        if _ip_is_blocked(ip_str):
            raise UnsafeURLError(f"geblokkeerd (niet-publiek) adres voor {host}: {ip_str}")


async def safe_get(client: httpx.AsyncClient, url: str, *, max_redirects: int = 5, **kwargs) -> httpx.Response:
    """Als client.get, maar SSRF-safe: valideert de URL én elke redirect-hop.

    Volgt redirects handmatig (kwargs['follow_redirects'] wordt genegeerd) zodat
    een publieke URL die naar een intern adres 302't alsnog wordt geblokkeerd.
    """
    kwargs.pop("follow_redirects", None)
    current = url
    for _ in range(max_redirects + 1):
        await assert_public_url(current)
        resp = await client.get(current, follow_redirects=False, **kwargs)
        if resp.status_code in _REDIRECT_CODES and "location" in resp.headers:
            current = urljoin(current, resp.headers["location"])
            continue
        return resp
    raise UnsafeURLError(f"te veel redirects vanaf {url}")
