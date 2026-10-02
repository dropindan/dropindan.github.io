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
  "max_pages": 5,                    // pagination cap (default 1)
  "wait_for_selector": "div.card",   // wait for this before scraping each start URL

  // --- human-like infinite scroll ---
  "infinite_scroll": true,           // scroll the page before scraping
  "max_scrolls": 30,                 // scroll-step cap (default 30)
  "scroll_step_min_px": 300,         // each scroll moves a random amount in this range
  "scroll_step_max_px": 800,
  "scroll_pause_min_ms": 500,        // random pause between scroll steps
  "scroll_pause_max_ms": 1800,

  // --- being human-like between pages ---
  "delay_min_seconds": 1,            // random delay between page loads
  "delay_max_seconds": 3,
  "timeout_ms": 30000,               // navigation/selector timeout
  "user_agent": "Mozilla/5.0 ...",   // custom user-agent string
  "output": "results.json"           // default output file
}
```

Every output row also gets a `_source_url` column recording the page it came
from.

## Looking human

Two things in the config help a headed run behave like a real person rather
than a bot:

**Custom user-agent.** Set `"user_agent"` to any string and every request in
the session sends it. Use a current real browser UA (the example config ships
with a recent Chrome-on-macOS string). Omit it to use Chromium's own default.
You can confirm what the page sees with
`page.evaluate("navigator.userAgent")`.

**Human-like scrolling.** With `"infinite_scroll": true`, the scraper doesn't
jump to the bottom in one shot (an obvious bot tell). It scrolls down in small
steps of a random size (`scroll_step_min_px`–`scroll_step_max_px`), pauses a
jittered amount between steps (`scroll_pause_min_ms`–`scroll_pause_max_ms`),
occasionally nudges back up a little, and now and then takes a longer "reading"
pause — then stops once the page height stops growing. Widen the pause ranges
to slow it down further on sensitive sites.

The random delay between page loads (`delay_min_seconds`–`delay_max_seconds`)
adds the same jitter to pagination.

> These measures make scraping gentler and more natural; they are not a license
> to evade a site's access controls. Scrape only what you're permitted to, and
> respect `robots.txt` and each site's terms of service.

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
