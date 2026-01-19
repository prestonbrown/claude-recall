#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
File locking context manager for safe concurrent file access.
"""

import fcntl
from pathlib import Path


class FileLock:
    """Context manager for file locking."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.lock_path = file_path.with_suffix(file_path.suffix + ".lock")
        self.lock_file = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = open(self.lock_path, 'w')
        fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_file:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()
            # Note: We don't delete the lock file to avoid race conditions
            # with other processes trying to acquire the lock. The lock file
            # is just an empty marker file, so leaving it is harmless.
        return False
