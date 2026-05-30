"""Atomic I/O helpers shared across rover modules.

Mirrors the helpers in ``arm-drone-lidar-workflow/base-station/rtk_io.py`` so
that anything reading rover and base output files sees the same atomicity and
permission contract:

  * mkstemp inside the destination directory (same filesystem → rename is atomic)
  * 0644 permissions on the final file (chmod on the tempfile, then rename)
  * trailing newline on JSON payloads (matches base output exactly)

If you're tempted to reach for a third-party "atomicwrites" package: don't —
the whole point is that the rover and base agree on this one function, and
neither side pulls in extra dependencies for it.

Public API:
    atomic_write_json(path, data)  — write JSON via mkstemp + os.replace

Cross-reference:
    arm-drone-lidar-workflow/base-station/rtk_io.py:atomic_write_json

Changelog:
    0.10.2  2026-05-30  Extracted from telemetry.py (Stage B of alignment overhaul).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(path: Path | str, data: dict) -> None:
    """Write *data* as JSON to *path* via mkstemp + os.replace.

    Mirrors ``base-station/rtk_io.py:atomic_write_json`` byte-for-byte so any
    process that already knows how to read ``/run/rtk-base/status.json`` can
    read the rover's status.json with the same expectations.

    Creates the parent directory if absent. Raises on failure — callers log
    at whatever severity suits their context.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.write("\n")
        # chmod is mostly a no-op on Windows; harmless either way.
        try:
            os.chmod(tmp, 0o644)
        except OSError:
            pass
        # os.replace is atomic on both POSIX and Windows (unlike os.rename on Windows
        # when the destination exists).
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


__all__ = ["atomic_write_json"]
