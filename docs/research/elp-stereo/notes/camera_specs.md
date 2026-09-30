# ELP 16MP IMX298 wide-angle USB camera (118/120 deg) for measurement use on a Raspberry Pi 4B

Confidence tags used throughout: **[VENDOR]** = manufacturer or seller claim, unverified; **[SONY]** = sensor maker's product brief; **[COMMUNITY]** = user report; **[CALC]** = my own arithmetic, done in this session; **[INFER]** = my reasoning, not independently verified. H/M/L = high/medium/low confidence.

Research date: 2026-09-29. Amazon pages returned a bot-block to direct fetch, so the Amazon listing text comes only from search-engine snippets. ELP's own sites (elpcctv.com, webcamerausb.com) were fetched in full.

---

## 1. Exact ELP model / SKU, ELP's own spec sheet, and where the Amazon listing is wrong or ambiguous

### Takeaway
The user's camera is almost certainly the **ELP-USB16MP01-BH120**: the IMX298 board with the "H120" 120-degree "no distortion" M12 lens in a black box housing. The board-only version is **ELP-USB16MP01-H120**. ELP's own page says the H120 lens has an **"FOV about 118 degree"** and never says whether that angle is horizontal or diagonal. ELP publishes no focal length, no f-number and no distortion percentage for this lens. Several numbers in the Amazon listing, and in ELP's own "Image area" row, are wrong or cannot be checked.

### Cited Findings
- ELP's official product page for **ELP-USB16MP01-H120** says "With undistorted 120 degree lens, FOV is about 118 degree". It lists the sibling lens SKUs and their FOVs: LC1100 (63 deg), L75 (76), V100 (80), H100 (95), H110 (107), **H120 (118)**, F28 2.8 mm (90), F36 3.6 mm (76), L170 fisheye, L180 fisheye (>180). **[VENDOR, H that this is ELP's claim]** — [ELP elpcctv H120](https://www.elpcctv.com/16-megapixel-120-degree-no-distortion-hd-usb-micro-camera-module-wide-angle-p-361.html)
- ELP's box-housing variant is **ELP-USB16MP01-BH120**: "With no distortion lens (FOV about 118 degree)". Its other specs: working current 180–240 mA, board/box 41x41 mm, standard 3 m cable (1/2/5 m optional). The sensor, format and frame-rate table is the same as the H120's. **[VENDOR]** — [ELP elpcctv BH120](http://www.elpcctv.com/oem-elp-16mp-full-hd-1080p-no-distortion-mini-usb-camera-wide-angle-free-driver-p-369.html)
- ELP's spec table for H120 / BH120 **[VENDOR]** ([H120](https://www.elpcctv.com/16-megapixel-120-degree-no-distortion-hd-usb-micro-camera-module-wide-angle-p-361.html), [BH120](http://www.elpcctv.com/oem-elp-16mp-full-hd-1080p-no-distortion-mini-usb-camera-wide-angle-free-driver-p-369.html)):
  - Sensor: IMX298, 1/2.8", 1.12 um pixel, 4656x3496
  - "Image Area 6.4mm x 5.3mm" (see Inferences: this is wrong)
  - Output: MJPEG / YUY2 (YUYV)
  - Min illumination: 0.5 lux (test conditions not stated)
  - Shutter: "Electronic Rolling Shutter / Frame Exposure"
  - Interface: USB 2.0 High Speed, UVC
  - AEC/AWB/AGC: "Support"
  - Adjustable parameters: "Brightness, Contrast, Saturation, Hue, Sharpness, Gamma, Gain, White Balance, Backlight Contrast, Exposure"
  - Power: 5 V USB bus power, 4-pin 2.0 mm socket
  - Current: 150–240 mA for the H120 board, 180–240 mA for the BH120
  - Working temperature: −10 to 70 °C; storage: −20 to 85 °C
  - Board: 38x38 mm (32x32-compatible holes), about 30 g
  - OS: Linux with UVC (kernel above 2.6.26)
- ELP's webcamerausb.com H120 page (US $67.20) adds that the lens is "Changeable S Mount lens … mini M12 Mount optional Lens, fixed focus, manual adjust to focus at difference distances". It also lists "Buttoncamera: Support". **[VENDOR]** — [webcamerausb H120](https://www.webcamerausb.com/elp-free-driver-16mp-webcam-plug-and-play-cmos-imx298-sensor-micro-distortion-120-degree-wide-angle-uhd-usb-camera-module-for-ocr-document-scanning-p-408.html)
- ELP's frame-rate table, the same on all 16MP pages **[VENDOR]** ([elpcctv H120](https://www.elpcctv.com/16-megapixel-120-degree-no-distortion-hd-usb-micro-camera-module-wide-angle-p-361.html)):

  | Mode | MJPEG | YUY2 |
  |---|---|---|
  | 4656x3496, 4208x3120, 4160x3120, 4000x3000, 3840x2160, 3264x2448, 2592x1944 | 10 fps | 1 fps |
  | 2320x1744, 2048x1536 | 30 fps | 1 fps |
  | 1920x1080, 1600x1200 | 30 fps | 5 fps |
  | 1280x960, 1280x720, 1024x768 | 30 fps | 10 fps |
  | 800x600 | 30 fps | 15 fps |
  | 640x480 | 30 fps | 30 fps |

  The webcamerausb.com copy of the table gives **1280x960 and 1024x768 MJPEG as 10 fps** where elpcctv.com gives 30 fps, so ELP's own pages disagree ([webcamerausb H120](https://www.webcamerausb.com/elp-free-driver-16mp-webcam-plug-and-play-cmos-imx298-sensor-micro-distortion-120-degree-wide-angle-uhd-usb-camera-module-for-ocr-document-scanning-p-408.html)).
- The Amazon listing B0D8J3Y5TW is titled "ELP 16MP Wide Angle USB Camera for Raspberry Pi and Computer … 120Degree … IMX298". Search snippets describe it as having a "fixed focus, wide angle 120 degree low distortion lens", "Video compression format: MJPEG", and "Full resolution of 4656x3496 is limited to 10fps under Linux". The last point appears to come from a customer review. **[VENDOR / COMMUNITY via search snippet, M]** — [Amazon US](https://www.amazon.com/ELP-Raspberry-120Degree-Industrial-Lightburn/dp/B0D8J3Y5TW), [Amazon UK](https://www.amazon.co.uk/ELP-Raspberry-120Degree-Industrial-Lightburn/dp/B0D8J3Y5TW)
- A separate Amazon listing sells the bare-board version as "118degree No Distortion Lens". **[VENDOR]** — [Amazon B0C289GYVZ](https://www.amazon.com/ELP-Raspberry-118degree-Distortion-Industrial/dp/B0C289GYVZ)
- ELP also sells an H110 (107 deg) and an H100 (95 deg) "micro/no distortion" IMX298 variant at a similar price (about US $66). **[VENDOR]** — [webcamerausb 16MP category](https://www.webcamerausb.com/16mp-imx298-usb-camera-c-41/), [webcamerausb H110](https://www.webcamerausb.com/elp-110-degree-wide-angle-micro-distortion-lens-webcamera-16megapixels-high-definition-cmos-color-imx298-sensor-support-uvc-driverless-machine-vision-industrial-usb-camera-module-for-scanning-robot-advertise-machines-p-416.html)
- eBay lists an "ELP 16MP USB Camera for Computer 120 Degree Wide Angle Lens" with UPC 757350433780. That UPC is a second identifier you can check against the box label. — [eBay 388476557016](https://www.ebay.com/itm/388476557016)

### Inferences
- **Model ID (M):** "black aluminum box + bracket + 118/120 deg no-distortion lens + IMX298" matches ELP's **BH120** SKU. The bare-board **H120** carries the same lens. Confirm by:
  - reading the label on the housing or the retail box;
  - checking `lsusb -v` (iManufacturer/iProduct);
  - checking whether the stock cable is 3 m, which is BH120's standard length.
- **Listing discrepancies, item by item:**
  1. **"120 Field of View" (title) vs "118 degree" (body).** Both come from ELP. "120" is the lens family name (H120); "about 118 deg" is ELP's measured FOV. **Neither states the axis** (H, V or D). Treat it as ambiguous. [H that it is ambiguous]
  2. **"Minimum Focal Length 20 mm / Maximum Focal Length 200 m"** is Amazon template garbage. The real effective focal length is about 1.5–2.0 mm (see §2). [H]
  3. **f/1.8** does not appear on any ELP page I fetched. It is unverified. [gap]
  4. **"4K Web Camera"**: 3840x2160 exists only as a 10 fps MJPEG mode (YUY2 at 1 fps), so "4K webcam" is marketing. The mode is also almost certainly a 16:9 crop of the 4:3 sensor, so it has a different FOV. [VENDOR table + INFER]
  5. **"Low distortion" / "no distortion" / "undistorted"**: no TV-distortion percentage is published anywhere. ELP's own pages alternate between "micro distortion", "low distortion" and "no distortion" for the same H120 lens, so these are marketing words, not specs. [H]
  6. **ELP's "Image Area 6.4 mm x 5.3 mm" is wrong** for the active array. 4656 x 1.12 um = 5.21 mm and 3496 x 1.12 um = 3.92 mm [CALC]. 6.4 mm is close to Sony's *die* size (6.433 x 4.921 mm) ([Sony brief](https://dlscorp.com/wp-content/uploads/2019/08/ProductBrief_IMX298_20160210.pdf)), and 5.3 mm matches nothing. Use 5.215 x 3.916 mm (6.521 mm diagonal) for any optics math. [H]
  7. **YUY2 at 1 fps at 4656x3496** is at or beyond what USB 2.0 can carry (see §4). [CALC]
  8. The 1/2.8" format, 1.12 um pixels, 4656x3496, rolling shutter and UVC claims all match Sony and ELP. [H]

### Gaps
- No ELP datasheet PDF was found. ELP's "Download" tabs link only to a generic downloads page.
- No published lens EFL, f-number, TV distortion, relative illumination, MTF or IR-cut cutoff for the H120 lens.
- I could not read the full Amazon B0D8J3Y5TW page (bot-blocked), so its Q&A and reviews could not be checked directly.
- SNR and dynamic range for the module: ELP publishes neither.

---

## 2. Real focal length of the 118/120-degree lens, whether the FOV is horizontal or diagonal, and whether "low distortion" is true

### Takeaway
All figures here are calculations **[CALC]** from Sony's active-array size (5.215 x 3.916 mm, 6.521 mm diagonal).

- If 118 deg is the **diagonal** FOV of a rectilinear lens: f ≈ **1.96 mm ≈ 1749 px** at full resolution, giving HFOV ≈ 106 deg and VFOV ≈ 90 deg.
- If 118 deg is the **horizontal** FOV: f ≈ **1.57 mm ≈ 1399 px**, giving a DFOV of about 129 deg.

A lens this wide sold as "no distortion" should be assumed to have **noticeable barrel distortion** until measured. A comparable Arducam IMX298 UVC module shows that these vendors' quoted FOVs run far wider than rectilinear optics would allow for the stated EFL. Calibrate with a full distortion model; a fisheye model may be needed if the rational/k1–k3 model fits poorly.

### Cited Findings
- IMX298 active array: 4656(H) x 3496(V) at 1.12 um, diagonal 6.521 mm (Type 1/2.8). **[SONY, H]** — [Sony IMX298 Product Brief](https://dlscorp.com/wp-content/uploads/2019/08/ProductBrief_IMX298_20160210.pdf)
- ELP: H120 "FOV about 118 degree"; F28 (2.8 mm lens) "FOV 90 degree"; F36 (3.6 mm) "FOV 76 degree". **[VENDOR]** — [ELP elpcctv H120](https://www.elpcctv.com/16-megapixel-120-degree-no-distortion-hd-usb-micro-camera-module-wide-angle-p-361.html)
- Comparable Arducam IMX298 UVC board B0268: lens "FOV: 105°(H), EFL: 2.72MM, Lens Construction: 5G+IR, Mount: M12*P0.5mm", "Integral IR filter, only visible light". Its lens drawing is labelled "FOV:130° (IMX386)" and shows an IR_CUT element at the rear of the lens barrel. **[VENDOR, H that this is what Arducam states]** — [Arducam B0268 datasheet](https://www.uctronics.com/download/Amazon/B0268_16MP_Wide_Angle_UVC_Camera_Datasheet.pdf)

### Inferences
- **Focal length under each FOV interpretation [CALC]** (pixel focal length at full 4656x3496; halve it for the 2320x1744 mode if that mode is a 2x scale of the full array):

  | Interpretation | f (mm) | f (px, full res) | f (px, 2320x1744) | Implied HFOV / VFOV / DFOV |
  |---|---|---|---|---|
  | 118 deg = DFOV | 1.959 | 1749 | ~875 | 106.2 / 90.0 / 118.0 |
  | 118 deg = HFOV | 1.567 | 1399 | ~699 | 118.0 / 102.7 / 128.7 |
  | 120 deg = DFOV | 1.882 | 1681 | ~840 | 108.3 / 92.2 / 120.0 |
  | 120 deg = HFOV | 1.505 | 1344 | ~672 | 120.0 / 104.9 / 130.4 |
  | 118 deg = VFOV (unlikely) | 1.176 | 1050 | ~525 | 131.4 / 118.0 / 140.3 |

- **Sanity check against ELP's own F28 claim [CALC]:** a rectilinear 2.8 mm lens on this sensor gives HFOV 85.9 deg and DFOV 98.7 deg. ELP quotes "90 deg", which fits neither exactly. This suggests ELP's FOV numbers are rounded or measured in a way that includes distortion, so the H-vs-D question cannot be settled from ELP data (M).
- **Arducam analogue shows vendor FOV ≠ rectilinear FOV [CALC, M]:** Arducam's EFL of 2.72 mm on the same sensor gives a rectilinear HFOV of only 87.6 deg (DFOV 100.3 deg), yet Arducam states 105 deg H. Getting 105 deg horizontally from a 2.72 mm EFL requires strong barrel compression toward the edges. By analogy, an ELP lens marketed as "120 deg no distortion" may have a shorter real EFL and significant radial distortion.
- **Why a truly rectilinear 118 deg lens would be unusual [INFER, M]:** with a rectilinear HFOV of 118 deg, the image corners sit about 64 deg off-axis. Objects there are stretched by about 1/cos²(64°) ≈ 5x radially, and relative illumination falls off steeply, roughly as cos⁴. Low-cost M12 lenses sold as "no distortion" at 110–120 deg usually trade some barrel distortion for less stretch. Either way the corners will be soft and dark.
- **Practical guidance [INFER]:**
  - Calibrate intrinsics per resolution mode with OpenCV. Try `CALIB_RATIONAL_MODEL` first. If residuals exceed about 0.3 px at the edges, compare against `cv2.fisheye`.
  - Seed the calibration with fx ≈ fy ≈ 1400–1750 px at full res.
  - The calibrated fx will also tell you which FOV interpretation was right: fx ≈ 1750 means the 118 deg was diagonal and the lens is near-rectilinear.
- **Angular resolution [CALC]:** at f_px ≈ 1749, one pixel at image centre ≈ 0.57 mrad, which is about 0.57 mm at 1 m and 5.7 mm at 10 m. At the 2320x1744 mode it is about 1.1 mrad per pixel.
- **Depth of field / fixed focus [CALC]:** with f ≈ 1.6–2.0 mm, f/1.8 (unverified), and a circle of confusion of 1–2 px (1.12–2.24 um), the hyperfocal distance is about 0.6–1.9 m. The lens is therefore near-infinity-focused over most working ranges, but may be soft for a checkerboard closer than about 0.5 m.

### Gaps
- There is no manufacturer TV-distortion figure or measured distortion curve for the ELP H120 lens. No community calibration output (fx, fy, k1…k6) for this exact lens turned up.
- Whether each lower resolution is a **crop** or a **scale** of the full array is undocumented. The mix of aspect ratios suggests some are crops and some are scales:
  - 4656x3496 = 1.332
  - 4208x3120 = 1.349
  - 4160x3120 = 1.333
  - 3840x2160 = 16:9

  Intrinsics must therefore be calibrated per mode, not scaled.
- The f-number is unverified.

---

## 3. IMX298 sensor facts (optical format, pixels, shutter/readout, PDAF, colour, dynamic range, origin)

### Takeaway
The IMX298 is a 2015–16-era Sony **Exmor RS stacked BSI smartphone sensor**. It has 1.12 um pixels, a Bayer RGB colour filter, a rolling shutter and on-chip PDAF, and Sony explicitly says it is intended *only* for phones and tablets. In the ELP module the USB bridge/ISP hides almost all of the sensor's capabilities: no RAW output, no PDAF use (the lens is fixed-focus), no HDR mode exposed, no dual-sensor sync, and 10 fps at full resolution instead of 30.

### Cited Findings
- From the Sony product brief **[SONY, H]** ([Sony IMX298 Product Brief v1.0](https://dlscorp.com/wp-content/uploads/2019/08/ProductBrief_IMX298_20160210.pdf)):
  - "Diagonal 6.521 mm (Type 1/2.8) 16 Mega-pixel CMOS active pixel type stacked image sensor with a square pixel array", using Exmor RS technology with a backside-illuminated pixel structure.
  - "R, G, and B pigment primary color mosaic filter is employed" — a Bayer RGB colour filter.
  - Total pixels 4720x3600 (16.99 M); effective 4672x3520 (16.44 M); **active 4656x3496 (16.28 M)**; chip size 6.433 x 4.921 mm; unit cell 1.12 x 1.12 um.
  - Features: **Phase Detection Auto Focus (PDAF)**; single-frame HDR via "spatially multiplexed exposure"; "Full resolution @30 frame/s (Normal / HDR). 4K2K @30 frame/s, 1080p @60 frame/s"; RAW10/8 and COMP8 output; binning and sub-sampling; on-chip noise reduction ("Chroma noise reduction and RAW noise reduction"); dynamic defect-pixel correction; MIPI CSI-2 at 2 or 4 lanes up to 1.5 Gbps per lane; **"Dual sensor synchronization operation"**; built-in temperature sensor; "electronic shutter with variable integration time".
  - Sony: "this product is designed for use in cellular phone and tablet pc … Sony does not guarantee the quality and reliability of product" in other applications.
- Arducam also sells an IMX298 native MIPI camera for the Pi (a separate product with a special driver), which confirms the sensor's phone-module origin and third-party reuse. — [Arducam IMX298 wiki](https://docs.arducam.com/Raspberry-Pi-Camera/Native-camera/IMX298/)

### Inferences
- **Rolling-shutter readout [INFER, M]:** the sensor can deliver full resolution at 30 fps, so its fastest full-frame readout is at most about 33 ms. The ELP bridge caps full-res output at 10 fps, and the sensor may be clocked more slowly in that mode, so the effective top-to-bottom skew could be anywhere from about 33 ms to about 100 ms. This matters for a rotating mast or a moving rover: capture stereo and checkerboard frames only while stationary. Measure the actual skew, for example by imaging a fast-spinning disc or LED strobe.
- **Noise [INFER, M]:** 1.12 um pixels have a small full-well capacity and worse per-pixel SNR than 1.4–2.9 um sensors. The ELP board also applies its own ISP noise reduction, sharpening and gamma before MJPEG compression. Expect visible chroma noise and smeared fine texture indoors or at dusk. ELP's "0.5 lux min illumination" has no stated conditions and should be treated as meaningless.
- **Measurement implication [INFER, H]:** you get only ISP-processed MJPEG or YUY2, never RAW Bayer. Demosaicing, sharpening, lens-shading correction and any geometric processing happen in unknown firmware and cannot be turned off, except for whatever the Sharpness/Gamma UVC controls allow. The sensor's hardware dual-sync feature is **not** exposed over USB, so two ELP units cannot be hardware-synchronised. Stereo pairs must be captured of a static scene, or you must accept up to one frame period (100 ms at 10 fps) of offset.
- "4K Web Camera" is also misleading at the sensor level: the sensor itself can do 4K at 30 fps, but this USB 2.0 module can only deliver 10 fps MJPEG at 3840x2160.

### Gaps
- The full Sony IMX298 datasheet (NDA) is not public. There are no official figures for dynamic range (dB), SNR, full-well, read noise, QE or line time. I found no reliable third-party measurements.
- The USB bridge/ISP chip on the ELP board (commonly a Sonix or SunplusIT UVC SoC) could not be identified from any source.

---

## 4. UVC controls on Linux, exposure/white-balance locking, formats actually reported, fps on a Pi 4, still capture, and first-frame behaviour

### Takeaway
ELP advertises the standard UVC control set: brightness, contrast, saturation, hue, sharpness, gamma, gain, white balance, backlight compensation, exposure, AEC/AWB/AGC, and "button camera" (a snapshot button). There is no focus control. Community and Arducam documentation for this class of IMX298 UVC board show manual exposure through `exposure_auto=1` plus `exposure_absolute` in 100 us units (range 1–5000, i.e. 0.1–500 ms) and a manual white-balance temperature. So exposure and WB **can** be locked, but I found **no public `v4l2-ctl --list-ctrls` dump for the ELP BH120/H120 itself**. Treat the exact ranges as unverified until you run it on your unit. Full-resolution 10 fps MJPEG is reported under Linux. Full-resolution YUY2 at "1 fps" is at or over the USB 2.0 limit.

### Cited Findings
- ELP lists these adjustable parameters: "Brightness, Contrast, Saturation, Hue, Sharpness, Gamma, Gain, White Balance, Backlight Contrast, Exposure", plus "AEC Support / AWB Support / AGC Support". **[VENDOR]** — [ELP elpcctv H120](https://www.elpcctv.com/16-megapixel-120-degree-no-distortion-hd-usb-micro-camera-module-wide-angle-p-361.html). The webcamerausb page also lists "Buttoncamera: Support". — [webcamerausb H120](https://www.webcamerausb.com/elp-free-driver-16mp-webcam-plug-and-play-cmos-imx298-sensor-micro-distortion-120-degree-wide-angle-uhd-usb-camera-module-for-ocr-document-scanning-p-408.html)
- Arducam's IMX298 UVC module B0268 (analogous, not identical) shows these Windows DirectShow property pages **[VENDOR, M as a proxy]** ([Arducam B0268 datasheet](https://www.uctronics.com/download/Amazon/B0268_16MP_Wide_Angle_UVC_Camera_Datasheet.pdf)):
  - Video Proc Amp: Brightness 0, Contrast 32, Hue 0, Saturation 64, Sharpness 3, Gamma 100, White Balance 4600 (auto ticked), Backlight Comp 1, Gain 0, PowerLine Frequency 50 Hz.
  - Camera Control: Exposure −6 (auto ticked), Low Light Compensation (ticked); Focus/Zoom/Iris/Pan/Tilt greyed out.
  - YUY2 is quoted only up to 1024x768 at 8 fps on that board.
- Arducam's UVC documentation says Linux `v4l2-ctl` shows `exposure_auto` and `exposure_absolute` "min=1, max=5000" in "0.1ms" units. You set manual mode with `v4l2-ctl -c exposure_auto=1`, then `exposure_absolute=10` for 1 ms. **[VENDOR, M — generic to Arducam UVC boards, model not specified]** — [Arducam: Adjust the minimum exposure time](https://docs.arducam.com/UVC-Camera/Adjust-the-minimum-exposure-time/)
- A `v4l2-ctl --list-formats-ext` listing shows an IMX298 UVC camera (Arducam) reporting **MJPG 4656x3496 at an interval of 0.100 s (10.000 fps)** on a Raspberry Pi, with the highest resolutions capped at 10 fps and lower ones up to 30 fps. **[COMMUNITY via search snippet, M — I could not locate and fetch the original post]**
- An Amazon review snippet for B0D8J3Y5TW says: "At 2320x1744 @ 30fps MJPG … very crisp images; Full resolution of 4656x3496 is limited to 10fps under Linux". **[COMMUNITY via search snippet, M]** — [Amazon B0D8J3Y5TW](https://www.amazon.com/ELP-Raspberry-120Degree-Industrial-Lightburn/dp/B0D8J3Y5TW)
- LightBurn users running ELP or Arducam 16MP IMX298 cameras at 4656x3496:
  - hit "Pattern NOT found" during lens calibration (an ELP 16MP with a 68-degree lens, over honeycomb and over white card; unresolved in that thread);
  - one Arducam IMX298 user who did get it calibrated saw about 1 mm X-axis inconsistency between small and large workpieces.

  **[COMMUNITY]** — [LightBurn: Trouble calibrating ELP 16mp](https://forum.lightburnsoftware.com/t/trouble-calibrating-elp-16mp-camera/120980), [LightBurn: Camera upgrade to 16mp](https://forum.lightburnsoftware.com/t/camera-upgrade-to-16mp/55758)

### Inferences
- **Expected control names on Pi OS Bookworm (kernel 6.x) [INFER, M]:** newer uvcvideo and v4l-utils show:
  - `auto_exposure` (menu: 1 = Manual Mode, 3 = Aperture Priority Mode) instead of `exposure_auto`;
  - `exposure_time_absolute` instead of `exposure_absolute` (same 100 us units);
  - `white_balance_automatic` + `white_balance_temperature`;
  - `gain`, `brightness`, `contrast`, `saturation`, `hue`, `gamma`, `sharpness`, `backlight_compensation`, `power_line_frequency`.

  Expect **no** focus control (the lens is fixed-focus). Verify with `v4l2-ctl -d /dev/videoN --list-ctrls-menus`.
- **Locking exposure and WB for measurement [INFER, M]:**
  - Order matters: set `auto_exposure=1` and `white_balance_automatic=0` first, then write `exposure_time_absolute`, `gain` and `white_balance_temperature`.
  - Also consider `backlight_compensation=0` and leaving `power_line_frequency` at your mains frequency.
  - UVC settings live in the camera's RAM. They usually revert to firmware defaults on power-cycle or re-enumeration, and some UVC firmwares also reset on every stream open. Re-apply all controls after every open and read them back (`--get-ctrl`) before capture. **No ELP-specific report of controls not persisting was found; this is general UVC behaviour.**
- **"Exposure −6" on Windows [INFER, M]:** DirectShow uses log2 seconds, so −6 ≈ 1/64 s ≈ 15.6 ms. This does not map directly onto the Linux 100 us units.
- **YUY2 at full resolution is physically marginal [CALC, H]:**
  - One 4656x3496 YUY2 frame = 32.55 MB.
  - Maximum USB 2.0 high-bandwidth isochronous throughput = 3 x 1024 B x 8000 microframes/s = 24.6 MB/s, so an isochronous camera can deliver at most about 0.75 fps.
  - "1 fps" is only achievable if the camera uses bulk transfers.
  - Expect ≤1 fps or failure. Use MJPEG for anything above 640x480 at speed.
- **Two cameras on one Pi 4 [INFER, M]:** all four Pi 4 USB-A ports hang off one VL805 controller. USB 2.0 devices on any port likely share one 480 Mbit/s high-speed bus, so a USB 3 port does not help a USB 2 camera. Two full-res MJPEG streams at 10 fps (each JPEG likely 1–3 MB, unverified) could exceed the practical USB 2.0 bandwidth. Plan to:
  - run each camera at a lower frame rate, or
  - open the cameras sequentially for stills, or
  - test `uvcvideo` with `quirks=128` (FIX_BANDWIDTH) if you get "No space left on device" (ENOSPC) errors.

  The OpenPNP thread below reports two identical ELP Full-HD cameras failing on a shared root hub for bandwidth reasons.
- **Still capture [INFER, M]:** ELP advertises "Buttoncamera" (a UVC snapshot-button interrupt), not a higher-resolution still pin. Under Linux, capture video frames via V4L2 or OpenCV at 4656x3496 MJPEG and **save the MJPEG bytes directly as .jpg**. Decoding 16 MP JPEGs on the Pi 4 CPU is slow, perhaps a few hundred ms per frame (unmeasured estimate).
- **First frames [INFER, M]:** no ELP-specific report was found. UVC cameras running AEC/AWB typically need several frames to converge after stream start or a mode change. Even with manual exposure, the first 1–3 frames after STREAMON can be stale or partially exposed. Discard about 5–10 frames (0.5–1 s at 10 fps) after any stream start or control change, and check `exposure_time_absolute` read-back.
- **LightBurn "Pattern not found" at 16 MP [INFER, L–M]:** likely caused by the wide FOV, strong distortion and small target in frame, and possibly MJPEG artefacts at full resolution. OpenCV users should use a large board, `findChessboardCornersSB`, or a ChArUco board, and calibrate at the exact resolution mode used for measurement.

### Gaps
- No actual `v4l2-ctl --list-ctrls` or `--list-formats-ext` dump for the ELP BH120/H120 was found online. Exact ranges and defaults for exposure, gain, WB and gamma are unknown for this unit.
- Sustained full-res 10 fps MJPEG on a Pi 4 specifically (rather than a PC) is supported only by a search snippet and the Amazon review mention. It is unverified for two simultaneous cameras.
- There is no data on MJPEG frame size or quality factor at full resolution, or on whether the JPEG quality control is exposed.
- Whether UVC still-image capture method 2/3 is supported is unknown.

---

## 5. Known issues on Raspberry Pi 4 / Linux, including identical serial numbers across two units

### Takeaway
Few ELP-16MP-specific failure reports exist publicly. The relevant documented issues are:
- identical USB IDs and serial numbers on identical ELP units, so cameras must be identified by USB port path;
- USB 2.0 bandwidth limits with two cameras;
- difficult checkerboard detection at 16 MP with wide lenses (LightBurn).

Overheating, disconnects, colour cast, lens shading and glued focus are plausible but undocumented for this model.

### Cited Findings
- OpenPNP users with **two identical ELP HD USB cameras** found they had "the same ID and serial number (zero)". A maintainer said Full-HD cameras "will not work if connected to the same root USB hub, the band-width is not enough"; the user fixed it by moving to newer hardware. **[COMMUNITY, M — ELP 1080p model, not the 16MP, but same vendor and firmware family]** — [OpenPNP Google Group](https://groups.google.com/g/openpnp/c/_WpAoqkPLl4)
- A Raspberry Pi forum thread covers udev rules for identical USB cameras (distinguishing by port). **[COMMUNITY, title only; not fetched]** — [RPi forum: udev rule for identical USB cameras](https://forums.raspberrypi.com/viewtopic.php?t=145943)
- LightBurn calibration failures at 4656x3496 with an ELP 16MP (68-deg lens). **[COMMUNITY]** — [LightBurn thread](https://forum.lightburnsoftware.com/t/trouble-calibrating-elp-16mp-camera/120980)
- ELP rates the BH120 at 180–240 mA at 5 V (≤1.2 W) and −10 to 70 °C operating temperature. **[VENDOR]** — [ELP BH120](http://www.elpcctv.com/oem-elp-16mp-full-hd-1080p-no-distortion-mini-usb-camera-wide-angle-free-driver-p-369.html)
- **Unreliable source, noted so it is not reused:** an AliExpress "wiki" article about the 16MP USB box IMX298 camera claims it "must be connected to a USB 3.0 port" for "uncompressed 16MP streams". That is false for a USB 2.0 device, and the article reads as auto-generated. **Do not cite.** — [AliExpress wiki-ssr article](https://www.aliexpress.com/s/wiki-ssr/article/16MP-USB-box-camera-IMX298)

### Inferences
- **Stereo pair identification [INFER, H]:** assume both units report the same VID:PID and an empty or identical serial. Bind them by physical port:
  - use `/dev/v4l/by-path/…-video-index0` symlinks, or
  - write udev rules on `ENV{ID_PATH}` / `KERNELS=="1-1.x"` to create `/dev/cam_left` and `/dev/cam_right`.

  Verify with `udevadm info -q property -n /dev/video0 | grep -E 'ID_SERIAL|ID_PATH'` on both cameras. Each UVC camera also creates two /dev/video nodes (capture plus metadata); use index0.
- **Power [INFER, M]:** two cameras at ≤240 mA each are well within the Pi 4's 1.2 A total USB budget. Power is unlikely to cause disconnects unless the Pi supply is marginal or the LiDAR/ESP32 share the same bus.
- **Thermal [INFER, L]:** ≤1.2 W in an aluminium box should run warm but not overheat. Stereo baseline and intrinsics can drift slightly with temperature, so calibrate at operating temperature.
- **Lens shading / colour [INFER, M]:** wide-angle M12 lenses on 1/2.8" sensors usually show corner vignetting and some colour shading, especially with a mismatched chief-ray angle. For point-cloud colourisation, consider a flat-field (vignetting) correction and fixed WB.

### Gaps
- I found no public reports specific to ELP 16MP IMX298 units of: overheating, USB disconnects on Pi 4, MJPEG artefacts, colour cast, lens shading magnitude, firmware bugs, or serial numbers of *16MP* units.
- Whether the stock H120 lens is glued or thread-locked in its holder (common on ELP boards) is undocumented. Inspect it, and warm any thread-locker gently if you need to refocus.

---

## 6. Narrower M12 lenses (6 mm, 8 mm), low-distortion options, and swapping or refocusing the stock lens

### Takeaway
ELP says the lens is a changeable **M12 (S-mount)** lens with manual focus. The analogous Arducam IMX298 board confirms **M12 x P0.5** with the **IR-cut filter inside the lens barrel**, so replacement lenses must include an IR-cut filter. Low-distortion 6 mm and 8 mm M12 lenses sized for 1/1.8" (larger than 1/2.8", so they fully cover the sensor) cost about **US $19** from Commonlands. They are rated for 6–8 MP at larger pixels, so they will not fully resolve 1.12 um pixels.

### Cited Findings
- ELP H120: "Changeable S Mount lens: This camera module has mini M12 Mount optional Lens, fixed focus, manual adjust to focus at difference distances", and "optional other M12 Mount lens". **[VENDOR]** — [webcamerausb H120](https://www.webcamerausb.com/elp-free-driver-16mp-webcam-plug-and-play-cmos-imx298-sensor-micro-distortion-120-degree-wide-angle-uhd-usb-camera-module-for-ocr-document-scanning-p-408.html). ELP also sells the same board with 2.8 mm (F28) and 3.6 mm (F36) lenses. — [webcamerausb F28](https://www.webcamerausb.com/elp-high-definition-webcam-16megapixels-uvc-cmos-imx298-sensor-16mp-ultra-hd-camera-module-usb-free-drive-for-android-linux-windows-plug-play-laptop-camera-with-m12-mount-lens-interchangeable-p-410.html)
- Arducam IMX298 UVC board lens: "Mount: M12*P0.5mm", "Lens Construction: 5G+IR". The drawing shows IR_CUT at the rear of the barrel. **[VENDOR, M as a proxy for ELP]** — [Arducam B0268 datasheet](https://www.uctronics.com/download/Amazon/B0268_16MP_Wide_Angle_UVC_Camera_Datasheet.pdf)
- Commonlands **CIL062**: "no distortion 6mm M12 Lens for up to 1/1.8" 6-8MP cameras", hybrid glass/plastic, US $19. Offered at F/2.8 or F/4.0, M12A or M12B, with or without a 650 nm IR-cut filter. **[VENDOR]** — [Commonlands CIL062](https://commonlands.com/products/no-distortion-6mm-m12-lens)
- Commonlands **CIL083**: "8mm lens for up to 6MP-8MP 1/1.8" sensors", F/2.8, with or without 650 nm IRC, US $19. **[VENDOR]** — [Commonlands CIL083](https://commonlands.com/products/low-distortion-8mm-m12-lenses)
- Commonlands **CIL052** (5.2 mm): described as low-distortion (−0.1% at a 7.2 mm reference circle) and resolving 16 MP+ at 1.4 um pitch. **[VENDOR via search snippet, M]** — [Commonlands CIL052](https://commonlands.com/products/low-distortion-5mm-m12-lens-cil052)
- Arducam sells low-distortion M12 lens kits for Pi cameras. **[VENDOR]** — [Arducam M12 lens kit (Amazon)](https://www.amazon.com/Arducam-Distortion-Lenses-Arduino-Raspberry/dp/B07NW8VR71)

### Inferences
- **FOV and f_px with narrower lenses on the IMX298 (rectilinear) [CALC]:**

  | Lens | HFOV / VFOV / DFOV | f (px, full res) |
  |---|---|---|
  | 5.2 mm | 53.3 / 41.3 / 64.2 deg | 4643 |
  | 6 mm | 47.0 / 36.1 / 57.0 deg | 5357 |
  | 8 mm | 36.1 / 27.5 / 44.3 deg | 7143 |

  A 6 mm lens gives about 3x the pixel focal length of the stock lens, which improves stereo depth resolution about 3x at the same baseline and disparity precision, at the cost of FOV.
- **Resolution match [INFER, M]:** lenses rated "6–8 MP at 1/1.8"" are specified for roughly 2 um pixels. On 1.12 um pixels they will be MTF-limited, so the effective resolution is below 16 MP. That is still likely better than the stock 118-degree lens toward the edges.
- **IR-cut [INFER, M]:** if the stock lens carries the IR-cut filter (as on the Arducam analogue), choose the "With 650nm IRC Filter" variant. Without it, colours will have a strong magenta/IR cast outdoors and point-cloud colourisation will be wrong.
- **Mount check [INFER, M]:** confirm the lens-holder thread and flange clearance on your unit before ordering. Measure the barrel OD and check that the box housing's front aperture fits longer 6–8 mm barrels. M12A vs M12B variants differ in back-focal/flange geometry.
- **Refocusing [INFER, M]:** swapping requires unscrewing the M12 barrel, possibly breaking a thread-locker spot. Refocus at the working distance, then lock the thread (a dab of thread-locker or a lock ring) so intrinsics stay stable. Any refocus invalidates the calibration.

### Gaps
- Stock H120 lens barrel length and diameter, IR-cut location, and whether it is glued: no ELP data.
- The fit of 6–8 mm barrels inside the BH120 box housing is unknown.
- ELP's own price and availability for narrower replacement lenses (e.g. "16MP no distortion 6 mm/8 mm" M12) were not found on the pages fetched.
