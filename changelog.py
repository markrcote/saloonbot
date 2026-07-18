"""Parses CHANGELOG.md into structured entries for the /changelog Discord command."""

import os
import re
from collections import namedtuple
from datetime import date, timedelta

CHANGELOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "CHANGELOG.md")

ENTRY_HEADER_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) — (.+)$")

ChangelogEntry = namedtuple("ChangelogEntry", ["date", "title", "body"])


def parse_changelog(path=CHANGELOG_PATH):
    """Parse CHANGELOG.md into a list of ChangelogEntry, newest first (file order)."""
    with open(path) as f:
        text = f.read()

    entries = []
    for block in text.split("\n## ")[1:]:
        header, _, body = block.partition("\n")
        match = ENTRY_HEADER_RE.match(header.strip())
        if not match:
            continue
        entry_date = date.fromisoformat(match.group(1))
        entries.append(ChangelogEntry(entry_date, match.group(2).strip(), body.strip()))
    return entries


def select_recent_entries(entries, today=None, min_count=5, days=7):
    """Return the entries from the last `days` days, or the `min_count` most
    recent entries, whichever is more. `entries` must be newest-first."""
    if not entries:
        return []
    today = today or date.today()
    cutoff = today - timedelta(days=days)
    within_window = [e for e in entries if e.date >= cutoff]
    if len(within_window) >= min_count:
        return within_window
    return entries[:min_count]
