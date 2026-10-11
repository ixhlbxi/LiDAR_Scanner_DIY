# Fact-check of design-conversation claims: DIY stationary RTK LiDAR scanner for filling occlusions in drone LiDAR data

Research date: 2026-09-29. Verdict scale: VERIFIED / PARTLY CORRECT / WRONG / UNVERIFIABLE. Confidence: High / Medium / Low.
"DS" = manufacturer datasheet or vendor claim. "IND" = independent measurement or peer-reviewed study.
Prices are retail list prices seen on the page at the date above. They change often.

## Claim 1: LDROBOT LD19 specs

### Takeaway
PARTLY CORRECT, high confidence. Sample rate, range, and angular resolution match the datasheet. The accuracy figure of ±45 mm is the datasheet worst case; the datasheet also gives a 10 mm standard deviation. The rated sunlight tolerance is 30 klx. That is well below the 80 klx rating of the RPLIDAR S2/S3, so "weak in sunlight" is fair relative to those sensors. The claim of 5-6 m effective range in bright sun has no independent source.

### Cited Findings
- (DS) Ranging frequency 4,500 Hz. Range accuracy ±45 mm over 0.3-12 m, with 10 mm standard deviation over 0.3-12 m. Measurement resolution 15 mm. Angle error ±2°. Scan frequency 10 Hz typical. Resists 30 klx of ambient light. — [LD19 datasheet (Botland mirror)](https://botland.de/img/art/inne/21991_Karta%20katalogowa.pdf); [Core Electronics listing](https://core-electronics.com.au/dtof-ld19-laser-lidar-sensor-kit-12m.html)
- (DS) Measuring range 0.02-12 m. Sampling 4,500 Hz. Sweep 10 Hz. Angular resolution ≤1°. UART at 230,400 bps. 5 V at 180 mA (0.9 W). Operating temperature -10 to 40 °C. Anti-glare 30 klx. Laser is "FDA Class 1". Waveshare lists "ranging accuracy 10 mm", which is most likely the σ value mislabeled as accuracy. — [Waveshare Wiki DTOF LIDAR LD19](https://www.waveshare.com/wiki/DTOF_LIDAR_LD19)
- LDROBOT's official v2.6 datasheet URL now returns 404, so I verified against mirrors. — [ldrobot.com (dead link)](https://www.ldrobot.com/images/2023/05/23/LDROBOT_LD19_Datasheet_EN_v2.6_Q1JXIRVq.pdf)

### Inferences
- 4,500 samples/s ÷ 10 Hz = 450 points per revolution = 0.8°. This matches the claim. At 5 Hz the result is about 0.4° and 900 points per revolution.
- The ±2° "angle error" in the datasheet is large. It is probably a mounting or zero-index tolerance, not random jitter, and it means the LiDAR→mast extrinsic calibration has to be measured. At 8 m, 2° is about 28 cm of lateral error if left uncalibrated.
- "Range noise of several cm" is roughly right: σ is about 1 cm and the worst-case error is ±4.5 cm.

### Gaps
- I could not confirm the 905 nm wavelength in a readable LDROBOT datasheet. The PDFs would not extract. I believe the LD19 datasheet lists roughly 895-915 nm, but treat that as unverified (Medium confidence).
- I found no independent outdoor test of LD19 range versus illuminance, so the 5-6 m figure is UNVERIFIABLE. It is plausible given the 30 klx rating (full sun is about 100 klx) but has no source.

## Claim 2: RPLIDAR S2 / S3 / S2E

### Takeaway
S2: VERIFIED, high confidence. The one qualification is that 30 m applies to white (90%) targets, and black (10%) targets reach only 10 m. S3: range VERIFIED (40 m at 70% reflectivity, 15 m at 10%). The S3 price is PARTLY CORRECT: I found only a European price of €649. S2E: VERIFIED.

### Cited Findings
- (DS) S2: 0.05-30 m at 90% reflectivity and 0.05-10 m at 10%. 32,000 samples/s. 10 Hz. Angular resolution 0.1125°. Accuracy ±30 mm. Resolution 13 mm. IP65. Power >2 W. Variants: S2L (18 m), S2P (50 m), and S2E (Ethernet UDP 10/100M, 30 m). — [Slamtec S2 spec page](https://www.slamtec.com/en/s2/spec)
- (DS) S2 price USD $399.00 at DFRobot. Sunlight resistance >80,000 lux. IEC-60825 Class 1. — [DFRobot RPLiDAR S2](https://www.dfrobot.com/product-2616.html)
- (DS) S3: 40 m at 70% reflectivity, 15 m at 10%. 32 kHz sampling. 0.1125°. 80,000 lux. IP65. Height about 4 cm. — [Seeed RPLiDAR S3](https://www.seeedstudio.com/RPLiDAR-S3M1-p-5753.html); [DFRobot S3](https://www.dfrobot.com/product-2732.html)
- S3 price €649.00. — [welectron](https://www.welectron.com/SLAMTEC-S3-Lidar_1)

### Inferences
- The S2 has about 7× the sample density of the LD19 (0.11° vs 0.8°) and 2.7× the sunlight rating. For thin-wire and sphere-target work, that is the biggest single upgrade available in this price class.
- The usable range on dark bark, wet soil, or asphalt is about 10 m (S2) or 15 m (S3), not 30 or 40 m.

### Gaps
- I did not obtain a current US price for the S3. The €649 price suggests roughly $550-700, which is consistent with the claim.

## Claim 3: SICK TiM571 and Hokuyo UST-20LX

### Takeaway
The specs are VERIFIED. The claim that they cost "2-4× an S2/S3" is WRONG, high confidence. They cost about 6-8× an S2 ($399).

### Cited Findings
- (DS) SICK TiM571-2050101: working range 0.05-25 m, 270° field of view, angular resolution 0.33°, IP67. — [RS Online](https://us.rs-online.com/product/sick/tim571-2050101/71940126/); [SICK product page](https://www.sick.com/cz/en/catalog/products/lidar-and-radar-sensors/lidar-sensors/tim/tim571-2050101/p/p412444)
- Price: $2,772 list at DOIG Corp; €3,307.20 including VAT at Generation Robots. — [DOIG](https://www.doigcorp.com/SICK-1075091-TiM571-2050101); [Generation Robots](https://www.generationrobots.com/en/403310-sick-tim571-2050101-laser-range-finder.html)
- (DS) Hokuyo UST-20LX: 20 m, 270°, 0.25°, 25 ms scan, IP65, 130 g, Ethernet. Price $2,580 (the listing is dated 2021). — [Hokuyo spec PDF](https://www.hokuyo-usa.com/download_file/view/4bca81d6-4cc1-417b-9472-9e5ecdf3c0c4/236); [Acroname](https://acroname.com/store/lidar-sensor-r360-ust-20lx)

### Inferences
- Both sensors have a coarser angular step (0.25-0.33°) than the S2/S3 (0.11°) and only a 270° field of view. What they add is industrial robustness: IP67, a temperature range, and SICK's multi-echo and fog filtering. For this project they are poor value.

### Gaps
- I did not check a current 2026 price for the UST-20LX.

## Claim 4: Livox Mid-360 / Mid-360S / Unitree L2, and FAST-LIO2 / Point-LIO

### Takeaway
Mid-360: VERIFIED, high confidence. 360 × 59° field of view, 40 m at 10% reflectivity, 200k points/s, Ethernet, built-in IMU, 9-27 V, 6.5 W, about $899. Mid-360S: VERIFIED that it exists, with nearly identical specs. Unitree L2: $419, 30 m, 360 × 96°, 64k effective points/s, built-in IMU. FAST-LIO2 supports Livox sensors. Mid-360 support comes through community forks and the livox_ros_driver2.

### Cited Findings
- (DS) Mid-360: horizontal 360°, vertical -7° to 52° (59° total). 40 m at 10% reflectivity, 70 m at 80%. Blind zone 0.1 m. 200,000 points/s (first return). Range precision ≤2 cm at 10 m. Angular precision <0.15°. IMU ICM40609. 9-27 V DC. 6.5 W average, 14 W while self-heating. 100BASE-TX Ethernet. 265 g. IP67. 10 Hz. 905 nm, Class 1. — [Livox Mid-360 specs](https://www.livoxtech.com/mid-360/specs)
- Mid-360 price $899.00 USD. — [RoboStore](https://robostore.com/products/livox-mid-360-lidar)
- (DS) Mid-360S exists. Same field of view, 40 m at 10%, 200k points/s, ICM40609 IMU, 9-27 V, 6.5 W. It adds PTPv2/GPS sync, a -20 to 55 °C operating range, and ≤4 cm precision at 0.2 m. — [Livox Mid-360S specs](https://www.livoxtech.com/mid-360s/specs); [OpenELAB comparison](https://openelab.io/blogs/learn-2/livox-mid-360-vs-mid-360s-whats-the-difference-and-which-should-you-choose)
- (DS) Unitree L2: $419.00. 0.05-30 m. 64,000 points/s. 360° × 96° field of view. Built-in IMU. 100 klx outdoor rating. Class 1. -10 to 50 °C. Resellers advertise "128,000 points/s sampling" and "360 × 90°". — [Unitree shop](https://shop.unitree.com/products/unitree-4d-lidar-l2); [youyeetoo](https://youyeetoo.com/products/unitree-l2-4d-3d-lidar)
- The FAST-LIO README lists support for Livox Avia, Horizon, and MID-70, plus Velodyne and Ouster. It does not list the Mid-360 explicitly. Community forks such as fast_lio_mid360 and emNavi/Fast-LIO2 run it on the Mid-360. — [hku-mars/FAST_LIO](https://github.com/hku-mars/FAST_LIO); [SylarAnh/fast_lio_mid360](https://github.com/SylarAnh/fast_lio_mid360); [emNavi/Fast-LIO2](https://github.com/emNavi/Fast-LIO2)

### Inferences
- The Mid-360 costs about the same as a TiM571 divided by three, and it gives a full 3D, IMU-synced, Ethernet sensor. That makes it the natural "replace the rotating mast" option.
- The L2 is the budget 3D option. Its 64k effective points/s is about a third of the Mid-360's rate.

### Gaps
- I did not verify L2 range precision, power draw, or scan pattern.
- I did not verify Point-LIO support for the Mid-360 and L2 against the Point-LIO README.

## Claim 5: The Raspberry Pi 4 needs degraded settings to run FAST-LIO2 on a Mid-360

### Takeaway
PARTLY CORRECT / contradicted, medium confidence. The FAST-LIO authors officially list the Raspberry Pi 4B with 8 GB as a supported ARM platform. Saying it "can only run with degraded settings" is overstated. However, a 4 GB Pi 4 running Python acquisition plus a camera alongside the SLAM will be tight. A Pi 5 or Jetson is a sensible recommendation, but I found no source that makes it a requirement.

### Cited Findings
- The README says FAST-LIO2 supports "ARM-based platforms including Khadas VIM3, Nvidia TX2, Raspberry Pi 4B (8G RAM)". It uses an ikd-Tree and parallel KD-tree search and supports LiDAR rates above 100 Hz. — [hku-mars/FAST_LIO](https://github.com/hku-mars/FAST_LIO); [FAST-LIO2 paper, arXiv 2107.06829](https://arxiv.org/pdf/2107.06829)
- Results with the Mid-360 depend on the driver, time sync, calibration, and compute budget. — [OpenELAB Mid-360S + FAST-LIO2](https://openelab.io/blogs/learn/livox-mid-360s-fast-lio2-slam-real-time-mapping-workflow-ros2)

### Inferences
- For a stationary scanner, SLAM is optional. You can log raw data on the Pi and run FAST-LIO2 or registration offline on a laptop. That removes the compute question entirely.

### Gaps
- I found no published per-scan timing benchmark for FAST-LIO2 with a Mid-360 at 200k points/s on a Pi 4 specifically.

## Claim 6: F9P static PPK tolerates more obstruction than real-time RTK

### Takeaway
PARTLY CORRECT, medium-high confidence. The direction is right: static post-processing beats RTK under canopy. But one peer-reviewed study found that 20-minute static F9P sessions post-processed with adapted RTKLIB gave sub-decimeter median horizontal error even under full mixed canopy. So "fails under dense canopy" is too pessimistic, while "5-10 min" is probably too short for canopy work. 20 minutes or more is the studied figure.

### Cited Findings
- (IND) Tomaštík & Everett, *Sensors* 2023. ZED-F9P with an ANN-MB-00 antenna. 20-minute static sessions, repeated 10× leaf-on (Aug-Oct 2021) and 10× leaf-off (Feb-Apr 2022). Sites: open sky, partial canopy, and full mixed deciduous/coniferous canopy. Processed with RTKLIB 2.4.3 b34 and the demo5 b34g fork. Result: "sub-decimeter median horizontal errors even under tree canopy." A Pixel 5 phone gave about 1.5 m under canopy. — [PMC10056071](https://pmc.ncbi.nlm.nih.gov/articles/PMC10056071/)
- (IND) *Geomatics* 2026, vol. 6(2), 34. Under canopy, F9P RTK averaged 0.17-0.18 m horizontal error leaf-on, improving 58% to about 0.07 m leaf-off. Area errors were under 2%. — [doi:10.3390/geomatics6020034](https://doi.org/10.3390/geomatics6020034) (MDPI page returned 403, so this is from the abstract snippet)
- (IND) F9P static ambiguity-fix rate of about 80% with a few cm horizontal accuracy over an hour-long session. RTK/NRTK gave <5 cm horizontal. — [PMC8001986, "Feasibility of low-cost dual-frequency GNSS for land surveying"](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8001986/)

### Inferences
- Occupy each scan station for at least 20 minutes and log RAWX/SFRBX. Process with RTKLIB demo5 against the ARM_BASE logs. Near facades, expect a better result than under canopy because more sky is open, but multipath bias remains.

### Gaps
- I found no study that isolates 5-10 minute sessions under dense canopy for the F9P.

## Claim 7: Circular GCP centre bias vs checkerboard

Skipped per instructions; another researcher covers it.

## Claim 8: UWB (Qorvo DW1000/DW3000)

### Takeaway
PARTLY CORRECT, medium confidence. LOS accuracy of a few cm to 10 cm is VERIFIED; one study measured a 2.1 cm mean ranging error for the DW3000. NLOS gives meter-scale outliers, which is VERIFIED. The ESP32+DW3000 board costs about $44 at Makerfabs, not $30, so the price is PARTLY CORRECT. The anchor-count geometry is standard. There is decimeter-level UWB forester tracking under forest canopy in the literature.

### Cited Findings
- (IND) The DW3000 had a mean ranging error of 2.145 cm, compared with 2.48 cm for the NXP SR150. — [Push the Limit of Highly Accurate Ranging on Commercial UWB Devices](https://www.researchgate.net/publication/380615990_Push_the_Limit_of_Highly_Accurate_Ranging_on_Commercial_UWB_Devices)
- (IND) Cross-platform study: a DW3000 on a single chip antenna had the worst NLOS ranging accuracy among the platforms tested. — [ACM, Challenges in Platform-Independent UWB Ranging](https://dl.acm.org/doi/pdf/10.1145/3556564.3558238)
- (IND) In one study, LOS RMSE was 0.28 m (median 0.21 m). NLOS mean error was 3.78 m with variance 41.56 m², showing large positive biases. — [PMC10934496](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10934496/)
- (IND) UWB was used to track foresters and map stem locations with decimeter-level accuracy under canopy. Branch and stem occlusion produces positive ranging biases. — [Expert Systems with Applications 2024](https://www.sciencedirect.com/science/article/pii/S0957417424023868)
- Makerfabs ESP32 UWB DW3000: $43.80. — [Makerfabs](https://www.makerfabs.com/esp32-uwb-dw3000.html)

### Inferences
- "10-30 cm through light foliage" is consistent with the forest study's decimeter-level result, but I found no source for that exact range.
- Geometry: 3 non-collinear anchors give a unique 2D fix, and 4 non-coplanar anchors give a 3D fix. With 2 anchors there are two mirror solutions. This is standard trilateration and needs no source.

### Gaps
- I did not find a controlled measurement of foliage-only (no trunk) UWB error.

## Claim 9: ESP32 Wi-Fi FTM (802.11mc)

### Takeaway
VERIFIED, medium-high confidence. Accuracy is about 1 m at best, with meter-level errors from multipath. The original ESP32 (the chip on most LoRa boards, including this rover's) does NOT support FTM.

### Cited Findings
- FTM is supported on ESP32-C3, C5, C6, C61, S2, S3, and S31, and not on the classic ESP32. Espressif notes that RTT ranging is limited by RF interference, multipath, antenna orientation, and calibration. It recommends ESP32-to-ESP32 FTM. — [ESP-IDF FTM example README](https://github.com/espressif/esp-idf/blob/master/examples/wifi/ftm/README.md)
- Community reports put 802.11mc FTM at about 1 m accuracy at best, and it performs poorly at short distances. — [ESP32 Forum, ESP32-C3 FTM](https://www.esp32.com/viewtopic.php?t=21183)

### Gaps
- I found no independent outdoor ESP32 FTM accuracy study.

## Claim 10: SX1280 ranging, and SX1262 lacking it

### Takeaway
VERIFIED, high confidence. The SX1280/SX1281 (2.4 GHz) has a built-in two-way ranging engine. Semtech reports <0.5 m precision over cable and about 1 m LOS, averaged over frequency hopping. The SX1262 (sub-GHz) has no ranging engine.

### Cited Findings
- (DS/app note) Two-way ranging needs no clock sync. A basic frequency-hopping protocol gave <0.5 m precision over cable and about 1 m in LOS radiated tests. About 1 m accuracy is achievable at SF9/1600 kHz, averaging 80 exchanges over 40 hopped channels. — [Semtech AN1200.89 Theory and Principle of Advanced Ranging](https://www.semtech.com/uploads/technology/LoRa/theory-and-principle-of-advanced-ranging.pdf); [SX1280/81 datasheet Rev 3.2](https://media.digikey.com/pdf/Data%20Sheets/Semtech%20PDFs/SX1280-81_Rev3.2_Mar2020.pdf)
- The SX1280 is described as "the first commercial device to expose ranging functionality in addition to communication." — [PMC11991044](https://pmc.ncbi.nlm.nih.gov/articles/PMC11991044/)

### Inferences
- The SX1262 verdict rests on the absence of any ranging mode in the SX126x family documentation. The SX1280 datasheet title reads "...Transceiver with Ranging Capability", and the SX126x datasheets have no equivalent.

### Gaps
- I did not check whether newer Semtech parts (LR2021 and similar) add sub-GHz ranging.

## Claim 11: Bluetooth 6.0 Channel Sounding accuracy

### Takeaway
VERIFIED, medium confidence. The Bluetooth SIG targets 10 cm. Early implementations report about ±20 cm, and vendors cite 10-50 cm, degrading with distance. The claim's "10 cm-1 m" is a fair range.

### Cited Findings
- Bluetooth SIG blog: "A step towards 10-cm ranging accuracy". Uses phase-based ranging plus RTT. Up to about 150 m range at maximum power. — [Bluetooth SIG blog](https://www.bluetooth.com/blog/bluetooth-channel-sounding-a-step-towards-10-cm-ranging-accuracy-for-secure-access-digital-key-and-proximity-services/)
- Early implementations reported about ±20 cm. — [heise online](https://www.heise.de/en/news/Channel-Sounding-Bluetooth-can-locate-devices-better-in-future-9858423.html)
- Vendor figure: about 10 cm below 5 m, and ±50 cm up to 100 m. — [Dasenic](https://www.dasenic.com/blog/knowledgeHub/bluetooth-channel-sounding) (vendor blog, low weight)

### Gaps
- I found no peer-reviewed outdoor or foliage measurement.

## Claim 12: Low-frequency magnetic (magneto-inductive) positioning

### Takeaway
PARTLY CORRECT, medium-low confidence. MI fields do penetrate soil, rock, walls, and vegetation without multipath, and metal and conductive ground distort them. Reported accuracy is decimeter to sub-meter, with a range of up to about 50 m. The "decimeter over tens of meters" figure is at the optimistic end.

### Cited Findings
- kHz MI fields penetrate soil, concrete, and rock with negligible attenuation and are not subject to multipath or shadow fading. One Tx/Rx pair gives 3-D position plus orientation. — [Abrudan et al., "Distortion Rejecting Magneto-Inductive 3-D Localization (MagLoc)", IEEE JSAC 2015](https://www.cs.ox.ac.uk/files/9048/Abrudan%20et%20al%202015%20IEEE%20JSAC.pdf) (the PDF would not parse, so this comes from the search abstract)
- A data-driven induced-field system reported sub-20 cm (2D) and sub-30 cm (3D) accuracy, indoors and outdoors. — [arXiv 2602.00817](https://arxiv.org/html/2602.00817v1)
- Magnetoquasistatic positioning works at ranges up to about 50 m. Accuracy is degraded by ground conductivity and nearby metal. — [Wikipedia: Magnetoquasistatic field](https://en.wikipedia.org/wiki/Magnetoquasistatic_field); [ResearchGate: A Positioning System Based on Low-Frequency Magnetic Fields](https://www.researchgate.net/publication/353645697_A_Positioning_System_Based_on_Low-Frequency_Magnetic_Fields)

### Gaps
- I could not extract MagLoc's own error and range numbers. There is no off-the-shelf hobby hardware, so this is research-grade only.

## Claim 13: MPU-9250 dead reckoning drift vs tactical-grade IMU

### Takeaway
MPU-9250 part: VERIFIED in direction, medium confidence. Free-inertial position error grows with t² from accelerometer bias and t³ from gyro bias, which gives meters within tens of seconds. Tactical-grade part: PARTLY CORRECT. "Decimeters over minutes of walking" holds only with ZUPT-aided foot-mounted mechanization, not free-inertial operation.

### Cited Findings
- Gyro bias produces third-order position error and accelerometer bias produces second-order error. Low-grade MEMS IMUs accumulate position error rapidly. — [PMC5982656 Robust PDR based on MEMS-IMU](https://pmc.ncbi.nlm.nih.gov/articles/PMC5982656/)
- ZUPT, ZARU, and heuristic drift reduction are needed, and heading error remains unobservable under ZUPT. — [PMC5038733](https://pmc.ncbi.nlm.nih.gov/articles/PMC5038733/)
- With vehicle constraints, a wheel-mounted MEMS DR system drifts <1.8% of distance travelled. — [Wheel-INS, arXiv 1912.07805](https://arxiv.org/pdf/1912.07805)

### Inferences
- Worked example: an uncompensated 1 mg (0.0098 m/s²) accelerometer bias gives ½·b·t² ≈ 18 m after 60 s. Consumer MEMS residual bias after calibration is typically ≥1 mg, so "meters within a minute" is conservative.
- For a stationary scanner this is irrelevant for position. The IMU is only useful for tilt/levelling and for mast-rotation sanity checks.

### Gaps
- I found no sourced tactical-grade free-inertial drift numbers. They would need an IMU datasheet (for example, Honeywell HG4930).

## Claim 14: RTK under canopy and near facades

### Takeaway
VERIFIED, medium confidence. Fix rates drop sharply. Reported F9P and low-cost figures include about 41% fix in an orchard (low-quality source), 3.45% fix in a dense Hong Kong urban canyon for conventional RTK, and 0.17-0.18 m average horizontal error under leaf-on canopy.

### Cited Findings
- (IND) Dense urban canyon with buildings and trees: conventional GNSS-RTK overall fix rate 3.45%. — [arXiv 2212.05477, 3D LiDAR aided GNSS NLOS mitigation](https://arxiv.org/pdf/2212.05477)
- (IND) Under canopy, leaf-on RTK horizontal error was 0.17-0.18 m, compared with about 0.07 m leaf-off. — [Geomatics 2026 6(2):34](https://doi.org/10.3390/geomatics6020034)
- F9P orchard (light canopy): 41% fixed at 9.4 cm RMS. Urban canyon: 87% fix. — [AliExpress wiki article](https://www.aliexpress.com/s/wiki-ssr/article/d1-ublox) (low-quality aggregator; do not rely on it without the primary test)

### Gaps
- I did not locate the primary source for the 41% / 87% figures.

## Claim 15: TLS/ground scans registered to UAV LiDAR via overlapping surfaces

### Takeaway
VERIFIED, high confidence. Coarse-to-fine registration (feature, RANSAC, or canopy-density matching followed by ICP) of ground-based scans to ULS/ALS is an established workflow for forest occlusion filling.

### Cited Findings
- Automated fusion of forest airborne and terrestrial clouds through canopy density analysis, with ICP refinement. Residual 0.069 m (3D). — [ISPRS J. Photogramm. Remote Sens. 2019](https://www.sciencedirect.com/science/article/abs/pii/S0924271619301923)
- Improved RANSAC-ICP for registering handheld SLAM and UAV-LiDAR point clouds at plot scale. — [Forests 2024, 15(6):893](https://doi.org/10.3390/f15060893)
- Optimized coarse-to-fine registration of UAV and TLS in dense forest. — [GIScience & Remote Sensing 2023](https://www.tandfonline.com/doi/full/10.1080/15481603.2023.2197281)
- Markerless aerial-terrestrial co-registration using a deformable pose graph. — [arXiv 2410.09896](https://arxiv.org/pdf/2410.09896)
- Ground-based and UAV-LiDAR fusion for QSM in planted forest. — [Forest Ecosystems 2022](https://www.sciencedirect.com/science/article/pii/S2197562022000653)

### Inferences
- Under canopy, the overlap between the ground and aerial clouds is mostly stems and ground. Near facades it is walls and roof edges. The RTK/PPK station position plus ICP on those surfaces is the standard approach.

## Claim 16: Registration spheres of 150-200 mm; points needed for a sphere fit

### Takeaway
PARTLY CORRECT / UNVERIFIABLE on the exact sizes, low-medium confidence. Spheres are standard TLS targets. I found no citable minimum point count. The literature frames fit quality in terms of surface coverage, and routine fits use hundreds to thousands of points.

### Cited Findings
- Spheres are widely used as tie points and GCPs because they look the same from any angle. — [Sensors 2025, openable spherical target system](https://doi.org/10.3390/s25247512)
- Sphere-target clouds usually contain "more than thousands" of points. Fit accuracy depends on coverage: with more than 30% coverage the fit is very accurate (the paper's simulated figure is 0.01 mm, which looks idealized). With less than 20% coverage it is about ±1 mm. — [PMC8621624, An Algorithm for Fitting Sphere Target of Terrestrial LiDAR](https://pmc.ncbi.nlm.nih.gov/articles/PMC8621624/)
- Lab tests with four scanners showed sub-mm sphere-fit accuracy. — [Rigorous feature extraction for spherical targets, Remote Sens. 2022](https://doi.org/10.3390/rs14061491)

### Inferences
- LD19 feasibility: a 200 mm sphere at 5 m subtends about 2.3°. At 0.8° per sample that gives only 2-3 points per scan line, plus however many mast steps cross it. With ±45 mm range error, the centre fit will be at the cm level at best. With an S2/S3 (0.11°) it is about 20 points per line. Keep targets within about 3-5 m, or use larger spheres.

### Gaps
- I did not verify commercial sphere diameters. My recollection is that 139/145 mm and 200 mm are common, but that is unsourced.

## Claim 17: Nodding/rotating 2D-LiDAR SLAM while moving needs good odometry

### Takeaway
VERIFIED, medium confidence. LOAM (Zhang & Singh, RSS 2014) was built on a rotating 2D Hokuyo, and it depends explicitly on motion compensation within each sweep.

### Cited Findings
- LOAM: Lidar Odometry and Mapping in Real-time. The original rig was a 2D laser scanner rotating on a motor. — [RSS 2014 proceedings](https://www.roboticsproceedings.org/rss10/p07.pdf) (URL from my own knowledge, not re-fetched this session)

### Inferences
- For stop-and-scan operation (the scanner stationary during each revolution of the mast), this problem does not arise. Keep the design stationary per station.

## Claim 18: Wet surfaces and water at 905 nm, and grazing incidence

### Takeaway
PARTLY CORRECT, medium confidence. Clear water reflects less than 10% at 905 nm, and wet or water-covered surfaces become specular, so returns drop at oblique angles. Water absorption itself is much weaker at 905 nm than at 1550 nm, so the claim that "leaf water absorbs 905 nm" is weak. The loss comes from specular geometry, not absorption.

### Cited Findings
- At 905 nm, clear-water reflectance is below 10% and rises with suspended sediment. Water absorption is significantly higher at 1550 nm than at 905 nm. — [Paul et al. 2020, Water Resources Research](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2019WR026810); [Comparison of 905 vs 1550 nm rangefinders in adverse conditions](https://www.researchgate.net/publication/263472962_Comparison_of_905_nm_and_1550_nm_semiconductor_laser_rangefinders'_performance_deterioration_due_to_adverse_environmental_conditions)
- 905 nm backscatter from water-covered asphalt modelled; the water film changes scattering. — [Optics Express 2025, 33(13):28841](https://opg.optica.org/oe/fulltext.cfm?uri=oe-33-13-28841)
- Rain adhering to the sensor window causes missing points and reduced reflectivity. — [Sensors 2024 24(10):2997](https://www.mdpi.com/1424-8220/24/10/2997)

### Inferences
- Riverbanks and wet stream beds: expect dropouts on standing water and on wet rock at grazing angles. Dry stream beds are fine.

## Claim 19: Overhead conductor detection and US clearance numbers

### Takeaway
The mixed-pixel/resolution argument is VERIFIED by geometry. MUTCD: the "15 ft min" is VERIFIED. The "19 ft max over roadway" is WRONG: the 11th edition maximum over the roadway is 25.6 ft to the top of the housing, and 19 ft is the maximum for faces not over the roadway, measured from the sidewalk. NESC: 15.5 ft for communication cables over truck-traffic roads is VERIFIED. The other values are from memory (medium confidence).

### Cited Findings
- MUTCD 11th Ed. (Dec 2023) §4D.09: the bottom of a signal housing over any portion of a highway usable by motor vehicles "shall be at least 15 feet above the pavement". The top of the housing over the roadway "should not be more than 25.6 feet above the pavement". Faces not over the roadway: minimum 8 ft and maximum 19 ft above the sidewalk, or above pavement grade if there is no sidewalk. — [UpCodes MUTCD 2023 §4D.09](https://up.codes/s/mounting-height-of-signal-faces); [MUTCD 11th Ed. Part 4 PDF](https://mutcd.fhwa.dot.gov/pdfs/11th_Edition/part4.pdf)
- NESC Table 232-1: communication cables over roads and streets subject to truck traffic need 15.5 ft (4.7 m) at final sag. — [CommScope manual citing NESC Table 232-1](https://www.manualsdir.com/manuals/585665/commscope-trunk-distribution-cable.html?page=64); [2023 NESC clearance chart (Connexus)](https://www.connexusenergy.com/application/files/7916/9955/0959/2023_NESC_Clearance_Charts.pdf)
- Power conductors are typically 25-50 mm in diameter. UAV LiDAR's higher density improves wire detection over classic ALS (2.5-13 pts/m²). — [CIGRE Electra 2021](https://electra.cigre.org/318-october-2021/technology-e2e/using-lidar-scanning-to-measure-or-identify-electrical-conductors.html); [PMC10575426](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10575426/)

### Inferences
- LD19 at 6.5 m range: 0.8° gives about 9 cm between samples, so a 1-2 cm wire is hit on roughly 10-20% of scan lines, and any hit is a mixed return with the background. An S2/S3 at 0.11° gives about 1.3 cm spacing, which gives regular hits. For wire clearance, the S2/S3 or Mid-360 is materially better.
- The following NESC 2017/2023 Table 232-1 values for truck-traffic roads are from my own knowledge and were NOT confirmed from a readable table: supply cables meeting 230C1 and effectively grounded neutrals, 15.5 ft; open supply conductors 0-750 V, 16.0 ft; open supply conductors 750 V-22 kV, 18.5 ft. Confirm them against the NESC 2023 book or the Connexus/Nobles charts.

### Gaps
- None of the utility-chart PDFs would extract, so the full NESC row is unverified.

## Claim 20: Lens prices

### Takeaway
M12 6 mm at $10-20 is VERIFIED ($9.99). The "C-mount 6 mm at $30-60" figure mixes up mounts. The official Raspberry Pi 6 mm lens is CS-mount and costs $25. True C-mount 6 mm machine-vision lenses cost more, but I found no price for them this session.

### Cited Findings
- Arducam M2506ZH04 (6 mm, 1/2.5", M12): $9.99. — [UCTronics/Arducam](https://www.uctronics.com/m2506zh04.html)
- Official Raspberry Pi 6 mm CS-mount wide-angle lens for the HQ camera (made by CGL): $25. — [Raspberry Pi CS-mount lens guide](https://datasheets.raspberrypi.com/hq-camera/cs-mount-lens-guide.pdf); [SparkFun](https://www.sparkfun.com/products/16762); [PiShop.us](https://www.pishop.us/product/6mm-wide-angle-lens-for-raspberry-pi-hq-camera-cs/)

### Gaps
- I have no sourced price for a C-mount 6 mm lens. Low-distortion machine-vision C-mount lenses (Computar, Fujinon, Kowa) are generally over $100, but that is unverified.
