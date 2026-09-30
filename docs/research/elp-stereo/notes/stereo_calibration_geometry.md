# Stereo calibration, target-detection accuracy and LiDAR-camera extrinsics for the ELP IMX298 stereo + LD19 rotating scanner

Legend. **[Cited]** means the claim comes from a linked source. **[Calc]** means I calculated it (the Python was run in this session and the numbers are reproduced below). **[Textbook]** means standard projective-geometry or photogrammetry fact, stated from background knowledge without a fetched source this session. Confidence is H, M or L.

Common inputs to every calculation:
- IMX298 active array 4656 x 3496 at 1.12 um pixels. That makes the sensor 5.215 x 3.916 mm, diagonal 6.521 mm, i.e. a 1/2.8" class sensor. **[Calc]**
- Rectilinear focal length from a 118 deg FOV:
  - If 118 deg is the horizontal FOV: f = (4656/2) / tan(59 deg) = **1399 px (1.57 mm)**.
  - If 118 deg is the diagonal FOV: f = (5820/2) / tan(59 deg) = **1749 px (1.96 mm)**. **[Calc]**
- **Conflicting vendor data.** ELP listings describe the 118 deg "no distortion" module as a **2.8 mm** lens ([ELP/Amazon listing, via search summary](https://www.amazon.com/ELP-Raspberry-118degree-Distortion-Industrial/dp/B0C289GYVZ)).
  - 2.8 mm / 1.12 um = **2500 px**. On this sensor a rectilinear 2.8 mm lens gives only 86 deg HFOV and 99 deg DFOV.
  - An equidistant (f-theta) mapping with 118 deg HFOV gives f = 2328 / 1.0297 rad = **2261 px**. **[Calc]**
  - So the real centre focal length probably lies somewhere in **1400-2500 px**. It must be measured by calibration.
  - The stated "118 deg" and "2.8 mm" cannot both hold for a truly rectilinear lens on this sensor. Either the lens has substantial barrel distortion, which is plausible since M12 "low distortion" is marketing, or the FOV was quoted for a different sensor format.
- 6 mm M12 lens: f = 6 / 0.00112 = **5357 px**. HFOV is 47.0 deg and VFOV 36.1 deg, so it is a narrow lens. **[Calc]**
- Baseline B = 0.165 m.

---

## Q1. Stereo depth error dZ = Z^2 * d_disp / (f_px * B). Are the numbers right, and is 0.2 px a realistic disparity precision?

### Takeaway
The formula and the quoted numbers are correct: 2.2 / 1.7 cm at 5 m and 19.5 / 15.6 cm at 15 m for f = 1400 / 1750 px, and 0.6 cm / 5.1 cm for 6 mm. Two caveats:
- The true f may be nearer 2200-2500 px (see the common inputs), which would make the stock lens about 1.5x better.
- 0.2 px is realistic-to-optimistic for triangulating well-resolved checkerboard corners. It is optimistic for dense SGBM on natural scenes, where 0.3-1 px effective is more typical.

A bigger threat than matching noise is **mechanical stability of the stereo extrinsics**. Keeping the systematic disparity bias under 0.2 px needs relative yaw stable to about **0.008 deg (0.14 mrad)**.

### Cited Findings
- For a carefully calibrated stereo setup under real-world conditions, Pinggera, Pfeiffer, Franke and Mester (ECCV 2014, "Know Your Limits: Accuracy of Long Range Stereoscopic Object Measurements in Practice") report a "consistent error limit of 1/10 pixel" for long-range object disparity measurement ([Springer](https://link.springer.com/chapter/10.1007/978-3-319-10605-2_7), abstract via search summary). This is an object-level, carefully optimised result, not per-pixel dense SGBM.
- The Middlebury and KITTI benchmarks "do not sufficiently treat local sub-pixel matching accuracy". Dedicated sub-pixel interpolation functions for SGM have been proposed because standard interpolation is a limitation ([ResearchGate: New Sub-Pixel Interpolation Functions for SGM](https://www.researchgate.net/publication/292150125_New_Sub-Pixel_Interpolation_Functions_for_Accurate_Real-Time_Stereo-Matching_Algorithms); [ScienceDirect: Improving sub-pixel accuracy for long range stereo](https://www.sciencedirect.com/science/article/abs/pii/S1077314211001792)).
- Chessboard corners refine more accurately than ArUco-marker corners, "since each corner is surrounded by two black squares". ChArUco interpolated corners reach "very accurate subpixel accuracy" ([OpenCV ChArUco tutorial](https://docs.opencv.org/3.4.20/df/d4a/tutorial_charuco_detection.html)).
- A user calibrating a 120 deg camera with `cv::calibrateCamera` and the rational model reported about 0.15 px reprojection RMS ([OpenCV Q&A](https://answers.opencv.org/question/218169/opencv-fisheye-calibration-fails/), via search summary). This is an empirical single report.

### Inferences
- **[Calc, H] Formula derivation.** Z = f*B/d, so |dZ/dd| = f*B/d^2 = Z^2/(f*B), which gives dZ = Z^2 * dd / (f*B). This is the standard first-order result and it is correct.
- **[Calc, H] Depth error dZ for B = 0.165 m:**

| f (px) | dd | 5 m | 10 m | 15 m | 20 m | 30 m |
|---|---|---|---|---|---|---|
| 1399 (118 deg HFOV rectilinear) | 0.1 px | 1.1 cm | 4.3 cm | 9.7 cm | 17 cm | 39 cm |
| 1399 | **0.2 px** | **2.2 cm** | 8.7 cm | **19.5 cm** | 35 cm | 78 cm |
| 1399 | 0.5 px | 5.4 cm | 22 cm | 49 cm | 87 cm | 1.95 m |
| 1399 | 1.0 px | 10.8 cm | 43 cm | 97 cm | 1.73 m | 3.9 m |
| 1749 (118 deg DFOV) | **0.2 px** | **1.7 cm** | 6.9 cm | **15.6 cm** | 28 cm | 62 cm |
| 1749 | 1.0 px | 8.7 cm | 35 cm | 78 cm | 1.39 m | 3.1 m |
| 2500 (if the lens really is 2.8 mm) | 0.2 px | 1.2 cm | 4.8 cm | 10.9 cm | 19 cm | 44 cm |
| 5357 (6 mm) | **0.2 px** | **0.6 cm** | 2.3 cm | **5.1 cm** | 9.1 cm | 20 cm |
| 5357 | 1.0 px | 2.8 cm | 11 cm | 25 cm | 45 cm | 1.0 m |

  - The claim is verified: about 2 cm at 5 m and 15-20 cm at 15 m (stock), and about 0.6 cm at 5 m and about 5 cm at 15 m (6 mm).
- **[Calc/Textbook, M] Is 0.2 px realistic for checkerboard-corner triangulation?**
  - Disparity is a difference of two independent corner measurements, so sigma_d = sqrt(2) * sigma_corner. It also picks up residual rectification or epipolar error.
  - With a per-image corner sigma of about 0.1 px, typical for well-resolved squares (at least 15-20 px) with cornerSubPix, sigma_d is about 0.14 px, so 0.2 px is attainable.
  - At 15 m a 20 cm board is only about 19-23 px wide (see Q2). The corners are then poorly conditioned: blur, 1.12 um pixel noise and MJPEG compression all matter. Budget 0.3-0.5 px there, and expect 0.2 px only for large targets or close range.
  - This is my estimate; no source measured IMX298/MJPEG specifically.
- **[Inference, M] Dense SGBM on natural scenes.**
  - OpenCV SGBM outputs disparity in 1/16 px steps, but that is quantisation, not accuracy.
  - Parabola sub-pixel fits show "pixel-locking" bias, per the sub-pixel SGM literature above.
  - On textured natural scenes expect **0.3-1 px** effective. That means roughly 0.3-1 m depth error at 15 m with the stock lens.
  - Dense stereo on this rig is therefore a *qualitative* or near-range cross-check only, not a metric one beyond about 5-8 m.
- **[Calc, H] Sensitivity to baseline stability.**
  - A relative rotation error delta (rad) about the vertical axis between the two cameras shifts every disparity by about f*delta px. This is a systematic error that does not average out.
  - For 0.2 px: delta < 0.2/1399 = 1.4e-4 rad = **0.008 deg** (stock lens), or 0.2/5357 = 3.7e-5 rad = **0.002 deg** (6 mm).
  - M12 lens barrels that rotate in their threads, PCB flex and thermal drift can easily exceed this.
  - Recommendations: a rigid metal bracket, thread-locked lenses, and a periodic check of stereo yaw against LiDAR ranges to planar surfaces at known distance, as an online correction.
- **[Calc, M] Other factors.**
  - With a 1.57-2.5 mm focal length at f/2-ish, hyperfocal distance is short, so depth of field is fine.
  - A 6 mm lens focused at 15 m will blur a calibration board at 1-2 m. You would need a larger board (A1/A0) at 3-6 m, or to calibrate at operating focus with a far board.

### Gaps
- No published measurement of disparity or corner precision specifically for the IMX298 / ELP UVC MJPEG pipeline. The 1.12 um pixels have high read noise and JPEG will add bias. Measure empirically: fixed rig, 50 repeated captures of a static target, standard deviation of the corners.
- The ELP lens's true focal length and projection type could not be confirmed from vendor data (2.8 mm vs 118 deg are inconsistent).

---

## Q2. Angular resolution (1/f_px) and pixels needed on target for detection

### Takeaway
- 1/f_px radians is correct at the image centre of a rectilinear lens: 0.041 deg/px at f = 1399 and 0.033 deg/px at f = 1749.
- The naive HFOV/width (0.025 deg/px) is the *average* and *understates* the centre IFOV for a rectilinear lens. It happens to be exactly right for an equidistant (fisheye-like) mapping.
- A 20 cm board at 15 m is 19-23 px wide with the stock lens, too small for a multi-square checkerboard or ChArUco. Detection guidance points to **at least 5 px per square/bit for robust decoding** (2 px absolute Nyquist floor) and 10-20+ px per square for good sub-pixel corners.
- For GCPs at 5-30 m, use a single large 2x2 "X" (saddle) target, 40-60 cm, optionally with a large low-bit tag for ID. Do not use a small multi-square board.

### Cited Findings
- AprilTag guidance: the recommended value is **5 pixels per bit**; 2 px per bit is the lowest (Nyquist) but 5 is recommended "to avoid detection pitfalls" ([Optitag: Designing the perfect AprilTag](https://optitag.io/blogs/news/designing-your-perfect-apriltag)). Other sources quote about 10 px per tag "step" as a common minimum ([UCLA LEMUR: Determining the Ideal Resolution for AprilTag Detection](https://uclalemur.com/blog/determining-the-ideal-resolution-for-apriltag-detection), via search summary).
- Families with fewer bits are readable at longer range for the same physical size ([Laserscanning Europe: AprilTag size](https://www.laserscanning-europe.com/en/what-apriltags-what-apriltag-size-should-use), via search summary).
- AprilTag localisation accuracy varies substantially between detector libraries. A dedicated edge-refinement method was proposed to improve it ([Kallwies et al., IEEE ICRA 2020, "Determining and Improving the Localization Accuracy of AprilTag Detection"](https://ieeexplore.ieee.org/document/9197427/)).
- ChArUco: after detection with homography, OpenCV recommends disabling ArUco corner refinement and applying subpixel refinement to the interpolated chessboard corners ([OpenCV ChArUco tutorial](https://docs.opencv.org/3.4.20/df/d4a/tutorial_charuco_detection.html)).

### Inferences
- **[Textbook/Calc, H] Centre IFOV.**
  - For a rectilinear lens, x = f*tan(theta), so dtheta/dx = cos^2(theta)/f. At theta = 0 that is 1/f.
  - Towards the edge each pixel subtends *less* angle, by cos^2(59 deg) = 0.265. So the edges are about 3.8x finer than the centre, which is why the average (118/4656 = 0.0253 deg/px) is smaller than the centre value.
  - Results: f = 1399 gives 0.715 mrad = **0.0410 deg/px**; f = 1749 gives 0.572 mrad = **0.0328 deg/px**; 6 mm (5357) gives 0.187 mrad = **0.0107 deg/px**. The claim is verified.
  - If the lens is closer to equidistant, the IFOV is about uniform at 0.0253 deg/px (f of about 2261). Again, this has to be measured.
- **[Calc, H] Width of a 20 cm target (subtended angle = 2*atan(0.1/Z)):**

| Z | angle | px @ f=1399 | px @ f=1749 | px @ f=5357 |
|---|---|---|---|---|
| 5 m | 2.29 deg | 56 | 70 | 214 |
| 10 m | 1.15 deg | 28 | 35 | 107 |
| 15 m | **0.76 deg** | **18.7** | **23.3** | **71** |
| 20 m | 0.57 deg | 14 | 17.5 | 54 |
| 30 m | 0.38 deg | 9.3 | 11.7 | 36 |

  - The claim is verified: 0.76 deg, about 19-23 px (stock), about 70 px (6 mm).
- **[Inference, M] Consequences for detection.**
  - A 20 cm board divided into 4 squares across has 4.7-5.8 px squares at 15 m (stock lens). `findChessboardCorners` (which needs the whole grid and quad detection) will fail or be unreliable at that size. `cornerSubPix` with the default 11x11 window overlaps neighbouring corners when squares are under about 11 px.
  - AprilTag 36h11 is 10 cells wide including borders, so at 18.7 px it gets about 1.9 px per cell, below Nyquist. An ArUco 4x4 (6 cells with border) gets about 3.1 px per cell: marginal.
  - For a 5 px/bit tag36h11 at 15 m with f = 1399 you need a tag of 10 * 5 / 1399 * 15 = **54 cm**.
  - For a 2x2 X-target with 20 px quadrants (robust saddle-point fit) at 30 m with f = 1399: 2 * 20 * 30 / 1399 = **86 cm**; at 15 m, **43 cm**.
- **[Inference, M] Typical sub-pixel precision.**
  - Well-imaged checkerboard or ChArUco corners with cornerSubPix: about 0.03-0.1 px. The best reported calibration RMS values of 0.1-0.2 px imply per-corner noise in this range.
  - Small or blurry targets: 0.2-0.5 px. AprilTag corners from edge fitting: 0.1-0.5 px depending on library and refinement (Kallwies et al.).
  - A 0.2 px corner error equals 0.008 deg (stock) or 2.1 mm at 15 m. A 0.5 px error is 5.4 mm at 15 m. **Bearing precision is not the limiting factor for resection**; LiDAR range and target-centre definition are (see Q6).
- **[Inference, M] Target recommendation.** Use a large high-contrast 2x2 checker "X" (a photogrammetric checker target) on a flat plate mounted on the rod, and fit the saddle point locally (OpenCV `cornerSubPix` with a window about half the quadrant size, or a Förstner or saddle-point operator). ID can come from a coarse ArUco 4x4 beside it, or from known approximate azimuth.

### Gaps
- No controlled study found that gives `findChessboardCorners` success rate against square size in pixels. The "about 5-10 px per square minimum" is practitioner experience, not a cited benchmark.
- Kallwies et al.'s numerical results were not extracted (paywalled).

---

## Q3. Checkerboard corners vs circular / bull's-eye targets: eccentricity bias

### Takeaway
The principle is correct: a checker corner is a projective point, while an ellipse centre is not the projected circle centre. For **20 cm targets at 10-20 m the bias is negligible**:
- 0.02-0.07 px with the stock lens, 0.06-0.27 px with a 6 mm lens.
- That is at most about 0.5 mm, or at most about 10 arcsec, at the target.
- Closed form: bias_px is about f * R^2 * sin(t) * cos(t) / Z^2.

Prefer checker/X targets for detection robustness and ease of saddle-point location at low pixel counts, not because of eccentricity bias.

### Cited Findings
- "The elliptical image centre" does not coincide with "the true imaged circle centre" under perspective projection. The eccentricity "is larger than usually assumed, and must be compensated for high-accuracy applications". Spherical targets "do not show better results than circular targets" ([Luhmann 2014, ISPRS Archives XL-5, 363](https://isprs-archives.copernicus.org/articles/XL-5/363/2014/); journal version [Photogrammetric Record 29(148), 2014](https://onlinelibrary.wiley.com/doi/10.1111/phor.12084)).
- Eccentricity is zero at the principal point and increases with imaging angle; the error is radial, pointing away from the principal point ([search summary of Luhmann 2014 and related work](https://www.researchgate.net/publication/270912494_Eccentricity_in_images_of_circular_and_spherical_targets_and_its_impact_on_spatial_intersection)). This statement applies to a target plane parallel to the image plane; tilted targets produce non-zero bias even on-axis (my simulation below).
- Later work continues to model and correct this, for example [Spherical target eccentricity correction (ISPRS J. 2025)](https://www.sciencedirect.com/science/article/pii/S0924271625004617) and [Eccentricity Correction Methods for Circular Targets in Perspective Projection (Metrology 2026)](https://doi.org/10.3390/metrology6020028). Contents were not read beyond titles.
- Luhmann (2014) computes eccentricity by projecting points on the circle and fitting a least-squares ellipse ([ISPRS archive](https://isprs-archives.copernicus.org/articles/XL-5/363/2014/)). I used the same numerical method below.

### Inferences
- **[Calc, H] Numerical simulation.**
  - Method: circle radius R = 0.10 m (20 cm diameter), 20,000 perimeter points projected with a pinhole camera. Ellipse centre taken as the midpoint of the x-extrema; the configuration is symmetric in y. Bias is measured relative to the projected circle centre.
  - t = target tilt from fronto-parallel; "off" = target direction off the optical axis.

| f | Z | t = 30 deg, on-axis | t = 45 deg, on-axis | t = 60 deg, on-axis | t = 45 deg, 40 deg off-axis |
|---|---|---|---|---|---|
| 1400 | 5 m | 0.24 px (0.87 mm) | **0.28 px** (1.0 mm, 41") | 0.24 px | 0.05 px |
| 1400 | 10 m | 0.06 px (0.43 mm) | **0.070 px** (0.50 mm, 10") | 0.06 px | 0.011 px |
| 1400 | 20 m | 0.015 px | **0.0175 px** (0.25 mm, 2.6") | 0.015 px | 0.003 px |
| 5360 | 10 m | 0.23 px | **0.27 px** (0.50 mm) | 0.23 px | 0.043 px |
| 5360 | 20 m | 0.058 px | **0.067 px** (0.25 mm) | 0.058 px | 0.011 px |

  - These match the closed-form approximation bias_px = f * R^2 * sin(t) * cos(t) / Z^2 exactly. For example, 1400 * 0.01 * 0.5 / 100 = 0.070 px.
  - In object space: bias is about R^2 * sin(t) * cos(t) / Z, i.e. **0.5 mm at 10 m** for a 20 cm target at 45 deg. It is independent of lens and falls as 1/Z.
  - It is maximal at t = 45 deg and grows as R^2, so a 60 cm target has 9x the bias (4.5 mm at 10 m).
- **[Inference, H] Conclusion for this project.**
  - The eccentricity bias (at most about 1 mm, at most about 40 arcsec at 5 m) is one to two orders of magnitude below the LD19's range noise (sigma 10 mm, accuracy ±45 mm; see Q6) and the ±5-10 cm system target.
  - It is only worth correcting at close range with large circular targets, or for calibration-grade work (for example circle-grid intrinsic calibration at 0.5-2 m, where it does matter).
  - Checker/X targets are still recommended, because the saddle point stays well-defined under blur, defocus and JPEG ringing, and does not depend on the threshold level. Ellipse fitting on a 20-pixel blob is sensitive to thresholding and illumination gradients, which are likely larger error sources than eccentricity.

### Gaps
- Could not extract Luhmann's own numerical tables; the PDF text was not parseable in this environment. The simulation above substitutes for them.
- The rod-mounted target's physical centre versus the survey-point offset (plumb, tilt of rod) will dominate at this accuracy level. Not researched.

---

## Q4. Pure rotation gives no depth; does the off-axis camera offset give usable parallax?

### Takeaway
Confirmed. Under pure rotation about the camera centre, images are related by the depth-independent homography H = K * R * K^-1, so SfM cannot recover depth.

The cameras sit about 80-90 mm off the rotation axis, so rotating the platform creates a baseline b = 2r * sin(dpsi/2): about 47 mm at 30 deg and 90 mm at 60 deg for r = 0.09 m. That is small and depends on the encoder, and the fixed 165 mm stereo pair is the better depth source. Rotational parallax is still useful for **calibrating the camera's offset from the axis** and as extra views for colorisation.

### Cited Findings
- No external source fetched this session for the pure-rotation homography. It is a standard result (Hartley and Zisserman, *Multiple View Geometry*, chapter 8, "infinite homography" / rotating camera).

### Inferences
- **[Textbook, H]** For camera centre C fixed and rotation R, x' = K * R * K^-1 * x for every scene point regardless of depth. The epipole is undefined because there is no translation, so triangulation is degenerate. Panorama stitching relies on exactly this.
- **[Calc, M] Parallax from the axis offset.**
  - Camera at radius r from the vertical rotation axis; the platform rotates by dpsi between two images that both see the point. The chord baseline is b = 2r * sin(dpsi/2).
  - Approximate disparity is f * b_perp / Z, where only the component of b perpendicular to the line of sight counts. The numbers below use b and are therefore upper bounds.
  - r = 0.05 m, dpsi = 60 deg: b = 50 mm, giving about 14 px at 5 m and 4.7 px at 15 m (f = 1400).
  - r = 0.09 m, dpsi = 60 deg: b = 90 mm, giving about 25 px at 5 m and 8.4 px at 15 m.
  - With a 118 deg FOV, the same point stays in view across about 100 deg of rotation, so baselines of up to about 2 * 0.09 * sin(50 deg) = 138 mm are available. That is comparable to the stereo baseline, but mostly along the viewing direction rather than across it for points near the image centre.
  - Accuracy depends on knowing the rotation angle. An encoder or step-count error of 0.05 deg at f = 1400 is 1.2 px of apparent shift. A pure-rotation error is a homography error, and it is inseparable from parallax unless jointly estimated in bundle adjustment.
- **[Inference, M] Use in practice.**
  - Jointly bundle-adjust all images from one station with a model of "camera rigidly mounted at unknown T_platform_cam, platform rotates about a fixed axis by angle psi_i (initialised from stepper counts)".
  - This recovers T_platform_cam, and with it the camera offset from the axis, and improves psi_i. It then gives multi-view depth with an effective baseline of up to about 140 mm plus the 165 mm stereo baseline.
  - This is essentially what photogrammetric panoramic-station work does. It is worth doing only if dense stereo depth is really needed; the LiDAR already gives depth.

### Gaps
- Actual camera placement relative to the axis (one camera on the axis vs. both symmetric) is unknown. If one camera sits near the axis, that camera gets no parallax at all.

---

## Q5. OpenCV camera model, calibration practice, reprojection error, stereo calibration, rolling shutter, lens stability

### Takeaway
For a nominal 118 deg "low distortion" M12 lens, start with OpenCV's pinhole model with `CALIB_RATIONAL_MODEL` (k1-k6 plus p1, p2) via `calibrateCamera`, or ideally `calibrateCameraCharuco` / ChArUco. Compare it against the fisheye (Kannala-Brandt) model on held-out images.

The pinhole family, rational model included, is generally usable to about 120 deg; beyond that fisheye/KB is needed. 118 deg is at that boundary, and the "2.8 mm vs 118 deg" inconsistency suggests the lens is not rectilinear, so test both.

Calibration practice:
- Use a ChArUco board, 25+ images, full-frame coverage including the corners, and tilts up to about 45 deg.
- Expect about 0.2-0.5 px RMS. Under 1 px is "good" and 0.3-0.8 px is typical.
- Calibrate intrinsics per camera, then `stereoCalibrate` with `CALIB_FIX_INTRINSIC`.
- Rolling shutter does not matter if the scene and the platform are stationary during exposure.
- Mechanical stability of the lens and bracket matters a great deal (see Q1).

### Cited Findings
- Pinhole covers up to about 90 deg FOV, "pinhole-wide" (rational) stretches to about 120 deg, and fisheye covers the rest up to 180 deg. The rational form "gives the optimisation more degrees of freedom to bend the projection curve at larger angles" ([CalibrX blog: Pinhole, Wide or Fisheye Camera Models](https://calibrx.io/blog/pinhole-wide-fisheye-camera-models/)). This is a vendor blog; moderate authority.
- A 120 deg camera "works quite well" with `cv::calibrateCamera()` and the rational model, with users reporting about 0.15 px ([OpenCV Q&A forum](https://answers.opencv.org/question/218169/opencv-fisheye-calibration-fails/)). Empirical and anecdotal.
- The Kannala-Brandt model (OpenCV `cv::fisheye`) is a polynomial radial model that omits tangential distortion ([search summary](https://medium.com/@iamgouri180/camera-calibration-with-opencv-a-practical-guide-for-fisheye-and-standard-cameras-2d75fb2830ce); [MATLAB Fisheye Calibration Basics](https://www.mathworks.com/help/vision/ug/fisheye-calibration-basics.html)).
- A review and comparison of wide-angle calibration models and targets exists ([Geometric Wide-Angle Camera Calibration: A Review and Comparative Study, arXiv 2306.09014](https://arxiv.org/pdf/2306.09014)). The PDF was too large to fetch, so its conclusions were not extracted.
- Coverage: "Ensure that the entire image area was covered evenly" and include tilts "up to about 45 degrees" in both x and y ([calib.io knowledge base via search summary: 5 Biggest Calibration Mistakes](https://calib.io/blogs/knowledge-base/5-biggest-calibration-mistakes); [Understanding Reprojection Error](https://calib.io/blogs/knowledge-base/understanding-reprojection-errors)).
- Number of images: "at least 25 snapshots of the ChArUco board to begin". Reprojection error "less than 1 pixel is considered good", with 0.3-0.8 px "typical for a well-executed calibration". A low number alone does not guarantee a good calibration if pose or image coverage is lacking ([Limelight ChArUco calibration docs](https://docs.limelightvision.io/docs/docs-limelight/getting-started/performing-charuco-camera-calibration)).
- ChArUco allows partial or occluded views, which is useful for getting corners into the image edges, and its interpolated corners are accurate ([OpenCV ChArUco tutorial](https://docs.opencv.org/5.0/tutorials/objdetect/charuco_detection/charuco_detection.html)).

### Inferences
- **[Inference, M] Model choice procedure.**
  1. Calibrate with (a) the rational pinhole model with k1-k6, p1, p2, and (b) `cv::fisheye` (KB4).
  2. Compare RMS on a **held-out** image set and inspect residual vectors near the corners. Rational models can overfit and "fold" outside the calibrated region, so ensure the extreme corners are covered.
  3. If both struggle, tools like calib.io's Calib, Kalibr (pinhole-equi, double-sphere) or basalt/camodocal offer extended unified / double-sphere models. Use them only if needed.
- **[Inference, M] You do not need to undistort to rectilinear for colorisation or bearings.** Project LiDAR points with `cv2.projectPoints` (or `cv2.fisheye.projectPoints`), and compute bearings with `cv2.undistortPoints` on detected corners only. Rectifying a 118 deg image to a pinhole view throws away the edges or wastes resolution.
- **[Inference, M] Board and procedure details for this camera.**
  - Use a rigid printed ChArUco on aluminium dibond or glass, sized so each square is at least 20-30 px at the capture distance. Measure the printed square size with calipers.
  - Lock focus before calibrating. These are fixed-focus M12 modules; avoid the "AF" ELP variants for metric work.
  - Fix exposure, gain and white balance through UVC: `v4l2-ctl -c auto_exposure=1` (manual), `white_balance_automatic=0`. Control names vary by driver.
  - Capture at the full 4656x3496 MJPEG. Note that UVC USB 2.0 caps 16MP at a low frame rate, and JPEG artefacts slightly degrade corners. Use the highest JPEG quality available.
- **[Inference, M] Expected RMS.** About 0.2-0.5 px at 16MP / 1.12 um with MJPEG. In angular terms 0.3 px is about 0.012 deg (f = 1400), which is more than adequate.
- **[Inference, H] Stereo calibration.**
  1. Calibrate each camera's intrinsics separately with many images.
  2. Run `cv2.stereoCalibrate(..., flags=cv2.CALIB_FIX_INTRINSIC)` on image pairs where **both** cameras see the board at the same time. For fisheye use `cv2.fisheye.stereoCalibrate`.
  3. Check the rectified epipolar error. Mean |dy| after `stereoRectify` should be about 0.1-0.3 px.
  4. Non-synchronised USB cameras are fine *only* with a stationary board and rig. With the rig on a tripod and the board on a stand, sync is irrelevant.
- **[Inference, H] Rolling shutter.**
  - Pure geometric effect: none if neither the camera nor the scene moves during readout.
  - On the rotating platform, capture only while the stepper is **stopped and settled**. Any residual vibration during an approximately 30-100 ms rolling readout at full resolution produces row-dependent skew.
  - Example: 0.1 deg/s residual rotation over 50 ms is 0.005 deg, about 0.12 px at f = 1400. That is negligible if settled, not if the mast is ringing.
- **[Inference, H] Lens and mount instability.** An M12 lens that rotates slightly in its thread changes the focal length and principal point. A shifted PCB or bracket changes the stereo extrinsics. Apply thread-locker to the lens, use a metal bracket, and re-verify calibration after transport. A quick field check: stereo-triangulate a checker at a LiDAR-measured distance.

### Gaps
- The arXiv 2306.09014 comparative conclusions (which model wins at about 120 deg, and target comparison) were not extracted.
- No ELP-IMX298-specific calibration reports (RMS values, distortion coefficients) were found.

---

## Q6. Resection with two targets (range + bearing, leveled) vs bearings-only, and error propagation

### Takeaway
- **Confirmed for 2D:** with IMU leveling, unknowns are (E, N, heading), plus height if needed. Range and horizontal bearing to 2 known targets give 4 observations for 3 unknowns, a unique solution with 1 redundancy.
- Bearings-only on a leveled instrument needs **3** targets: classic three-point resection (Snellius-Pothenot), which fails when the station lies on the circle through the 3 targets (the "danger circle").
- Full 6-DOF camera-only resection (P3P) gives up to 4 solutions from 3 points; a 4th point makes it unique.
- Aim for 60-120 deg angular separation between targets as seen from the station, ideally about 90 deg.

**Critical correction:** the LD19's specified range is **0.02-12 m**, with ±45 mm accuracy and 10 mm standard deviation. **LiDAR range to targets at 15-30 m is not available.** Even at 5-12 m, angular sampling of about 0.8 deg per point (14 cm spacing at 10 m) gives very few hits on a 20 cm target.

### Cited Findings
- LD19 specifications ([LDROBOT LD19 datasheet v2.6](https://www.ldrobot.com/images/2023/05/23/LDROBOT_LD19_Datasheet_EN_v2.6_Q1JXIRVq.pdf); [Waveshare wiki](https://www.waveshare.com/wiki/DTOF_LIDAR_LD19), via search summary):
  - Measuring range 0.02-12 m.
  - Accuracy ±45 mm (mean of 100 measurements, 300-12000 mm, 70% diffuse reflectivity).
  - Ranging standard deviation 10 mm; resolution 15 mm.
  - 4500 Hz sample rate, 10 Hz sweep, angular resolution at most 1 deg.

### Inferences
- **[Calc, H] LD19 sampling.** 4500 / 10 = 450 points per revolution, i.e. 0.8 deg per point. At 10 m that is 14 cm between points; at 12 m, 17 cm. A 20 cm target at 10 m (1.15 deg) gets **1-2 hits per scan line**, and those are likely mixed or edge returns. The rotating platform adds samples in the other axis, but the within-plane spacing stays fixed.
  - Recommendation: make the LiDAR-side target a flat plate of at least 40-60 cm (several points per line and several lines). Fit a plane, then intersect it with the camera ray through the checker X. This gives range from the plane fit, averaging N points so the effective sigma is about 10 mm / sqrt(N), rather than from a single return.
  - Keep targets within about 10 m. Beyond 12 m, use camera bearings only (3+ targets) or GNSS.
- **[Textbook/Calc, H] Observation counting.**
  - 2D leveled: 3 unknowns (x, y, psi). Each range+bearing target gives 2 observations. One target is underdetermined (the station can be anywhere on a circle, with heading tied to position). Two targets give 4 observations for 3 unknowns.
  - Ranges alone from 2 targets give 2 circle intersections (mirror ambiguity). The bearing difference resolves it, and heading = azimuth(station to target) minus measured bearing.
  - Bearings-only, leveled: each target gives 1 observation, so 3 targets is the minimum (Snellius-Pothenot) and 4 gives redundancy and a check.
  - Unleveled 6-DOF: P3P (Gao et al. / Kneip) gives up to 4 real solutions, so a 4th point is needed for uniqueness. With IMU tilt, OpenCV's `solvePnP` can still be used with a prior, but the 2D formulation is simpler.
- **[Calc, M] Error propagation. Assumes 2 targets, horizontal distances d1 and d2, separation angle gamma at the station, target separation L.**
  - *Bearing noise to lateral error:* sigma_lat = d * sigma_b.
    - sigma_b = 0.02 deg (about 0.5 px at f = 1400): 3.5 mm at 10 m, 7 mm at 20 m.
    - sigma_b = 0.05 deg: 8.7 mm at 10 m, 17.5 mm at 20 m.
    - Camera bearing noise is small compared with LD19 range noise.
  - *Position from two ranges:* the two range lines of position cross at angle gamma. Horizontal position error is about sigma_r / sin(gamma) per axis (standard intersection geometry). With sigma_r of about 10-45 mm and gamma = 90 deg: 1-4.5 cm. With gamma = 30 deg: 2-9 cm. At gamma of 0 or 180 deg it is unstable.
  - *Heading:* in effect it is the rotation that aligns the measured inter-target vector (scanner frame) with the known vector, so sigma_psi is about sqrt(2) * sigma_p_perp / L, where sigma_p_perp is each target's measured position error perpendicular to the inter-target line.
    - L = 10 m, sigma_p_perp = 1 cm: 0.08 deg. L = 10 m, 3 cm: 0.24 deg.
    - L = 20 m, 1 cm: 0.04 deg. L = 20 m, 3 cm: 0.12 deg.
    - L = 30 m, 3 cm: 0.08 deg.
    - A 0.1 deg heading error produces 1.7 cm lateral error at 10 m, 5.2 cm at 30 m. That is significant against a ±5-10 cm target for distant scan points.
  - *Geometry:* gamma about 90 deg minimises position DOP. Larger L minimises heading error. Place targets on roughly orthogonal bearings, as far apart as LiDAR range allows (about 10 m each gives L of about 14 m at gamma = 90 deg).
  - The claim of 60-90 deg separation is reasonable; 60-120 deg is acceptable.
- **[Inference, M] Combining with GNSS.** If the ZED-F9P RTK is fixed (±1-2 cm), position is known and the targets only need to supply heading. Then a single well-measured target at distance d gives heading error of about sqrt(sigma_b^2 + (sigma_pos/d)^2). For sigma_pos = 2 cm and d = 10 m that is about 0.11 deg, and 2+ targets average it down. Resection is then a heading or backsight problem, which is much less demanding.

### Gaps
- LD19 beam divergence, spot size, and behaviour on thin rods or retroreflective tape (saturation, range walk) were not researched. They matter for "range to a target on a rod".
- Rod plumbness and target-centre offset relative to the surveyed point were not researched.

---

## Q7. LiDAR-camera extrinsic calibration tools for a stationary rotating-2D-LiDAR scanner

### Takeaway
Because each station produces a dense, static 3D cloud, **tools built for 3D LiDAR apply once the scanner's own LiDAR-to-rotation-axis calibration is solved**. Best fits:
1. **koide3 `direct_visual_lidar_calibration`**: targetless, handles dense static clouds and pinhole or fisheye cameras, ROS1/ROS2.
2. **Checkerboard/plane-based methods** on the per-station cloud: ACFR `cam_lidar_calibration`, MATLAB Lidar Camera Calibrator, or a custom point-to-plane solver.
3. **Zhang and Pless 2004**, if calibrating directly against individual 2D scan lines, for example before the rotating-cloud geometry is trusted.

Kalibr is for camera intrinsics, stereo and camera-IMU calibration, not LiDAR. ankitdhall `lidar_camera_calibration` is ROS1, 3D-3D, ArUco-based and dated.

### Cited Findings
- **Zhang and Pless 2004** (IROS, pp. 2301-2306): "Extrinsic calibration of a camera and laser range finder (improves camera calibration)". The system observes a planar pattern in several poses; the laser line on the plane gives point-on-plane constraints; a closed-form solution is followed by nonlinear refinement. Demonstrated with a SICK PLS 2D scanner ([WUSTL open scholarship](https://openscholarship.wustl.edu/cse_research/1103/)).
- Other 2D-LRF/camera methods: point-to-line constraint ([ScienceDirect 2012](https://www.sciencedirect.com/science/article/pii/S1877705812006790)); a plane with a triangular hole ([IJCAS](https://link.springer.com/article/10.1007/s12555-012-0619-7)); 2D LRF to **fisheye** camera ([Springer 2014](https://link.springer.com/chapter/10.1007/978-3-319-14364-4_89)); one-shot with vertical planes ([JEET 2019](https://link.springer.com/article/10.1007/s42835-019-00087-z)).
- **koide3 direct_visual_lidar_calibration**: target-less, single-shot (at minimum one point cloud / image pair), automatic (no initial guess), and supports spinning and non-repetitive LiDARs and pinhole, fisheye and omnidirectional cameras. It uses pixel-level direct registration, claimed more robust than edge-based methods, and densifies LiDAR data into a dense cloud with "rich geometrical and surface texture information" ([GitHub](https://github.com/koide3/direct_visual_lidar_calibration); [docs](https://koide3.github.io/direct_visual_lidar_calibration/); [paper arXiv 2302.05094](https://arxiv.org/pdf/2302.05094)).
- **ACFR cam_lidar_calibration** (ITSC 2021): chessboard-based (example A1 board, 95 mm squares, 7x5 inner vertices), with optimised sample selection. Demonstrated with a Velodyne VLP-16 and a Baraja Spectrum-Scan, both 3D LiDARs ([GitHub](https://github.com/acfr/cam_lidar_calibration)).
- **ankitdhall lidar_camera_calibration**: ROS package using 3D-3D point correspondences, with ArUco markers on boards hung from a corner ([GitHub](https://github.com/ankitdhall/lidar_camera_calibration)).
- MFCalib is another targetless single-shot method using multi-feature edges ([arXiv 2409.00992](https://arxiv.org/pdf/2409.00992)). A LiDAR-fisheye calibration method is in [Appl. Sci. 2025](https://doi.org/10.3390/app15042044). Joint camera-intrinsic plus LiDAR-extrinsic calibration is in [arXiv 2202.13708](https://arxiv.org/pdf/2202.13708).

### Inferences
- **[Inference, M] Suitability for this rig.**
  - Order of calibrations:
    1. **LiDAR to rotation axis** (the rotating-2D-scanner "internal" calibration: LD19 plane offset and tilt relative to the axis). Scan planar walls and a room and minimise plane thickness.
    2. **Camera intrinsics and stereo** (OpenCV / Kalibr).
    3. **Camera to platform** (T_platform_cam).
  - Both sensors ride the platform, so T_lidar_cam is fixed. Each image at angle psi_i has pose R_z(psi_i) * T_platform_cam.
  - Tool fit:

| Tool | Input LiDAR | Target | Fit here |
|---|---|---|---|
| Zhang and Pless 2004 (implement yourself, or MRPT / various GitHub ports) | 2D scan lines | planar checkerboard | Good: native 2D; needs many board poses; per-line data is sparse (0.8 deg spacing) |
| koide3 direct_visual_lidar_calibration | dense static cloud | none (natural scene) | **Very good**: static dense cloud per station is its ideal input; uses LiDAR intensity (the LD19 provides an intensity/confidence byte) and supports fisheye |
| ACFR cam_lidar_calibration | 3D cloud (ROS) | A1 chessboard | Usable with the per-station cloud exported as a ROS message; ROS1 overhead |
| MATLAB Lidar Camera Calibrator (Lidar Toolbox) | 3D cloud | checkerboard | Usable, commercial; board-plane plus edge fitting on dense clouds |
| ankitdhall lidar_camera_calibration | 3D (Velodyne) | ArUco boards | Poor fit; dated ROS1 |
| Autoware CalibrationToolkit | 3D (Velodyne) | checkerboard | Legacy; not recommended |
| Kalibr | none (camera-IMU / multi-camera) | AprilGrid | Use for stereo intrinsics/extrinsics and camera-IMU; not LiDAR |

- **[Inference, M] Simplest robust DIY route.**
  1. Place a large checkerboard (about 1 m) at 4-6 poses, 2-8 m away.
  2. For each pose, capture a full station scan plus images.
  3. The camera gives the board pose from `solvePnP`, so a plane (n_c, d_c) in the camera frame.
  4. The LiDAR cloud gives the segmented board points.
  5. Solve for T_cam_lidar by minimising point-to-plane distances (Zhang and Pless's cost applied to 3D points). At least 3 non-parallel board poses are needed; 6+ is recommended.
  - This is about 100 lines of numpy/scipy and avoids ROS entirely.
  - Then run koide3 as an independent cross-check.

### Gaps
- No tool found designed specifically for "stationary rotating 2D LiDAR + camera on the same rotating platform". The recommendation above is an inferred adaptation.
- MATLAB Lidar Camera Calibrator and Kalibr pages were not fetched; their descriptions are from background knowledge (confidence M).
- MRPT's camera-2D-LRF calibration app was not verified to still exist.

---

## Q8. Colourisation pipeline and the stereo pair's effect

### Takeaway
Pipeline:
1. Transform each LiDAR point into each image's camera frame (per-image pose = R_z(psi_i) * T_platform_cam).
2. Project with the calibrated distortion model.
3. Reject points behind the camera or outside the image.
4. Resolve occlusion with a per-image z-buffer (depth map rendered from the LiDAR cloud or mesh, with a tolerance).
5. Choose the best image per point: nearest the image centre, near-frontal, closest camera to the LiDAR origin, sharpest.
6. Blend or harmonise exposure. Lock UVC exposure and white balance.

PDAL's `filters.colorization` is top-down raster (GeoTIFF) colourisation and **does not do perspective projection or occlusion**, so it is unsuitable here. Write the projection in numpy/OpenCV, and optionally use Open3D for visualisation and ray-casting.

The stereo pair mainly helps by providing a second viewpoint 165 mm away, filling LiDAR-visible points occluded in one camera, and by cross-checking colour consistency. Rotation already provides many overlapping views per station.

### Cited Findings
- PDAL `filters.colorization` "populates dimensions in the point buffer using input values read from a raster file", searching "the XY coordinates of each point in the raster". It is a top-down projection via GDAL ([PDAL docs](https://pdal.io/en/stable/stages/filters.colorization.html); [PDAL workshop](https://pdal.io/en/2.9.0/workshop/manipulation/colorization/colorization.html)).
- Colour not time-coincident with the point cloud produces discontinuities ([Spatialised: Colouring point clouds with PDAL](https://www.spatialised.net/colouring-point-clouds-with-pdal/), via search summary).
- In streaming mode, points outside the raster are dropped ([PDAL issue #3391](https://github.com/PDAL/PDAL/issues/3391)).

### Inferences
- **[Inference, M] Occlusion handling.**
  - The LiDAR origin (on the mast) and the camera centres differ by several cm to tens of cm. Points visible to the LiDAR can therefore be hidden from a camera behind foreground objects, and would otherwise pick up the foreground's colour ("colour bleeding" at depth edges).
  - Standard fix: for each image, splat all projected points into a depth buffer, keeping the minimum depth per pixel (dilate splats by 2-5 px to close gaps between sparse points). Accept a point's colour only if its depth is within tolerance of the buffer, e.g. max(5 cm, 1% of Z).
  - Open3D's `RaycastingScene` can ray-cast against a mesh for exact visibility if a mesh (Poisson / ball-pivoting) is built.
- **[Inference, M] Choosing the best image per point.**
  - Score each candidate on: distance of the projection from the principal point (the calibration is most reliable there, with least vignetting); angle between the viewing ray and the surface normal; distance; image sharpness.
  - Take the argmax, or a weighted blend of the top 2-3.
  - With 118 deg FOV and full rotation, each point is seen in many images, so plenty of candidates exist.
- **[Inference, M] Exposure consistency.**
  - Set manual exposure and white balance per station.
  - Outdoors with sun, bracketing or per-image gain normalisation using overlap regions (least-squares gain per image from co-visible points) removes seams.
  - Store linear-ish RGB before blending where possible; MJPEG from UVC is already gamma-encoded and compressed.
- **[Inference, M] Stereo pair vs single camera.**
  - A second camera 165 mm away means a point occluded in camera A (by a nearby pole, say) is often visible in camera B, and vice versa, which reduces holes near depth discontinuities.
  - It also doubles the candidate images per rotation step, allowing blending and outlier rejection: if A and B disagree strongly, one is probably occluded or specular.
  - The camera closest to the LiDAR optical centre should be preferred, since it has the least parallax to the LiDAR.
  - If the two sensors differ in colour response, cross-camera colour calibration is needed (a colour checker, or a 3x3 matrix from overlap).
- **[Inference, M] Library roles.**
  - OpenCV: `projectPoints` / `fisheye.projectPoints`, `undistortPoints`.
  - numpy: vectorised z-buffer.
  - Open3D: I/O, normals, ray-casting, and `color_map_optimization` (Zhou and Koltun) if meshing.
  - CloudCompare: inspection and manual QC.
  - PDAL: LAS/LAZ I/O, CRS reprojection, final export (fits with `scripts/georef.py` and DEC-034).

### Gaps
- Open3D `color_map_optimization` / `RaycastingScene` and CloudCompare colourisation features were not fetched this session; the capabilities come from background knowledge (confidence M).
- No published DIY rotating-2D-LiDAR colourisation pipeline was reviewed for exposure-handling specifics.
