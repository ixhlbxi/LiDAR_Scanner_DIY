# Attribution and Upstream Obligations

**Status: OPEN. Read this before any public release, before any ARM Group field use, and before changing LICENSE.**

Created September 14, 2026. This file exists because the rover is derived from someone else's work and the obligations that come with that are easy to forget once the hardware finally works.

---

## What this project is built on

**PiLiDAR** by Philip Gutjahr

- Current repo: https://github.com/PiLiDAR/PiLiDAR
- Original repo (migrated): https://github.com/Finin-Quincey/PiLiDAR
- Upstream license: **CC BY-NC-SA 4.0** (Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International)
- License text: https://creativecommons.org/licenses/by-nc-sa/4.0/
- Copyright (c) 2024 Philip Gutjahr

PiLiDAR is the codebase foundation for this rover (see DEC-002 in docs/DECISIONS.md). The LD19 + stepper mast scanning concept, the GPIO interrupt approach to scan-angle capture, and the general structure of the capture pipeline come from PiLiDAR. Even where code has been rewritten, the design is derived.

If the Unitree L2 path is adopted (retiring DEC-015 through DEC-017 and the PiLiDAR foundation), re-evaluate this file. A clean-room rewrite around a different sensor and SDK may no longer be a derivative work, but that is a judgement call to make deliberately, not by default. Document the reasoning in DECISIONS.md when it happens.

---

## The two problems that must be resolved

### 1. License conflict: this repo says GPL-3.0, upstream requires CC BY-NC-SA

The LICENSE file in this repo is GPL-3.0. CC BY-NC-SA 4.0 is ShareAlike: derivative works must be distributed under the same license (or a CC-designated compatible one). GPL-3.0 is not on that list. As of the creation date, this repo is out of compliance with its upstream license the moment it is shared publicly.

Fix options, in order of preference:

- Change LICENSE to CC BY-NC-SA 4.0 to match upstream. Simplest, honest, and the only option that requires no permission.
- Ask Philip Gutjahr for written permission to relicense the derivative. Unlikely to be needed unless the other option is unworkable.

### 2. NonCommercial conflict: the `arm_group` mode is commercial use

The README describes an `arm_group` operating mode that tags output with project codes and exports to State Plane for TBC import. Using this device to produce deliverables for ARM Group clients is commercial use. CC BY-NC-SA forbids that without a separate grant.

The upstream LICENSE.md includes a **backer exception**: backers who support the project through its funding platforms may use the device to offer scanning as a service (but may not sell the device or derivatives as a product). Read the full text in the upstream repo before relying on it.

Fix options:

- Become a backer of PiLiDAR through whatever funding platform the project uses, keep the receipt, and note it here with the date. This is the path the author explicitly built for people in exactly this situation.
- Contact Philip Gutjahr directly for a written commercial-use grant. Keep the correspondence with the repo.
- Keep the rover strictly in `personal` mode and never use it for ARM work until one of the above is done.

Doing nothing is not an option once the device produces a billable deliverable.

---

## Credit checklist (do all of these before any public release)

- [ ] Add an "Acknowledgements" or "Based on" section to README.md naming PiLiDAR, Philip Gutjahr, the upstream URL, and the CC BY-NC-SA 4.0 license, with a plain statement that this project modifies the original.
- [ ] Change LICENSE to CC BY-NC-SA 4.0, or obtain and document written permission to do otherwise.
- [ ] Keep upstream copyright notices intact in any file that still contains PiLiDAR code, and add a header line noting it was adapted from PiLiDAR.
- [ ] Resolve the commercial-use question (backer status or written grant) and record the outcome below.
- [ ] Consider opening an issue or discussion on the upstream repo describing what this fork does (RTK integration, IMU, LoRa telemetry). The author may want to know, and it is the courteous thing to do for a project you built on. Not required by the license.
- [ ] If any bug fixes are made to PiLiDAR-derived code that would apply upstream (the rpi-lgpio Bookworm fix in DEC-029 is an example, though upstream has since fixed it independently), offer them back as a pull request.

---

## Resolution log

Record dates and outcomes here as items above are closed.

| Date | Item | Outcome |
|---|---|---|
| | | |

---

## Other dependencies

Standard permissive or copyleft-compatible libraries used by this project (Open3D, numpy, pyserial, rpi-lgpio, and whatever else lands in pyproject.toml) carry their own licenses and should be listed in a THIRD_PARTY_LICENSES.md once the dependency set stabilizes. None of them is expected to conflict with CC BY-NC-SA. PiLiDAR is the only upstream that shapes the license of this repo as a whole.
