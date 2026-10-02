"""Shared helpers for the scraper's two modes (headed browser and fast HTTP)."""

import csv
import json
import random
import sys
import time
from pathlib import Path


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
