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
    0.1.2  2026-09-23  GNSS records go ONLY to gnss*.jsonl, never mirrored
                        into scan*.jsonl (T1-053); generic _Stream + _rotate()
                        replace the two-branch _rotate_file(); lost_records
                        counts records drained but not written on a failed
                        flush; write()'s drop-oldest path uses a dedicated
                        _count_lock and never waits on the flush lock
                        (S2-R4); stop() sets _stopping before cancelling the
                        timer so a racing _schedule_flush() cannot leave a
                        stray live Timer behind (S3-R4)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import shutil
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from rover import __version__
from rover._io import atomic_write_json
from rover.config import RoverConfig

logger = logging.getLogger(__name__)

_QUEUE_MAX = 10_000  # records buffered between flushes before dropping oldest
_FSYNC_EVERY = 10  # periodic flushes between fsync calls


@dataclass
class _Stream:
    """Per-stream (scan / gnss) file state, rotated generically by _rotate()."""

    stem: str
    path: Path | None = None
    file: TextIO | None = None
    index: int = 0


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

        # Per-stream file state (T1-053: gnss records live ONLY in self._gnss)
        self._scan = _Stream("scan")
        self._gnss = _Stream("gnss")

        # Thread-safe write queue
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=_QUEUE_MAX)

        # Flush timer
        self._flush_timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._running = False
        self._stopping = False

        # Counters — guarded by _count_lock, which is never held across disk
        # I/O, so a stalled flush (holding _lock) can't block a producer's
        # drop-oldest path (S2-R4).
        self._count_lock = threading.Lock()
        self._degraded = False
        self._dropped = 0
        self._lost = 0
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

    @property
    def lost_records(self) -> int:
        """Records drained from the queue but never written, due to a failed flush."""
        return self._lost

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
        self._scan = _Stream("scan")
        self._gnss = _Stream("gnss")
        self._open_stream(self._scan)
        self._open_stream(self._gnss)

        self._stopping = False
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
            # Drop the oldest so a stalled disk cannot eat all memory. This
            # must NEVER wait on `_lock` — `_flush()` holds that lock across
            # disk I/O, so a stalled disk must not block the producer
            # (S2-R4). `queue.Queue`'s own internal lock already makes each
            # get_nowait()/put_nowait() call atomic, so no extra lock is
            # needed around them: a get_nowait() that raises Empty means a
            # concurrent _flush() already drained the queue for us (nothing
            # of ours was actually lost); one that returns an item means a
            # real record was discarded, and a subsequent Full on put_nowait
            # means our own record was the one that didn't fit. `_count_lock`
            # only protects the counters themselves, never blocking on I/O.
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
        with self._count_lock:
            self._dropped += 1
            dropped = self._dropped
        if dropped in (1, 100, 1000) or dropped % 10_000 == 0:
            logger.warning("SessionLogger queue full — dropped %d records so far", dropped)

    def _note_lost(self, n: int) -> None:
        """Count records drained from the queue but never written (failed flush)."""
        if n <= 0:
            return
        with self._count_lock:
            self._lost += n
            lost = self._lost
        logger.error("SessionLogger flush failed — %d record(s) lost (total %d)", n, lost)

    def stop(self, metadata: dict[str, Any] | None = None) -> None:
        """Flush remaining records, write metadata, and close files.

        Safe to call multiple times (second call is a no-op).

        Args:
            metadata: Optional extra fields merged into metadata.json.
        """
        if not self._running:
            return

        self._running = False
        # Set BEFORE cancelling the timer: a concurrent _periodic_flush()
        # that already passed the `_running` check in _schedule_flush() and
        # is mid-way through creating+starting a new Timer (start-then-publish,
        # T1-041) has not yet published it to `self._flush_timer` — cancel()
        # below could then miss it. `_stopping` closes that window: any
        # `_schedule_flush()` call that hasn't started its Timer yet will see
        # this flag and return without creating one (S3-R4).
        self._stopping = True

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
        if not self._running or self._stopping:
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
        """Drain the queue and write all records to disk.

        If `_write_record` raises partway through the drained batch, the
        records that were never written are counted as lost (not silently
        dropped) via `_note_lost`, then the exception is re-raised so
        `_periodic_flush` marks the logger degraded, same as before.
        """
        with self._lock:
            records: list[dict] = []
            while True:
                try:
                    records.append(self._queue.get_nowait())
                except queue.Empty:
                    break

            written = 0
            try:
                for record in records:
                    self._write_record(record)
                    written += 1
            except Exception:
                self._note_lost(len(records) - written)
                raise

            # Flush file buffers
            if self._scan.file is not None and not self._scan.file.closed:
                self._scan.file.flush()
            if self._gnss.file is not None and not self._gnss.file.closed:
                self._gnss.file.flush()

            # Check rotation
            self._maybe_rotate()

    def _write_record(self, record: dict) -> None:
        """Write a single record to its stream — GNSS records go ONLY to
        gnss*.jsonl (T1-053); everything else goes to scan*.jsonl."""
        line = json.dumps(record, separators=(",", ":")) + "\n"
        stream = self._gnss if record.get("type") == "gnss" else self._scan
        if stream.file is not None:
            stream.file.write(line)

    # ------------------------------------------------------------------
    # Internal — rotation
    # ------------------------------------------------------------------

    def _open_stream(self, stream: _Stream) -> None:
        """Open (or re-open) a stream's base file, `<stem>.jsonl`."""
        assert self._session_dir is not None
        stream.path = self._session_dir / f"{stream.stem}.jsonl"
        stream.file = open(stream.path, "a", encoding="utf-8")
        stream.index = 0

    def _maybe_rotate(self) -> None:
        """Rotate log files if they exceed the configured size limit."""
        if self._lc.rotate_size_mb <= 0:
            return

        limit_bytes = self._lc.rotate_size_mb * 1024 * 1024

        for stream in (self._scan, self._gnss):
            if stream.path is not None and stream.path.exists():
                if stream.path.stat().st_size >= limit_bytes:
                    self._rotate(stream)

    def _rotate(self, stream: _Stream) -> None:
        """Open a new numbered segment, then close and swap out the current one.

        Opens the new segment FIRST. If that ``open()`` fails (ENOSPC,
        EROFS, ...), the current file handle is never touched and the index
        is never advanced — the old file stays open and writable and every
        later flush keeps landing in it. Closing the old file before opening
        the new one (the previous order) left the stream closed with no
        replacement on a failed open, wedging every subsequent flush.
        """
        assert self._session_dir is not None

        next_index = stream.index + 1
        next_path = self._session_dir / f"{stream.stem}_{next_index:03d}.jsonl"
        try:
            new_file = open(next_path, "a", encoding="utf-8")
        except OSError as e:
            if not self._degraded:
                logger.error("Rotation of %s log to %s failed: %s", stream.stem, next_path.name, e)
            self._degraded = True
            return
        if stream.file is not None and not stream.file.closed:
            stream.file.close()
        stream.index = next_index
        stream.path = next_path
        stream.file = new_file
        logger.info("Rotated %s log to %s", stream.stem, stream.path.name)

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
            "lost_records": self._lost,
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
        for stream in (self._scan, self._gnss):
            f = stream.file
            if f is not None and not f.closed:
                f.flush()
                os.fsync(f.fileno())

    def _close_files(self) -> None:
        """Close all open file handles."""
        for stream in (self._scan, self._gnss):
            if stream.file is not None and not stream.file.closed:
                stream.file.close()
            stream.file = None
