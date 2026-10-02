# Generic scraper

A config-driven web scraper with **two modes** that share the same JSON config:

- **`scrape.py` — headed browser mode** ([Playwright](https://playwright.dev/python/)).
  Runs a **visible Chromium window** on your workstation, so you can watch it
  work, log in by hand, and solve captchas yourself. The browser profile is
  persisted between runs, so you usually only log in once. Runs JavaScript.
- **`fetch.py` — fast browser-less mode** ([curl_cffi](https://github.com/lexiforest/curl_cffi)).
  No browser, much faster and lighter, with a **real Chrome TLS/HTTP2
  fingerprint**, **proxy rotation**, and **HTTP 403 retry with exponential
  backoff**. Does **not** run JavaScript.

All site-specific details live in a small JSON config of CSS selectors; the
scripts never need editing for a new site.

### Which mode?

| Use `fetch.py` (fast) when… | Use `scrape.py` (browser) when… |
|---|---|
| Static HTML or JSON APIs | Page content is rendered by JavaScript |
| You need many requests, quickly | You need to log in / solve a captcha by hand |
| You want proxy rotation + TLS fingerprinting | The page uses infinite scroll or complex interaction |

A common setup is both: `fetch.py` for bulk pages, `scrape.py` for the few
that truly need a browser.

## Setup (once)

```bash
cd scraper
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium       # only needed for scrape.py (browser mode)
```

## Run

**Headed browser mode:**

```bash
python scrape.py configs/example.json
```

| Flag | What it does |
|---|---|
| `--out results.csv` | Output file; `.csv` or `.json` (default from config) |
| `--pause-first` | Pause on the first page so you can log in, then press Enter in the terminal to continue |
| `--headless` | Run without a window (for servers/CI) |
| `--profile-dir mydir` | Where cookies/logins are stored (default `.browser-profile`) |
| `--executable-path /path/to/chrome` | Use your own Chrome/Chromium instead of Playwright's bundled one |

**Fast browser-less mode:**

```bash
python fetch.py configs/example.json
python fetch.py configs/example.json --impersonate chrome131
python fetch.py configs/example.json --proxies http://user:pass@h1:port,http://h2:port
```

| Flag | What it does |
|---|---|
| `--out results.csv` | Output file; `.csv` or `.json` (default from config) |
| `--impersonate chrome131` | curl_cffi fingerprint target (overrides config) |
| `--proxies a,b,c` | Comma-separated proxy URLs to rotate through (overrides config) |

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
  "user_agent": "Mozilla/5.0 ...",   // custom user-agent string (browser mode)
  "output": "results.json",          // default output file

  // --- fast browser-less mode only (fetch.py) ---
  "impersonate": "chrome131",        // curl_cffi TLS/HTTP2 fingerprint target
  "headers": { "Accept-Language": "en-US,en;q=0.9" },  // extra request headers
  "proxies": [                       // proxies to rotate through (round-robin)
    "http://user:pass@host1:port",
    "http://host2:port"
  ],
  "max_retries": 4,                  // retries on 403/429/5xx before giving up
  "backoff_base_seconds": 1,         // exponential backoff base
  "backoff_cap_seconds": 30,         // backoff ceiling

  // route every target URL through a scraping-API gateway (see below)
  "api_gateway": {
    "endpoint": "https://api.scraperapi.com/",
    "api_key_env": "SCRAPERAPI_KEY",
    "url_param": "url",
    "params": { "render": "true" }
  }
}
```

Every output row also gets a `_source_url` column recording the page it came
from.

> **Scroll vs. pagination by mode.** `infinite_scroll` and the `scroll_*` keys
> apply only to the browser mode (`scrape.py`) — there's no JavaScript to scroll
> in `fetch.py`. For pagination, `scrape.py` *clicks* the `next_page_selector`
> element, while `fetch.py` reads that element's `href` and fetches the next URL
> directly (so in fast mode the selector must point at a link).

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

## Fingerprinting, proxies, and retries (fast mode)

`fetch.py` adds three anti-blocking features that the browser mode gets for
free (a real browser already has a real fingerprint and your real IP):

**TLS/HTTP2 fingerprint.** `curl_cffi` reproduces a real browser's ClientHello
and HTTP/2 settings, so the connection's JA3/JA4 fingerprint matches Chrome.
Set `"impersonate"` to a specific version like `"chrome131"` (pin the version
so your fingerprint doesn't drift on upgrade). Also set matching `"headers"`
(e.g. `Accept-Language`) so your headers agree with the fingerprint.

**Proxy rotation.** List proxies in `"proxies"` (or pass `--proxies`), and each
request round-robins to the next one. A proxy that errors or returns 403/429 is
dropped from the rotation automatically; with no proxies configured it connects
directly.

**403 retry with exponential backoff.** On a 403/429/5xx the request is retried
up to `max_retries` times, sleeping `backoff_base_seconds * 2**attempt` (capped
at `backoff_cap_seconds`) with full jitter between tries. A `Retry-After`
response header is honored when present. After the last attempt the URL is
skipped rather than crashing the run.

## Routing through a scraping-API gateway (fast mode)

Instead of (or as well as) your own proxies, `fetch.py` can forward every
target URL through a hosted scraping API such as
[ScraperAPI](https://docs.scraperapi.com/synchronous-apis/using-the-api-endpoint),
which handles proxies, rendering, and anti-bot for you. Add an `api_gateway`
block to the config — see `configs/scraperapi-example.json`:

```jsonc
"api_gateway": {
  "endpoint": "https://api.scraperapi.com/",
  "api_key_env": "SCRAPERAPI_KEY",   // env var that holds your key
  "api_key_param": "api_key",        // query param name for the key
  "url_param": "url",                // query param that carries the target URL
  "params": { "render": "true", "country_code": "us" }  // any extra params
}
```

Then export your key and run:

```bash
export SCRAPERAPI_KEY=your_key_here
python fetch.py configs/scraperapi-example.json
```

Each request becomes
`https://api.scraperapi.com/?api_key=KEY&url=<target>&render=true&country_code=us`,
and the gateway returns the target page's HTML, which is parsed with your
normal selectors. Notes:

- The **API key is read from the environment**, never stored in the config, so
  the config is safe to commit.
- `_source_url` in the output and all pagination stay on the **real target
  URL**, not the gateway URL, so `next_page_selector` links resolve correctly.
- The block is **generic**: point `endpoint`/`*_param`/`params` at any
  forward-proxy API with the same "pass my URL as a query parameter" shape.
- Hosted gateways can be slow (ScraperAPI may take up to ~70s with `render`),
  so the example sets a generous `timeout_ms` and backoff.

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
