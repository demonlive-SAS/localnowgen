#!/usr/bin/env python3
"""Build localnow.m3u: every channel in one group, sorted by tvg-name.

Fetches the upstream Local Now playlist (or reads a local file with --input),
adds a tvg-name attribute, sets group-title to "Fast Local Now", removes
duplicate channels, sorts alphabetically by tvg-name and writes the result.
"""

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SOURCE_URL = os.environ.get("LOCALNOW_M3U_URL", "https://www.apsattv.com/localnow.m3u")
DEFAULT_OUTPUT = Path(os.environ.get("M3U_OUTPUT", "localnow.m3u"))
GROUP_TITLE = "Fast Local Now"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 45

ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')

log = logging.getLogger("generate_playlist")


@dataclass
class Channel:
    duration: str
    attrs: dict[str, str]
    name: str
    url: str
    extra_lines: list[str] = field(default_factory=list)  # e.g. #EXTVLCOPT lines


def split_extinf(line: str) -> tuple[str, str, str]:
    """Split '#EXTINF:<dur> <attrs>,<name>' on the first comma outside quotes."""
    body = line[len("#EXTINF:"):]
    in_quotes = False
    for i, ch in enumerate(body):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "," and not in_quotes:
            head, name = body[:i], body[i + 1:]
            break
    else:
        head, name = body, ""
    head = head.strip()
    duration, _, attr_text = head.partition(" ")
    return duration or "-1", attr_text, name.strip()


def parse_m3u(text: str) -> list[Channel]:
    channels: list[Channel] = []
    lines = [ln.strip() for ln in text.splitlines()]
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.startswith("#EXTINF"):
            continue

        duration, attr_text, name = split_extinf(line)
        attrs = dict(ATTR_RE.findall(attr_text))

        extra: list[str] = []
        url = ""
        while i < len(lines):
            nxt = lines[i]
            i += 1
            if not nxt:
                continue
            if nxt.startswith("#EXTINF"):  # entry without a URL
                i -= 1
                break
            if nxt.startswith("#"):
                extra.append(nxt)
                continue
            url = nxt
            break

        if not url:
            log.warning("Skipping %r: no stream URL found.", name)
            continue
        channels.append(Channel(duration, attrs, name or attrs.get("tvg-name", ""), url, extra))
    return channels


def transform(channels: list[Channel]) -> list[Channel]:
    """Set tvg-name/group-title, drop duplicates, sort by tvg-name."""
    seen: set[str] = set()
    result: list[Channel] = []
    for ch in channels:
        key = ch.attrs.get("tvg-id") or ch.url
        if key in seen:
            log.info("Dropping duplicate channel: %s (%s)", ch.name, key)
            continue
        seen.add(key)

        ch.attrs["tvg-name"] = ch.name.replace('"', "'")
        ch.attrs["group-title"] = GROUP_TITLE
        result.append(ch)

    result.sort(key=lambda c: (c.attrs["tvg-name"].casefold(), c.attrs["tvg-name"], c.attrs.get("tvg-id", "")))
    return result


def format_m3u(channels: list[Channel]) -> str:
    preferred = ("tvg-id", "tvg-name", "tvg-logo", "group-title")
    out = ["#EXTM3U"]
    for ch in channels:
        ordered = [k for k in preferred if k in ch.attrs]
        ordered += [k for k in ch.attrs if k not in preferred]
        attr_text = " ".join(f'{k}="{ch.attrs[k]}"' for k in ordered)
        out.append(f"#EXTINF:{ch.duration} {attr_text},{ch.name}")
        out.extend(ch.extra_lines)
        out.append(ch.url)
    return "\n".join(out) + "\n"


def fetch_source(url: str) -> str:
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.headers["User-Agent"] = USER_AGENT
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text.lstrip("\ufeff")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="read this local M3U instead of fetching SOURCE_URL")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="output path (default: %(default)s)")
    args = parser.parse_args()

    try:
        if args.input:
            log.info("Reading playlist from %s", args.input)
            text = args.input.read_text(encoding="utf-8-sig")
        else:
            log.info("Fetching playlist from %s", SOURCE_URL)
            text = fetch_source(SOURCE_URL)
    except (requests.RequestException, OSError, UnicodeDecodeError) as exc:
        log.error("Failed to load source playlist: %s", exc)
        return 1

    parsed = parse_m3u(text)
    channels = transform(parsed)
    if not channels:
        log.error("No channels found in source playlist; leaving %s untouched.", args.output)
        return 1

    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(format_m3u(channels), encoding="utf-8", newline="\n")
    tmp.replace(args.output)
    log.info("Wrote %d channels to %s (%d duplicates removed).", len(channels), args.output, len(parsed) - len(channels))
    return 0


if __name__ == "__main__":
    sys.exit(main())
