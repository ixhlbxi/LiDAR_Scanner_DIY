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
    (
        r"(?i)carries STATUS/LINK|STATUS/LINK telemetry",
        "the rover emits STATUS only; LINK is defined but never sent",
    ),
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
    (r"README_ORIGINAL", "archived as docs/archive/README_v0.9.2.md")
]

ENFORCED.add("docs/ATTRIBUTION.md")
REQUIRED["docs/ATTRIBUTION.md"] = [
    (r"^## Project Lineage", 1),
    (r"archive/README_v0\.9\.2\.md", 1),
]
FORBIDDEN_BY_FILE["docs/ATTRIBUTION.md"] = [(r"Open3D", "not a dependency")]

ENFORCED.add("docs/V2_SLAM_CONCEPT.md")
REQUIRED["docs/V2_SLAM_CONCEPT.md"] = [(r"Unitree L2", 1)]


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
