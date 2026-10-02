# Generic headed scraper

A config-driven web scraper that runs a **visible Chromium window** on your
workstation using [Playwright](https://playwright.dev/python/). Because it's
headed, you can watch it work, log in by hand, and solve captchas yourself —
the browser profile is persisted between runs so you usually only log in once.

All site-specific details live in a small JSON config of CSS selectors; the
script itself never needs editing for a new site.

## Setup (once)

```bash
cd scraper
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Run

```bash
python scrape.py configs/example.json
```

Useful flags:

| Flag | What it does |
|---|---|
| `--out results.csv` | Output file; `.csv` or `.json` (default from config) |
| `--pause-first` | Pause on the first page so you can log in, then press Enter in the terminal to continue |
| `--headless` | Run without a window (for servers/CI) |
| `--profile-dir mydir` | Where cookies/logins are stored (default `.browser-profile`) |
| `--executable-path /path/to/chrome` | Use your own Chrome/Chromium instead of Playwright's bundled one |

## Config format

```jsonc
{
  "start_urls": ["https://example.com/listings"],  // required: pages to visit
  "item_selector": "div.card",       // each match becomes one output row;
                                     // omit to scrape the page as one record
  "fields": {                        // required: what to extract per item
    "title": "h2",                                    // inner text of first match
    "link":  { "selector": "a", "attr": "href" },     // read an attribute instead
    "whole": { "selector": "" }                       // empty selector = the item itself
  },
  "next_page_selector": "a.next",    // click this to paginate (omit for single page)
  "max_pages": 5,                    // pagination/scroll cap (default 1)
  "wait_for_selector": "div.card",   // wait for this before scraping each start URL
  "infinite_scroll": true,           // scroll to the bottom before scraping
  "max_scrolls": 10,                 // infinite-scroll cap
  "scroll_pause_ms": 1500,           // wait between scrolls
  "delay_min_seconds": 1,            // polite random delay between pages
  "delay_max_seconds": 3,
  "timeout_ms": 30000,               // navigation/selector timeout
  "user_agent": "...",               // optional UA override
  "output": "results.json"           // default output file
}
```

Every output row also gets a `_source_url` column recording the page it came
from.

## A typical login-gated workflow

```bash
python scrape.py configs/mysite.json --pause-first
```

1. A Chromium window opens on the first start URL.
2. Log in / click through cookie banners / solve the captcha in the window.
3. Press **Enter** in the terminal — scraping begins.
4. Next time, your session is still in `.browser-profile`, so you can skip
   `--pause-first`.

## Be a good citizen

Scrape only sites you're permitted to, respect `robots.txt` and the site's
terms of service, and keep the built-in delays — they're there so you don't
hammer anyone's servers.
