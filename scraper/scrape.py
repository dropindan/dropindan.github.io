#!/usr/bin/env python3
"""Generic headed web scraper.

Drives a visible (headed) Chromium window on your workstation via Playwright,
so you can watch it work, log in manually, and get past captchas yourself.
Everything site-specific lives in a small JSON config file of CSS selectors.

Usage:
    python scrape.py config.json
    python scrape.py config.json --out results.csv
    python scrape.py config.json --pause-first   # pause on first page to log in
    python scrape.py config.json --headless      # run without a window (CI etc.)

See configs/example.json and README.md for the config format.
"""

import argparse
import csv
import json
import random
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def log(msg: str) -> None:
    print(f"[scraper] {msg}", flush=True)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    for key in ("start_urls", "fields"):
        if key not in config:
            sys.exit(f"Config is missing required key: {key!r}")
    return config


def polite_delay(config: dict) -> None:
    """Sleep a random, human-like interval between page loads."""
    lo = config.get("delay_min_seconds", 1.0)
    hi = max(config.get("delay_max_seconds", 3.0), lo)
    time.sleep(random.uniform(lo, hi))


def extract_field(element, spec) -> str:
    """Extract one field from an element.

    A spec is either a CSS selector string (meaning: inner text of the first
    match) or an object: {"selector": "...", "attr": "href"} to read an
    attribute instead of text. An empty selector targets the item element
    itself.
    """
    if isinstance(spec, str):
        spec = {"selector": spec}
    selector = spec.get("selector", "")
    target = element.query_selector(selector) if selector else element
    if target is None:
        return ""
    attr = spec.get("attr")
    if attr:
        return target.get_attribute(attr) or ""
    return (target.inner_text() or "").strip()


def scroll_to_bottom(page, config: dict) -> None:
    """Scroll an infinite-scroll page like a human until it stops growing.

    Instead of jumping straight to the bottom, this scrolls down in small,
    randomly-sized steps with jittered pauses between them, occasionally
    nudging back up a little and now and then taking a longer "reading"
    pause. That cadence looks far more like a real person than a single
    programmatic jump, which many sites flag.
    """
    max_scrolls = config.get("max_scrolls", 30)
    step_min = config.get("scroll_step_min_px", 300)
    step_max = config.get("scroll_step_max_px", 800)
    pause_min = config.get("scroll_pause_min_ms", 500)
    pause_max = config.get("scroll_pause_max_ms", 1800)

    stagnant = 0
    last_height = 0
    for i in range(max_scrolls):
        height = page.evaluate("document.body.scrollHeight")
        offset = page.evaluate("window.scrollY + window.innerHeight")
        # Stop once new content has stopped loading at the bottom.
        if height == last_height and offset >= height - 2:
            stagnant += 1
            if stagnant >= 2:
                break
        else:
            stagnant = 0
        last_height = height

        step = random.randint(int(step_min), int(step_max))
        page.mouse.wheel(0, step)
        page.wait_for_timeout(random.randint(int(pause_min), int(pause_max)))

        # Occasionally scroll back up a touch, the way people do.
        if random.random() < 0.15:
            page.mouse.wheel(0, -random.randint(80, 200))
            page.wait_for_timeout(random.randint(300, 900))

        # Every so often, a longer pause as if reading.
        if random.random() < 0.1:
            page.wait_for_timeout(random.randint(1500, 3500))


def scrape_page(page, config: dict) -> list[dict]:
    item_selector = config.get("item_selector")
    fields = config["fields"]
    rows = []
    if item_selector:
        elements = page.query_selector_all(item_selector)
        log(f"  found {len(elements)} items matching {item_selector!r}")
        for el in elements:
            rows.append({name: extract_field(el, spec) for name, spec in fields.items()})
    else:
        # No item selector: treat the whole page as a single record.
        body = page.query_selector("body")
        rows.append({name: extract_field(body, spec) for name, spec in fields.items()})
    for row in rows:
        row["_source_url"] = page.url
    return rows


def goto_next_page(page, config: dict) -> bool:
    """Advance to the next page if pagination is configured. Returns True on success."""
    next_selector = config.get("next_page_selector")
    if not next_selector:
        return False
    button = page.query_selector(next_selector)
    if button is None or not button.is_enabled():
        return False
    try:
        button.click()
        page.wait_for_load_state("domcontentloaded")
    except PlaywrightTimeoutError:
        return False
    return True


def write_output(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".csv":
        if not rows:
            out_path.write_text("", encoding="utf-8")
            return
        fieldnames = list(dict.fromkeys(k for row in rows for k in row))
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
    log(f"wrote {len(rows)} rows to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generic headed web scraper (Playwright).")
    parser.add_argument("config", help="Path to a JSON config file")
    parser.add_argument("--out", default=None, help="Output file (.json or .csv); default from config or results.json")
    parser.add_argument("--headless", action="store_true", help="Run without a visible browser window")
    parser.add_argument("--pause-first", action="store_true",
                        help="Pause after loading the first page so you can log in / solve a captcha, then press Enter to continue")
    parser.add_argument("--profile-dir", default=None,
                        help="Browser profile directory (keeps cookies/logins between runs); default .browser-profile")
    parser.add_argument("--executable-path", default=None,
                        help="Path to a Chromium/Chrome binary, if you don't want Playwright's bundled one")
    args = parser.parse_args()

    config = load_config(args.config)
    out_path = Path(args.out or config.get("output", "results.json"))
    profile_dir = args.profile_dir or config.get("profile_dir", ".browser-profile")
    max_pages = config.get("max_pages", 1)

    all_rows: list[dict] = []
    with sync_playwright() as p:
        launch_kwargs = {
            "headless": args.headless,
            "viewport": {"width": 1366, "height": 900},
        }
        if args.executable_path:
            launch_kwargs["executable_path"] = args.executable_path
        if config.get("user_agent"):
            launch_kwargs["user_agent"] = config["user_agent"]

        # A persistent context keeps cookies and logins in profile_dir
        # between runs, so you only have to log in once.
        context = p.chromium.launch_persistent_context(profile_dir, **launch_kwargs)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(int(config.get("timeout_ms", 30000)))

        first_page = True
        try:
            for url in config["start_urls"]:
                log(f"visiting {url}")
                page.goto(url, wait_until="domcontentloaded")

                if first_page and args.pause_first:
                    input("[scraper] Browser is open. Log in / solve captchas as needed, "
                          "then press Enter here to start scraping... ")
                first_page = False

                if config.get("wait_for_selector"):
                    try:
                        page.wait_for_selector(config["wait_for_selector"])
                    except PlaywrightTimeoutError:
                        log(f"  warning: wait_for_selector never appeared on {url}, scraping anyway")

                page_num = 1
                while True:
                    if config.get("infinite_scroll"):
                        scroll_to_bottom(page, config)
                    all_rows.extend(scrape_page(page, config))
                    if page_num >= max_pages or not goto_next_page(page, config):
                        break
                    page_num += 1
                    log(f"  page {page_num}")
                    polite_delay(config)

                polite_delay(config)
        finally:
            context.close()

    write_output(all_rows, out_path)


if __name__ == "__main__":
    main()
