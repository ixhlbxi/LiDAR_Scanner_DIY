"""SweepPlanner — pure decision logic for the 360-then-rewind sweep (DEC-015 amended)."""

from __future__ import annotations

from rover.config import StepperConfig
from rover.sweep import SweepAction, SweepPlanner


def _cfg(sweep_deg=9.0, step_interval_deg=1.125, rest=0.5) -> StepperConfig:
    return StepperConfig(
        enabled=True,
        steps_per_rev=3200,
        rpm=1.0,
        step_interval_deg=step_interval_deg,
        direction_pin=17,
        step_pin=27,
        enable_pin=22,
        sweep_deg=sweep_deg,
        rewind_rpm=10.0,
        rest_before_sweep_sec=rest,
    )


def _run(planner: SweepPlanner, n: int) -> list[SweepAction]:
    """Simulate a perfect stepper for n actions."""
    pos = 0
    out = []
    for _ in range(n):
        a = planner.next_action(pos)
        out.append(a)
        pos += a.steps
    return out


def test_rest_then_scan_then_rewind_then_rest():
    p = SweepPlanner(_cfg())  # 9° sweep = 80 steps, 10-step increments
    acts = _run(p, 12)
    assert acts[0] == SweepAction("rest", seconds=0.5)
    assert [a.kind for a in acts[1:9]] == ["scan_step"] * 8
    assert all(a.steps == 10 for a in acts[1:9])
    assert acts[9] == SweepAction("rewind", steps=-80)  # 80 steps < one 45° chunk (400)
    assert acts[10] == SweepAction("rest", seconds=0.5)
    assert acts[11].kind == "scan_step"
    assert p.sweep_index == 1


def test_last_increment_is_clamped_to_sweep_end():
    p = SweepPlanner(_cfg(sweep_deg=10.0))  # 10° = 88.9 → 89 steps
    acts = _run(p, 11)
    scan = [a.steps for a in acts if a.kind == "scan_step"]
    assert sum(scan) == 89
    assert scan[-1] == 9


def test_full_360_never_exceeds_one_turn_and_rewinds_in_45deg_chunks():
    p = SweepPlanner(_cfg(sweep_deg=360.0, step_interval_deg=1.575))  # 3200 steps, 14/step
    pos = 0
    peak = 0
    rewinds = []
    for _ in range(400):
        a = p.next_action(pos)
        pos += a.steps
        peak = max(peak, pos)
        if a.kind == "rewind":
            rewinds.append(a.steps)
        if p.sweep_index == 1:
            break
    assert peak == 3200
    assert pos == 0
    assert all(-400 <= s < 0 for s in rewinds)  # 45° = 400 steps
    assert sum(rewinds) == -3200


def test_planner_is_position_based():
    """A step that fails leaves the position unchanged; the planner must ask
    for the same increment again, never assume the move happened (Review Focus 3)."""
    p = SweepPlanner(_cfg())
    assert p.next_action(0).kind == "rest"
    first = p.next_action(0)
    again = p.next_action(0)  # the move above failed: still at 0
    assert first == again == SweepAction("scan_step", steps=10)
    # A position past the end (should never happen, but must not scan further)
    assert p.next_action(95).kind == "rewind"


def test_zero_rest_still_emits_rest_action():
    """rest_before_sweep_sec = 0 still yields a rest action (the loop logs sweep_start there)."""
    p = SweepPlanner(_cfg(rest=0.0))
    assert p.next_action(0) == SweepAction("rest", seconds=0.0)
