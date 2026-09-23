"""Thread-safe JSONL session logger for PiLiDAR-RTK Rover.

Creates a timestamped session directory, writes sensor records as
newline-delimited JSON, handles periodic flushing, optional file
rotation by size, and writes session metadata on close.

Public API:
    SessionLogger(config, config_path) — create logger
    .start()   -> Path                 — open session, return session dir
    .write(record)                     — enqueue a record (thread-safe)
    .stop(metadata)                    — flush, write metadata, close

Dependencies:
    - rover.config (RoverConfig)

Changelog:
    0.1.0  2026-03-22  Initial implementation (Task 3, Phase 3)
    0.1.1  2026-09-23  _schedule_flush() starts the Timer before publishing
                        it to self._flush_timer
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from rover import __version__
from rover._io import atomic_write_json
from rover.config import RoverConfig

logger = logging.getLogger(__name__)

_QUEUE_MAX = 10_000  # records buffered between flushes before dropping oldest
_FSYNC_EVERY = 10  # periodic flushes between fsync calls


class SessionLogger:
    """Thread-safe JSONL session logger.

    Records are enqueued via .write() from any thread and flushed to disk
    by a background timer at the configured interval.
    """

    def __init__(
        self,
        config: RoverConfig,
        config_path: Path | None = None,
    ) -> None:
        self._config = config
        self._config_path = Path(config_path) if config_path is not None else None
        self._lc = config.logging

        self._session_dir: Path | None = None
        self._start_time: datetime | None = None

        # File handles
        self._scan_file: TextIO | None = None
        self._gnss_file: TextIO | None = None
        self._scan_path: Path | None = None
        self._gnss_path: Path | None = None

        # Rotation state
        self._scan_index: int = 0
        self._gnss_index: int = 0

        # Thread-safe write queue
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=_QUEUE_MAX)

        # Flush timer
        self._flush_timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._running = False

        self._degraded = False
        self._dropped = 0
        self._flush_count = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def session_dir(self) -> Path | None:
        """Path to the current session directory, or None if not started."""
        return self._session_dir

    @property
    def degraded(self) -> bool:
        """True once any flush has failed; the logger keeps running regardless."""
        return self._degraded

    @property
    def dropped_records(self) -> int:
        """Records discarded because the queue was full."""
        return self._dropped

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> Path:
        """Create session directory, open log files, start flush timer.

        Returns:
            Path to the created session directory.

        Raises:
            RuntimeError: If already started.
        """
        if self._running:
            raise RuntimeError("SessionLogger is already running")

        now = datetime.now(UTC)
        self._start_time = now
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        session_name = f"{self._lc.session_prefix}_{timestamp}"

        self._session_dir = Path(self._lc.output_dir) / session_name
        self._session_dir.mkdir(parents=True, exist_ok=True)

        # Copy config to session directory
        self._copy_config()

        # Open log files
        self._scan_path = self._session_dir / "scan.jsonl"
        self._scan_file = open(self._scan_path, "a", encoding="utf-8")
        self._scan_index = 0

        self._gnss_path = self._session_dir / "gnss.jsonl"
        self._gnss_file = open(self._gnss_path, "a", encoding="utf-8")
        self._gnss_index = 0

        self._running = True
        self._schedule_flush()

        logger.info("Session started: %s", self._session_dir)
        return self._session_dir

    def write(self, record: dict) -> None:
        """Enqueue a record for writing. Thread-safe, non-blocking.

        Args:
            record: A dict with at least a "type" field.

        Raises:
            RuntimeError: If the logger is not running.
        """
        if not self._running:
            raise RuntimeError("SessionLogger is not running")
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            # Drop the oldest so a stalled disk cannot eat all memory. The whole
            # recovery is locked so a concurrent _flush() draining the queue
            # between our get_nowait() and put_nowait() can't cause a phantom
            # drop count (Empty means nothing of ours was actually lost) or an
            # uncounted real drop (Full again means our put really did fail).
            with self._lock:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                else:
                    self._note_dropped()
                try:
                    self._queue.put_nowait(record)
                except queue.Full:
                    # Another producer refilled it since we made room for
                    # ourselves — drop this record instead.
                    self._note_dropped()

    def _note_dropped(self) -> None:
        """Increment the drop counter and warn at a decaying frequency."""
        self._dropped += 1
        if self._dropped in (1, 100, 1000) or self._dropped % 10_000 == 0:
            logger.warning("SessionLogger queue full — dropped %d records so far", self._dropped)

    def stop(self, metadata: dict[str, Any] | None = None) -> None:
        """Flush remaining records, write metadata, and close files.

        Safe to call multiple times (second call is a no-op).

        Args:
            metadata: Optional extra fields merged into metadata.json.
        """
        if not self._running:
            return

        self._running = False

        # Cancel pending flush timer
        if self._flush_timer is not None:
            self._flush_timer.cancel()
            self._flush_timer = None

        # Final drain
        try:
            self._flush()
            self._fsync_files()
        except Exception as e:
            logger.error("SessionLogger final flush failed: %s", e)
            self._degraded = True

        # Write metadata
        try:
            self._write_metadata(metadata)
        except Exception as e:
            logger.error("SessionLogger metadata write failed: %s", e)
            self._degraded = True

        # Close files
        self._close_files()

        logger.info("Session stopped: %s", self._session_dir)

    # ------------------------------------------------------------------
    # Internal — config snapshot
    # ------------------------------------------------------------------

    def _copy_config(self) -> None:
        """Copy config file to session directory."""
        assert self._session_dir is not None

        if self._config_path is not None and self._config_path.exists():
            shutil.copy2(self._config_path, self._session_dir / "config.toml")
        else:
            # No file path — write effective config as JSON
            effective = self._session_dir / "effective_config.json"
            effective.write_text(
                json.dumps(self._config.to_dict(), indent=2),
                encoding="utf-8",
            )

    # ------------------------------------------------------------------
    # Internal — flush and write
    # ------------------------------------------------------------------

    def _schedule_flush(self) -> None:
        """Schedule the next periodic flush.

        Builds the Timer into a local and starts it BEFORE publishing it to
        `self._flush_timer` — publishing an unstarted Timer first leaves a
        window where a concurrent reader (e.g. a test asserting
        `is_alive()`) can observe a Timer object that exists but hasn't
        actually started running yet.
        """
        if not self._running:
            return
        timer = threading.Timer(self._lc.flush_interval_sec, self._periodic_flush)
        timer.daemon = True
        timer.start()
        self._flush_timer = timer

    def _periodic_flush(self) -> None:
        """Called by timer: flush, then ALWAYS reschedule (T1-011)."""
        try:
            self._flush()
            self._flush_count += 1
            if self._flush_count % _FSYNC_EVERY == 0:
                self._fsync_files()
        except Exception as e:
            if not self._degraded:
                logger.error("SessionLogger flush failed — continuing degraded: %s", e)
            self._degraded = True
        finally:
            self._schedule_flush()

    def _flush(self) -> None:
        """Drain the queue and write all records to disk."""
        with self._lock:
            records: list[dict] = []
            while True:
                try:
                    records.append(self._queue.get_nowait())
                except queue.Empty:
                    break

            for record in records:
                self._write_record(record)

            # Flush file buffers
            if self._scan_file is not None and not self._scan_file.closed:
                self._scan_file.flush()
            if self._gnss_file is not None and not self._gnss_file.closed:
                self._gnss_file.flush()

            # Check rotation
            self._maybe_rotate()

    def _write_record(self, record: dict) -> None:
        """Write a single record to the appropriate file."""
        line = json.dumps(record, separators=(",", ":")) + "\n"

        if record.get("type") == "gnss" and self._gnss_file is not None:
            self._gnss_file.write(line)
        if self._scan_file is not None:
            self._scan_file.write(line)

    # ------------------------------------------------------------------
    # Internal — rotation
    # ------------------------------------------------------------------

    def _maybe_rotate(self) -> None:
        """Rotate log files if they exceed the configured size limit."""
        if self._lc.rotate_size_mb <= 0:
            return

        limit_bytes = self._lc.rotate_size_mb * 1024 * 1024

        if self._scan_path is not None and self._scan_path.exists():
            if self._scan_path.stat().st_size >= limit_bytes:
                self._rotate_file("scan")

        if self._gnss_path is not None and self._gnss_path.exists():
            if self._gnss_path.stat().st_size >= limit_bytes:
                self._rotate_file("gnss")

    def _rotate_file(self, which: str) -> None:
        """Open a new numbered file, then close and swap out the current one.

        Opens the new segment FIRST. If that ``open()`` fails (ENOSPC,
        EROFS, ...), the current file handle is never touched and the index
        is never advanced — the old file stays open and writable and every
        later flush keeps landing in it. Closing the old file before opening
        the new one (the previous order) left the stream closed with no
        replacement on a failed open, wedging every subsequent flush.
        """
        assert self._session_dir is not None

        if which == "scan":
            next_index = self._scan_index + 1
            next_path = self._session_dir / f"scan_{next_index:03d}.jsonl"
            try:
                new_file = open(next_path, "a", encoding="utf-8")
            except OSError as e:
                if not self._degraded:
                    logger.error("Rotation of scan log to %s failed: %s", next_path.name, e)
                self._degraded = True
                return
            if self._scan_file is not None and not self._scan_file.closed:
                self._scan_file.close()
            self._scan_index = next_index
            self._scan_path = next_path
            self._scan_file = new_file
            logger.info("Rotated scan log to %s", self._scan_path.name)
        elif which == "gnss":
            next_index = self._gnss_index + 1
            next_path = self._session_dir / f"gnss_{next_index:03d}.jsonl"
            try:
                new_file = open(next_path, "a", encoding="utf-8")
            except OSError as e:
                if not self._degraded:
                    logger.error("Rotation of gnss log to %s failed: %s", next_path.name, e)
                self._degraded = True
                return
            if self._gnss_file is not None and not self._gnss_file.closed:
                self._gnss_file.close()
            self._gnss_index = next_index
            self._gnss_path = next_path
            self._gnss_file = new_file
            logger.info("Rotated gnss log to %s", self._gnss_path.name)

    # ------------------------------------------------------------------
    # Internal — metadata and cleanup
    # ------------------------------------------------------------------

    def _write_metadata(self, extra: dict[str, Any] | None = None) -> None:
        """Write metadata.json to the session directory.

        Includes a `session` block carrying profile / project_code / mission_tag /
        target_crs_epsg / units (DEC-030, DEC-034) so that `scripts/georef.py` can
        re-export the session in the recorded CRS without parsing config.toml.
        """
        assert self._session_dir is not None

        end_time = datetime.now(UTC)
        config_hash = self._compute_config_hash()

        sess = self._config.session
        meta: dict[str, Any] = {
            "session_id": self._session_dir.name,
            "start_time": (self._start_time.isoformat() if self._start_time else None),
            "end_time": end_time.isoformat(),
            "device_name": self._config.general.device_name,
            "firmware_version": __version__,
            "config_hash": config_hash,
            "logger_degraded": self._degraded,
            "dropped_records": self._dropped,
            "session": {
                "profile": sess.profile,
                "project_code": sess.project_code,
                "mission_tag": sess.mission_tag,
                "target_crs_epsg": sess.target_crs_epsg,
                "units": sess.units,
            },
        }

        if extra:
            meta.update(extra)

        meta_path = self._session_dir / "metadata.json"
        atomic_write_json(meta_path, meta)
        logger.info("Metadata written: %s", meta_path)

    def _compute_config_hash(self) -> str | None:
        """SHA-256 hash of the config file in the session directory."""
        assert self._session_dir is not None

        config_copy = self._session_dir / "config.toml"
        if config_copy.exists():
            data = config_copy.read_bytes()
            return hashlib.sha256(data).hexdigest()

        effective = self._session_dir / "effective_config.json"
        if effective.exists():
            data = effective.read_bytes()
            return hashlib.sha256(data).hexdigest()

        return None

    def _fsync_files(self) -> None:
        for f in (self._scan_file, self._gnss_file):
            if f is not None and not f.closed:
                f.flush()
                os.fsync(f.fileno())

    def _close_files(self) -> None:
        """Close all open file handles."""
        for f in (self._scan_file, self._gnss_file):
            if f is not None and not f.closed:
                f.close()
        self._scan_file = None
        self._gnss_file = None
