"""Local file creation policy for trace-derived data."""

import os


def open_private(path: str, flags: int) -> int:
    """Apply an owner-only POSIX creation mode; leave existing files alone."""
    return os.open(path, flags, 0o600)
