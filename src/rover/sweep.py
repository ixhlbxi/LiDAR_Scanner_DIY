"""Sweep planner — 360-then-rewind mast motion (DEC-015, amended 2026-09-23).

Pure decision logic, no I/O: given the stepper's actual position it returns the
next action for the acquisition loop. Position-based on purpose — a failed
step leaves the position unchanged, and the planner simply asks for the same
move again instead of drifting past the sweep end.

Cycle: rest (magnetometer on, platform still) → scan steps up to sweep_deg →
rewind to home in chunks of at most REWIND_CHUNK_DEG → rest → ...

Changelog:
    0.1.0  2026-09-23  Initial (stage 5).
"""

from __future__ import annotations

from dataclasses import dataclass

from rover.config import StepperConfig


@dataclass(frozen=True)
class SweepAction:
    kind: str  # "rest" | "scan_step" | "rewind"
    steps: int = 0
    seconds: float = 0.0


class SweepPlanner:
    """Decides rest → scan_step* → rewind* → rest from the stepper's real position."""

    REWIND_CHUNK_DEG: float = 45.0  # bounds stop latency during a rewind

    def __init__(self, config: StepperConfig) -> None:
        per_rev = config.steps_per_rev
        self._increment = max(1, round(config.step_interval_deg / (360.0 / per_rev)))
        self.sweep_steps = round(config.sweep_deg / 360.0 * per_rev)
        self._rewind_chunk = max(1, round(self.REWIND_CHUNK_DEG / 360.0 * per_rev))
        self._rest_sec = config.rest_before_sweep_sec
        self._phase = "rest"
        self.sweep_index = 0

    def next_action(self, current_step: int) -> SweepAction:
        if self._phase == "rest":
            self._phase = "scan"
            return SweepAction("rest", seconds=self._rest_sec)
        if self._phase == "scan":
            remaining = self.sweep_steps - current_step
            if remaining > 0:
                return SweepAction("scan_step", steps=min(self._increment, remaining))
            self._phase = "rewind"
        # rewind
        if current_step > 0:
            return SweepAction("rewind", steps=-min(self._rewind_chunk, current_step))
        self._phase = "scan"
        self.sweep_index += 1
        return SweepAction("rest", seconds=self._rest_sec)
