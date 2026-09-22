# Stage 1 — Hygiene and Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the repo a guaranteed line-ending policy, one formatter configuration, one version source, and a licence that matches its upstream, so every later stage's diff is clean and the public repo is compliant.

**Architecture:** Six independent commits on branch `fix/stage1-hygiene`, merged `--no-ff`. No behaviour changes; the only code edits are the version imports in `logger.py` and `ntrip.py`. The format-only commit is isolated so `git blame` can skip it.

**Tech Stack:** git attributes, ruff 0.x, setuptools dynamic version, pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-audit-remediation-design.md` §3

## Global Constraints

- Python 3.11+ (`requires-python = ">=3.11"`), stdlib preferred.
- Repo path contains spaces and a comma: always quote it in shell commands.
- Run every command from the repo root: `C:/Users/bbiscotti/OneDrive - ARM GROUP Enterprises, Inc/Documents/GitHub/LiDAR_Scanner_DIY`.
- Use the Write tool for any file content containing backslashes or backticks (machine CLAUDE.md rule); never route file content through a shell string.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Test suite baseline is 272 passed; it must stay green after every task.
- Finding IDs closed: T1-036, T1-054, T1-055, T1-056, T3-003, D-008. Reference them in commit messages.

## Review Focus

1. **A clone on a machine with `core.autocrlf=false`** must still check out `deploy/install.sh` with LF, otherwise bash rejects the shebang. Pinned by Task 1 step 5.
2. **`pip install -e .` after the dynamic version switch** must report `0.10.0`, not fail with "version not found"; a wrong attribute path breaks every install. Pinned by Task 4 step 4.
3. **The format-only commit must change zero behaviour**; a `ruff check --fix` rule that rewrites semantics (e.g. `UP` rewriting `Optional[X]` where `from __future__ import annotations` is absent) would be invisible in a green suite. Pinned by Task 3 step 3 (only `I` and `F401` fixes are applied automatically; `UP` is review-only).
4. **`LICENSE` must be the CC BY-NC-SA 4.0 legal code, not the human-readable deed**; the deed is not a licence. Pinned by Task 5 step 2 (first-line assertion).
5. **Renormalize must produce an empty diff**; a non-empty diff means the index held CRLF somewhere and the audit's "index is LF" claim was wrong. Pinned by Task 1 step 4.

---

### Task 1: `.gitattributes` and the clone-not-copy note

**Files:**
- Create: `.gitattributes`
- Modify: `deploy/install.sh:1-8` (header comment only)

**Interfaces:**
- Consumes: nothing.
- Produces: a repo-level guarantee that every text file is stored and checked out LF; later tasks rely on it when they add shell/service files.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b fix/stage1-hygiene
```

- [ ] **Step 2: Write `.gitattributes`** (Write tool)

```
# Line-ending policy — every text file is stored and checked out LF.
# The deploy tree runs on a Raspberry Pi; bash, systemd and udev reject CRLF.
* text=auto eol=lf

# Explicit, so a future `text=auto` heuristic miss can never CRLF these.
*.sh       text eol=lf
*.service  text eol=lf
*.rules    text eol=lf
*.toml     text eol=lf
*.py       text eol=lf
*.md       text eol=lf
*.json     text eol=lf
*.ini      text eol=lf
*.cpp      text eol=lf
*.h        text eol=lf
deploy/**  text eol=lf

# Binary assets.
*.png  binary
*.jpg  binary
*.jpeg binary
```

- [ ] **Step 3: Add the clone note to the installer header**

In `deploy/install.sh`, after the line `# Install / refresh rover deployment assets on a Raspberry Pi.` insert:

```bash
#
# Clone this repo on the Pi (git checkout honours .gitattributes and writes LF).
# Do NOT copy the working tree from a Windows machine with scp/rsync/OneDrive:
# that ships CRLF and bash/systemd/udev will reject these files.
```

- [ ] **Step 4: Renormalize and verify the index was already LF**

```bash
git add --renormalize .
git status --short
```

Expected: only `.gitattributes` (new) and `deploy/install.sh` (modified) listed. If any other file appears, stop: the index held CRLF and the audit claim was wrong; report it before continuing.

- [ ] **Step 5: Verify checkout under `autocrlf=false` yields LF**

```bash
git -c core.autocrlf=false show HEAD:deploy/install.sh | python -c "import sys; d=sys.stdin.buffer.read(); print('crlf', d.count(b'\r\n'))"
```

Expected: `crlf 0`.

- [ ] **Step 6: Commit**

```bash
git add .gitattributes deploy/install.sh
git commit -m "chore: add .gitattributes LF policy and clone-not-copy note (T1-055)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Ruff configuration

**Files:**
- Modify: `pyproject.toml` (append `[tool.ruff]` blocks)
- Modify: `CLAUDE.md:99-100` (§5 Coding Standards, first bullet)

**Interfaces:**
- Produces: `ruff check` and `ruff format --check` as the repo's lint contract; every later stage runs both before merging.

- [ ] **Step 1: Append the ruff config to `pyproject.toml`**

```toml

[tool.ruff]
line-length = 100
target-version = "py311"
src = ["src", "scripts", "tests"]

[tool.ruff.lint]
# E/W pycodestyle, F pyflakes, I isort, UP pyupgrade, B bugbear.
select = ["E", "F", "W", "I", "UP", "B"]
# Line length is the formatter's job; B008 (function-call defaults) is a
# pattern this codebase uses deliberately for dataclass factories.
ignore = ["E501", "B008"]

[tool.ruff.lint.isort]
known-first-party = ["rover"]

[tool.ruff.format]
quote-style = "double"
```

- [ ] **Step 2: Confirm ruff reads the config and report the count**

```bash
python -m ruff check src scripts tests --statistics | tail -5
python -m ruff format --check src scripts tests | tail -1
```

Expected: a non-zero finding count (the next task fixes them) and "N files would be reformatted". Record both numbers in the commit message.

- [ ] **Step 3: Update CLAUDE.md §5**

Replace the line

```
- Python 3.11+, type hints on public APIs. Format with `ruff` (preferred) or `black`+`isort`.
```

with

```
- Python 3.11+, type hints on public APIs. Format and lint with `ruff` (config in
  `pyproject.toml`): `python -m ruff format src scripts tests` then
  `python -m ruff check src scripts tests`. Both must be clean before a merge.
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml CLAUDE.md
git commit -m "chore: add ruff config (line-length 100, py311) and document the commands (T1-054)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Format-only commit

**Files:**
- Modify: every `.py` under `src/`, `scripts/`, `tests/` that ruff rewrites.

**Interfaces:**
- Produces: a clean `ruff format --check`; a `.git-blame-ignore-revs` entry so blame skips this commit.

- [ ] **Step 1: Run the formatter**

```bash
python -m ruff format src scripts tests
```

- [ ] **Step 2: Apply only the import-order and unused-import fixes automatically**

```bash
python -m ruff check src scripts tests --select I,F401 --fix
```

- [ ] **Step 3: Review the remaining findings by hand, do not auto-fix `UP`**

```bash
python -m ruff check src scripts tests
```

For each remaining finding: `F841` unused variable and `F541` f-string without placeholders may be fixed by hand if trivially safe. Leave every `UP`, `B` and `E7xx` finding in place with a `# noqa: <code>` only where the code is deliberate; otherwise fix by hand. The rule: this commit must not change runtime behaviour. If unsure, leave it and note the code in the commit message.

- [ ] **Step 4: Verify the suite is unchanged**

```bash
python -m pytest -q 2>&1 | tail -2
python -m ruff format --check src scripts tests
```

Expected: `272 passed`; "N files already formatted", zero would-be-reformatted.

- [ ] **Step 5: Commit and register the commit for blame-ignore**

```bash
git add -A src scripts tests
git commit -m "style: ruff format + import ordering, no behaviour change (T1-054)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git rev-parse HEAD > .git-blame-ignore-revs
```

Then edit `.git-blame-ignore-revs` to prepend a comment line `# ruff format-only commit, stage 1 (2026-09)` above the SHA, and:

```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
git add .git-blame-ignore-revs
git commit -m "chore: blame-ignore the format-only commit

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Single version source

**Files:**
- Modify: `src/rover/__init__.py`
- Modify: `pyproject.toml` (`[project]` and a new `[tool.setuptools.dynamic]`)
- Modify: `src/rover/logger.py` (import + `_write_metadata`)
- Modify: `src/rover/ntrip.py` (import + `USER_AGENT`)
- Create: `tests/test_version.py`

**Interfaces:**
- Produces: `rover.__version__: str` as the only version literal. `logger.py` writes `"firmware_version": __version__`; `ntrip.USER_AGENT == f"PiLiDAR-RTK-Rover/{__version__} (NTRIP)"`.

- [ ] **Step 1: Write the failing test** (`tests/test_version.py`)

```python
"""Version coherence — one literal, three consumers (T1-036)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import rover
from rover import ntrip

REPO = Path(__file__).resolve().parents[1]


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", rover.__version__), rover.__version__


def test_pyproject_version_is_dynamic() -> None:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in data["project"], "pyproject must not carry a literal version"
    assert "version" in data["project"].get("dynamic", [])
    assert data["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "rover.__version__"}


def test_ntrip_user_agent_carries_package_version() -> None:
    assert rover.__version__ in ntrip.USER_AGENT


def test_logger_has_no_hardcoded_version_literal() -> None:
    src = (REPO / "src" / "rover" / "logger.py").read_text(encoding="utf-8")
    assert '"firmware_version": "' not in src, "logger.py must import __version__"
```

- [ ] **Step 2: Run it to confirm failure**

```bash
python -m pytest tests/test_version.py -v
```

Expected: `test_pyproject_version_is_dynamic`, `test_ntrip_user_agent_carries_package_version` and `test_logger_has_no_hardcoded_version_literal` FAIL; `test_version_is_semver` passes.

- [ ] **Step 3: Set the source of truth**

`src/rover/__init__.py`:

```python
"""PiLiDAR-RTK Rover — RTK-enabled LiDAR scanning platform."""

__version__ = "0.10.0"
```

- [ ] **Step 4: Make pyproject dynamic**

In `pyproject.toml`, under `[project]`, delete `version = "0.10.0"` and add `dynamic = ["version"]`. Then add:

```toml
[tool.setuptools.dynamic]
version = {attr = "rover.__version__"}
```

Verify the install still resolves:

```bash
pip install -e . --no-deps -q && pip show pilidar-rtk | grep -i ^version
```

Expected: `Version: 0.10.0`.

- [ ] **Step 5: Wire the consumers**

`src/rover/logger.py`: add `from rover import __version__` after `from rover.config import RoverConfig`, and change `"firmware_version": "0.10.0",` to `"firmware_version": __version__,`.

`src/rover/ntrip.py`: add `from rover import __version__` after `from rover.config import RoverConfig`, and change

```python
USER_AGENT = "PiLiDAR-RTK-Rover/0.10 (NTRIP)"
```

to

```python
USER_AGENT = f"PiLiDAR-RTK-Rover/{__version__} (NTRIP)"
```

- [ ] **Step 6: Run the tests**

```bash
python -m pytest tests/test_version.py tests/test_logger.py tests/test_ntrip.py -q
```

Expected: all pass. If a `test_ntrip.py` test asserted the old literal user agent, update that assertion to use `ntrip.USER_AGENT`.

- [ ] **Step 7: Commit**

```bash
git add src/rover/__init__.py pyproject.toml src/rover/logger.py src/rover/ntrip.py tests/test_version.py
git commit -m "fix: single version source in rover.__version__; pyproject dynamic (T1-036)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Relicense to CC BY-NC-SA 4.0

**Files:**
- Modify: `LICENSE` (replace content)
- Modify: `pyproject.toml` (`[project]` gains `license`)
- Modify: `README.md` (two new sections after Documentation)
- Modify: `docs/ATTRIBUTION.md` (checklist + resolution log)
- Create: `tests/test_license.py`

**Interfaces:**
- Produces: repo licence = CC BY-NC-SA 4.0 everywhere the licence is named.

- [ ] **Step 1: Write the failing test** (`tests/test_license.py`)

```python
"""Licence coherence after the relicense (D-008)."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_license_file_is_cc_by_nc_sa_legal_code() -> None:
    first = (REPO / "LICENSE").read_text(encoding="utf-8").lstrip().splitlines()[0]
    assert "Attribution-NonCommercial-ShareAlike 4.0 International" in first, first


def test_pyproject_declares_license() -> None:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["license"] == "CC-BY-NC-SA-4.0"


def test_readme_acknowledges_upstream() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "## Acknowledgements" in readme
    assert "PiLiDAR" in readme and "CC BY-NC-SA 4.0" in readme
    assert "## Licence" in readme
```

- [ ] **Step 2: Run it to confirm failure**

```bash
python -m pytest tests/test_license.py -v
```

Expected: all three FAIL.

- [ ] **Step 3: Replace `LICENSE` with the legal code**

```bash
curl -fsSL https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.txt -o LICENSE
head -1 LICENSE
```

Expected first line contains `Attribution-NonCommercial-ShareAlike 4.0 International`. If the fetch fails (no network), stop and ask the operator to supply the file; do not paste the deed.

- [ ] **Step 4: Declare the licence in pyproject**

Under `[project]` in `pyproject.toml`, add `license = "CC-BY-NC-SA-4.0"` on the line after `requires-python`.

- [ ] **Step 5: Add the README sections**

Append to `README.md`:

```markdown

## Acknowledgements

This project is a derivative of [PiLiDAR](https://github.com/PiLiDAR/PiLiDAR) by
Philip Gutjahr, released under the
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) licence.
It modifies the original: RTK GNSS integration, IMU fusion, LoRa telemetry, and
the Base-Station companion workflow are additions; the rotating-mast LD19 scan
concept is inherited. Full attribution detail and the licence reasoning are in
[docs/ATTRIBUTION.md](docs/ATTRIBUTION.md).

## Licence

[CC BY-NC-SA 4.0](LICENSE) — Attribution-NonCommercial-ShareAlike 4.0 International,
matching the upstream project. Personal, educational use only; not an ARM Group tool.
```

- [ ] **Step 6: Tick the ATTRIBUTION checklist and log it**

In `docs/ATTRIBUTION.md`, change the first two checklist items from `- [ ]` to `- [x]`. Append a row to the Resolution log table:

```
| September 22, 2026 | LICENSE + README credit | Relicensed to CC BY-NC-SA 4.0 (commit <sha, fill after commit>); Acknowledgements and Licence sections added to README; pyproject `license` set. Remaining checklist items (upstream notices in derived files, upstream issue, PR of fixes) stay open. |
```

- [ ] **Step 7: Run the tests**

```bash
python -m pytest tests/test_license.py -q
```

Expected: 3 passed.

- [ ] **Step 8: Commit, then fill the SHA into the log and amend**

```bash
git add LICENSE pyproject.toml README.md docs/ATTRIBUTION.md tests/test_license.py
git commit -m "chore: relicense to CC BY-NC-SA 4.0 to match upstream PiLiDAR (D-008)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git rev-parse --short HEAD
```

Replace `<sha, fill after commit>` in `docs/ATTRIBUTION.md` with the printed SHA, then:

```bash
git add docs/ATTRIBUTION.md
git commit -m "docs: record relicense commit SHA in ATTRIBUTION resolution log

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `.gitignore` and `.gitkeep`

**Files:**
- Modify: `.gitignore`
- Delete: `scripts/.gitkeep`

- [ ] **Step 1: Edit `.gitignore`**

Replace the last two lines

```
# lgpio temp files
/tmp/lg_*
```

with

```
# lgpio temp files land in $LG_WD (systemd sets /tmp); nothing to ignore here.

# Session tooling and audit quarantine
.remember/
_graveyard/
```

- [ ] **Step 2: Remove the placeholder**

```bash
git rm -q scripts/.gitkeep
git status --short
```

Expected: `D scripts/.gitkeep`, `M .gitignore`.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: drop dead /tmp ignore rule and scripts/.gitkeep (T1-056, T3-003)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Merge stage 1

- [ ] **Step 1: Full verification on the branch**

```bash
python -m pytest -q 2>&1 | tail -1
python -m ruff check src scripts tests
python -m ruff format --check src scripts tests | tail -1
git ls-files -z 'deploy/*' | xargs -0 python -c "
import sys
for p in sys.argv[1:]:
    d=open(p,'rb').read(); c=d.count(b'\r\n')
    print(p, 'crlf', c, 'lone-lf', d.count(b'\n')-c)"
```

Expected: `279 passed` (272 + 7 new), ruff clean, format clean, every deploy file `crlf 0`. If the count differs, report the real number.

- [ ] **Step 2: Merge**

```bash
git checkout main
git merge --no-ff fix/stage1-hygiene -m "Merge stage 1: hygiene and identity (T1-036, T1-054, T1-055, T1-056, T3-003, D-008)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git branch -d fix/stage1-hygiene
```

- [ ] **Step 3: Mark the rows done in the audit report**

In `docs/AUDIT_super_20260922_1810.md`, change the `triage` cell of T1-036, T1-054, T1-055, T1-056, T3-003 and D-008 from `fix`/`simplify` to `done (<merge sha>)`. Commit on `main`:

```bash
git add docs/AUDIT_super_20260922_1810.md
git commit -m "audit: mark stage 1 findings done

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
