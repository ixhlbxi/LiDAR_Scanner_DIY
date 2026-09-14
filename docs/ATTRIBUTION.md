# Attribution and Upstream Obligations

**Status: OPEN. Read this before any public release, before changing LICENSE, and before the device's use category ever changes.**

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

## Use category (decided September 14, 2026)

**This is Brian's personal educational project. It is not an ARM Group product, tool, or deliverable, and it will not be used on billable jobs or client work.**

Where ARM Group appears in this repo (the `arm_group` mode, the Base-Station NTRIP companion role, State Plane export for TBC), it is a novelty: a personal hobby device being pointed at the firm's base station because that is the RTK source Brian has access to. Nothing the device produces feeds a client deliverable, a project record, or an invoice.

This is squarely non-commercial under CC BY-NC-SA. To keep it that way: no real client project codes on output, no scan data handed to a client or dropped into a job folder, no billing against anything the device produces.

**If this category ever changes** (someone wants to use it on a real job, even once), stop and read the "If commercial use is ever reconsidered" section below before doing so.

---

## The one problem that still must be resolved

### License conflict: this repo says GPL-3.0, upstream requires CC BY-NC-SA

The LICENSE file in this repo is GPL-3.0. CC BY-NC-SA 4.0 is ShareAlike: derivative works must be distributed under the same license (or a CC-designated compatible one). GPL-3.0 is not on that list. As of the creation date, this repo is out of compliance with its upstream license the moment it is shared publicly. The personal-use decision does not fix this; it only closes the NonCommercial question.

Fix options, in order of preference:

- Change LICENSE to CC BY-NC-SA 4.0 to match upstream. Simplest, honest, and the only option that requires no permission.
- Ask Philip Gutjahr for written permission to relicense the derivative. Unlikely to be needed unless the other option is unworkable.

---

## If commercial use is ever reconsidered

The upstream LICENSE.md includes a **backer exception**: backers who support the project through its funding platforms may use the device to offer scanning as a service (but may not sell the device or derivatives as a product). Read the full text in the upstream repo before relying on it.

Paths, in order of preference:

- Become a backer of PiLiDAR through whatever funding platform the project uses, keep the receipt, and note it in the resolution log with the date.
- Contact Philip Gutjahr directly for a written commercial-use grant. Keep the correspondence with the repo.

Doing nothing is not an option once the device produces a billable deliverable.

---

## Credit checklist (do all of these before any public release)

- [ ] Add an "Acknowledgements" or "Based on" section to README.md naming PiLiDAR, Philip Gutjahr, the upstream URL, and the CC BY-NC-SA 4.0 license, with a plain statement that this project modifies the original.
- [ ] Change LICENSE to CC BY-NC-SA 4.0, or obtain and document written permission to do otherwise.
- [ ] Keep upstream copyright notices intact in any file that still contains PiLiDAR code, and add a header line noting it was adapted from PiLiDAR.
- [ ] Consider opening an issue or discussion on the upstream repo describing what this fork does (RTK integration, IMU, LoRa telemetry). The author may want to know, and it is the courteous thing to do for a project you built on. Not required by the license.
- [ ] If any bug fixes are made to PiLiDAR-derived code that would apply upstream (the rpi-lgpio Bookworm fix in DEC-029 is an example, though upstream has since fixed it independently), offer them back as a pull request.

---

## Resolution log

Record dates and outcomes here as items above are closed.

| Date | Item | Outcome |
|---|---|---|
| September 14, 2026 | Commercial-use question | Closed by decision: personal educational project, not an ARM Group tool. ARM involvement is a novelty (shared base station), not a business use. Reopen this file if that changes. |

---

## Other dependencies

Standard permissive or copyleft-compatible libraries used by this project (Open3D, numpy, pyserial, rpi-lgpio, and whatever else lands in pyproject.toml) carry their own licenses and should be listed in a THIRD_PARTY_LICENSES.md once the dependency set stabilizes. None of them is expected to conflict with CC BY-NC-SA. PiLiDAR is the only upstream that shapes the license of this repo as a whole.
