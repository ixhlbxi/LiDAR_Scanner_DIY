# Two ELP 16MP IMX298 UVC cameras on a Raspberry Pi 4B (Bookworm) alongside ZED-F9P, LD19/CP2102, ESP32 and a USB SSD

Scope: stationary rotating scanner, triggered still capture. Device under study: ELP 16MP IMX298 (ELP-USB16MP01 family), USB 2.0 UVC, MJPEG 4656x3496 @ 10 fps, YUY2 4656x3496 @ 1 fps.

Labels used below: **[DOC]** documented by vendor/kernel/Raspberry Pi; **[COMMUNITY]** forum/issue reports; **[CALC]** my own arithmetic; **[MEMORY]** from background knowledge, not re-verified with a fetched source in this session (treat as needing confirmation). Confidence: High / Medium / Low.

Research date: 2026-09-29. About 20 tool calls. Several sources I wanted (the ideasonboard UVC FAQ, the Good Penguin blog) returned 403 or a bot-check page, so parts of the analysis rely on the kernel source and mailing-list threads.

---

## Q1. Raspberry Pi 4 USB topology: do all USB 2.0 devices share a single 480 Mbps bus?

### Takeaway
Yes, and this is documented by Raspberry Pi. All four Pi 4 ports hang off one VIA VL805 xHCI controller on one PCIe lane, and the USB 2.0 lines of all four ports go through a single USB 2.0 hub inside the VL805. So every USB 2.0 device (both ELP cameras, the F9P, the CP2102 and the ESP32 bridge) shares one 480 Mbps high-speed bus, whichever port it is plugged into. Moving a camera to the blue USB 3 port does not give it its own bandwidth. Confidence: High.

### Cited Findings
- [DOC] "The USB 2.0 lines on all four ports are connected to a single USB 2.0 hub within the VL805. This limits the total available bandwidth for USB 1.1 and USB 2.0 devices to that of a single USB 2.0 port." Pi 4 current limit: "1200mA total across all ports." — [raspberrypi/documentation, usb-bus-on-raspberry-pi.adoc](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/usb-bus-on-raspberry-pi.adoc)
- [DOC] The same page says full-speed webcams "transfer a lot of data and incur additional software overhead, reliable operation is not guaranteed" (this is about USB 1.1 devices behind hubs, not the ELP, which is high-speed). — [raspberrypi/documentation](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/usb-bus-on-raspberry-pi.adoc)
- [COMMUNITY] Forum posts confirm that the VLI chip contains an integrated 4-port USB 2.0 hub, so total USB 2.0 bandwidth across all ports is 480 Mbit/s, and that all four ports sit behind one PCIe lane (about 4 Gbps). — [RPi 4 USB ports shared? (RPi Forums)](https://forums.raspberrypi.com/viewtopic.php?t=261373)
- [COMMUNITY] raspberrypi/linux issue #3406, "RPi4: Cannot use multiple USB webcams at higher resolutions": two USB 2.0 webcams at 800x448 YUYV. The second camera hangs in `VIDIOC_DQBUF` and the kernel logs "USB isochronous frame lost (-18)". `UVC_QUIRK_FIX_BANDWIDTH` did not help. The only workaround was lowering the resolution on both cameras. No RPi engineer resolution appears in the thread. — [raspberrypi/linux #3406](https://github.com/raspberrypi/linux/issues/3406)

### Inferences
- [INFERENCE, High] Plugging the two cameras into different ports, or into a USB 3 hub, does not add USB 2.0 bandwidth on a Pi 4. A USB 3 hub carries high-speed devices over its USB 2.0 half, which terminates at the same VL805 USB 2.0 hub.
- [INFERENCE, High] A USB 3 SSD in a blue port uses the separate SuperSpeed path. It does not consume the shared 480 Mbps USB 2.0 budget. It only shares the roughly 4 Gbps PCIe lane, which has plenty of headroom here. Put the SSD on USB 3, not on the USB 2.0 hub.
- [MEMORY, Medium; Pi 5, not Pi 4] The Pi 5's RP1 has two independent xHCI controllers, each serving one USB 3 and one USB 2 port. Two USB 2.0 cameras on different Pi 5 controllers would therefore not share a 480 Mbps bus. I did not fetch a source for this in this session. If confirmed, the Pi 5 is the clean hardware escape from the Pi 4 constraint.

### Gaps
- I found no Raspberry Pi engineer statement about VL805 periodic (isochronous) scheduling, such as how much microframe time the VL805 lets periodic endpoints reserve.

---

## Q2. uvcvideo isochronous bandwidth reservation, "No space left on device", quirks, and per-camera bandwidth

### Takeaway
Two cameras fail because uvcvideo reserves isochronous bandwidth when streaming starts (STREAMON), based on the payload size the camera itself requests. The reservation is not based on the actual MJPEG data rate. `UVC_QUIRK_FIX_BANDWIDTH` (quirks=128) only recalculates for uncompressed formats, so it does nothing for MJPEG. My calculations show that a full-res 16 MP stream (MJPEG at 10 fps or YUY2 at 1 fps) almost certainly needs the largest isochronous alternate setting. Two such streams cannot run at once on one USB 2.0 bus. Plan on opening cameras sequentially, one streaming at a time. Confidence: High that full-res concurrent streaming fails, Medium on the exact numbers.

### Cited Findings
- [DOC: kernel source] In `uvc_fixup_video_ctrl()` the bandwidth fix applies only when `!(format->flags & UVC_FMT_FLAG_COMPRESSED) && stream->dev->quirks & UVC_QUIRK_FIX_BANDWIDTH`. The recalculation is `width*height/8*bpp * fps`, divided by 8 for high-speed, plus a 12-byte header, with a floor `bandwidth = max_t(u32, bandwidth, 1024)`. For MJPEG (compressed) the value reported by the camera (`dwMaxPayloadTransferSize`) is used unchanged. — [torvalds/linux drivers/media/usb/uvc/uvc_video.c](https://raw.githubusercontent.com/torvalds/linux/master/drivers/media/usb/uvc/uvc_video.c)
- [DOC: kernel source] The isochronous alternate setting is chosen in `uvc_video_start_transfer()`, which picks the smallest endpoint with `psize >= bandwidth`. Bandwidth is therefore committed at stream start, not at `open()`. — [uvc_video.c](https://raw.githubusercontent.com/torvalds/linux/master/drivers/media/usb/uvc/uvc_video.c)
- [COMMUNITY] UVC_QUIRK_FIX_BANDWIDTH overrides the device-provided `dwMaxPayloadTransferSize` with a computed value, and only for uncompressed formats. — [search summary of Good Penguin blog and kernel sources](https://www.thegoodpenguin.co.uk/blog/multiple-uvc-cameras-on-linux/) (blog page itself was bot-blocked when fetched)
- [COMMUNITY: linux-uvc-devel] Thread "uvcvideo overallocates bandwidth for compressed (e.g. MJPG) video". Example: a Logitech C270 at 1280x960 MJPEG uses about 9 Mbps but the reservation is about 150 Mbps, which blocks a second camera on a shared 480 Mbps bus with about 190 Mbps of usable isochronous throughput. A compression-factor module parameter was proposed. Oleksij Rempel objected that a "compressed frame can be as big as uncompressed" and pointed to bulk-transfer cameras as the proper fix. It was not merged as proposed. — [linux-uvc-devel (narkive)](https://linux-uvc-devel.narkive.com/hK5VJA2r/uvcvideo-overallocates-bandwidth-for-compressed-e-g-mjpg-video-proposed-fix)
- [COMMUNITY] A `bandwidth_cap` uvcvideo module-parameter patch was posted to linux-media. — [spinics linux-media msg175596](https://www.spinics.net/lists/linux-media/msg175596.html) (not fetched; I have not verified whether it was merged. I believe it is not in mainline.)
- [COMMUNITY] The AgRoboticsResearch `uvc_multi_cam_patch` forces a small fixed payload for compressed formats. It achieved "8 cameras (4 per USB controller) streaming 1280x720 MJPEG @ 30fps" on Jetson 5.15-tegra, with the warning that it "bypasses standard USB bandwidth management and may cause instability if actual data rates exceed the forced low payload size." — [AgRoboticsResearch/uvc_multi_cam_patch](https://github.com/AgRoboticsResearch/uvc_multi_cam_patch)
- [COMMUNITY] Users on Ubuntu and NVIDIA forums report `quirks=128` not helping for two cameras, sometimes producing `VIDIOC_STREAMON: Input/output error` instead. Mixing one YUYV camera with one MJPEG camera sometimes works. — [Ubuntu Forums 2364399](https://ubuntuforums.org/archive/index.php/t-2364399.html); [NVIDIA forum "No space left on device (28)"](https://forums.developer.nvidia.com/t/cannot-stream-2-usb-cameras-no-space-left-on-device-28/75084)
- [COMMUNITY] Isochronous camera reservations on a Pi 4 hurt other USB devices. Two cameras at 1280x720 @ 30 fps under crowsnest/camera-streamer caused Klipper USB-CAN timeouts during homing and probing. Stopping crowsnest fixed it. — [mainsail-crew/crowsnest #202](https://github.com/mainsail-crew/crowsnest/issues/202)
- [DOC: vendor] ELP 16MP (ELP-USB16MP01) formats: MJPEG 4656x3496 @ 10 fps (also 4208x3120, 4000x3000, 3840x2160, 3264x2448, 2592x1944 @ 10 fps; 2320x1744 and below up to 30 fps); YUY2 4656x3496 @ 1 fps, with 2320x1744 and below at 5–30 fps. — [webcamerausb.com ELP-USB16MP01 product page](http://www.webcamerausb.com/elp-16mp-usb-camera-module-46563496-cmos-imx298-sensor-security-industrial-webcam-for-windows-android-mac-linux-raspberry-pi-camera-laptop-pc-camera-usb20-driverless-p-252.html)

### Inferences (calculations)
- [CALC, High] YUY2 full-res frame: 4656 × 3496 = 16,277,376 px; × 2 bytes = **32,554,752 B ≈ 32.55 MB (31.05 MiB)** per frame. At 1 fps: **32.55 MB/s ≈ 260 Mbit/s**.
- [MEMORY, High: USB 2.0 spec] A high-bandwidth isochronous endpoint moves at most 3 × 1024 = 3072 B per 125 µs microframe, which is 3072 × 8000 = **24.58 MB/s (≈197 Mbit/s)**. The host may give periodic (iso + interrupt) transfers at most 80% of each microframe, about 6000 B of about 7500 B. This matches the "~190 Mbps" figure in the linux-uvc-devel thread.
- [CALC, Medium] Consequence for YUY2: 32.55 MB/frame at ≤24.58 MB/s means that if the camera streams isochronously, a full-res YUY2 frame takes **≥1.32 s** to transfer. A true 1.0 fps is not possible over isochronous transfer. Either the ELP bridge uses **bulk** endpoints (UVC allows this, and bulk is not reserved in advance), or the real frame rate is below 1 fps. **Check on hardware:** `lsusb -v -d <vid:pid>` and look at the VideoStreaming interface endpoint "Transfer Type" (Isochronous or Bulk) and `wMaxPacketSize` (0x1400 = 3×1024). This single fact decides whether two ELPs can ever stream at the same time.
- [CALC, Medium] MJPEG full-res at 10 fps: a 16.28 MP frame at about 1.0–1.5 bits/pixel (a typical webcam MJPEG range; the ELP's compression is not specified) is about 2.0–3.1 MB per frame. At 10 fps that is **20–30 MB/s**, which is at or above the 24.58 MB/s single-endpoint isochronous ceiling. A camera sized for that mode will almost certainly request the maximum (3072 B/µframe) alternate setting, about 51% of the microframe and about 64% of the 80% periodic budget. A second camera asking for the same cannot fit, and `VIDIOC_STREAMON` returns ENOSPC ("No space left on device"). Quirks=128 does not apply to MJPEG (kernel code above).
- [INFERENCE, High] Bandwidth is reserved only at STREAMON (alt-setting selection happens in `uvc_video_start_transfer`). Both `/dev/video*` nodes can therefore be **open** at the same time, with formats and controls configured on both. Only **streaming** has to be serialized: STREAMON A → grab → STREAMOFF A → STREAMON B → grab → STREAMOFF B. STREAMOFF puts the interface back to alt setting 0 and frees the reservation.
- [INFERENCE, Medium] Simultaneous streaming is plausible only at reduced modes (for example 1920x1080 MJPEG), and only if the ELP firmware requests a smaller alternate setting for those modes. Many cameras request the maximum for every MJPEG mode, so test it. Custom kernel patches (bandwidth_cap, AgRobotics) are possible on Pi OS but mean rebuilding `uvcvideo.ko` for every kernel update. Not recommended for this project.
- [INFERENCE, Medium] Effect on the other devices: the F9P (CDC-ACM bulk plus a small interrupt endpoint), the CP2102 carrying LD19 data at 230400 baud (about 23 kB/s), and the ESP32 bridge (115200 baud) are all low-rate, and bulk traffic uses whatever the isochronous reservation leaves. The risk is latency and jitter, not throughput. The crowsnest #202 report shows this effect on a Pi 4. For this scanner, a camera streams only while the mast is stopped and only for about 1–3 s. LD19 or F9P serial timing hiccups during that window are the thing to watch. Log serial-read gaps or CP2102 overruns while a camera is streaming.

### Gaps
- I could not confirm the ELP board's endpoint type (iso vs bulk) or its alternate-setting table. No public `lsusb -v` dump for the ELP-USB16MP01 was found.
- I could not confirm whether the `bandwidth_cap` patch was ever merged into mainline or the RPi kernel.
- No measured MJPEG frame size for the ELP IMX298 at 4656x3496 was found. The 2–3 MB/frame figure is an estimate.

---

## Q3. Best practice for capturing full-resolution stills from UVC cameras on Linux (OpenCV, v4l2-ctl, fswebcam, GStreamer, libcamera/Picamera2, linuxpy)

### Takeaway
Use plain V4L2: OpenCV `CAP_V4L2`, or a thin V4L2 Python binding. Request MJPG at 4656x3496, set controls explicitly, discard warm-up frames, and **save the MJPEG bitstream as-is** instead of decoding and re-encoding it. libcamera/Picamera2 is built for CSI cameras, and its UVC support is limited and not the right tool here. UVC cameras have no hardware trigger, so "triggered still" in practice means stream briefly and keep one settled frame. Confidence: Medium-High.

### Cited Findings
- [DOC: RPi engineer 6by9] "The libcamera-apps have been written mainly with a focus on the Pi camera modules... USB webcams will use the UVC (Usb Video Class) pipeline handler, and typically produce YUYV or MJPEG streams. That generally means that they can't produce the YUV420 images that the libcamera-apps request for the preview stream." — [RPi Forums t=347113](https://forums.raspberrypi.com/viewtopic.php?t=347113)
- [COMMUNITY] Picamera2 with a USB camera: preview in MJPEG works, but video recording fails ("Invalid format: MJPEG"), and YUYV fails for lack of `FrameDurationLimits`. The reporter notes "full support for USB may not be available". — [raspberrypi/picamera2 #788](https://github.com/raspberrypi/picamera2/issues/788)
- [COMMUNITY] With OpenCV, set `CAP_PROP_FOURCC` = MJPG plus width and height after opening. `CAP_PROP_CONVERT_RGB=false` returns the undecoded buffer. Use `v4l2-ctl --list-formats-ext` to see which modes exist. — [OpenCV Q&A: change VideoCapture format to MJPEG](https://answers.opencv.org/question/186940/change-videocapture-format-to-mjpeg/)
- [COMMUNITY] Known bug report: `cv::VideoCapture` with `CAP_V4L2` returning incomplete JPEG data on some cameras and versions. — [opencv/opencv #23311](https://github.com/opencv/opencv/issues/23311)
- [COMMUNITY] For controls OpenCV cannot set, people drive V4L2 directly (for example python-v4l2capture). — [royshil gist](https://gist.github.com/royshil/0f674c96281b686a9a62)

### Inferences / recommended practice
- [INFERENCE, Medium] Order of operations in OpenCV: `cv2.VideoCapture(path, cv2.CAP_V4L2)` → set FOURCC MJPG **before** width and height (otherwise OpenCV may negotiate YUYV and fall back to a low resolution) → set `CAP_PROP_BUFFERSIZE=1` → optionally `CAP_PROP_CONVERT_RGB=0` to get the raw JPEG → verify with `get()` that 4656x3496 was really granted.
- [INFERENCE, High] Lowest-risk capture tool for validation: `v4l2-ctl -d /dev/cam_left --set-fmt-video=width=4656,height=3496,pixelformat=MJPG --stream-mmap --stream-count=N --stream-skip=K --stream-to=out.jpg`. It writes the raw MJPEG bytes with no decode. `fswebcam` and GStreamer `v4l2src ! image/jpeg,width=4656,height=3496 ! multifilesink` also work. GStreamer adds dependencies and little value for stills.
- [MEMORY, Medium] Python options: `linuxpy` (successor to `v4l2py`) exposes V4L2 mmap capture and controls in pure Python, with no OpenCV decode. Useful for grabbing raw MJPEG frames with kernel timestamps (`v4l2_buffer.timestamp`). I did not fetch its docs this session.
- [MEMORY, Medium] Many UVC MJPEG frames omit the DHT (Huffman table) segment. They decode in libjpeg-turbo/OpenCV but some strict viewers reject them. FFmpeg's `mjpeg2jpeg` bitstream filter exists to insert the default tables. Test a saved ELP frame in the offline toolchain (georef.py / OpenCV / PIL) before relying on raw-save.
- [INFERENCE, Medium] Warm-up: auto exposure and auto white balance on UVC cameras converge over several frames after STREAMON. At full-res MJPEG (10 fps) discarding about 5–15 frames costs about 0.5–1.5 s. For repeatable colorization, **lock exposure, gain and white balance manually**. Frames then only need to be discarded to flush stale buffers (2–4 frames, one per mmap buffer), and all stations get the same color.
- [MEMORY, Medium] Control persistence: uvcvideo caches control values and restores them after suspend/resume. Closing and reopening the node does not reset them in the driver. Camera firmware resets them on USB re-enumeration or power loss, and some firmwares reset exposure on stream start. Re-apply every control after each open, before STREAMON, and read them back. In kernels 5.x and later the control names are `auto_exposure` / `exposure_time_absolute` / `white_balance_automatic` / `white_balance_temperature` (older: `exposure_auto` / `exposure_absolute`). Set auto_exposure to manual mode (value 1) **before** writing the exposure time.
- [MEMORY, Medium] uvcvideo does not implement the UVC "still image" capture methods (method 2/3, separate still frame descriptors). In practice all Linux tools use the video stream. The ELP's 10 fps MJPEG full-res mode **is** the still mode.

### Gaps
- No source confirmed whether the ELP exposes a JPEG quality control. uvcvideo generally exposes no JPEG quality control, so compression level is fixed by the camera firmware.
- The linuxpy/v4l2py docs were not fetched. Treat its API claims as unverified.

---

## Q4. Stable device naming for two identical cameras (same or missing serial numbers)

### Takeaway
Name the cameras by **physical USB port path** (`ID_PATH` / `KERNELS=="1-1.x"` / `/dev/v4l/by-path`) and filter for the capture node (`ATTR{index}=="0"`). Do not use serial or `by-id`, because identical ELPs typically report the same serial (or none), so `by-id` links collide. The catch is that the naming then depends on which port each camera is plugged into, so label the cables. Confidence: High.

### Cited Findings
- [COMMUNITY] For identical USB cameras on a Pi, `udevadm info -q property -n /dev/videoX` shows `ID_PATH` (for example `platform-...usb-0:1.5:1.0` on older Pis). The `ID_PATH` differs per port even when serials are identical, and `/dev/v4l/by-path/...-video-index0` and `-video-index1` symlinks carry it. Write `/etc/udev/rules.d/` rules keyed on `ID_PATH`. — [RPi Forums "udev rule for identical USB cameras" t=145943](https://forums.raspberrypi.com/viewtopic.php?t=145943); [mdtujn blog: udev rule to discern 2 identical webcams](http://mdtujn.blogspot.com/2018/08/udev-rule-to-discern-2-identical.html)

### Inferences
- [MEMORY, Medium-High] On a Pi 4 the VL805 sits on PCIe, so by-path names look like `/dev/v4l/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0-video-index0`. `usb-0:1.N` is the port behind the VL805's internal USB 2.0 hub (bus 1, hub port N). Check the real strings on the Pi with `ls -l /dev/v4l/by-path/`.
- [MEMORY, High] Each UVC camera creates two nodes on current kernels (metadata nodes since about 4.16): `video-index0` is the image capture node and `video-index1` is the UVC metadata node (`V4L2_BUF_TYPE_META_CAPTURE`). Always open index0. `/dev/videoN` numbering is assigned in probe order and changes between boots and plugs, so never hard-code `/dev/video0`.
- [INFERENCE, High] Suggested rule (verify the port numbers on hardware):
  `SUBSYSTEM=="video4linux", KERNELS=="1-1.3", ATTR{index}=="0", SYMLINK+="cam_left"`
  `SUBSYSTEM=="video4linux", KERNELS=="1-1.4", ATTR{index}=="0", SYMLINK+="cam_right"`
  (`KERNELS` matches the USB device node in the parent chain; a hub in between changes it to something like `1-1.3.2`.) Add a startup self-check: each symlink resolves, and each node reports 4656x3496 MJPG. Log a warning and mark that camera unavailable otherwise, per the CLAUDE.md error-handling rule.
- [INFERENCE, Medium] If a powered hub is added (see Q5), the port path goes through the hub. Keep the hub fixed and cabled permanently, or the names break.
- [INFERENCE, Medium] Left/right identity must also be checked after installation, for example by covering one lens and checking brightness. A swapped cable silently swaps the extrinsics.

### Gaps
- No Pi-4-specific by-path listing was fetched. The exact string above is from memory.

---

## Q5. Power budget and heat

### Takeaway
ELP specifies 150–240 mA at 5 V per camera, so two cameras draw about 0.3–0.5 A. The Pi 4 USB ports supply 1.2 A **total** (documented). Adding the F9P board, the CP2102/LD19 path, the ESP32 and especially a USB SSD will likely exceed that. Use a **powered hub** (or power the peripherals separately) for the cameras and/or the SSD. Remember that a hub adds power, not USB 2.0 bandwidth. Confidence: High for the budget logic, Low for the heat question.

### Cited Findings
- [DOC: vendor] ELP-USB16MP01: USB bus powered, DC 5 V, "150mA~240mA"; operating temperature −10 to 70 °C; "Electronic rolling shutter / Frame exposure." — [webcamerausb.com ELP-USB16MP01](http://www.webcamerausb.com/elp-16mp-usb-camera-module-46563496-cmos-imx298-sensor-security-industrial-webcam-for-windows-android-mac-linux-raspberry-pi-camera-laptop-pc-camera-usb20-driverless-p-252.html)
- [DOC] Pi 4: "1200mA total across all ports". The 1.6 A figure applies to the Pi 5 with a 5 A supply, not the Pi 4. — [raspberrypi/documentation](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/usb-bus-on-raspberry-pi.adoc)

### Inferences
- [CALC + MEMORY, Medium] Rough USB load: 2 × ELP 0.24 A = 0.48 A; ZED-F9P breakout on USB about 0.1–0.15 A; ESP32 LoRa board at TX burst about 0.15–0.25 A; CP2102 alone is small, but if the LD19 (motor plus laser, about 0.3 A class) is powered from the same USB 5 V it matters; a 2.5" USB SSD about 0.5–0.9 A at spin-up or write. The total can reach about 1.3–2.0 A, over the 1.2 A limit. Under-current appears as camera disconnects, `-71`/`-110` errors and SSD resets rather than a clean failure. The project already uses split power domains (DEC-018). Powering the cameras and SSD from the 5 V compute rail through a powered hub fits that.
- [INFERENCE, Medium] Best placement: SSD in a blue USB 3 port (SuperSpeed path, separate from the USB 2.0 hub), ideally a powered USB 3 hub or an SSD with its own supply. Cameras on a powered USB 2/3 hub or direct Pi ports if the total stays under 1.2 A. Monitor `vcgencmd get_throttled` and `dmesg` for over-current events.
- [INFERENCE, Low] Heat: streaming a 16 MP sensor plus MJPEG encoder continuously warms the housing. Since this design streams only about 1–3 s per station, average dissipation (about 1 W peak per camera from 5 V × 0.24 A) is small. Thermal drift of focus or intrinsics is a bigger concern for calibration than component temperature. Keep the camera powered but idle between stations so its temperature stays stable, and calibrate at operating temperature.

### Gaps
- No measured current or thermal data for the ELP aluminum-housing variant was found. The vendor gives only 150–240 mA.
- Current draw for LD19, F9P board and ESP32 board was not sourced here. Check against docs/HARDWARE.md.

---

## Q6. CPU cost of decoding 16 MP MJPEG on a Pi 4, memory, and storage throughput

### Takeaway
No published Pi 4 benchmark for decoding a 16 MP JPEG was found. My estimate is several hundred ms per frame with libjpeg-turbo NEON on one Cortex-A72 core, and a decoded BGR frame is about 49 MB. The recommendation is to **not decode on the Pi at all during scanning**: write the camera's MJPEG bytes (about 2–4 MB) straight to disk, and decode or colorize offline in `scripts/georef.py` (consistent with DEC-022). Confidence: Medium for the architecture, Low for the timing numbers.

### Cited Findings
- [DOC] libjpeg-turbo is "generally 2-6x as fast as libjpeg" and uses NEON SIMD on ARM. — [libjpeg-turbo.org](https://libjpeg-turbo.org/)
- [COMMUNITY] Older Pi JPEG-decode benchmarks cover only Pi 1/2 at 640x480 (Pi 2: about 85 images/s multi-threaded CPU vs 40 images/s OMX). There is no Pi 4 data, and the OMX/MMAL hardware JPEG path is deprecated on Bookworm. — [info-beamer OMX vs CPU jpeg decoding](https://info-beamer.com/blog/omx-jpeg-decoding-performance-vs-libjpeg-turbo); [RPi Forums "Does Pi 4 provide any HW JPEG decoder?"](https://forums.raspberrypi.com/viewtopic.php?t=261983)
- [COMMUNITY] UVC cameras "can make the CPU work quite hard" decoding MJPEG/YUYV into formats that Python libraries use. — [RPi Forums t=347113](https://forums.raspberrypi.com/viewtopic.php?t=347113)

### Inferences (calculations)
- [CALC, High] Decoded sizes: BGR8 = 16,277,376 × 3 = **48.8 MB**; grayscale = 16.3 MB; YUY2 raw = 32.6 MB. Two cameras × a few buffers stays well under 1 GB, so it fits a 2/4/8 GB Pi 4. OpenCV V4L2 mmap buffers (default 4 per camera × about 32 MB for YUY2) add up, so set `CAP_PROP_BUFFERSIZE=1` or 2.
- [CALC/ESTIMATE, Low] Decode time: libjpeg-turbo on an A72 at 1.5–1.8 GHz is roughly 30–60 MP/s per core (estimate, not measured), which gives about **0.3–0.6 s per 16 MP frame**. PNG encoding of a 16 MP RGB image with zlib on a Pi 4 plausibly takes several seconds per frame and produces about 20–30 MB files. Avoid PNG in the capture loop.
- [CALC, Medium] Per-station storage (2 cameras): raw MJPEG about 2 × 3 MB = 6 MB; YUY2 raw about 65 MB; PNG about 40–60 MB. A 36-station rotation (every 10°) gives about 220 MB of MJPEG or about 2.3 GB of YUY2.
- [MEMORY/ESTIMATE, Medium] microSD on a Pi 4 (SDR104-limited to about 40–50 MB/s read; typical A1/A2 card sustained writes about 10–30 MB/s) handles MJPEG easily, but YUY2 or PNG at scale is slow and wears the card. A USB 3 SSD on a Pi 4 typically sustains 250–350 MB/s. Use the SSD for any raw or lossless captures, and write via a background thread so the next station is not blocked.

### Gaps
- No measured Pi 4 16 MP JPEG decode or encode timings were found. Benchmark on the target with `python -c "import cv2,time; ..."` against a real ELP frame.
- No measured ELP MJPEG frame size was found.

---

## Q7. MJPEG artifacts vs YUY2 for sub-pixel corner detection; YUY2 4:2:2 and colorization

### Takeaway
There is expert guidance, but no quantitative study, that JPEG artifacts degrade checkerboard corner accuracy. Use **YUY2 (uncompressed luma) or a lossless format for intrinsic/extrinsic calibration frames**, and MJPEG for routine colorization frames. YUY2's 4:2:2 chroma subsampling is irrelevant to corner detection (luma is full-res) and harmless for LiDAR point colorization. Confidence: Medium.

### Cited Findings
- [COMMUNITY: MathWorks staff, Dima Lisin] "Please do not save your calibration images as jpeg. Jpeg compression creates image artifacts, which affect corner detection accuracy. You should either use a format with no compression or with lossless compression, like tiff or png." — [MATLAB Answers 163015](https://www.mathworks.com/matlabcentral/answers/163015-reason-for-checkerboard-corner-detection-to-fail)
- [COMMUNITY] Checkerboards allow precise sub-pixel corner estimation. Robust detectors (for example localized Radon-transform based ones) keep sub-pixel accuracy under noise and blur. — [Accurate Detection and Localization of Checkerboard Corners for Calibration (academia.edu)](https://www.academia.edu/66783579/Accurate_Detection_and_Localization_of_Checkerboard_Corners_for_Calibration); [Pyramidal Blur Aware X-Corner Chessboard Detector (arXiv 2110.13793)](https://arxiv.org/pdf/2110.13793)

### Inferences
- [INFERENCE, Medium] JPEG's 8x8 DCT blocking and quantization of high frequencies bias the edge gradients that `cornerSubPix` uses, so the effect is largest at low quality settings and small checker squares. With a fixed-quality camera encoder we cannot control quality, so assume MJPEG adds sub-pixel noise. I found no quantified figure (for example a px RMS difference).
- [INFERENCE, Medium] Practical split: (a) **calibration sessions** capture YUY2 full-res, taking only the Y plane and saving it as 16-bit-free 8-bit grayscale PNG (about 10–16 MB, lossless). This is slow (≥1.3 s transfer if isochronous, see Q2) but calibration is offline and rare. If YUY2 4656x3496 turns out unusable, capture YUY2 at 2320x1744 (5+ fps per vendor) for calibration, but then intrinsics are for a binned or scaled mode and **must match the resolution used in operation**. Intrinsics do not transfer between sensor modes unless the scaling is known exactly. (b) **Scan sessions** use MJPEG full-res for colorization.
- [INFERENCE, High] 4:2:2 in YUY2 halves horizontal chroma resolution only. Projected LiDAR points are far sparser than 4656 px per row at typical ranges, so chroma resolution does not limit point colorization. Webcam MJPEG is itself usually 4:2:2 or 4:2:0 [MEMORY], so neither format has full chroma.
- [INFERENCE, Medium] Also consider the camera's ISP: webcam firmware applies sharpening and noise reduction to both formats. Set `sharpness` to its minimum for calibration, because halo edges bias sub-pixel corners too.

### Gaps
- No paper quantifying JPEG quality vs checkerboard reprojection error was fetched.

---

## Q8. Rolling shutter and vibration settling after stepper stop

### Takeaway
The ELP is a rolling-shutter sensor (vendor spec), but rolling shutter only distorts images when the camera or scene moves during readout. On a scanner that fully stops before capture it is a non-issue, **provided the mast has stopped ringing**. The real risk is residual oscillation after the NEMA17/A4988 stop, combined with long exposure. Gate capture on the IMU gyro being quiet, not on a fixed delay. Confidence: Medium.

### Cited Findings
- [DOC: vendor] ELP-USB16MP01 shutter: "Electronic rolling shutter / Frame exposure." — [webcamerausb.com ELP-USB16MP01](http://www.webcamerausb.com/elp-16mp-usb-camera-module-46563496-cmos-imx298-sensor-security-industrial-webcam-for-windows-android-mac-linux-raspberry-pi-camera-laptop-pc-camera-usb20-driverless-p-252.html)

### Inferences
- [CALC, Medium] Readout time: at 10 fps the full-res frame readout is ≤100 ms (the sensor's actual readout is probably shorter, but the ELP bridge's timing is not documented). Any angular velocity during that window shears the image. At 4656 px across (for example about 70–120° HFOV depending on lens, so about 0.015–0.026°/px), a residual rotation of only 0.1°/s over 100 ms is about 0.01°, or under 1 px. Mast wobble after an abrupt stop can be much larger, which is why gating matters.
- [INFERENCE, Medium] Settling: the stepper-mast system rings after deceleration. Recommend: (1) decelerate with a ramp, not an abrupt stop; (2) keep the A4988 enabled (holding torque) during capture; (3) wait until the MPU-9250 gyro norm is below a threshold (for example <0.05°/s) for about 100–200 ms, with a timeout; (4) record the gyro RMS during each capture in the JSONL record as a quality flag. The IMU is already on the platform (DEC-012), so this adds no hardware.
- [INFERENCE, Medium] Keep exposure short with fixed gain. Motion blur from residual vibration scales with exposure time, while rolling-shutter skew scales with readout time. Both are covered by the gyro gate.
- [INFERENCE, Medium] Camera streaming may itself add USB-induced jitter to serial reads (Q2). Holding the stepper still during capture also keeps motor EMI off the IMU (DEC-013).

### Gaps
- No measured settling time was found for comparable NEMA17 mast rigs. It must be measured on this hardware with the IMU.
- The IMX298 line readout time through the ELP bridge was not found.

---

## Q9. Synthesis: recommended capture architecture for this rover

### Takeaway
**One camera streams at a time. Stream only while the platform is stopped and settled. Save the MJPEG bytes without decoding. Name cameras by port path. Put the SSD on USB 3 with a powered hub.** Concurrent full-res streaming of two ELPs on a Pi 4 should be treated as not viable (Q1 and Q2). A Pi 5 (two independent USB controllers, unverified here) or bulk-endpoint cameras are the only clean ways around it. Confidence: Medium-High.

### Cited Findings
- All four Pi 4 ports share one USB 2.0 hub (480 Mbps). — [raspberrypi/documentation](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/usb-bus-on-raspberry-pi.adoc)
- The MJPEG bandwidth request is taken from the camera, FIX_BANDWIDTH does not apply to MJPEG, and the alt setting is chosen at stream start. — [uvc_video.c](https://raw.githubusercontent.com/torvalds/linux/master/drivers/media/usb/uvc/uvc_video.c)
- Picamera2/libcamera is not suitable for UVC stills. — [RPi Forums t=347113](https://forums.raspberrypi.com/viewtopic.php?t=347113); [picamera2 #788](https://github.com/raspberrypi/picamera2/issues/788)

### Inferences (proposed sequence per station)
1. Stepper ramps down and stops, stays enabled. Wait for the gyro-quiet gate (Q8).
2. For cam in (left, right), **sequentially**: (open once at startup and keep open; controls re-applied and read back) → STREAMON → discard frames until the frame's kernel timestamp is later than the gate time plus about 2 buffers → dequeue one MJPEG buffer → STREAMOFF (frees the isochronous reservation) → hand the bytes to a writer thread (SSD) with a JSONL record: camera id, by-path, kernel timestamp, mast angle, gyro RMS, exposure, gain and WB values actually read back.
3. Expected cost: about 0.5–1.5 s per camera (STREAMON latency plus about 2–10 frames at 10 fps), so about 1–3 s per station for both. No decode on the Pi.
4. Calibration mode (separate, rare): YUY2 full-res (if the ELP delivers it; verify iso vs bulk and actual fps), Y plane saved as lossless PNG, sharpness at minimum.
5. Validation tests on hardware before committing: (a) `lsusb -v` endpoint type and `wMaxPacketSize` for each alt setting; (b) try both cameras streaming simultaneously at 4656x3496 MJPEG and expect ENOSPC, to confirm; (c) measure serial-gap and overrun behavior of the LD19/CP2102 and F9P while one camera streams; (d) check `dmesg` for `-71`/over-current events with everything powered; (e) time STREAMON-to-first-frame and the AE/AWB-locked frame count.

### Gaps
- Whether the ELP uses bulk or isochronous transfer is unknown, and this is the biggest open variable. With bulk, two cameras could share bandwidth (each frame just takes longer) instead of failing ENOSPC.
- STREAMON-to-first-frame latency for this camera is unmeasured.
- The Pi 5 USB topology claim is from memory and should be verified in the RPi docs if a Pi 5 upgrade is considered.
