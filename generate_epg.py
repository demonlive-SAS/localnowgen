#!/usr/bin/env python3
"""Fetch the Local Now EPG feed and convert it to XMLTV (epg.xml)."""

import logging
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = os.environ.get(
    "LOCALNOW_EPG_URL",
    "https://data-store-trans-cdn.api.cms.amdvids.com/live/epg/US/website",
)
OUTPUT_FILE = Path(os.environ.get("EPG_OUTPUT", "epg.xml"))
CHANNEL_ID_PREFIX = "LN_"  # must match the tvg-id values in the M3U
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 45

log = logging.getLogger("generate_epg")


def unix_to_xmltv(timestamp: Any) -> str | None:
    """Convert a Unix timestamp (seconds) to XMLTV UTC format, or None on failure."""
    try:
        dt = datetime.fromtimestamp(int(float(timestamp)), tz=timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError) as exc:
        log.error("Error converting timestamp %r: %s", timestamp, exc)
        return None
    return dt.strftime("%Y%m%d%H%M%S +0000")


def build_xmltv(data: Any) -> ET.ElementTree | None:
    """Build an XMLTV tree from the API's JSON payload."""
    if not isinstance(data, dict) or not isinstance(data.get("channels"), list):
        log.error("Invalid API response: 'channels' key missing or not a list.")
        return None

    tv = ET.Element(
        "tv",
        {
            "generator-info-name": "GitHub Actions EPG Generator",
            "generator-info-url": "https://github.com/features/actions",
        },
    )

    channel_count = 0
    program_count = 0

    for channel in data["channels"]:
        if not isinstance(channel, dict) or "_id" not in channel or "name" not in channel:
            log.warning("Skipping invalid channel entry: %s", channel)
            continue

        channel_id = f"{CHANNEL_ID_PREFIX}{channel['_id']}"
        channel_name = channel.get("name") or "Unknown Channel"

        channel_elem = ET.SubElement(tv, "channel", id=channel_id)
        ET.SubElement(channel_elem, "display-name").text = str(channel_name)
        channel_count += 1

        programs = channel.get("program", [])
        if not isinstance(programs, list):
            log.warning("Channel %r (%s) has invalid 'program' data; skipping programs.", channel_name, channel_id)
            continue

        for program in programs:
            if not isinstance(program, dict):
                log.warning("Skipping invalid program entry for %s: %s", channel_id, program)
                continue

            start_ts = program.get("starts_at")
            end_ts = program.get("ends_at")
            title = program.get("program_title")
            if start_ts is None or end_ts is None or title is None:
                log.warning("Skipping program with missing data for %s: %s", channel_id, program)
                continue

            start = unix_to_xmltv(start_ts)
            stop = unix_to_xmltv(end_ts)
            if start is None or stop is None:
                log.warning("Skipping program with bad timestamps for %s: %s", channel_id, program)
                continue

            if int(float(start_ts)) >= int(float(end_ts)):
                log.warning("Skipping program with start >= end for %s: %s", channel_id, program)
                continue

            prog_elem = ET.SubElement(tv, "programme", start=start, stop=stop, channel=channel_id)
            ET.SubElement(prog_elem, "title", lang="en").text = str(title)

            description = program.get("program_description")
            if description and str(description).strip():
                ET.SubElement(prog_elem, "desc", lang="en").text = str(description)

            program_count += 1

    log.info("Processed %d channels and %d programmes.", channel_count, program_count)
    if channel_count == 0:
        log.error("No valid channels were processed.")
        return None
    if program_count == 0:
        log.warning("No valid programmes were processed; output will lack programme details.")

    return ET.ElementTree(tv)


def save_xmltv(path: Path, tree: ET.ElementTree) -> None:
    """Write the tree to *path* atomically."""
    ET.indent(tree, space="  ")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    tmp.replace(path)
    log.info("Wrote XMLTV data to %s", path)


def make_session() -> requests.Session:
    """Create a session that retries transient failures."""
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = USER_AGENT
    return session


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    log.info("Fetching EPG data from %s", API_URL)
    try:
        with make_session() as session:
            response = session.get(API_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        log.error("Failed to fetch EPG data: %s", exc)
        return 1
    except ValueError as exc:
        log.error("Error decoding EPG JSON response: %s", exc)
        return 1

    tree = build_xmltv(data)
    if tree is None:
        log.error("XMLTV creation failed; no output written.")
        return 1

    try:
        save_xmltv(OUTPUT_FILE, tree)
    except OSError as exc:
        log.error("Error writing %s: %s", OUTPUT_FILE, exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
