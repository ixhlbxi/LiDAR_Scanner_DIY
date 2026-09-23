"""Post-processing: JSONL session → georeferenced PLY + (optionally) LAS.

CLI: python -m scripts.georef <session_dir> [--crs EPSG] [--units ft|m]
                                            [--out-prefix PREFIX] [--no-las]

Reads `scan.jsonl` + `metadata.json` from a session directory; builds 3D points
by applying per-scan GNSS position + IMU orientation to each LiDAR slice;
emits PLY (always) and, when `laspy` + `pyproj` are available, a LAS file in
the session's target CRS.

This is the deliberate v0.10 deferred-georef pipeline (DEC-022, DEC-034). Acquisition
logs in SI / WGS84 / local ENU; CRS conversion happens here.

Coordinate flow:

    LiDAR polar (angle, distance)  →  local Cartesian (forward, left, up)
    ─(T_lidar_imu — identity in v1.0 absent calibration; DEC-024)─►
    IMU frame
    ─(slerp(t_scan) using IMU ring buffer; DEC-014)─►
    World-aligned per-scan orientation
    ─(GNSS antenna position; T_body_gnss zero in v1.0 absent calibration)─►
    Local ENU (origin = first valid GNSS fix in the session)
    ─(pyproj transform → target_crs_epsg from metadata.json or --crs)─►
    Target CRS (e.g. NAD83(2011) PA-N ft-US for arm_group profile)

Heights are ellipsoidal (WGS84) throughout; no geoid model is applied. Z is
scaled to the target CRS's horizontal unit so LAS/PLY axes agree.

Defaults:
    * `target_crs_epsg = 0` (the personal-profile default) → no CRS conversion;
      output stays in local ENU meters.
    * `arm_group` sessions → target_crs_epsg from `metadata.json`, units from
      `metadata.json.session.units`.

Failure modes:
    * `numpy` missing → script exits with a clear install hint.
    * `laspy` missing → LAS export is skipped with a warning; PLY still emitted.
    * `pyproj` missing AND target_crs != 0 → script aborts with install hint.
    * `target_crs` names a geographic (not projected) CRS → script aborts;
      a point cloud needs planar coordinates.
    * Session has no GNSS records → emits points in raw LiDAR frame and warns;
      useful for indoor / no-fix scans. The exported LAS carries no CRS in
      this case either, for the same reason.

Decision references: DEC-014, DEC-022, DEC-024, DEC-034.

Dependencies: numpy (required); laspy + pyproj (optional, install via `[post]`
extra).

Changelog:
    0.12.0  2026-09-23  project_to_crs() returns (xyz, epsg_to_embed) so a LAS
                        file never carries a CRS its coordinates aren't
                        actually in (no GNSS fix, geographic target, or a
                        units/CRS mismatch); rejects geographic target CRSs;
                        export_las() catches any add_crs() failure, not just
                        AttributeError; yaw stripped from IMU orientation when
                        no session record ever supplied a magnetometer sample;
                        session_to_pointcloud() warns when the mast angle
                        never changes (planar/continuous-mode output).
    0.11.0  2026-09-22  Rotation-aware session load (rotated scan/gnss segments,
                        columnar lidar, batched IMU); mount + mast rotation applied
                        before the IMU quaternion; Z scaled to the target CRS's
                        horizontal unit; double-precision PLY; CRS-embed warning.
    0.10.0  2026-05-23  Initial implementation (Phase E of overhaul).
"""

from __future__ import annotations

import argparse
import bisect
import importlib
import json
import logging
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("georef")

R_EARTH_M = 6378137.0  # WGS84 semi-major axis
US_SURVEY_FOOT_M = 0.3048006096012192


# ---------------------------------------------------------------------------
# State-Plane zone vocabulary
# ---------------------------------------------------------------------------
#
# Mirrors the *naming* of arm-drone-lidar-workflow/base-station/configure_base.py:
# ZONE_EPSG, so cross-repo conversation about zones uses the same keys. The
# *values* differ deliberately:
#
#   sibling repo uses NAD83(HARN) State Plane codes in meters (e.g. PA_NORTH=2271)
#                 because their NTRIP base-setup workflow is HARN/meters native.
#   this rover uses NAD83(2011) State Plane codes in US Survey Foot (e.g.
#                 PA_NORTH=6563) because BASE_STATION_INTEGRATION.md §5 specifies
#                 that as the rover-output contract for arm_group profile.
#
# If you need the sibling's HARN codes here (rare — you'd be using rover output
# in a HARN-native workflow), pass --crs directly with the EPSG code; this dict
# is only consulted for the friendly-name lookup in CLI logs.
#
# Every code below is verified against pyproj 3.7.2 (test_zone_epsg_table_
# resolves_to_named_ftus_crs): each must resolve to the named NAD83(2011) ftUS
# State Plane CRS with unit_conversion_factor == US_SURVEY_FOOT_M. An earlier
# table had 9 of 12 codes wrong (e.g. PA_NORTH=6346, which is actually
# NAD83(2011) / UTM zone 17N, metric) — fixed 2026-09-22.
ZONE_EPSG: dict[str, int] = {
    "PA_NORTH": 6563,  # NAD83(2011) / Pennsylvania North (ftUS)
    "PA_SOUTH": 6565,  # NAD83(2011) / Pennsylvania South (ftUS)
    "NJ": 6527,  # NAD83(2011) / New Jersey (ftUS)
    "MD": 6488,  # NAD83(2011) / Maryland (ftUS)
    "DE": 6436,  # NAD83(2011) / Delaware (ftUS)
    "NY_EAST": 6537,  # NAD83(2011) / New York East (ftUS)
    "NY_CENTRAL": 6535,  # NAD83(2011) / New York Central (ftUS)
    "NY_WEST": 6541,  # NAD83(2011) / New York West (ftUS)
    "NY_LONG_ISLAND": 6539,  # NAD83(2011) / New York Long Island (ftUS)
    "VA_NORTH": 6593,  # NAD83(2011) / Virginia North (ftUS)
    "VA_SOUTH": 6595,  # NAD83(2011) / Virginia South (ftUS)
    "WV_NORTH": 6601,  # NAD83(2011) / West Virginia North (ftUS)
    "WV_SOUTH": 6603,  # NAD83(2011) / West Virginia South (ftUS)
}


def zone_name_for(epsg: int) -> str:
    """Return the friendly zone name for an EPSG code, or 'EPSG:NNNN' as fallback."""
    for name, code in ZONE_EPSG.items():
        if code == epsg:
            return name
    return f"EPSG:{epsg}"


# ---------------------------------------------------------------------------
# Lazy-import wrappers — keep the script importable even when post-process
# deps aren't installed
# ---------------------------------------------------------------------------


_NP = None


def _require_numpy():
    global _NP
    if _NP is None:
        try:
            import numpy as np
        except ImportError as e:
            raise SystemExit(
                'numpy is required for scripts/georef.py — install via `pip install -e ".[post]"`'
            ) from e
        _NP = np
    return _NP


def _optional_import(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Session loader
# ---------------------------------------------------------------------------


@dataclass
class SessionData:
    """All inputs to georef, in memory."""

    metadata: dict
    lidar_records: list[dict]
    imu_records: list[dict]
    gnss_records: list[dict]


_SEGMENT_RE = re.compile(r"^(scan|gnss)(?:_(\d+))?\.jsonl$")


def _segment_files(session_dir: Path, stem: str) -> list[Path]:
    """`<stem>.jsonl, <stem>_001.jsonl, …` in numeric order (SessionLogger rotation)."""
    found: list[tuple[int, Path]] = []
    for p in session_dir.glob(f"{stem}*.jsonl"):
        m = _SEGMENT_RE.match(p.name)
        if m and m.group(1) == stem:
            found.append((int(m.group(2) or 0), p))
    return [p for _, p in sorted(found)]


def _iter_jsonl(paths: list[Path]):
    for p in paths:
        for line in p.read_text().splitlines():
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                logger.warning("skipping malformed line in %s", p.name)


def _flatten_imu_batch(rec: dict) -> list[dict]:
    """One batched IMU record → one dict per sample."""
    ts = rec["t"]
    return [
        {
            "timestamp": ts[i],
            "accel": rec["accel"][i],
            "gyro": rec["gyro"][i],
            "mag": rec["mag"][i],
            "orientation": rec["orientation"][i],
        }
        for i in range(len(ts))
    ]


def load_session(session_dir: Path) -> SessionData:
    """Load metadata.json + every scan*/gnss* segment (rotation-aware)."""
    metadata_path = session_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"No metadata.json in {session_dir}")
    metadata = json.loads(metadata_path.read_text())

    scan_files = _segment_files(session_dir, "scan")
    if not scan_files:
        raise FileNotFoundError(f"No scan.jsonl in {session_dir}")

    lidar: list[dict] = []
    imu: list[dict] = []
    gnss: list[dict] = []
    for rec in _iter_jsonl(scan_files):
        t = rec.get("type")
        if t == "lidar":
            lidar.append(rec)
        elif t == "imu":
            imu.extend(_flatten_imu_batch(rec))
        elif t == "gnss":
            gnss.append(rec)

    # gnss records are mirrored into scan.jsonl by the logger; dedicated gnss*
    # segments are supplemental (e.g. a rotated segment whose mirror in
    # scan.jsonl was itself rotated away) rather than a strict either/or —
    # de-duplication across the two sources is deferred (stage 4).
    gnss_files = _segment_files(session_dir, "gnss")
    if gnss_files:
        extra = [r for r in _iter_jsonl(gnss_files) if r.get("type") == "gnss"]
        gnss = gnss + extra if gnss else extra

    logger.info(
        "Loaded session: %d lidar, %d imu, %d gnss records across %d scan segment(s)",
        len(lidar),
        len(imu),
        len(gnss),
        len(scan_files),
    )
    return SessionData(metadata=metadata, lidar_records=lidar, imu_records=imu, gnss_records=gnss)


# ---------------------------------------------------------------------------
# Quaternion + slerp helpers (scalar-first [w, x, y, z], per CLAUDE.md §9)
# ---------------------------------------------------------------------------


def _quat_normalize(q):
    np = _require_numpy()
    q = np.asarray(q, dtype=float)
    n = np.linalg.norm(q)
    return q / n if n > 0 else np.array([1.0, 0.0, 0.0, 0.0])


def _quat_slerp(q1, q2, t: float):
    """Spherical linear interpolation for two scalar-first quaternions.

    Implements DEC-014's slerp directly without scipy so the script runs anywhere
    numpy is installed.
    """
    np = _require_numpy()
    q1 = _quat_normalize(q1)
    q2 = _quat_normalize(q2)
    dot = float(np.dot(q1, q2))
    if dot < 0.0:
        q2 = -q2
        dot = -dot
    if dot > 0.9995:
        # Nearly identical — fall back to lerp + normalize
        result = q1 + t * (q2 - q1)
        return _quat_normalize(result)
    theta_0 = math.acos(dot)
    sin_theta_0 = math.sin(theta_0)
    theta = theta_0 * t
    s1 = math.sin(theta_0 - theta) / sin_theta_0
    s2 = math.sin(theta) / sin_theta_0
    return s1 * q1 + s2 * q2


def _quat_to_rotmat(q):
    """Convert scalar-first quaternion [w, x, y, z] to a 3x3 rotation matrix."""
    np = _require_numpy()
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _rotmat_to_quat(r):
    """Convert a 3x3 rotation matrix to a scalar-first quaternion [w, x, y, z].

    Standard trace-based extraction (Shepperd's method), picking the largest
    of the four denominators to stay numerically stable near any singularity.
    Inverse of _quat_to_rotmat.
    """
    np = _require_numpy()
    trace = r[0, 0] + r[1, 1] + r[2, 2]
    if trace > 0:
        s = 0.5 / math.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (r[2, 1] - r[1, 2]) * s
        y = (r[0, 2] - r[2, 0]) * s
        z = (r[1, 0] - r[0, 1]) * s
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = 2.0 * math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2])
        w = (r[2, 1] - r[1, 2]) / s
        x = 0.25 * s
        y = (r[0, 1] + r[1, 0]) / s
        z = (r[0, 2] + r[2, 0]) / s
    elif r[1, 1] > r[2, 2]:
        s = 2.0 * math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2])
        w = (r[0, 2] - r[2, 0]) / s
        x = (r[0, 1] + r[1, 0]) / s
        y = 0.25 * s
        z = (r[1, 2] + r[2, 1]) / s
    else:
        s = 2.0 * math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1])
        w = (r[1, 0] - r[0, 1]) / s
        x = (r[0, 2] + r[2, 0]) / s
        y = (r[1, 2] + r[2, 1]) / s
        z = 0.25 * s
    return np.array([w, x, y, z])


def _strip_yaw(q):
    """Remove the yaw (rotation about world/body Z) component of a
    quaternion, keeping roll and pitch.

    Method: convert q to a rotation matrix, read the yaw angle off its
    upper-left 2x2 block (standard Z-first Euler extraction), then
    left-multiply the matrix by R_z(-yaw) to cancel it —
    R_z(-yaw) @ R(q) keeps R(q)'s roll/pitch while zeroing its heading.
    Used by session_to_pointcloud() when no magnetometer data is present in
    the session (see its docstring / the INFO log it emits).
    """
    r = _quat_to_rotmat(q)
    yaw = math.atan2(float(r[1, 0]), float(r[0, 0]))
    r_no_yaw = _rot_z(-math.degrees(yaw)) @ r
    return _rotmat_to_quat(r_no_yaw)


def orientation_at(t_scan: float, imu_records: list[dict]):
    """Find IMU samples bracketing *t_scan* and return slerp'd quaternion.

    If imu_records is empty, returns identity quaternion (acquisition without
    orientation correction — still useful for sanity-check exports).
    """
    np = _require_numpy()
    if not imu_records:
        return np.array([1.0, 0.0, 0.0, 0.0])

    # imu_records assumed sorted by timestamp.
    lo = bisect.bisect_left(imu_records, t_scan, key=lambda r: r["timestamp"])

    if lo == 0:
        return np.asarray(imu_records[0]["orientation"], dtype=float)
    if lo >= len(imu_records):
        return np.asarray(imu_records[-1]["orientation"], dtype=float)

    a = imu_records[lo - 1]
    b = imu_records[lo]
    span = b["timestamp"] - a["timestamp"]
    if span <= 0:
        return np.asarray(a["orientation"], dtype=float)
    t = (t_scan - a["timestamp"]) / span
    t = max(0.0, min(1.0, t))
    return _quat_slerp(a["orientation"], b["orientation"], t)


# ---------------------------------------------------------------------------
# Geometry helpers — mount/mast rotation and local ENU
# ---------------------------------------------------------------------------


def _rot_z(theta_deg: float):
    np = _require_numpy()
    c, s = math.cos(math.radians(theta_deg)), math.sin(math.radians(theta_deg))
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def enu_offset_m(lat, lon, alt, lat0, lon0, alt0) -> tuple[float, float, float]:
    """Small-baseline ENU offset (m) of (lat, lon, alt) from the origin. Equirectangular;
    adequate well under 1 km."""
    lat0_rad = math.radians(lat0)
    e = math.radians(lon - lon0) * R_EARTH_M * math.cos(lat0_rad)
    n = math.radians(lat - lat0) * R_EARTH_M
    return e, n, alt - alt0


def geodetic_from_enu(east, north, up, lat0: float, lon0: float, alt0: float):
    """Vectorised inverse of enu_offset_m (arrays in, arrays out)."""
    np = _require_numpy()
    lat0_rad = math.radians(lat0)
    lats = lat0 + np.degrees(north / R_EARTH_M)
    lons = lon0 + np.degrees(east / (R_EARTH_M * math.cos(lat0_rad)))
    return lats, lons, alt0 + up


# ---------------------------------------------------------------------------
# Point cloud assembly
# ---------------------------------------------------------------------------


def lidar_points_to_local(lidar_record: dict, quat):
    """One columnar lidar record → (N×3 body-ENU-aligned points, N intensities).

    Chain (spec §5): scan plane (LiDAR x forward, y left) is mounted as the body
    X-Z plane → rotate about body Z by the commanded mast angle → rotate by the
    IMU quaternion. Always returns a tuple, even for an empty record.
    """
    np = _require_numpy()
    angles = np.asarray(lidar_record.get("angle", []), dtype=float)
    dists = np.asarray(lidar_record.get("distance", []), dtype=float)
    inten = np.asarray(lidar_record.get("intensity", []), dtype=np.uint8)
    if angles.size == 0:
        return np.zeros((0, 3)), np.zeros(0, dtype=np.uint8)
    a = np.deg2rad(angles)
    x_l = dists * np.cos(a)
    y_l = dists * np.sin(a)
    body = np.column_stack([x_l, np.zeros_like(x_l), y_l])  # mount: LiDAR y → body up
    body = body @ _rot_z(float(lidar_record.get("mast_angle_deg", 0.0))).T
    world = body @ _quat_to_rotmat(quat).T
    return world, inten


def session_to_pointcloud(session: SessionData):
    """Assemble all lidar records into one Nx3 point cloud (local ENU meters)
    plus an aligned intensity array.

    Origin is the first valid GNSS fix (fix_type >= 2). When no fix is available,
    the origin is the rover itself (all points are in LiDAR-relative meters).
    """
    np = _require_numpy()
    imu_sorted = sorted(session.imu_records, key=lambda r: r["timestamp"])
    gnss_sorted = sorted(
        [g for g in session.gnss_records if g.get("fix_type", 0) >= 2],
        key=lambda r: r["timestamp"],
    )

    if len(session.lidar_records) > 1:
        mast_angles = {rec.get("mast_angle_deg", 0.0) for rec in session.lidar_records}
        if len(mast_angles) == 1:
            logger.warning("mast angle never changed: output is planar (continuous mode?)")

    # DEC-013 / DEC-012: a 6-DOF Madgwick filter (no magnetometer) has no
    # absolute heading reference, so its yaw is pure gyro-integration drift —
    # meaningless on a rover that is stationary between scans. When nothing in
    # the session ever supplied a magnetometer sample, strip yaw from every
    # orientation and let the commanded mast angle (already applied in
    # lidar_points_to_local via _rot_z) stand in for heading instead.
    strip_yaw = not any(r.get("mag") is not None for r in session.imu_records)
    if strip_yaw:
        logger.info(
            "no magnetometer data: using IMU roll/pitch only; yaw from the "
            "commanded mast angle (6-DOF gyro yaw drifts on a static rover)"
        )

    if not gnss_sorted:
        logger.warning(
            "Session has no GNSS fix records — output will be in raw LiDAR ENU "
            "with no georeferencing."
        )
        origin_lat, origin_lon, origin_alt = None, None, None
    else:
        origin = gnss_sorted[0]
        origin_lat = origin["lat"]
        origin_lon = origin["lon"]
        origin_alt = origin.get("alt", 0.0)
        logger.info(
            "Session origin (local ENU): lat=%.7f lon=%.7f alt=%.2f",
            origin_lat,
            origin_lon,
            origin_alt,
        )

    chunks_xyz = []
    chunks_int = []
    for rec in session.lidar_records:
        quat = orientation_at(rec["timestamp"], imu_sorted)
        if strip_yaw:
            quat = _strip_yaw(quat)
        pts_local, intens = lidar_points_to_local(rec, quat)
        if pts_local.size == 0:
            continue

        # Translate by GNSS-derived position offset relative to session origin.
        if origin_lat is not None:
            # Find nearest GNSS fix for this scan
            scan_fix = _nearest_gnss(rec["timestamp"], gnss_sorted)
            if scan_fix is not None:
                dE, dN, dU = enu_offset_m(
                    scan_fix["lat"],
                    scan_fix["lon"],
                    scan_fix.get("alt", 0.0),
                    origin_lat,
                    origin_lon,
                    origin_alt,
                )
                pts_local = pts_local + np.array([dE, dN, dU])

        chunks_xyz.append(pts_local)
        chunks_int.append(intens)

    if not chunks_xyz:
        logger.warning("No lidar points to export")
        return np.zeros((0, 3)), np.zeros(0, dtype=np.uint8), (origin_lat, origin_lon, origin_alt)

    xyz = np.vstack(chunks_xyz)
    intensity = np.concatenate(chunks_int)
    logger.info("Assembled %d points across %d scans", len(xyz), len(session.lidar_records))
    return xyz, intensity, (origin_lat, origin_lon, origin_alt)


def _nearest_gnss(t_scan: float, gnss_sorted: list[dict]) -> dict | None:
    if not gnss_sorted:
        return None
    i = bisect.bisect_left(gnss_sorted, t_scan, key=lambda r: r["timestamp"])
    if i == 0:
        return gnss_sorted[0]
    if i >= len(gnss_sorted):
        return gnss_sorted[-1]
    before, after = gnss_sorted[i - 1], gnss_sorted[i]
    return before if t_scan - before["timestamp"] <= after["timestamp"] - t_scan else after


# ---------------------------------------------------------------------------
# CRS conversion (local ENU → target CRS)
# ---------------------------------------------------------------------------


def project_to_crs(xyz, origin_lat_lon_alt, target_epsg: int, units: str):
    """Convert N×3 local-ENU metres to the target CRS.

    With ``target_epsg == 0`` the ENU frame is kept and only ``units`` applies.
    Otherwise X/Y are projected with pyproj and Z (ellipsoidal height, metres)
    is scaled to the CRS's horizontal unit so all three axes agree; if ``units``
    then disagrees with the CRS unit, all three axes are converted (ft-US ↔ m)
    and the choice is logged.

    Returns:
        (xyz_out, epsg_to_embed) — a LAS file must never carry a CRS label its
        coordinates aren't actually in, so ``epsg_to_embed`` is 0 whenever that
        would be true: no GNSS origin, no CRS requested, or a unit mismatch
        forced a conversion away from the CRS's native unit. Only when the
        output truly is in ``target_epsg`` does ``epsg_to_embed`` equal it.

    Raises:
        SystemExit: pyproj is missing and a conversion was requested, or
            ``target_epsg`` names a geographic (not projected) CRS — a LAS/PLY
            point cloud needs planar coordinates, and a geographic CRS (e.g.
            EPSG:4326) would silently hand back lat/lon-shaped numbers instead.
    """
    np = _require_numpy()
    if origin_lat_lon_alt[0] is None:
        if target_epsg != 0:
            logger.warning("no GNSS fix: exporting local ENU, LAS will carry no CRS")
        out = xyz / US_SURVEY_FOOT_M if units == "ft" else xyz
        return out, 0

    if target_epsg == 0:
        out = xyz / US_SURVEY_FOOT_M if units == "ft" else xyz
        return out, 0

    pyproj = _optional_import("pyproj")
    if pyproj is None:
        raise SystemExit(
            'pyproj is required when target_crs_epsg != 0 — install via `pip install -e ".[post]"`'
        )
    crs = pyproj.CRS.from_epsg(target_epsg)
    if not crs.is_projected:
        raise SystemExit(f"target CRS must be projected; EPSG:{target_epsg} is geographic")

    lat0, lon0, alt0 = origin_lat_lon_alt
    lats, lons, alts = geodetic_from_enu(xyz[:, 0], xyz[:, 1], xyz[:, 2], lat0, lon0, alt0)
    transformer = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    xs, ys = transformer.transform(lons, lats)

    # Metres per horizontal CRS unit (1.0 for metric CRSs, 0.3048006… for ftUS).
    unit_m = float(crs.axis_info[0].unit_conversion_factor)
    zs = alts / unit_m  # ellipsoidal height, same unit as X/Y
    out = np.column_stack([xs, ys, zs])

    crs_is_ft = abs(unit_m - US_SURVEY_FOOT_M) < 1e-9 or abs(unit_m - 0.3048) < 1e-9
    epsg_to_embed = target_epsg
    if units == "m" and crs_is_ft:
        logger.warning(
            "--units m on a ftUS CRS: values converted, LAS written without CRS; "
            "pick the metric sibling CRS to keep the label"
        )
        out = out * unit_m
        epsg_to_embed = 0
    elif units == "ft" and not crs_is_ft:
        logger.warning(
            "--units ft on a metric CRS: values converted, LAS written without CRS; "
            "pick the ftUS sibling CRS to keep the label"
        )
        out = out / US_SURVEY_FOOT_M
        epsg_to_embed = 0
    return out, epsg_to_embed


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------


def export_ply(out_path: Path, xyz, intensity) -> None:
    """Write a binary little-endian PLY file with intensity-as-color."""
    np = _require_numpy()
    n = len(xyz)
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property double x\n"
        "property double y\n"
        "property double z\n"
        "property uchar red\n"
        "property uchar green\n"
        "property uchar blue\n"
        "end_header\n"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(header.encode("ascii"))
        # 3 float64 + 3 uint8 = 27 bytes per point
        vtx = np.zeros(n, dtype=[("xyz", "<f8", 3), ("rgb", "u1", 3)])
        vtx["xyz"] = xyz.astype(np.float64)
        gray = intensity.astype(np.uint8)
        vtx["rgb"][:, 0] = gray
        vtx["rgb"][:, 1] = gray
        vtx["rgb"][:, 2] = gray
        f.write(vtx.tobytes(order="C"))
    logger.info("PLY written: %s (%d points)", out_path, n)


def export_las(out_path: Path, xyz, intensity, target_epsg: int) -> bool:
    """Write a LAS 1.4 point record format 6 file. Returns False if laspy
    isn't available."""
    laspy = _optional_import("laspy")
    if laspy is None:
        logger.warning("laspy not installed — skipping LAS export (PLY still emitted)")
        return False
    np = _require_numpy()

    header = laspy.LasHeader(point_format=6, version="1.4")
    if target_epsg > 0:
        try:
            header.add_crs(f"EPSG:{target_epsg}")
        except Exception as e:
            # Broad on purpose: an older/incompatible laspy version, a pyproj
            # error surfacing through add_crs(), or anything else that can go
            # wrong embedding the CRS must still leave the LAS file written —
            # the geometry is correct even when the label isn't embeddable.
            logger.warning(
                "laspy %s cannot embed CRS EPSG:%d — LAS written without CRS (%s)",
                getattr(laspy, "__version__", "?"),
                target_epsg,
                e,
            )

    las = laspy.LasData(header)
    las.x = xyz[:, 0]
    las.y = xyz[:, 1]
    las.z = xyz[:, 2]
    # Intensity in LAS is uint16; scale our 0..255 up so renderers don't darken.
    las.intensity = intensity.astype(np.uint16) << 8

    out_path.parent.mkdir(parents=True, exist_ok=True)
    las.write(str(out_path))
    logger.info("LAS written: %s (%d points, EPSG:%d)", out_path, len(xyz), target_epsg)
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Post-process a rover session: JSONL -> georeferenced PLY/LAS.",
    )
    parser.add_argument(
        "session_dir", type=Path, help="Path to the rover session directory (contains scan.jsonl)"
    )
    parser.add_argument(
        "--crs",
        type=int,
        default=None,
        help="Override target EPSG (default: metadata.json.session.target_crs_epsg)",
    )
    parser.add_argument(
        "--units",
        choices=["m", "ft"],
        default=None,
        help="Override output units (default: metadata.json.session.units)",
    )
    parser.add_argument(
        "--out-prefix",
        type=str,
        default=None,
        help="Output filename prefix (default: session directory name)",
    )
    parser.add_argument(
        "--no-las", action="store_true", help="Skip LAS export even if laspy is installed"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    session_dir: Path = args.session_dir
    if not session_dir.is_dir():
        parser.error(f"Not a directory: {session_dir}")

    session = load_session(session_dir)

    sess_meta = session.metadata.get("session", {})
    target_epsg = args.crs if args.crs is not None else int(sess_meta.get("target_crs_epsg", 0))
    units = args.units or sess_meta.get("units", "m")

    profile = sess_meta.get("profile", "personal")
    if profile == "arm_group" and target_epsg == 0:
        parser.error(
            "Session has arm_group profile but no target_crs_epsg recorded "
            "and no --crs override given. Pass --crs <EPSG> to export."
        )

    logger.info(
        "Exporting session=%s profile=%s target=%s (EPSG:%d) units=%s",
        session_dir.name,
        profile,
        zone_name_for(target_epsg),
        target_epsg,
        units,
    )

    xyz, intensity, origin = session_to_pointcloud(session)
    if len(xyz) == 0:
        logger.error("No points to export")
        return 1

    epsg_to_embed = target_epsg
    if target_epsg != 0 or units == "ft":
        xyz, epsg_to_embed = project_to_crs(xyz, origin, target_epsg, units)

    prefix = args.out_prefix or session_dir.name
    out_dir = session_dir / "export"
    export_ply(out_dir / f"{prefix}.ply", xyz, intensity)
    if not args.no_las:
        export_las(out_dir / f"{prefix}.las", xyz, intensity, epsg_to_embed)

    logger.info("Export complete: %s", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
