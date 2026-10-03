"""Build/commit metadata for the /version Discord command.

`.version` is written at image build time (see Dockerfile.bot/Dockerfile.server):
line 1 is the commit SHA, line 2 its ISO-8601 commit date, line 3 its subject.
Lines 2-3 are optional, so an old single-line file still works. Without a
`.version` file (local dev), the same fields are read from `git log`.
"""

import subprocess
from collections import namedtuple
from datetime import datetime

VERSION_PATH = ".version"

VersionInfo = namedtuple("VersionInfo", ["sha", "date", "subject"])


def parse_version_text(text):
    """Parse `.version`-format text (sha, date, subject lines) into a VersionInfo.

    Returns None if there's no SHA."""
    lines = [line.strip() for line in text.splitlines()] + ["", "", ""]
    sha, date, subject = lines[:3]
    if not sha:
        return None
    return VersionInfo(sha, date or None, subject or None)


def _git_version():
    try:
        result = subprocess.run(["git", "log", "-1", "--format=%H%n%cI%n%s"],
                                capture_output=True, text=True)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return parse_version_text(result.stdout)


def load_version(path=VERSION_PATH):
    """Read version info from `path`, falling back to `git log`; None if neither works."""
    try:
        with open(path) as f:
            info = parse_version_text(f.read())
    except FileNotFoundError:
        info = None
    return info or _git_version()


def format_version(info):
    """Format version info for Discord: short SHA, commit date, and subject."""
    if info is None:
        return "?"
    parts = [f"`{info.sha[:12]}`"]
    if info.date:
        try:
            committed = datetime.fromisoformat(info.date)
        except ValueError:
            committed = None
        if committed and committed.tzinfo:
            # Discord timestamp markup renders in each viewer's own timezone.
            epoch = int(committed.timestamp())
            parts.append(f"<t:{epoch}:f> (<t:{epoch}:R>)")
        else:
            parts.append(info.date)
    text = " · ".join(parts)
    if info.subject:
        text += f"\n> {info.subject}"
    return text
