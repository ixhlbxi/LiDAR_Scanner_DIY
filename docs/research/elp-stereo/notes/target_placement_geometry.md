# Target placement geometry for camera resection (hypothesis, pending tests 11–14)

**Date:** 2026-09-30
**Status:** Hypothesis. Nothing here is a procedure until bench tests 11–14 below
have run. It feeds the "target field procedure" decision that DEC-036 leaves open,
and it motivates the DEC-036 amendment of 2026-09-30.

Legend: **[Calc]** computed this session from the formulas in §5; **[Assumed]**
an input that a test below must confirm.

## 1. Inputs

- Target: ARM Sky High GCP, 24 in (0.6096 m) 2×2 checker. **[Cited, DEC-036]**
- Mast height 1.5 m above the target plane, level ground unless stated. **[Assumed]**
- Focal length at full resolution (4656×3496): 1,400 / 1,749 / 2,500 px, the three
  candidates in `stereo_calibration_geometry.md`. Test 6 settles it. **[Assumed]**
- Detection floor: ~20 px of foreshortened target height (~10 px per quadrant),
  from the DEC-036 amendment. Test 11 measures it. **[Assumed]**
- LD19: 0.8° between points (4,500 Hz ÷ 10 Hz). Mast step 1.575°
  (`step_interval_deg`, `config/default.toml`). **[Cited]**

## 2. Target size and LiDAR coverage versus distance **[Calc]**

| Distance | Viewing angle | Flat height px (f 1,400 / 1,749 / 2,500) | LD19 points on a flat target | Vertical (rod) target px, f 1,749 |
|---|---|---|---|---|
| 2 m | 36.9° | 205 / 256 / 366 | ~117 | 533 |
| 3 m | 26.6° | 114 / 142 / 203 | ~43 | 355 |
| 4 m | 20.6° | 70 / 88 / 125 | ~20 | 267 |
| 5 m | 16.7° | 47 / 59 / 84 | ~11 | 213 |
| 6 m | 14.0° | 33 / 42 / 60 | ~6 | 178 |
| 7 m | 12.1° | 25 / 31 / 45 | ~4 | 152 |
| 8 m | 10.6° | 19 / 24 / 35 | ~3 | 133 |
| 10 m | 8.5° | 13 / 16 / 22 | ~1 | 107 |
| 12 m | 7.1° | 9 / 11 / 16 | <1 | 89 |
| 15 m | 5.7° | 6 / 7 / 10 | 0 | 71 |
| 20 m | 4.3° | 3 / 4 / 6 | 0 | 53 |

Terrain helps flat targets. With ground tilted 10° toward the scanner: 10 m gives
27 / 34 / 48 px and 15 m gives 15 / 19 / 27 px. With the scanner 3 m above the
target (a bank): 10 m gives 23 / 29 / 42 px.

A taller mast helps less than it seems. Foreshortened height goes roughly as
h / d², so the usable distance grows only with √h: 2 m instead of 1.5 m moves the
flat limit from ~7 m to ~8 m.

## 3. Findings

1. **Flat targets: 4–6 m is the working band, ~7 m the limit on level ground.**
   The 20 px floor falls between 7 and 9 m, depending on the true focal length.
   Inside 3 m the target sits more than ~27° below the horizon, which is out
   toward the edge of the wide lens where the distortion model is weakest and the
   rover frame may occlude it.
2. **"Bearing plus LD19 plane-fit range" only works to ~5 m on flat targets.**
   A flat target collects ~11 LD19 points at 5 m, ~4 at 7 m and ~1 at 10 m.
   Fitting the surrounding ground and intersecting the camera ray with it does
   not rescue longer ranges: at a viewing angle α, range error is height error ÷
   sin α, so 1 cm of plane height error becomes ~7 cm of range at 8.5°.
3. **Elevation is the weak observable.** It inherits the MPU-9250's levelling
   error (tenths of a degree) and flat-target foreshortening. Resect on azimuth.
   Take height from GNSS or the LD19 ground under the scanner.
4. **The mast, not the camera, likely dominates bearing error.** The camera
   measures ~0.01° (~2 mm at 10 m). Each target, however, is imaged at a different
   mast angle from an open-loop stepper at 0.1125° per microstep (DEC-016/017), and
   microstep positions are not evenly spaced. A 0.05–0.1° mast error is
   ~9–17 mm at 5–10 m. That still fits the ±5–10 cm budget, but the system-level
   bearing figure should be quoted as the mast figure until test 12 says otherwise.
5. **Heading-only is easy and prefers distance.** When GNSS gives position, one
   target sets heading, and heading error falls as lateral error ÷ distance.
   A rod target at 15–20 m (53–71 px) is ideal.

## 4. Provisional placement rules (to be confirmed)

- **Position and heading from targets:** 3 flat targets at 4–6 m, at similar
  distances, about 120° apart; a 4th is the check.
- **Scanner inside the target triangle.** Bearings-only resection is singular when
  the station lies on the circle through the three targets. Standing inside the
  triangle keeps it well clear of that circle.
- **Beyond ~7 m on level ground:** use rods, or don't use that target for
  position.
- **Heading only (GNSS fixed):** one target, as far away as can still be detected.
- **Share frames when you can.** With ~106° HFOV (if 118° is diagonal), two targets
  60–90° apart can appear in one image. Their angle apart then has no mast error
  in it. This trades against the 120° spread, and test 14 decides the balance.
- **Field practice:** clear a strip toward the scanner; keep the sun behind the
  scanner to limit sheen on the black quadrants; fly the drone before remounting
  any shared target on a rod.

## 5. Formulas (to recompute when test 6 fixes f)

With mast height h, horizontal distance d, target side L, focal length f px,
LD19 point spacing δ = 0.8°, and mast step s = 1.575°:

- Viewing angle α = atan(h / d) (+ ground tilt toward the scanner).
- Slant range r = √(d² + h²).
- Flat target, foreshortened height px ≈ f · L · sin α / r.
- Vertical target px ≈ f · L / d.
- LD19 points on a flat target ≈ [atan(h/(d − L/2)) − atan(h/(d + L/2))] / δ ×
  (L / d) / s, both angles in radians.
- Lateral error from bearing error σθ ≈ d · σθ.
- Range error from ray-plane intersection ≈ σz / sin α.

## 6. Bench tests (continue the numbering in `REPORT.md`)

| # | Test | Method | Answers |
|---|---|---|---|
| 11 | Flat-target detection floor | After test 6. Lay a Sky High target flat, 1.5 m mast, level ground, at 3, 5, 7 and 9 m; repeat at 7 and 9 m with the mast at 2 m. 20 captures each, sun behind and sun ahead. Run the checker detector; record detection rate and saddle-point σ | Real px floor and flat-target range; how much sheen and mast height matter |
| 12 | Mast bearing repeatability | Vertical target fixed at ~10 m. Image it after 20 full rotations returning to the same step index; then step through the 16 microsteps of one full step, imaging at each | Bearing σ from the mast; whether microstep error repeats and can be tabled out |
| 13 | Ground-plane range | Flat target with a cleared patch at 5, 7 and 9 m. Intersect the camera ray with the LD19 ground-plane fit; compare with taped or surveyed distance | Whether ray-plane range is usable beyond 5 m or the ~5 m limit stands |
| 14 | Resection geometry | Open sky, RTK fixed, surveyed nails. (a) 3 targets at 4–6 m, ~120° apart, scanner inside the triangle; (b) same targets with the scanner near their circle; (c) two targets sharing one frame. Resect each and compare to RTK | Accuracy of the recommended layout; danger-circle penalty; value of shared frames |

Test 14 is the "open-sky resection proof" already in ROADMAP v1.1, with the
layout variants added. Test 10 (LD19 on a target plate) still applies for
vertical targets.
