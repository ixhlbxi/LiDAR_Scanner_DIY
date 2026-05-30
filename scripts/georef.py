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

Defaults:
    * `target_crs_epsg = 0` (the personal-profile default) → no CRS conversion;
      output stays in local ENU meters.
    * `arm_group` sessions → target_crs_epsg from `metadata.json`, units from
      `metadata.json.session.units`.

Failure modes:
    * `numpy` missing → script exits with a clear install hint.
    * `laspy` missing → LAS export is skipped with a warning; PLY still emitted.
    * `pyproj` missing AND target_crs != 0 → script aborts with install hint.
    * Session has no GNSS records → emits points in raw LiDAR frame and warns;
      useful for indoor / no-fix scans.

Decision references: DEC-014, DEC-022, DEC-024, DEC-034.

Dependencies: numpy (required); laspy + pyproj (optional, install via `[post]`
extra).

Changelog:
    0.10.0  2026-05-23  Initial implementation (Phase E of overhaul).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("georef")


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
#                 PA_NORTH=6346) because BASE_STATION_INTEGRATION.md §5 specifies
#                 that as the rover-output contract for arm_group profile.
#
# If you need the sibling's HARN codes here (rare — you'd be using rover output
# in a HARN-native workflow), pass --crs directly with the EPSG code; this dict
# is only consulted for the friendly-name lookup in CLI logs.
ZONE_EPSG: dict[str, int] = {
    "PA_NORTH":   6346,   # NAD83(2011) / Pennsylvania North (ftUS)
    "PA_SOUTH":   6347,   # NAD83(2011) / Pennsylvania South (ftUS)
    "NJ":         6527,   # NAD83(2011) / New Jersey (ftUS)
    "MD":         6487,   # NAD83(2011) / Maryland (ftUS)
    "DE":         6446,   # NAD83(2011) / Delaware (ftUS)
    "NY_EAST":    6535,   # NAD83(2011) / New York East (ftUS)
    "NY_CENTRAL": 6536,   # NAD83(2011) / New York Central (ftUS)
    "NY_WEST":    6537,   # NAD83(2011) / New York West (ftUS)
    "VA_NORTH":   6592,   # NAD83(2011) / Virginia North (ftUS)
    "VA_SOUTH":   6593,   # NAD83(2011) / Virginia South (ftUS)
    "WV_NORTH":   6601,   # NAD83(2011) / West Virginia North (ftUS)
    "WV_SOUTH":   6602,   # NAD83(2011) / West Virginia South (ftUS)
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


def _require_numpy():
    try:
        import numpy as np  # noqa: F401 — caller imports
        return np
    except ImportError as e:
        raise SystemExit(
            "numpy is required for scripts/georef.py — install via "
            "`pip install -e \".[post]\"`"
        ) from e


def _try_import_laspy():
    try:
        import laspy
        return laspy
    except ImportError:
        return None


def _try_import_pyproj():
    try:
        import pyproj
        return pyproj
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


def load_session(session_dir: Path) -> SessionData:
    """Load metadata.json + all relevant JSONL records.

    Reads `scan.jsonl` (mixed lidar/imu/camera/event records) and `gnss.jsonl`
    if present (otherwise falls back to gnss records in scan.jsonl).
    """
    metadata_path = session_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"No metadata.json in {session_dir}")
    metadata = json.loads(metadata_path.read_text())

    scan_path = session_dir / "scan.jsonl"
    if not scan_path.exists():
        raise FileNotFoundError(f"No scan.jsonl in {session_dir}")

    lidar: list[dict] = []
    imu: list[dict] = []
    gnss: list[dict] = []

    for line in scan_path.read_text().splitlines():
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("skipping malformed scan.jsonl line")
            continue
        t = rec.get("type")
        if t == "lidar":
            lidar.append(rec)
        elif t == "imu":
            imu.append(rec)
        elif t == "gnss":
            gnss.append(rec)

    # Prefer a dedicated gnss.jsonl if present (Appendix B says it's optional).
    gnss_path = session_dir / "gnss.jsonl"
    if gnss_path.exists() and not gnss:
        for line in gnss_path.read_text().splitlines():
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "gnss":
                gnss.append(rec)

    logger.info(
        "Loaded session: %d lidar, %d imu, %d gnss records",
        len(lidar), len(imu), len(gnss),
    )
    return SessionData(metadata=metadata, lidar_records=lidar,
                       imu_records=imu, gnss_records=gnss)


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
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w)],
        [2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y)],
    ])


def orientation_at(t_scan: float, imu_records: list[dict]):
    """Find IMU samples bracketing *t_scan* and return slerp'd quaternion.

    If imu_records is empty, returns identity quaternion (acquisition without
    orientation correction — still useful for sanity-check exports).
    """
    np = _require_numpy()
    if not imu_records:
        return np.array([1.0, 0.0, 0.0, 0.0])

    # Binary search; imu_records assumed sorted by timestamp.
    lo, hi = 0, len(imu_records) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if imu_records[mid]["timestamp"] < t_scan:
            lo = mid + 1
        else:
            hi = mid

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
# Point cloud assembly
# ---------------------------------------------------------------------------


def lidar_points_to_local(lidar_record: dict, quat):
    """Convert one lidar scan record to Nx3 points in IMU-aligned local frame.

    LiDAR convention (CLAUDE.md §9): X forward, Y left, Z up. Angle 0° = X-axis,
    increasing CCW. Distance in meters.
    """
    np = _require_numpy()
    pts = lidar_record["points"]
    if not pts:
        return np.zeros((0, 3))
    angles_deg = np.array([p["angle"] for p in pts], dtype=float)
    distances = np.array([p["distance"] for p in pts], dtype=float)
    intensities = np.array([p.get("intensity", 0) for p in pts], dtype=np.uint8)

    a_rad = np.deg2rad(angles_deg)
    x = distances * np.cos(a_rad)
    y = distances * np.sin(a_rad)
    z = np.zeros_like(x)
    local = np.column_stack([x, y, z])

    R = _quat_to_rotmat(quat)
    rotated = local @ R.T
    return rotated, intensities


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
            origin_lat, origin_lon, origin_alt,
        )

    chunks_xyz = []
    chunks_int = []
    total_points = 0
    for rec in session.lidar_records:
        quat = orientation_at(rec["timestamp"], imu_sorted)
        pts_local, intens = lidar_points_to_local(rec, quat)
        if pts_local.size == 0:
            continue

        # Translate by GNSS-derived position offset relative to session origin.
        if origin_lat is not None:
            # Find nearest GNSS fix for this scan
            scan_fix = _nearest_gnss(rec["timestamp"], gnss_sorted)
            if scan_fix is not None:
                dE, dN, dU = _gnss_offset_meters(
                    scan_fix["lat"], scan_fix["lon"], scan_fix.get("alt", 0.0),
                    origin_lat, origin_lon, origin_alt,
                )
                pts_local = pts_local + np.array([dE, dN, dU])

        chunks_xyz.append(pts_local)
        chunks_int.append(intens)
        total_points += len(pts_local)

    if not chunks_xyz:
        logger.warning("No lidar points to export")
        return np.zeros((0, 3)), np.zeros(0, dtype=np.uint8), (origin_lat, origin_lon, origin_alt)

    xyz = np.vstack(chunks_xyz)
    intensity = np.concatenate(chunks_int)
    logger.info("Assembled %d points across %d scans",
                total_points, len(session.lidar_records))
    return xyz, intensity, (origin_lat, origin_lon, origin_alt)


def _nearest_gnss(t_scan: float, gnss_sorted: list[dict]) -> Optional[dict]:
    if not gnss_sorted:
        return None
    # Linear walk is fine for typical session sizes (<10k fixes); upgrade to
    # bisect if profiling says so.
    best = gnss_sorted[0]
    best_gap = abs(best["timestamp"] - t_scan)
    for fix in gnss_sorted[1:]:
        gap = abs(fix["timestamp"] - t_scan)
        if gap < best_gap:
            best, best_gap = fix, gap
    return best


def _gnss_offset_meters(lat: float, lon: float, alt: float,
                        origin_lat: float, origin_lon: float, origin_alt: float):
    """Small-baseline ENU offset (meters) from origin (lat0, lon0, alt0).

    Uses the equirectangular approximation — adequate for the rover's typical
    operating area (<< 1 km from session origin). For larger baselines,
    pyproj's pj_geod is more accurate, but for our purposes this is enough.
    """
    R_EARTH = 6378137.0  # WGS84 semi-major axis, meters
    lat0_rad = math.radians(origin_lat)
    dE = math.radians(lon - origin_lon) * R_EARTH * math.cos(lat0_rad)
    dN = math.radians(lat - origin_lat) * R_EARTH
    dU = alt - origin_alt
    return dE, dN, dU


# ---------------------------------------------------------------------------
# CRS conversion (local ENU → target CRS)
# ---------------------------------------------------------------------------


def project_to_crs(xyz, origin_lat_lon_alt, target_epsg: int, units: str):
    """Convert Nx3 (East, North, Up) local-ENU meters to the target CRS.

    Args:
        xyz: Nx3 float array in local ENU meters relative to origin.
        origin_lat_lon_alt: (lat, lon, alt) WGS84 — the local ENU origin.
        target_epsg: EPSG of the target CRS. 0 = no conversion (passthrough).
        units: "m" or "ft" — controls output Z and (when target CRS allows)
            horizontal units. For State-Plane ft-US codes (e.g. 6346) the CRS
            itself defines the units; we don't double-scale.

    Returns:
        Nx3 array in target CRS units.
    """
    np = _require_numpy()
    if target_epsg == 0 or origin_lat_lon_alt[0] is None:
        # No conversion; keep local ENU, optionally feet
        if units == "ft":
            return xyz * (1.0 / 0.3048006096012192)  # US Survey Foot
        return xyz

    pyproj = _try_import_pyproj()
    if pyproj is None:
        raise SystemExit(
            "pyproj is required when target_crs_epsg != 0 — install via "
            "`pip install -e \".[post]\"`"
        )

    origin_lat, origin_lon, origin_alt = origin_lat_lon_alt

    # Convert each ENU point back to (lat, lon, alt) WGS84, then forward to target CRS.
    # For typical rover baselines (<1 km) this is precise enough.
    R_EARTH = 6378137.0
    lat0_rad = math.radians(origin_lat)
    east, north, up = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    lats = origin_lat + np.degrees(north / R_EARTH)
    lons = origin_lon + np.degrees(east / (R_EARTH * math.cos(lat0_rad)))
    alts = origin_alt + up

    transformer = pyproj.Transformer.from_crs(
        "EPSG:4326", f"EPSG:{target_epsg}", always_xy=True
    )
    # always_xy=True → x = lon, y = lat
    xs, ys = transformer.transform(lons, lats)
    zs = alts
    # If the target CRS uses ft-US but the user explicitly asked for meters,
    # divide by 0.3048006096012192. We trust the EPSG's native units by default.
    return np.column_stack([xs, ys, zs])


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
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property uchar red\n"
        "property uchar green\n"
        "property uchar blue\n"
        "end_header\n"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(header.encode("ascii"))
        # Pack vertex bytes: 3 float32 + 3 uint8 = 15 bytes per point
        vtx = np.zeros(n, dtype=[("xyz", "<f4", 3),
                                  ("rgb", "u1", 3)])
        vtx["xyz"] = xyz.astype(np.float32)
        gray = intensity.astype(np.uint8)
        vtx["rgb"][:, 0] = gray
        vtx["rgb"][:, 1] = gray
        vtx["rgb"][:, 2] = gray
        f.write(vtx.tobytes(order="C"))
    logger.info("PLY written: %s (%d points)", out_path, n)


def export_las(out_path: Path, xyz, intensity, target_epsg: int) -> bool:
    """Write a LAS 1.4 point record format 6 file. Returns False if laspy
    isn't available."""
    laspy = _try_import_laspy()
    if laspy is None:
        logger.warning("laspy not installed — skipping LAS export (PLY still emitted)")
        return False
    np = _require_numpy()

    header = laspy.LasHeader(point_format=6, version="1.4")
    if target_epsg > 0:
        try:
            header.add_crs(f"EPSG:{target_epsg}")
        except AttributeError:
            # Older laspy versions name this differently
            pass

    las = laspy.LasData(header)
    las.x = xyz[:, 0]
    las.y = xyz[:, 1]
    las.z = xyz[:, 2]
    # Intensity in LAS is uint16; scale our 0..255 up so renderers don't darken.
    las.intensity = (intensity.astype(np.uint16) << 8)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    las.write(str(out_path))
    logger.info("LAS written: %s (%d points, EPSG:%d)",
                out_path, len(xyz), target_epsg)
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Post-process a rover session: JSONL -> georeferenced PLY/LAS.",
    )
    parser.add_argument("session_dir", type=Path,
                        help="Path to the rover session directory (contains scan.jsonl)")
    parser.add_argument("--crs", type=int, default=None,
                        help="Override target EPSG (default: metadata.json.session.target_crs_epsg)")
    parser.add_argument("--units", choices=["m", "ft"], default=None,
                        help="Override output units (default: metadata.json.session.units)")
    parser.add_argument("--out-prefix", type=str, default=None,
                        help="Output filename prefix (default: session directory name)")
    parser.add_argument("--no-las", action="store_true",
                        help="Skip LAS export even if laspy is installed")
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
        session_dir.name, profile, zone_name_for(target_epsg), target_epsg, units,
    )

    xyz, intensity, origin = session_to_pointcloud(session)
    if len(xyz) == 0:
        logger.error("No points to export")
        return 1

    if target_epsg != 0 or units == "ft":
        xyz = project_to_crs(xyz, origin, target_epsg, units)

    prefix = args.out_prefix or session_dir.name
    out_dir = session_dir / "export"
    export_ply(out_dir / f"{prefix}.ply", xyz, intensity)
    if not args.no_las:
        export_las(out_dir / f"{prefix}.las", xyz, intensity, target_epsg)

    logger.info("Export complete: %s", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
