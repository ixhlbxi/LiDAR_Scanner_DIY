"""Docs guard (stage 6): live docs agree with the code on the facts that drifted.

The tables below are the contract. Each stage-6 doc task adds its document to
ENFORCED and its facts to REQUIRED / FORBIDDEN_BY_FILE; the test functions stay
as they are. A new stale claim, a moved heading, or a mixed CRLF/LF file turns
this red.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

LIVE_DOCS: list[str] = [
    "README.md",
    "CLAUDE.md",
    "docs/ARCHITECTURE.md",
    "docs/ATTRIBUTION.md",
    "docs/BASE_STATION_INTEGRATION.md",
    "docs/DECISIONS.md",
    "docs/HARDWARE.md",
    "docs/ROADMAP.md",
    "docs/SPECIFICATIONS.md",
    "docs/V2_SLAM_CONCEPT.md",
    "deploy/SMOKE_CHECKLIST.md",
]

# Link and line-ending checks also cover these (history/tracking files).
LINKED_DOCS: list[str] = LIVE_DOCS + ["docs/CROSS_REPO_BACKLOG.md"]

# Docs whose stale-fact rules are enforced. Each stage-6 task adds its files.
ENFORCED: set[str] = set()

# (pattern, reason, allowed) — a line matching `pattern` fails unless it also
# matches `allowed` (None = never allowed in an enforced doc).
FORBIDDEN: list[tuple[str, str, str | None]] = [
    (r"\b634[67]\b", "not PA State Plane ftUS (PA North 6563, PA South 6565)", None),
    (
        r"rtcm_rx\+status_tx",
        "retired LoRa role (DEC-031 amended 2026-09-23)",
        r"(?i)retired|rejected",
    ),
    (r"RTCM_CHUNK", "RTCM over LoRa is retired", r"(?i)retired|reserved"),
    (
        r"/dev/tty(USB|ACM)\d",
        "udev symlinks are the primary ports",
        r"(?i)fallback|pre-install",
    ),
    (
        r"(?i)\bin progress\b|\bin flight\b",
        "stale status wording",
        None,
    ),
    (
        r"(?i)\(\s*stub\b|#\s*stub\b|\bstub today\b|—\s*stub\b",
        "every module is implemented",
        None,
    ),
    (
        r"2\s*[×x]\s*ZED-F9P|ZED-F9P\s*[×x]\s*2",
        "the rover needs one ZED-F9P (D-005)",
        None,
    ),
    (
        r"±\s*180",
        "sweep is 360° then rewind (DEC-015 amended)",
        r"(?i)amend|supersed|originally|was\b",
    ),
    (
        r"(?i)carries STATUS/LINK|STATUS/LINK telemetry|receiving LoRa STATUS/LINK",
        "the rover emits STATUS only; LINK is defined but never sent",
        r"(?i)defined|never|retired|reserved|not sent",
    ),
    (
        r"(?i)LoRa-RTCM|RTCM over LoRa|LoRa[- ]relayed RTCM",
        "RTCM over LoRa is retired (DEC-031 amended 2026-09-23)",
        r"(?i)retired|reserved|removal|not needed|amended|never|dead|S5-F1|CR-002",
    ),
    (
        # MR-1 (2026-10-11): DEC-045 as filed said the LoRa boards stay "for the RTCM
        # fallback" and none of the patterns above matched that paraphrase.
        r"(?i)\bRTCM fallback\b",
        "there is no RTCM fallback over LoRa (DEC-031 amended 2026-09-23)",
        r"(?i)retired|supersede|amended|never|no RTCM fallback",
    ),
]

FORBIDDEN_BY_FILE: dict[str, list[tuple[str, str]]] = {}

# Global FORBIDDEN patterns a file may skip (decision history keeps original text).
EXEMPT: dict[str, set[str]] = {}

REQUIRED: dict[str, list[tuple[str, int]]] = {}

# --- Task 2: CLAUDE.md ---
ENFORCED.add("CLAUDE.md")
REQUIRED["CLAUDE.md"] = [
    (r"sweep\.py", 1),
    (r"lora_protocol\.py", 1),
    (r"_io\.py", 1),
    (r"pygeomag", 1),
    (r"python -m ruff format", 1),
    (r"/dev/rover-f9p", 1),
    (r"\[imu\]\.mount", 1),
    (r"antenna_offset_m", 1),
    (r"DEC-035", 2),
    (r"V2_SLAM_CONCEPT\.md", 1),
    (r"test_docs\.py", 1),
    (r"(?i)never share a base session", 1),
]
FORBIDDEN_BY_FILE["CLAUDE.md"] = [
    (r"Phase C", "stale phase label"),
    (r"(?i)overhaul in progress", "stale"),
]

# --- Task 3: README, ATTRIBUTION, V2_SLAM_CONCEPT, archive ---
# docs/README_ORIGINAL.md -> docs/archive/README_v0.9.2.md: cover it for link +
# line-ending checks the same way docs/CROSS_REPO_BACKLOG.md is (history/tracking file).
LINKED_DOCS.append("docs/archive/README_v0.9.2.md")

ENFORCED.add("README.md")
REQUIRED["README.md"] = [
    (r"V2_SLAM_CONCEPT\.md", 1),
    (r"tests\.hardware\.test_ntrip", 1),
    (r"SMOKE_CHECKLIST", 1),
]
FORBIDDEN_BY_FILE["README.md"] = [
    (r"README_ORIGINAL", "archived as docs/archive/README_v0.9.2.md"),
]

ENFORCED.add("docs/ATTRIBUTION.md")
REQUIRED["docs/ATTRIBUTION.md"] = [
    (r"^## Project Lineage", 1),
    (r"archive/README_v0\.9\.2\.md", 1),
]
FORBIDDEN_BY_FILE["docs/ATTRIBUTION.md"] = [(r"Open3D", "not a dependency")]

ENFORCED.add("docs/V2_SLAM_CONCEPT.md")
REQUIRED["docs/V2_SLAM_CONCEPT.md"] = [(r"Unitree L2", 1)]

# --- Task 4: DECISIONS ---
ENFORCED.add("docs/DECISIONS.md")
# DEC-015's original text keeps its "±180°" lines; the amendment block supersedes them.
# DEC-031's original (pre-amendment) text keeps its "LoRa-relayed RTCM"/"STATUS/LINK-Tx"
# wording too — decision history is not rewritten (global constraints); the amendment
# block right below states the current, retired-RTCM/status-only truth.
EXEMPT["docs/DECISIONS.md"] = {
    r"±\s*180",
    r"(?i)carries STATUS/LINK|STATUS/LINK telemetry|receiving LoRa STATUS/LINK",
    r"(?i)LoRa-RTCM|RTCM over LoRa|LoRa[- ]relayed RTCM",
}
REQUIRED["docs/DECISIONS.md"] = [
    (r"\*\*Amendment \(2026-09-23\):\*\*", 3),
    (r"\b6563\b", 1),
    (r"(?i)amended 2026-09-23", 2),
    (r"S5-F1", 1),
    (r"S5-R3", 1),
]

# --- Task 5: ARCHITECTURE ---
ENFORCED.add("docs/ARCHITECTURE.md")
REQUIRED["docs/ARCHITECTURE.md"] = [
    (r"\b6563\b", 1),
    (r"(?i)status-only", 1),
    (r"(?i)one client at a time", 1),
    (r"(?i)rest heading", 1),
    (r"antenna_offset_m", 1),
    (r"\[imu\]\.mount", 1),
    (r"logger_degraded", 1),
    (r"(?i)exit (code )?4", 1),
]
FORBIDDEN_BY_FILE["docs/ARCHITECTURE.md"] = [
    (r"(?i)current sense", "no current sensing exists"),
    (r"(?i)disk space monitor", "no disk monitor exists"),
]

# --- Task 6: SPECIFICATIONS ---
ENFORCED.add("docs/SPECIFICATIONS.md")
REQUIRED["docs/SPECIFICATIONS.md"] = [
    (r"/etc/rover/config\.toml", 1),
    (r"config/default\.toml", 2),
    (r"sweep_start", 1),
    (r"returned_home", 1),
    (r"return_home_failed", 1),
    (r"export\.json", 2),
    (r"_navd88", 1),
    (r"\"geometry\"", 1),
    (r"mast_angle_deg", 1),
    (r"\"pdop\"", 1),
    (r"antenna_offset_m", 1),
    (r"(?i)exit (code )?3", 1),
    (r"pyproj sync --file us_noaa_g2018u0\.tif", 1),
    (r"sweep\.py", 1),
]
FORBIDDEN_BY_FILE["docs/SPECIFICATIONS.md"] = [
    (r"/home/pi/rover", "config and data live under /etc/rover and /var/lib/rover"),
    (r"\"firmware_version\": \"0\.9", "metadata is generated from the running code"),
    (
        r"(?i)^\s*fusion_output_hz|^\s*rtcm_profile|^\s*survey_in_|^\s*\[power\]",
        "removed key shown as live",
    ),
]

# --- Task 7: BASE_STATION_INTEGRATION ---
ENFORCED.add("docs/BASE_STATION_INTEGRATION.md")
# Deviation (final fix wave, disclosed): the §2.2 heading "Fallback -- LoRa-Relayed
# RTCM" itself carries no same-line "retired" cue (the retirement is stated in the
# prose right below it), so it trips the global LoRa-RTCM rule on the heading line
# alone. The heading's text cannot change: CROSS_REPO_BACKLOG.md (out of scope for
# this stage) links to its exact anchor, and any edit to the heading's words shifts
# the GitHub-style slug and breaks that link. Exempting this one pattern for this
# file does not hide a live defect -- the section's other two same-pattern lines
# (::80 `CR-002`, ::221 "is retired") already carry an allowed word on their own line.
EXEMPT["docs/BASE_STATION_INTEGRATION.md"] = {r"(?i)LoRa-RTCM|RTCM over LoRa|LoRa[- ]relayed RTCM"}
REQUIRED["docs/BASE_STATION_INTEGRATION.md"] = [
    (r"\b6563\b", 1),
    (r"\b6565\b", 1),
    (r"(?i)one client at a time", 1),
    (r"CR-004", 1),
    (r"CR-005", 1),
    (r"\"schema_version\": 2", 1),
    (r"\bv10\b", 1),
    (r"ICY 200 OK", 1),
    (r"sensors_disabled", 1),
]
FORBIDDEN_BY_FILE["docs/BASE_STATION_INTEGRATION.md"] = [
    (r"Appendix C", "CLAUDE.md has no appendices"),
    (r"lora_rtcm_loss", "no such event"),
]

# --- Task 8: HARDWARE, SMOKE_CHECKLIST ---
ENFORCED.add("docs/HARDWARE.md")
REQUIRED["docs/HARDWARE.md"] = [
    (r"Heltec WiFi LoRa 32 V3", 2),
    (r"GPS-RTK-SMA", 1),
    (r"ANN-MB-00", 1),
    (r"\[imu\]\.mount", 1),
    (r"S5-F1", 1),
    (r"antenna_offset_m", 1),
]

ENFORCED.add("deploy/SMOKE_CHECKLIST.md")
REQUIRED["deploy/SMOKE_CHECKLIST.md"] = [
    (r"(?i)home the mast", 1),
    (r"return_home_failed", 1),
    (r"(?i)rewind", 1),
    (r"heading_settled", 1),
    (r"(?i)upgrading an existing pi", 1),
    (r"fusion_output_hz", 1),
    (r"S5-R3", 1),
    (r"S4-R1", 1),
]

# --- Task 9: ROADMAP + coverage ---
ENFORCED.add("docs/ROADMAP.md")
REQUIRED["docs/ROADMAP.md"] = [
    (r"v0\.11", 2),
    (r"SMOKE_CHECKLIST", 1),
    (r"dae5776", 1),
    (r"167f4a2", 1),
    (r"S5-R3", 1),
    (r"NC-1", 1),
]
FORBIDDEN_BY_FILE["docs/ROADMAP.md"] = [
    (r"(?i)set up git repository|start config\.py module", "2026-03 startup tasks"),
    (r"(?i)lora bandwidth insufficient for rtcm", "RTCM never travels over LoRa"),
]
REQUIRED["CLAUDE.md"].append((r"v0\.11\.0", 1))


def test_every_live_doc_is_enforced() -> None:
    assert set(LIVE_DOCS) == ENFORCED, set(LIVE_DOCS) ^ ENFORCED


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _slug(heading: str) -> str:
    """GitHub-style anchor: lowercase, drop punctuation except - and _, spaces → -."""
    h = heading.strip().lower()
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {_slug(m.group(2)) for m in re.finditer(r"^(#+)\s+(.*)$", text, re.M)}


def test_internal_links_resolve() -> None:
    failures = []
    for rel in LINKED_DOCS + sorted(
        p.relative_to(REPO).as_posix() for p in (REPO / "docs" / "archive").glob("*.md")
    ):
        src = REPO / rel
        for m in re.finditer(r"\]\(([^)\s]+)\)", _read(rel)):
            url = m.group(1)
            if url.startswith(("http://", "https://", "mailto:")):
                continue
            path, _, frag = url.partition("#")
            target = (src.parent / path).resolve() if path else src.resolve()
            if not target.exists():
                failures.append(f"{rel}: missing target {url}")
            elif frag and target.suffix == ".md" and frag not in _anchors(target):
                failures.append(f"{rel}: missing anchor {url}")
    assert not failures, "\n".join(failures)


def test_no_mixed_line_endings() -> None:
    mixed = []
    for rel in LINKED_DOCS:
        data = (REPO / rel).read_bytes()
        crlf = data.count(b"\r\n")
        lf = data.count(b"\n") - crlf
        if crlf and lf:
            mixed.append(f"{rel}: {crlf} CRLF + {lf} LF")
    assert not mixed, "\n".join(mixed)


def test_enforced_docs_have_no_stale_facts() -> None:
    failures = []
    for rel in sorted(ENFORCED):
        exempt = EXEMPT.get(rel, set())
        for n, line in enumerate(_read(rel).splitlines(), 1):
            for pattern, reason, allowed in FORBIDDEN:
                if pattern in exempt:
                    continue
                if re.search(pattern, line) and not (allowed and re.search(allowed, line)):
                    failures.append(f"{rel}:{n}: {reason}: {line.strip()[:100]}")
            for pattern, reason in FORBIDDEN_BY_FILE.get(rel, []):
                if re.search(pattern, line):
                    failures.append(f"{rel}:{n}: {reason}: {line.strip()[:100]}")
    assert not failures, "\n".join(failures)


def test_required_facts_present() -> None:
    missing = []
    for rel, rules in sorted(REQUIRED.items()):
        text = _read(rel)
        for pattern, minimum in rules:
            found = len(re.findall(pattern, text, re.M))
            if found < minimum:
                missing.append(f"{rel}: expected >= {minimum} of /{pattern}/, found {found}")
    assert not missing, "\n".join(missing)


def test_tables_only_name_live_docs() -> None:
    known = set(LIVE_DOCS) | {
        p.relative_to(REPO).as_posix() for p in (REPO / "docs" / "archive").glob("*.md")
    }
    stray = (ENFORCED | set(REQUIRED) | set(FORBIDDEN_BY_FILE) | set(EXEMPT)) - known
    assert not stray, stray


def test_code_comments_do_not_cite_claude_appendix() -> None:
    for rel in ("src/rover/gnss.py", "src/rover/lora_protocol.py"):
        assert "Appendix C" not in _read(rel), rel
