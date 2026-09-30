# Similar DIY / Open-Source Rotating-2D-LiDAR Scanners with Cameras — Prior Art and Lessons

Scope: stationary tripod scanners (2D LiDAR on stepper-rotated mast, Pi, IMU, GNSS, cameras), plus stereo-USB-on-Pi, ELP cameras, target-based TLS registration, and under-canopy georeferencing. Researched 2026-09-29. Where a claim is my own arithmetic or reading of source code rather than a published statement, it is placed under "Inferences".

## 1. PiLiDAR/PiLiDAR (the project's stated inspiration)

### Takeaway
PiLiDAR uses a single Raspberry Pi HQ Camera with an M12 fisheye lens, shoots 4 (optionally 8/16, optionally exposure-bracketed) photos, stitches them into an equirectangular panorama with a fixed Hugin template, and colors every point by looking up the pixel at that point's longitude/latitude **as seen from the scan origin**. That is, it ignores camera-to-LiDAR parallax. There is no formal camera-LiDAR extrinsic calibration and no published accuracy figure. It has no GNSS, no stereo and no targets.

### Cited Findings
**Hardware**
- LiDAR options: LD06 (~$80, 4500 Hz, 230400 baud, 2 cm to 12 m), LD19 (~$70), and STL27L (~$160, 21600 Hz, 921600 baud). The README shows a side-by-side comparing the "angular resolution of LD06 (left) vs. STL27L (right)". — [PiLiDAR README](https://github.com/PiLiDAR/PiLiDAR)
- The shipped `config.json` defaults to `"DEVICE": "STL27L"`, so the author's own working unit appears to be the STL27L. — [PiLiDAR config.json](https://github.com/PiLiDAR/PiLiDAR/blob/main/config.json)
- Camera: "Raspberry Pi HQ Camera with ArduCam M12 Lens" (~$60). The lens is Arducam M25156H18 (the README cites p.7 of the Arducam M12 lens kit PDF). An M12-to-C-mount adapter comes from Thingiverse thing:4444398. Capture dims are `[4056, 3040]` and the README claims a "6K 360° spherical map". — [PiLiDAR README](https://github.com/PiLiDAR/PiLiDAR); [config.json](https://github.com/PiLiDAR/PiLiDAR/blob/main/config.json)
- Mechanics: NEMA17 42-23 stepper, A4988 driver, and a 3D-printed planetary gearbox (Printables 782336). The config has `GEAR_RATIO "1 + 38/14"` (about 3.71:1), `MICROSTEPS 16`, `SCAN_ANGLE 180` and `TARGET_RES "1/6"` degrees. No slip ring is mentioned. — [README](https://github.com/PiLiDAR/PiLiDAR); [config.json](https://github.com/PiLiDAR/PiLiDAR/blob/main/config.json)
- IMU: GY-521 (MPU-6050; the README typo says "MPU 6060") on I2C bus 3 at address 104 (0x68), 50 Hz. The code reads DMP quaternions (`imu_orientation.py`: `DMP_get_roll_pitch_yaw`). — [README](https://github.com/PiLiDAR/PiLiDAR); [lib/imu_orientation.py](https://github.com/PiLiDAR/PiLiDAR/blob/main/lib/imu_orientation.py)
- Cost: "~$200 - $280 (in April of 2025) (not including power supply)". — [README](https://github.com/PiLiDAR/PiLiDAR)

**Panorama and colorization pipeline**
- Panoramas are stitched with Hugin from fisheye photos, from 4 to 8 angles, into a 360×180° spherical map. Exposure is held constant by reading the EXIF of an automatic exposure. White balance uses "iterative optimization of color gains", and blending is done with enblend. — [README](https://github.com/PiLiDAR/PiLiDAR); [Hackaday](https://hackaday.com/2025/04/18/a-pi-based-lidar-scanner/)
- In code, `hugin_stitch()` runs `pto_gen --projection=2 --fov=360`, then `pto_template` against a **pre-made template** (`hugin/template_4.pto`, plus `_8`, `_16` and AEB variants), then `hugin_executor --stitching`.
  - Because the template is fixed, lens parameters and yaw/pitch per image are pre-calibrated rather than solved per scan.
  - A slower `hugin_refine()` path runs `cpfind`/`cpclean`/`linefind`/`autooptimiser` but is commented out in the default flow. The header credits the CLI recipe to the StereoPi 360-camera script.
  - Config: `PANO.IMGCOUNT 4`, `PANO_WIDTH 3600`, `CAM.AEB 1`, `AEB_STOPS 2`.
  - — [lib/pano_utils.py](https://github.com/PiLiDAR/PiLiDAR/blob/main/lib/pano_utils.py); [config.json](https://github.com/PiLiDAR/PiLiDAR/blob/main/config.json)
- Colorization: `angular_from_cartesian()` turns each point into (theta, r, phi) measured from the origin. `get_sampling_coordinates()` then maps phi to image x (with a `+90° + z_rotate` offset) and theta to image y, and `angular_lookup()` samples the pano. The only camera-alignment knobs are `VERTEXCOLOUR.Z_ROTATE` (a yaw offset) and `SCALE`. — [lib/pointcloud.py](https://github.com/PiLiDAR/PiLiDAR/blob/main/lib/pointcloud.py); [config.json](https://github.com/PiLiDAR/PiLiDAR/blob/main/config.json)
- The author (Laserborg) explains in the Hackaday comments:
  - "the mechanical 2D lidar shoots a circle orthogonal to the camera direction".
  - The cloud is assembled "using the absolute stepper angle and calibrated offset translation and rotation between lidar and rotational axis".
  - "Each point in the 3D point cloud can be interpreted as a 3D vector from zero, where it's latitude and longitude component can be directly used to sample the pixel color."
  - — [Hackaday comments](https://hackaday.com/2025/04/18/a-pi-based-lidar-scanner/)
- LiDAR-to-axis calibration constants: `LIDAR_OFFSET_ANGLE -1.05` (degrees, "small lidar rotation fix"), `3D.Y_OFFSET -37.5` mm and `3D.Z_OFFSET -41.9` mm. — [config.json](https://github.com/PiLiDAR/PiLiDAR/blob/main/config.json); [lib/pointcloud.py](https://github.com/PiLiDAR/PiLiDAR/blob/main/lib/pointcloud.py)

**Processing, timing and problems**
- Processing: Open3D assembly from 2D planes, "global registration and ICP fine-tuning" for multi-scan alignment, and Poisson meshing ("very slow on Pi4, recommended to run on PC"). Export is PCD/PLY/e57. The README credits PRBonn KISS-ICP. — [README](https://github.com/PiLiDAR/PiLiDAR)
- Timing: "12s initialisation, 17s shooting 4x photos, 1:24m scanning 0.167° x 0.18°, 37s stitching, cleanup". — [README](https://github.com/PiLiDAR/PiLiDAR)
- Known problems listed in the README:
  - RPi.GPIO broke on Bookworm, so they switched to LGPIO. This matches this repo's DEC-029.
  - pye57 has no ARM64 wheel.
  - Poisson meshing is slow on the Pi.
  - — [README](https://github.com/PiLiDAR/PiLiDAR)
- A Hackaday commenter recommended replacing the "older, very noisy A4988" with a Trinamic TMC220x. — [Hackaday](https://hackaday.com/2025/04/18/a-pi-based-lidar-scanner/)
- GitHub issues:
  - Open: #1 (missing `mechanical_design/` folder, unspecified stepper voltage), #2 (request for sample files), #11 ("RAM?"), #16 ("Still active", March 2026).
  - Closed: #10 "distortion of point cloud" (October 2025). I could not extract the root cause or fix from the thread.
  - No issue discusses camera calibration or colorization accuracy.
  - — [Issues list](https://github.com/PiLiDAR/PiLiDAR/issues?q=is%3Aissue); [#10](https://github.com/PiLiDAR/PiLiDAR/issues/10); [#1](https://github.com/PiLiDAR/PiLiDAR/issues/1)
- The last commit in the cloned repo is dated 2026-05-08, so the repo is still maintained. — [GitHub](https://github.com/PiLiDAR/PiLiDAR) (from a local clone)
- Media coverage (Lidar News, XDA, GIGAZINE) repeats the README and adds no independent accuracy testing. — [Lidar News](https://lidarnews.com/raspberry-pi-lidar/); [XDA](https://www.xda-developers.com/lidar-scanner-raspberry-pi/); [GIGAZINE](https://gigazine.net/gsc_news/en/20250421-pilidar-raspberry-pi/)

### Inferences
- PiLiDAR's colorization is a **pure-rotation (nodal) approximation**. It is fine when the camera sits near the LiDAR's rotation origin and objects are far away.
  - This build has two ELP cameras at ±~82 mm from the mast axis (165 mm baseline). Direction error ≈ offset/range: about 41 mrad (≈2.3°) at 2 m and about 8 mrad (≈0.5°) at 10 m. These are many pixels at 16 MP.
  - The fix is to project each 3D point into each calibrated camera using its own intrinsics and extrinsics (a per-image pinhole model with the stepper angle), not to sample an equirectangular pano. This is my arithmetic, not a published PiLiDAR figure.
- PiLiDAR shows that a fixed stitching template plus stepper-indexed shots works reliably. The same idea carries over: calibrate the camera-to-axis extrinsic once, then trust the stepper angle per shot rather than feature-matching each scan.
- The `LIDAR_OFFSET_ANGLE` and Y/Z offsets are hand-tuned constants. This supports the plan to treat `T_lidar_imu` / LiDAR-to-axis calibration as a v1.1 item.

### Gaps
- There is no published accuracy (geometric or color registration) for PiLiDAR, and no paper or blog by the author beyond the README and Hackaday comments.
- I could not retrieve the root cause of issue #10 ("distortion").
- The exact M12 lens FOV is only in the Arducam PDF, which I did not fetch.
- The mechanical design files are not committed (issue #1).

## 2. Other rotating-2D-LiDAR 3D scanners (DIY and commercial)

### Takeaway
Most hobby rotating-2D-LiDAR scanners (Scanse Sweep kit, Charles' Labs, Instructables stepper builds) have no camera at all. Color, where it exists, is by range or intensity. Commercial TLS (for example the BLK360) uses multi-camera HDR spherical imagery and still shows parallax artefacts. I found no DIY rotating-2D-LiDAR project that uses stereo cameras.

### Cited Findings
**Scanse Sweep 3D Scanner Kit (discontinued)**
- Tripod-mounted. Controlled by a Raspberry Pi 3 with a stepper motor and driver HAT, plus a 9DoF IMU in a 3D-printed enclosure. — [Little Bird](https://littlebirdelectronics.com.au/products/scanse-sweep-3d-scanner-kit); [projects-raspberry](https://projects-raspberry.com/sweep-3d-scanner/)
- Produces scans in 2 to 10 minutes. — [projects-raspberry](https://projects-raspberry.com/sweep-3d-scanner/)
- Servo Magazine review: about 40 m range and a 1 Hz sweep at 500 Hz sample rate. The IMU is there "to determine its orientation in space". — [Servo Magazine](https://www.servomagazine.com/magazine/article/the-multi-rotor-hobbyist-scanse-sweep-3d-scanner-review)
- Problems reported in the same review:
  - USB communication failures and software instability.
  - "the black ABS enclosure got very hot in direct sunlight".
  - Stray sky points outdoors.
  - Long-range building scans "did not resolve any appreciable detail".
  - — [Servo Magazine](https://www.servomagazine.com/magazine/article/the-multi-rotor-hobbyist-scanse-sweep-3d-scanner-review)
- No camera. — same

**Charles' Labs 3D Lidar Scanner**
- LIDAR-Lite v3, Arduino Nano and two SG90 servos. About 1 cm accuracy to 40 m. Scans take under 1 minute to about 30 minutes, with up to 32k+ points. — [Charles' Labs](https://charleslabs.fr/en/project-3D+Lidar+Scanner)
- Lessons:
  - The servos were "wobbly".
  - Because the LiDAR is off-centre, "straight objects get curved" below 1 m unless the offset is calibrated. The same class of error as PiLiDAR's Y/Z offsets.
  - No camera.
  - — [Charles' Labs](https://charleslabs.fr/en/project-3D+Lidar+Scanner)

**Other hobby builds**
- An Instructables stepper plus 2D-LiDAR build sweeps 180° and color-codes by distance, with no camera. — [Instructables](https://www.instructables.com/LIDAR-PointCloud-3D-Mapping-With-Stepper-Motor-Con/)
- The FrederikHasecke ESP32 "3D LiDAR" uses 8 VL53L0X ToF sensors, a different class. — [GitHub](https://github.com/FrederikHasecke/arduino-3d-lidar)

**Commercial and open-source reference points**
- Leica BLK360: four 13 MP cameras, 5-bracket HDR, spherical imagery for colorized clouds. The G1 scans at 680k pts/s, with a full scan plus images in about 20 s. — [Leica BLK360](https://leica-geosystems.com/products/laser-scanners/scanners/leica-blk360); [spec sheet](https://shop.leica-geosystems.com/sites/default/files/2019-04/blk360_spec_sheet_2_0.pdf)
- A vendor knowledge base comparing the FARO M70 with the BLK360 mentions colorization parallax artefacts on the BLK360 (anecdotal, vendor KB). — [DiCarlo KB](https://help.dicarlotech.com/faro-m70-versus-blk-360)
- LidarCamera360 is an open-source suite for fusing 3D LiDAR with 360° panoramic cameras (extrinsic estimation plus GPU colorization). I did not evaluate it. — [GitHub](https://github.com/Everton-Braz/LidarCamera360)

### Inferences
- The camera side of this project goes beyond prior DIY art. PiLiDAR is the only comparable hobby build with color, and it uses a single camera. Expect to write the per-camera projection and colorization code rather than reuse it.
- Two failure themes recur in the hobby builds, and both argue for the planned TMC-quiet or solid mechanical design and the explicit calibration step:
  - Mechanical wobble or backlash.
  - Uncalibrated sensor-to-axis offsets.
- Heat in sun (Scanse) is relevant for a black enclosure holding the Pi plus two USB cameras.

### Gaps
- I did not find a hobby project reporting quantitative color-registration error (pixels or mm).
- OpenScan is a photogrammetry turntable, not a LiDAR scanner, and was not investigated.
- I found no public "Kyle's LD06 3D scanner" or similar named builds with cameras.
- FARO Focus camera specs (parallax-free "HDR camera" via a coaxial design) are not sourced here.

## 3. Stereo USB cameras on Raspberry Pi, and ELP cameras

### Takeaway
DIY Pi stereo work mostly uses short baselines (StereoPi 65 mm), low resolutions (≤1280×960 per eye) and OpenCV SGBM with checkerboard calibration. It reports few rigorous depth-accuracy numbers.

Two USB cameras at high resolution on a Pi 4 hit a well-documented USB isochronous-bandwidth limit. The practical pattern for a stationary scanner is **still capture while the platform is stopped, one camera at a time or with MJPEG**, not simultaneous video.

ELP IMX298 16 MP modules are UVC, MJPEG 4656×3496 at about 10 fps. They are sold for document, QR and "3D scanning" work, but I found no rigorous metrology reviews.

### Cited Findings
**Stereo on Pi**
- StereoPi (CM3+ based) has a 65 mm camera separation. Its tutorials use OpenCV SGBM/BM and reproject depth maps to point clouds. It also has a C++ vs Python speed comparison (numbers not retrieved: Medium 403). — [StereoPi tutorial](https://stereopi.com/blog/opencv-and-depth-map-stereopi-tutorial.html); [Hackaday.io StereoPi](https://hackaday.io/project/162954-stereopi-diy-stereoscopic-camera-with-raspberry); [realizator/stereopi-tutorial](https://github.com/realizator/stereopi-tutorial)
- mpr-projects (May 2025) setup: two Pi Camera Module 3s captured on a Pi 5, with asynchronous `capture_request` (no hardware sync, "acceptable for stationary scenes").
  - Calibration: checkerboard, then `cv.stereoCalibrate`, with a reprojection error of 0.27.
  - Matching: SGBM with P1 = 8·ch·25 and P2 = 32·ch·25, plus a speckle filter. Processing runs on a laptop, not the Pi.
  - Lessons: rectification is essential, parameter tuning dominates quality, and an interactive tuning GUI is recommended.
  - No depth accuracy is quantified.
  - — [mpr-projects](https://mpr-projects.com/index.php/2025/05/08/stereo-vision-with-two-rpi-cameras/)
- Arducam sells synchronized dual-camera HATs for Pi. These are CSI, not USB. — [Arducam blog](https://blog.arducam.com/dual-camera-hat-synchronize-stereo-pi-raspberry/)

**ELP stereo modules**
- ELP-USB960P2CAM-V90 is a synchronized-shutter stereo module on one board: 2560×960 side-by-side (1280×960 per eye), 90° lens, OV9750, about $80, UVC. The reviewer ran StereoBM without calibration and says "a few hours of calibration" are needed for reasonable depth. — [summet.com](https://www.summet.com/blog/2023/11/17/elp-synchronized-stereo-camera-module-elp-usb960p2cam-v90/)
- ELP also sells a 3840×1080 60 fps synchronous dual-lens module (ELP-USB3D1080P02-V83, 85° no-distortion lens). — [elpcctv.com](https://www.elpcctv.com/elp-4mp-3840x1080p-60fps-synchronous-dual-lens-usb-camera-module-with-no-distortion-85-degree-lens-p-406.html)
- An aggregator claims "sub-centimeter accuracy at 30 cm" on a Jetson Nano and "grainy edges beyond 1.5 m" at 1280×960 for ELP stereo modules. This is an unverified SEO/aggregator source, so treat it as anecdotal. — [AliExpress wiki](https://www.aliexpress.com/s/wiki-ssr/article/stereo-camera-usb)

**ELP IMX298 16 MP**
- Still resolution 4656×3496. MJPEG 4656×3496 at 10 fps and 2048×1536 at 30 fps. UVC, works on Raspberry Pi without drivers. — [Amazon ELP 75° no-distortion](https://www.amazon.com/ELP-Megapixel-Distortion-Webcamera-Industrial/dp/B0BGH2LDMP); [Amazon 120°](https://www.amazon.com/ELP-Raspberry-120Degree-Industrial-Lightburn/dp/B0D8J3Y5TW)
- Lens variants: 180° fisheye (≈152° vertical), 118° and 75° "no distortion", 100° AF and 68° AF. — [Amazon fisheye](https://www.amazon.com/ELP-180degree-Computer-Industrial-Surveillance/dp/B0BWS8PNBY); [Amazon 118°](https://www.amazon.com/ELP-Raspberry-118degree-Distortion-Industrial/dp/B0C289GYVZ); [ELP AF100](http://www.elpcctv.com/elp-16mp-imx298-sensor-autofocus-usb-camera-module-with-100-degree-lens-p-402.html); [ELP AF68](https://www.webcamerausb.com/elp-new-designed-16megapixels-af-hd-pc-webcam-128-sony-imx298-sensor-16mp-usb-camera-autofocus-for-barcode-qr-code-identification-camera-p-414.html)
- Marketed for document, passport, QR, "3D scanning" and LightBurn laser-cutter use. User reviews: "decent in good light". — [Amazon listings above](https://www.amazon.com/ELP-Megapixel-Distortion-Webcamera-Industrial/dp/B0BGH2LDMP)
- e-con Systems sells an IMX298 AF USB camera (See3CAM_160), an alternative with a documented SDK. — [e-con Systems](https://www.e-consystems.com/usb-cameras/16mp-sony-imx298-autofocus-usb-camera.asp)

**USB bandwidth on Pi 4**
- raspberrypi/linux #3406 (still open): a Pi 4 cannot stream two USB webcams at higher resolution. The second camera logs "USB isochronous frame lost (-18)".
  - Workarounds: lower resolution or fps, use MJPEG instead of YUYV, `UVC_QUIRK_FIX_BANDWIDTH` (limited help), and separate host controllers.
  - — [GitHub raspberrypi/linux#3406](https://github.com/raspberrypi/linux/issues/3406)
- The "No space left on device" error from V4L2 is really USB bandwidth reservation, not disk. — [The Good Penguin](https://www.thegoodpenguin.co.uk/blog/multiple-uvc-cameras-on-linux/); [NVIDIA forum](https://forums.developer.nvidia.com/t/cannot-stream-2-usb-cameras-no-space-left-on-device-28/75084)

### Inferences
- **Bandwidth.** The Pi 4's four USB ports sit behind one VL805 controller. The Pi 4 also carries the F9P (ACM), LD19 (CP210x), ESP32 and the two ELP cameras.
  - Expect to capture stills from the two 16 MP cameras sequentially, or open both only in MJPEG at full resolution with the platform stopped.
  - Do not plan on simultaneous 16 MP streaming during LiDAR acquisition. LD19 serial loss from USB contention would be the worst outcome.
- **Sync.** The ELP IMX298 units are separate, unsynchronized, rolling-shutter modules, which only matters if the platform is moving. On a stop-and-shoot tripod, sync is unnecessary. This is the same argument mpr-projects used.
- **Autofocus vs fixed focus.** AF variants break calibration: intrinsics change with focus. For measurement, use fixed-focus "no distortion" variants, or lock focus via V4L2 `focus_automatic_continuous=0` / `focus_absolute`. This is my inference from standard photogrammetry practice; there is no ELP-specific source.
- **Stereo depth resolution for this rig.**
  - Assumed: the 75° HFOV variant, focal length ≈ 2328/tan(37.5°) ≈ 3030 px, B = 0.165 m, 0.25 px disparity precision.
  - Formula: ΔZ ≈ Z²·Δd/(f·B).
  - Result: ≈1.2 cm at 5 m, ≈5 cm at 10 m, ≈20 cm at 20 m.
  - So stereo is useful for near-field targets and texture, but the LiDAR remains the range sensor beyond a few metres. My arithmetic; lens FOV is assumed.
- **Baseline.** 165 mm is about 2.5× StereoPi's 65 mm. That improves depth precision but raises minimum overlap distance and occlusion near the rig.

### Gaps
- No Pi 4 SGBM fps benchmark was retrieved (the StereoPi Medium page returned 403).
- No independent metrology or calibration-stability tests of ELP IMX298 modules. Nothing on rolling-shutter readout time, thermal focus drift or MJPEG compression artefacts.
- No confirmed LightBurn-community reports on IMX298 distortion or calibration quality were found in this pass.
- No project using two ELP 16 MP cameras as a stereo pair was found.

## 4. Target-based TLS registration and TLS-to-UAV co-registration

### Takeaway
Purpose-built targets beat spheres for TLS↔UAV-photogrammetry tie points. A three-plane plus black-circle target gave 0.7 to 1.0 cm 3D RMSE, versus 1.8 to 7.4 cm for spheres and cones.

Open-source sphere detection exists (CloudCompare qRansacSD, the Schnabel RANSAC). Low-cost TLS research still relies on manual alignment + ICP/NDT plus total-station control, not automatic targets.

### Cited Findings
**Urbančič et al., Sensors 2019**
- New target: three perpendicular 40×40 cm matte-white aluminium panels, a 30 cm black circle on the horizontal panel for UAV detection, and 15 cm holes in the vertical panels. — [PMC6679335](https://pmc.ncbi.nlm.nih.gov/articles/PMC6679335/)
- Detection: RANSAC plane intersection in TLS; least-squares image matching of the circle centre in UAV imagery. — [PMC6679335](https://pmc.ncbi.nlm.nih.gov/articles/PMC6679335/)

| Target | 3D RMSE (UAV at 20/40/75 m) |
|---|---|
| New target | 0.68–1.03 cm |
| 20 cm sphere | 1.82–4.70 cm |
| 15 cm sphere | 2.97–7.36 cm |
| 40 cm cone | 1.50–6.03 cm |

  — [PMC6679335](https://pmc.ncbi.nlm.nih.gov/articles/PMC6679335/)
- Why spheres failed in that study: overexposed white spheres gave noisy, "flattened" geometry in the UAV clouds, and z precision degraded with altitude. — [PMC6679335](https://pmc.ncbi.nlm.nih.gov/articles/PMC6679335/)

**Other target work**
- An openable reference-sphere system lets the sphere centroid be surveyed directly. It achieves registration and georeferencing on par with commercial targets. — [PMC12737144](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12737144/)
- CloudCompare's qRansacSD plugin implements Schnabel et al. RANSAC shape detection (planes, spheres, cylinders, cones). — [CloudCompare wiki](https://www.cloudcompare.org/doc/wiki/index.php/RANSAC_Shape_Detection_(plugin))
- An improved RANSAC sphere detection with a principal-curvature constraint has been published. — [PMC9371188](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9371188/)
- Python RANSAC sphere/plane tutorial. — [learngeodata](https://learngeodata.eu/3d-shape-detection-with-ransac-and-python-sphere-and-plane/)
- An open-source ROS LiDAR-camera calibration uses checkerboard corners picked in both modalities, then PnP-RANSAC plus LM. The classic 2D-LiDAR-to-camera method constrains LiDAR points to the checkerboard plane. — [heethesh/lidar_camera_calibration](https://github.com/heethesh/lidar_camera_calibration); [PMC6983200](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6983200/)

**Low-cost TLS prototype (Výbošťok et al., Sensors 2025)**
- Hardware: Livox Avia, Raspberry Pi CM4 and a Mandeye board. €2050. No camera. — [PMC12787914](https://pmc.ncbi.nlm.nih.gov/articles/PMC12787914/)
- Registration and control: 9 to 16 scans per plot, registered by manual initial alignment, ICP, then multi-view NDT (HDMapping v0.72). Plastic geodetic markers surveyed with a Topcon total station provided control. No GNSS or SLAM was used. — [PMC12787914](https://pmc.ncbi.nlm.nih.gov/articles/PMC12787914/)
- Results (151 trees):
  - DBH RMSE 1.50 cm, statistically comparable to a Stonex X120GO.
  - Height RMSE 0.99 m, with a −0.91 m bias.
  - Reference: RIEGL VZ-1000 DBH RMSE 0.75 cm.
  - — [PMC12787914](https://pmc.ncbi.nlm.nih.gov/articles/PMC12787914/)
- Code and docs: MIT-licensed. [mandeye_controller](https://github.com/JanuszBedkowski/mandeye_controller/tree/livox_sdk_1), build files at [zenodo 16531534](https://doi.org/10.5281/zenodo.16531534). — [PMC12787914](https://pmc.ncbi.nlm.nih.gov/articles/PMC12787914/)

### Inferences
- For TLS-to-UAV registration, the ARM drone workflow's GCPs can double as rover targets if they have strong 3D geometry.
  - Flat checkerboards and small spheres are weak for UAV photogrammetry.
  - For a 2D-LiDAR scanner with 0.17° to 0.2° angular steps, a 15 to 20 cm sphere at 10 m gets only a handful of points per scan line (0.2° ≈ 3.5 cm spacing at 10 m). Bigger targets or closer placement are required.
  - My arithmetic.
- The stereo ELP pair plus LiDAR could detect a combined target (a circle for images, planes for LiDAR) in both modalities. Urbančič's design is a template.

### Gaps
- There are no DIY or hobby projects (Reddit, Hackaday) doing automatic sphere or checkerboard target detection with LD06/LD19-class clouds. The research is all on survey-grade TLS.
- Point density and range noise of the LD19 on spheres (±cm-level) versus sphere-fit error were not found.

## 5. Under-canopy / GNSS-denied georeferencing

### Takeaway
Under canopy, GNSS gives only coarse (metre-level) georeferencing. Practitioners anchor TLS with one of:
- surveyed targets (reflectors on tripods, discs on trees, total-station control), or
- registration to ULS/ALS clouds via tree-stem matching plus ICP.

Research is moving to markerless stem-map or pose-graph methods.

### Cited Findings
- ESSD 2022 multi-platform German forest dataset (RIEGL VZ-400):
  - Tie points: five tripod-mounted cylindrical reflectors plus circular reflectors pinned to trees.
  - Initial georeferencing from RTK GNSS at one stable position "despite weak signals".
  - RiSCAN PRO Multi Station Adjustment RMSE ≈5 mm (max 8 mm).
  - TLS registered to ULS by tree-stem matching followed by ICP.
  - — [ESSD 14/2989/2022](https://essd.copernicus.org/articles/14/2989/2022/)
- Tree-based positioning (TreePS, Forests 2026) matches LiDAR stem maps for below-canopy positioning. A search snippet reports mean positioning errors of about 1.04 to 2.67 m for segmentation or TLS+ALS variants (I did not read the full text). — [TreePS](https://doi.org/10.3390/f17040483)
- Casseau, Chebrolu, Mattamala, Freissmuth and Fallon (Oxford, 2024) co-register aerial and terrestrial forest clouds without markers, using a deformable pose graph over terrestrial sub-clouds. No accuracy figures are in the abstract. — [arXiv 2410.09896](https://arxiv.org/abs/2410.09896)
- Target-less UAV-LiDAR registration via graph matching of tree locations. — [Scientific Reports 2025](https://www.nature.com/articles/s41598-025-29590-2)
- Canopy-shape-based automatic TLS-to-UAV registration. — [Forests 16(8):1347](https://doi.org/10.3390/f16081347)
- ICP to ALS is "constrained by the initial alignment quality". Leaf-off stems register better. — [search summary of ScienceDirect/ESSD results](https://www.sciencedirect.com/science/article/abs/pii/S1574954121002880)
- The low-cost Livox TLS prototype used no GNSS; control came from a total station. — [PMC12787914](https://pmc.ncbi.nlm.nih.gov/articles/PMC12787914/)

### Inferences
- For this rover under canopy, the realistic chain is:
  - RTK fix (F9P) at open-sky set-ups or a canopy-gap anchor scan.
  - Target or overlap chaining between set-ups (ICP, as PiLiDAR does).
  - Final ICP or stem-matching to the ARM UAV LiDAR cloud.
- F9P float or degraded solutions under canopy should be logged with quality flags. The existing JSONL/DEC-034 plan fits, but must not be trusted as cm-level truth.
- Camera imagery could help with manual tie-point picking against UAV orthophotos, but no project doing this with DIY hardware was found.

### Gaps
- There are no DIY or hobby (Reddit or forum) reports of low-cost 2D-LiDAR scanners georeferenced under canopy.
- PPK-under-canopy success rates for the F9P were not researched here (possibly covered by another researcher).
- Full-text accuracy numbers for TreePS and the Oxford pose-graph method were not retrieved.
