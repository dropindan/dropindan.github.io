#!/usr/bin/env python3
"""Generic browser-less scraper (fast HTTP mode).

A companion to scrape.py that uses curl_cffi instead of a real browser, so it's
much faster and lighter — but it does NOT run JavaScript. Use this mode for
static HTML and JSON APIs; use scrape.py (Playwright) when a page needs a real
browser (JS rendering, login flows, infinite scroll).

It shares the same JSON config format as scrape.py, plus three HTTP-mode extras:

    "impersonate":     a curl_cffi target, e.g. "chrome131" (TLS/HTTP2 fingerprint)
    "proxies":         a list of proxy URLs to rotate through
    "max_retries":     how many times to retry a blocked/failed request

Usage:
    python fetch.py config.json
    python fetch.py config.json --out results.csv
    python fetch.py config.json --impersonate chrome131
    python fetch.py config.json --proxies http://user:pass@host:port,http://host2:port

See README.md for the full config format.
"""

import argparse
import itertools
import random
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from common import load_config, log, polite_delay, write_output

# Status codes worth retrying: blocked / rate-limited / transient server errors.
RETRYABLE_STATUSES = {403, 408, 429, 500, 502, 503, 504}


class ProxyRotator:
    """Round-robins through a list of proxies, and can drop dead ones.

    With an empty list it yields None forever, i.e. a direct connection.
    """

    def __init__(self, proxies: list[str]):
        self._proxies = list(proxies)
        self._cycle = itertools.cycle(self._proxies) if self._proxies else None

    def next(self) -> str | None:
        if not self._cycle:
            return None
        return next(self._cycle)

    def drop(self, proxy: str) -> None:
        """Remove a proxy that keeps failing, and rebuild the rotation."""
        if proxy in self._proxies:
            self._proxies.remove(proxy)
            log(f"  dropped failing proxy {proxy!r} ({len(self._proxies)} left)")
        self._cycle = itertools.cycle(self._proxies) if self._proxies else None


def fetch_with_retries(url: str, session, rotator: ProxyRotator, config: dict) -> str | None:
    """Fetch a URL, rotating proxies and backing off exponentially on 403/429/5xx.

    Returns the response text, or None if every attempt failed.
    """
    max_retries = int(config.get("max_retries", 4))
    backoff_base = float(config.get("backoff_base_seconds", 1.0))
    backoff_cap = float(config.get("backoff_cap_seconds", 30.0))
    timeout = float(config.get("timeout_ms", 30000)) / 1000.0
    impersonate = config.get("impersonate", "chrome")

    for attempt in range(max_retries + 1):
        proxy = rotator.next()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            resp = session.get(
                url,
                impersonate=impersonate,
                proxies=proxies,
                timeout=timeout,
                headers=config.get("headers"),
            )
        except Exception as e:  # network error, dead proxy, timeout
            log(f"  attempt {attempt + 1} error on {url}: {e}")
            if proxy:
                rotator.drop(proxy)
            _backoff(attempt, backoff_base, backoff_cap)
            continue

        if resp.status_code in RETRYABLE_STATUSES:
            log(f"  attempt {attempt + 1} got HTTP {resp.status_code} on {url}")
            # A proxy that keeps getting blocked is probably burned.
            if proxy and resp.status_code in (403, 429):
                rotator.drop(proxy)
            if attempt < max_retries:
                _backoff(attempt, backoff_base, backoff_cap, resp)
                continue
            return None

        resp.raise_for_status()
        return resp.text

    log(f"  giving up on {url} after {max_retries + 1} attempts")
    return None


def _backoff(attempt: int, base: float, cap: float, resp=None) -> None:
    """Sleep with exponential backoff plus jitter.

    Honors a Retry-After header when the server sends one.
    """
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            wait = float(retry_after)
            log(f"  honoring Retry-After: sleeping {wait:.1f}s")
            time.sleep(wait)
            return
    # Exponential: base * 2**attempt, capped, with full jitter.
    delay = min(cap, base * (2 ** attempt))
    delay = random.uniform(0, delay)
    log(f"  backing off {delay:.1f}s")
    time.sleep(delay)


def extract_field(element, spec) -> str:
    """Extract one field from a BeautifulSoup element.

    A spec is either a CSS selector string (inner text of the first match) or
    an object {"selector": "...", "attr": "href"} to read an attribute. An
    empty selector targets the item element itself.
    """
    if isinstance(spec, str):
        spec = {"selector": spec}
    selector = spec.get("selector", "")
    target = element.select_one(selector) if selector else element
    if target is None:
        return ""
    attr = spec.get("attr")
    if attr:
        return target.get(attr, "") or ""
    return target.get_text(strip=True)


def scrape_html(html: str, url: str, config: dict) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    item_selector = config.get("item_selector")
    fields = config["fields"]
    rows = []
    if item_selector:
        elements = soup.select(item_selector)
        log(f"  found {len(elements)} items matching {item_selector!r}")
        for el in elements:
            rows.append({name: extract_field(el, spec) for name, spec in fields.items()})
    else:
        rows.append({name: extract_field(soup, spec) for name, spec in fields.items()})
    for row in rows:
        row["_source_url"] = url
    return rows


def find_next_url(html: str, current_url: str, config: dict) -> str | None:
    """Resolve the next page's URL from an anchor's href (no clicking here)."""
    next_selector = config.get("next_page_selector")
    if not next_selector:
        return None
    soup = BeautifulSoup(html, "lxml")
    link = soup.select_one(next_selector)
    if link is None:
        return None
    href = link.get("href")
    if not href:
        return None
    return urljoin(current_url, href)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generic browser-less scraper (curl_cffi).")
    parser.add_argument("config", help="Path to a JSON config file")
    parser.add_argument("--out", default=None, help="Output file (.json or .csv)")
    parser.add_argument("--impersonate", default=None, help="curl_cffi target, e.g. chrome131")
    parser.add_argument("--proxies", default=None,
                        help="Comma-separated proxy URLs to rotate through")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.impersonate:
        config["impersonate"] = args.impersonate
    out_path = Path(args.out or config.get("output", "results.json"))

    proxies = config.get("proxies", [])
    if args.proxies:
        proxies = [p.strip() for p in args.proxies.split(",") if p.strip()]
    rotator = ProxyRotator(proxies)
    if proxies:
        log(f"rotating through {len(proxies)} proxies")

    max_pages = config.get("max_pages", 1)
    all_rows: list[dict] = []
    session = cffi_requests.Session()

    for start_url in config["start_urls"]:
        url = start_url
        page_num = 1
        while url:
            log(f"fetching {url}")
            html = fetch_with_retries(url, session, rotator, config)
            if html is None:
                break
            all_rows.extend(scrape_html(html, url, config))
            if page_num >= max_pages:
                break
            next_url = find_next_url(html, url, config)
            if not next_url or next_url == url:
                break
            url = next_url
            page_num += 1
            polite_delay(config)
        polite_delay(config)

    write_output(all_rows, out_path)


if __name__ == "__main__":
    main()
